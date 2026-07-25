"""Bridge queue-mode tests (anti offline-fallback fixes).

Covers:

- exit_on_pending raises BridgeTaskPending right after the task file lands
- rerunning picks up a completed response (pause/resume)
- a malformed earlier response is flagged in the pending note
- BridgeTaskPending is NOT an Exception subclass, so broad ``except
  Exception`` fallbacks cannot silently swallow it
- response ``content`` may be a directly embedded JSON object/array
- run_template_validated retries bridge tasks with exact error feedback
- the serial executor pauses the stage as *pending* (not failed) and a rerun
  resumes and completes it
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from narrascape.llm.bridge import BridgeLLMClient, BridgeTaskPending
from narrascape.llm.client import LLMClient
from narrascape.llm.models import LLMConfig, Message, PromptTemplate


def _client(task_dir: Path, timeout: int = 5, wait_mode: str = "block") -> BridgeLLMClient:
    return BridgeLLMClient(task_dir=task_dir, timeout=timeout, wait_mode=wait_mode)


def _write_response(response_file: Path, payload: dict) -> None:
    response_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = response_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.rename(response_file)


# ─────────────────────────────────────────────
# exit_on_pending: pause instead of blocking
# ─────────────────────────────────────────────


def test_exit_on_pending_raises_and_keeps_task_file(tmp_path):
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, wait_mode="exit_on_pending")

    with pytest.raises(BridgeTaskPending) as excinfo:
        client.chat([Message(role="user", content="hello")])

    pending = excinfo.value
    assert pending.task_file.exists()
    assert pending.task_file.parent == task_dir / "pending"
    assert pending.response_file.parent == task_dir / "completed"
    assert pending.task_id in pending.task_file.name


def test_exit_on_pending_resumes_completed_response(tmp_path):
    """First call pauses; once the response exists, the rerun returns it."""
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, wait_mode="exit_on_pending")

    with pytest.raises(BridgeTaskPending) as excinfo:
        client.chat([Message(role="user", content="hello")])

    _write_response(excinfo.value.response_file, {"content": "done", "usage": {}})

    response = client.chat([Message(role="user", content="hello")])
    assert response.content == "done"
    # Task + response are archived after a successful read.
    assert (task_dir / "archive" / excinfo.value.response_file.name).exists()


def test_exit_on_pending_flags_unparseable_previous_response(tmp_path):
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, wait_mode="exit_on_pending")
    task_id = client._task_id("## User\n\nhello", False, "")
    response_file = task_dir / "completed" / f"response_{task_id}.json"
    response_file.parent.mkdir(parents=True, exist_ok=True)
    response_file.write_text('{"content": "truncated', encoding="utf-8")

    with pytest.raises(BridgeTaskPending) as excinfo:
        client.chat([Message(role="user", content="hello")])

    assert "atomically" in str(excinfo.value)


def test_pending_signal_is_not_an_exception_subclass(tmp_path):
    """except Exception must never swallow the pause control-flow signal."""
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, wait_mode="exit_on_pending")

    with pytest.raises(BridgeTaskPending):
        try:
            client.chat([Message(role="user", content="hello")])
        except Exception:  # noqa: BLE001 - simulates stage fallback paths
            pytest.fail("BridgeTaskPending was swallowed by except Exception")


# ─────────────────────────────────────────────
# Embedded-object response content
# ─────────────────────────────────────────────


def test_embedded_object_content_is_accepted(tmp_path):
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=5)
    task_id = client._task_id("## User\n\nhello", False, "")
    _write_response(
        task_dir / "completed" / f"response_{task_id}.json",
        {"content": {"emotion": "calm", "intensity": 0.5}, "usage": {}},
    )

    response = client.chat([Message(role="user", content="hello")])

    assert json.loads(response.content) == {"emotion": "calm", "intensity": 0.5}


def test_embedded_array_content_is_accepted(tmp_path):
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=5)
    task_id = client._task_id("## User\n\nhello", False, "")
    _write_response(
        task_dir / "completed" / f"response_{task_id}.json",
        {"content": [{"segment_id": 1}], "usage": {}},
    )

    response = client.chat([Message(role="user", content="hello")])

    assert json.loads(response.content) == [{"segment_id": 1}]


def test_missing_content_still_fails_fast(tmp_path):
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=5)
    task_id = client._task_id("## User\n\nhello", False, "")
    _write_response(task_dir / "completed" / f"response_{task_id}.json", {"usage": {}})

    with pytest.raises(RuntimeError, match="invalid"):
        client.chat([Message(role="user", content="hello")])


# ─────────────────────────────────────────────
# Validated retries over bridge: error feedback loop
# ─────────────────────────────────────────────


def _bridge_responder(task_dir: Path, answered: list[str], stop: threading.Event) -> None:
    """Answer each new bridge task: garbage first, valid JSON for corrections."""
    completed = task_dir / "completed"
    completed.mkdir(parents=True, exist_ok=True)
    while not stop.is_set():
        for task_file in sorted((task_dir / "pending").glob("task_*.md")):
            task_id = task_file.stem.removeprefix("task_")
            if task_id in answered:
                continue
            text = task_file.read_text(encoding="utf-8")
            if "previous response was not valid JSON" in text:
                payload = {"content": json.dumps({"emotion": "calm", "intensity": 0.4})}
            else:
                payload = {"content": "definitely not json"}
            _write_response(completed / f"response_{task_id}.json", payload)
            answered.append(task_id)
        time.sleep(0.05)


def test_run_template_validated_retries_bridge_with_error_feedback(tmp_path, monkeypatch):
    monkeypatch.setenv("NARRASCAPE_BRIDGE_DIR", str(tmp_path / "bridge"))
    monkeypatch.setenv("NARRASCAPE_BRIDGE_TIMEOUT", "30")
    client = LLMClient(LLMConfig(provider="bridge", log_enabled=False))

    answered: list[str] = []
    stop = threading.Event()
    thread = threading.Thread(
        target=_bridge_responder, args=(tmp_path / "bridge", answered, stop), daemon=True
    )
    thread.start()
    try:
        data = client.run_template_validated(
            PromptTemplate(user="Analyze: {text}"),
            validator=lambda d: ("emotion" in d, "missing emotion key"),
            text="hello",
            max_format_retries=2,
        )
    finally:
        stop.set()
        thread.join(timeout=5)

    assert data == {"emotion": "calm", "intensity": 0.4}
    # First task + at least one correction task carrying the parse error.
    assert len(answered) >= 2


# ─────────────────────────────────────────────
# Pipeline pause/resume
# ─────────────────────────────────────────────


def test_pipeline_pauses_stage_as_pending_and_rerun_completes(tmp_path, monkeypatch):
    from narrascape.config import NarrascapeConfig, ProjectConfig
    from narrascape.pipeline import Pipeline
    from narrascape.stages.base import Stage, StageContext, StageResult

    calls = {"count": 0}

    class PausableStage(Stage):
        name = "bridge_pausable"
        depends_on: list[str] = []

        def run(self, context: StageContext) -> StageResult:
            calls["count"] += 1
            if calls["count"] == 1:
                raise BridgeTaskPending(
                    "abc123",
                    tmp_path / "task_abc123.md",
                    tmp_path / "response_abc123.json",
                )
            return StageResult(self.name, True, message="done")

    monkeypatch.setattr(
        "narrascape.pipeline.get_stage_map", lambda: {"bridge_pausable": PausableStage}
    )
    # A script on disk keeps the executor from prepending research/write stages.
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "script.yaml").write_text(
        "segments:\n  - id: 1\n    text: hello\n", encoding="utf-8"
    )
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="bridge-pause-test", title="Bridge Pause", script_file="scripts/script.yaml"
        ),
        project_dir=tmp_path,
    )

    first = Pipeline(config, auto_approve=True)
    results = first.run(["bridge_pausable"])

    assert results["bridge_pausable"].success is False
    assert results["bridge_pausable"].metadata["awaiting_bridge"] is True
    assert results["bridge_pausable"].metadata["bridge_task_id"] == "abc123"
    assert first.state.get_stage_status("bridge_pausable") == "pending"

    second = Pipeline(config, auto_approve=True)
    resumed = second.run(["bridge_pausable"])

    assert resumed["bridge_pausable"].success is True
    assert second.state.get_stage_status("bridge_pausable") == "completed"


def test_multicall_stage_resumes_across_fresh_pipeline_clients(tmp_path, monkeypatch):
    """Completed calls replay until the whole stage reaches a terminal result."""
    from narrascape.config import NarrascapeConfig, ProjectConfig
    from narrascape.pipeline import Pipeline
    from narrascape.stages.base import Stage, StageContext, StageResult

    task_dir = tmp_path / ".narrascape" / "bridge"

    class TwoCallStage(Stage):
        name = "bridge_two_call"
        depends_on: list[str] = []
        client: LLMClient | None = None

        def run(self, context: StageContext) -> StageResult:
            assert self.client is not None
            first = self.client.complete("first bridge call")
            second = self.client.complete("second bridge call")
            return StageResult(self.name, True, message=f"{first.content}/{second.content}")

    monkeypatch.setattr(
        "narrascape.pipeline.get_stage_map", lambda: {TwoCallStage.name: TwoCallStage}
    )
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "script.yaml").write_text(
        "segments:\n  - id: 1\n    text: hello\n", encoding="utf-8"
    )
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="bridge-multicall-test",
            title="Bridge Multicall",
            script_file="scripts/script.yaml",
        ),
        project_dir=tmp_path,
    )

    def run_once():
        client = LLMClient(
            LLMConfig(
                provider="bridge",
                bridge_dir=task_dir,
                bridge_wait="exit_on_pending",
                log_enabled=False,
            )
        )
        TwoCallStage.client = client
        pipeline = Pipeline(config, llm_client=client, auto_approve=True)
        return pipeline, pipeline.run([TwoCallStage.name])[TwoCallStage.name]

    first_pipeline, first = run_once()
    assert first.metadata["awaiting_bridge"] is True
    _write_response(Path(first.metadata["bridge_response_file"]), {"content": "one"})

    _second_pipeline, second = run_once()
    assert second.metadata["awaiting_bridge"] is True
    assert second.metadata["bridge_task_id"] != first.metadata["bridge_task_id"]
    assert first_pipeline.state.get_stage_status(TwoCallStage.name) == "pending"
    _write_response(Path(second.metadata["bridge_response_file"]), {"content": "two"})

    third_pipeline, third = run_once()
    assert third.success is True
    assert third.message == "one/two"
    assert third_pipeline.state.get_stage_status(TwoCallStage.name) == "completed"
    assert not (task_dir / "resume" / TwoCallStage.name).exists()

    budget = json.loads((config.pipeline_dir / "budget_state.json").read_text(encoding="utf-8"))
    assert len(budget["entries"]) == 2


def test_validated_correction_resumes_across_fresh_clients(tmp_path):
    task_dir = tmp_path / "bridge"
    template = PromptTemplate(user="Analyze: {text}")

    def validator(data):
        return isinstance(data, dict) and "emotion" in data, "missing emotion key"

    usage_events: list[dict[str, int]] = []

    def new_client() -> LLMClient:
        client = LLMClient(
            LLMConfig(
                provider="bridge",
                bridge_dir=task_dir,
                bridge_wait="exit_on_pending",
                log_enabled=False,
            )
        )
        client.set_bridge_resume_scope("validated_stage")
        client.on_usage = lambda usage, model, estimated: usage_events.append(usage)
        return client

    with pytest.raises(BridgeTaskPending) as first_pending:
        new_client().run_template_validated(template, validator, text="hello")
    _write_response(
        first_pending.value.response_file,
        {"content": "not json", "usage": {"prompt_tokens": 3, "completion_tokens": 1}},
    )

    with pytest.raises(BridgeTaskPending) as correction_pending:
        new_client().run_template_validated(template, validator, text="hello")
    correction_text = correction_pending.value.task_file.read_text(encoding="utf-8")
    assert "previous response was not valid JSON" in correction_text
    _write_response(
        correction_pending.value.response_file,
        {
            "content": {"emotion": "calm"},
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
    )

    final_client = new_client()
    data = final_client.run_template_validated(template, validator, text="hello")
    final_client.clear_bridge_resume_scope("validated_stage")

    assert data == {"emotion": "calm"}
    assert len(usage_events) == 2
    assert not (task_dir / "resume" / "validated_stage").exists()


def test_interactive_retry_can_pause_for_bridge_task(tmp_path, monkeypatch):
    from narrascape.config import NarrascapeConfig, ProjectConfig
    from narrascape.pipeline import Pipeline
    from narrascape.stages.base import Stage, StageContext, StageResult

    calls = 0

    class InteractiveStage(Stage):
        name = "interactive_bridge"
        depends_on: list[str] = []

        def run(self, context: StageContext) -> StageResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                return StageResult(self.name, True, message="review me")
            raise BridgeTaskPending(
                "retry123",
                tmp_path / "task_retry123.md",
                tmp_path / "response_retry123.json",
            )

    monkeypatch.setattr(
        "narrascape.pipeline.get_stage_map", lambda: {InteractiveStage.name: InteractiveStage}
    )
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "script.yaml").write_text(
        "segments:\n  - id: 1\n    text: hello\n", encoding="utf-8"
    )
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="interactive-bridge-test",
            title="Interactive Bridge",
            script_file="scripts/script.yaml",
        ),
        project_dir=tmp_path,
    )
    pipeline = Pipeline(config, interactive=True, console=object())
    monkeypatch.setattr(
        pipeline.approval,
        "prompt_interactive",
        lambda stage_name, result, console: "retry",
    )

    result = pipeline.run([InteractiveStage.name])[InteractiveStage.name]

    assert result.metadata["awaiting_bridge"] is True
    assert pipeline.state.get_stage_status(InteractiveStage.name) == "pending"
