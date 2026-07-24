from __future__ import annotations

from pathlib import Path

from narrascape.cli import _get_llm_client
from narrascape.config import LLMConfig, NarrascapeConfig, ProjectConfig


def test_cli_passes_project_log_governance_to_llm_client(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("NARRASCAPE_LLM_MODE", raising=False)
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="logging",
            title="Logging",
            script_file="scripts/script.yaml",
        ),
        llm=LLMConfig(
            mode="ai_assistant",
            log_enabled=True,
            log_persist=True,
            log_max_entries=7,
            log_max_text_chars=256,
            log_include_parsed_output=True,
        ),
        project_dir=tmp_path,
    )

    client = _get_llm_client(config=config)

    assert client is not None
    assert client.config.log_max_entries == 7
    assert client.config.log_max_text_chars == 256
    assert client.config.log_include_parsed_output is True
    assert client.config.log_persist_path == tmp_path / ".narrascape" / "llm-calls.json"
