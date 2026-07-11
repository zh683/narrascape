from __future__ import annotations

from narrascape.providers.video_adapters import SeedanceVideoAdapter


class _Transport:
    def __init__(self):
        self.responses = [
            {"id": "task-7"},
            {"status": "running"},
            {"status": "succeeded", "content": {"video_url": "https://cdn.test/7.mp4"}},
        ]
        self.calls = []

    def request_json(self, method, url, *, headers, payload=None, timeout):
        self.calls.append((method, url, payload, timeout))
        return self.responses.pop(0)


def test_seedance_adapter_owns_submission_and_polling():
    transport = _Transport()
    adapter = SeedanceVideoAdapter(
        api_key=lambda: "secret",
        transport=transport,
        poll_interval=0,
        max_poll_time=5,
        max_poll_errors=2,
    )

    task_id = adapter.create_task({"model": "seedance", "content": []})
    video_url = adapter.poll(task_id or "")

    assert task_id == "task-7"
    assert video_url == "https://cdn.test/7.mp4"
    assert transport.calls[0][0] == "POST"
    assert transport.calls[1][0] == "GET"
