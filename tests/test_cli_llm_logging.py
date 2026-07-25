from __future__ import annotations

from pathlib import Path

from narrascape.cli import _get_llm_client, _llm_client_config
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


def test_cli_leaves_bridge_environment_defaults_unset(tmp_path: Path):
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="bridge-defaults",
            title="Bridge Defaults",
            script_file="scripts/script.yaml",
        ),
        project_dir=tmp_path,
    )

    runtime = _llm_client_config(config, provider="bridge")

    assert runtime.bridge_timeout is None
    assert runtime.bridge_wait is None


def test_cli_explicit_bridge_settings_override_environment_defaults(tmp_path: Path):
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="bridge-explicit",
            title="Bridge Explicit",
            script_file="scripts/script.yaml",
        ),
        llm=LLMConfig(timeout=17, bridge_wait="block"),
        project_dir=tmp_path,
    )

    runtime = _llm_client_config(config, provider="bridge")

    assert runtime.bridge_timeout == 17
    assert runtime.bridge_wait == "block"
