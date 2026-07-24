from __future__ import annotations

import json
from pathlib import Path

from narrascape.llm.client import LLMClient
from narrascape.llm.models import LLMConfig, Message


def _record(client: LLMClient, index: int, *, secret: str = "") -> None:
    client._log_call(
        template_name=f"template-{index}",
        messages=[
            Message(
                role="user",
                content=(
                    f"request {index} api_key={secret} Bearer bearer-{index} "
                    f'{{"password":"plain-secret-{index}"}} ' + "x" * 100
                ),
            )
        ],
        response=f"response {index} {secret} " + "y" * 100,
        parsed_output={"secret": secret, "payload": "z" * 100},
        success=True,
        error=None,
        latency_ms=10.0,
    )


def test_llm_logs_are_bounded_redacted_and_truncated(tmp_path: Path):
    secret = "sk-super-secret-value"
    client = LLMClient(
        LLMConfig(
            provider="local",
            api_key=secret,
            log_max_entries=2,
            log_max_text_chars=48,
        )
    )

    for index in range(3):
        _record(client, index, secret=secret)

    logs = client.get_logs()
    serialized = json.dumps([entry.to_dict() for entry in logs])
    assert [entry.template_name for entry in logs] == ["template-1", "template-2"]
    assert secret not in serialized
    assert "bearer-2" not in serialized
    assert "plain-secret-2" not in serialized
    assert "[REDACTED]" in serialized
    assert logs[-1].messages[0]["content"].endswith("...[truncated]")
    assert logs[-1].parsed_output == {"omitted": True, "type": "dict"}
    assert not (tmp_path / "llm-calls.json").exists()


def test_llm_log_persistence_is_opt_in_atomic_and_retained(tmp_path: Path):
    path = tmp_path / "llm-calls.json"
    client = LLMClient(
        LLMConfig(
            provider="local",
            log_persist_path=path,
            log_max_entries=2,
            log_max_text_chars=80,
        )
    )

    for index in range(3):
        _record(client, index)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["template_name"] for entry in persisted] == ["template-1", "template-2"]
    assert not path.with_name(f"{path.name}.lock").exists()


def test_llm_logging_can_be_disabled(tmp_path: Path):
    path = tmp_path / "llm-calls.json"
    client = LLMClient(LLMConfig(provider="local", log_enabled=False, log_persist_path=path))

    _record(client, 1, secret="sk-never-written")

    assert client.get_logs() == []
    assert not path.exists()


def test_llm_log_can_include_bounded_parsed_output_when_explicitly_enabled():
    client = LLMClient(
        LLMConfig(
            provider="local",
            log_include_parsed_output=True,
            log_max_text_chars=48,
        )
    )

    _record(client, 1, secret="sk-private")

    serialized = json.dumps(client.get_logs()[0].parsed_output)
    assert "sk-private" not in serialized
    assert "[REDACTED]" in serialized
    assert "...[truncated]" in serialized


def test_llm_log_bounds_message_count():
    client = LLMClient(LLMConfig(provider="local"))

    client._log_call(
        template_name="many-messages",
        messages=[Message(role="user", content=str(index)) for index in range(25)],
        response="done",
        parsed_output=None,
        success=True,
        error=None,
        latency_ms=1.0,
    )

    messages = client.get_logs()[0].messages
    assert len(messages) == 21
    assert messages[-1]["content"] == "[5 additional messages omitted]"
