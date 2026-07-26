from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from narrascape.llm import LLMClient, LLMConfig


def test_openai_multimodal_completion_sends_actual_image_block(tmp_path, monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"status":"approved"}'),
                        finish_reason="stop",
                    )
                ],
                model="vision-model",
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    fake_openai = SimpleNamespace(OpenAI=lambda **kwargs: fake_client)
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"real frame bytes")
    client = LLMClient(
        LLMConfig(provider="openai", model="vision-model", api_key="test", max_retries=0)
    )

    response = client.complete_multimodal("Inspect the frame.", [image], json_mode=True)

    assert response.extract_json() == {"status": "approved"}
    content = captured["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Inspect the frame."}
    assert content[1]["text"] == "Evidence image 1: frame.jpg"
    assert content[2]["type"] == "image_url"
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert captured["response_format"] == {"type": "json_object"}


def test_local_multimodal_completion_uses_configured_http_endpoint_without_auth(
    tmp_path, monkeypatch
):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {"message": {"content": '{"status":"approved"}'}, "finish_reason": "stop"}
                    ],
                    "model": "local-vision",
                    "usage": {},
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    image = tmp_path / "frame.png"
    image.write_bytes(b"real frame bytes")
    client = LLMClient(
        LLMConfig(
            provider="local",
            model="local-vision",
            base_url="http://localhost:11434/v1/chat/completions",
            api_key=None,
            max_retries=0,
        )
    )

    response = client.complete_multimodal("Inspect the frame.", [image], json_mode=True)

    assert response.extract_json() == {"status": "approved"}
    request = captured["request"]
    assert request.full_url == "http://localhost:11434/v1/chat/completions"
    assert request.get_header("Authorization") is None
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["response_format"] == {"type": "json_object"}
    content = payload["messages"][0]["content"]
    assert content[2]["type"] == "image_url"
    assert content[2]["image_url"]["url"].startswith("data:image/png;base64,")
