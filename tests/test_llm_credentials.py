"""P1 secrets-hygiene tests.

Covers the three credential-management fixes:

- ``llm.mode=api`` without an API key fails explicitly instead of silently
  degrading to assistant/bridge mode (cli._get_llm_client).
- ``load_config`` expands ``${VAR}`` / ``${VAR:-default}`` references in
  config string values and fails fast on unresolved credential placeholders.
- Plaintext ``llm.api_key`` values trigger a warning; ``.env`` discovery is
  limited to the working directory with an mtime-aware cache.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from narrascape.api_keys import APIKeys, find_env_file, load_env_file
from narrascape.config import LLMConfig, NarrascapeConfig, ProjectConfig, load_config


def _write_config(tmp_path: Path, data: dict) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return config_path


def _base_config(**llm_overrides: object) -> dict:
    llm = {"mode": "auto"}
    llm.update(llm_overrides)
    return {
        "project": {
            "name": "secrets-test",
            "title": "Secrets Test",
            "script_file": "scripts/script.yaml",
        },
        "llm": llm,
    }


@pytest.fixture(autouse=True)
def _reset_api_keys_cache():
    APIKeys.reset_cache()
    yield
    APIKeys.reset_cache()


# ─────────────────────────────────────────────
# ${VAR} interpolation in load_config
# ─────────────────────────────────────────────


def test_load_config_interpolates_env_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("NARRASCAPE_TEST_KEY", "sk-from-env")
    config_path = _write_config(
        tmp_path, _base_config(mode="api", api_key="${NARRASCAPE_TEST_KEY}")
    )

    cfg = load_config(config_path)

    assert cfg.llm.api_key == "sk-from-env"


def test_load_config_interpolates_default_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("NARRASCAPE_MISSING_KEY", raising=False)
    config_path = _write_config(
        tmp_path, _base_config(mode="api", api_key="${NARRASCAPE_MISSING_KEY:-fallback-key}")
    )

    cfg = load_config(config_path)

    assert cfg.llm.api_key == "fallback-key"


def test_load_config_env_wins_over_default(tmp_path, monkeypatch):
    monkeypatch.setenv("NARRASCAPE_TEST_KEY", "sk-real")
    config_path = _write_config(
        tmp_path, _base_config(mode="api", api_key="${NARRASCAPE_TEST_KEY:-fallback-key}")
    )

    cfg = load_config(config_path)

    assert cfg.llm.api_key == "sk-real"


def test_load_config_only_touches_env_reference_pattern(tmp_path, monkeypatch):
    monkeypatch.setenv("NARRASCAPE_TITLE_SUFFIX", "Director's Cut")
    data = _base_config()
    data["project"]["title"] = "Price $5, 100% ${NARRASCAPE_TITLE_SUFFIX} {literal}"
    config_path = _write_config(tmp_path, data)

    cfg = load_config(config_path)

    assert cfg.project.title == "Price $5, 100% Director's Cut {literal}"


def test_load_config_keeps_unresolved_non_credential_placeholder(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("NARRASCAPE_UNSET_TITLE", raising=False)
    data = _base_config()
    data["project"]["title"] = "Teaser ${NARRASCAPE_UNSET_TITLE}"
    config_path = _write_config(tmp_path, data)

    with caplog.at_level(logging.DEBUG, logger="narrascape.config"):
        cfg = load_config(config_path)

    assert cfg.project.title == "Teaser ${NARRASCAPE_UNSET_TITLE}"
    assert "NARRASCAPE_UNSET_TITLE" in caplog.text


def test_load_config_unresolved_api_key_reference_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("NARRASCAPE_UNSET_KEY", raising=False)
    config_path = _write_config(
        tmp_path, _base_config(mode="api", api_key="${NARRASCAPE_UNSET_KEY}")
    )

    with pytest.raises(ValueError) as excinfo:
        load_config(config_path)

    message = str(excinfo.value)
    assert "llm.api_key" in message
    assert "NARRASCAPE_UNSET_KEY" in message
    assert "quickstart" in message


def test_load_config_never_logs_secret_values(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("NARRASCAPE_TEST_KEY", "sk-super-secret-value")
    config_path = _write_config(
        tmp_path, _base_config(mode="api", api_key="${NARRASCAPE_TEST_KEY}")
    )

    with caplog.at_level(logging.DEBUG):
        load_config(config_path)

    assert "sk-super-secret-value" not in caplog.text


# ─────────────────────────────────────────────
# Plaintext api_key warning
# ─────────────────────────────────────────────


def test_load_config_warns_on_plaintext_api_key(tmp_path, caplog):
    config_path = _write_config(tmp_path, _base_config(mode="api", api_key="sk-plaintext-key"))

    with caplog.at_level(logging.WARNING, logger="narrascape.config"):
        cfg = load_config(config_path)

    assert cfg.llm.api_key == "sk-plaintext-key"
    assert "plaintext llm.api_key" in caplog.text
    assert "environment" in caplog.text
    # The warning must not echo the secret itself.
    assert "sk-plaintext-key" not in caplog.text


def test_load_config_no_warning_for_env_reference(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("NARRASCAPE_TEST_KEY", "sk-from-env")
    config_path = _write_config(
        tmp_path, _base_config(mode="api", api_key="${NARRASCAPE_TEST_KEY}")
    )

    with caplog.at_level(logging.WARNING, logger="narrascape.config"):
        load_config(config_path)

    assert caplog.text == ""


def test_load_config_no_warning_without_api_key(tmp_path, caplog):
    config_path = _write_config(tmp_path, _base_config())

    with caplog.at_level(logging.WARNING, logger="narrascape.config"):
        load_config(config_path)

    assert caplog.text == ""


# ─────────────────────────────────────────────
# mode=api explicit failure (no silent degradation)
# ─────────────────────────────────────────────


def _api_config(tmp_path: Path, **llm_overrides: object) -> NarrascapeConfig:
    return NarrascapeConfig(
        project=ProjectConfig(
            name="api-mode-test",
            title="API Mode Test",
            script_file="scripts/script.yaml",
        ),
        llm=LLMConfig(**llm_overrides),
        project_dir=tmp_path,
    )


def test_mode_api_uses_config_key(tmp_path):
    from narrascape.cli import _get_llm_client

    config = _api_config(tmp_path, mode="api", api_key="cfg-key")

    with patch.dict("os.environ", {}, clear=True):
        client = _get_llm_client(config=config)

    assert client is not None
    assert client.config.provider == "openai"
    assert client.config.api_key == "cfg-key"


def test_mode_api_falls_back_to_provider_env_var(tmp_path):
    from narrascape.cli import _get_llm_client

    config = _api_config(tmp_path, mode="api", provider="deepseek", model="deepseek-chat")

    with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "env-deepseek-key"}, clear=True):
        client = _get_llm_client(config=config)

    assert client is not None
    assert client.config.provider == "deepseek"
    assert client.config.api_key == "env-deepseek-key"


def test_mode_api_without_key_fails_explicitly(tmp_path, monkeypatch, capsys):
    import typer

    from narrascape.cli import _get_llm_client

    monkeypatch.setattr("narrascape.api_keys.load_env_file", lambda path=None: {})
    config = _api_config(tmp_path, mode="api")

    with patch.dict("os.environ", {}, clear=True), pytest.raises(typer.Exit):
        _get_llm_client(config=config)

    output = capsys.readouterr().out
    assert "llm.mode=api requires an API key" in output
    assert "OPENAI_API_KEY" in output
    assert "does not fall back" in output


def test_mode_api_rejects_unexpanded_placeholder_key(tmp_path):
    """Programmatically built configs with a literal ${VAR} key fail fast too."""
    import typer

    from narrascape.cli import _get_llm_client

    config = _api_config(tmp_path, mode="api", api_key="${OPENAI_API_KEY}")

    with patch.dict("os.environ", {}, clear=True), pytest.raises(typer.Exit):
        _get_llm_client(config=config)


def test_mode_auto_still_falls_back_to_assistant(tmp_path):
    """auto mode keeps its probing behavior: no keys -> assistant bridge."""
    from narrascape.cli import _get_llm_client

    config = _api_config(tmp_path, mode="auto")

    with patch.dict("os.environ", {}, clear=True):
        client = _get_llm_client(config=config)

    assert client is not None
    assert client.config.provider == "ai_assistant"


# ─────────────────────────────────────────────
# .env discovery scope and cache
# ─────────────────────────────────────────────


def test_env_file_search_is_cwd_only(tmp_path, monkeypatch):
    parent_env = tmp_path / ".env"
    parent_env.write_text("PARENT_KEY=from-parent\n", encoding="utf-8")
    child = tmp_path / "subdir"
    child.mkdir()
    monkeypatch.chdir(child)

    # The parent's .env is no longer discovered from a child directory.
    assert find_env_file() is None
    assert load_env_file() == {}

    child_env = child / ".env"
    child_env.write_text("CHILD_KEY=from-child\n", encoding="utf-8")

    assert find_env_file() == child_env
    assert load_env_file() == {"CHILD_KEY": "from-child"}


def test_env_var_beats_env_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("NARRASCAPE_PRIO_KEY=from-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NARRASCAPE_PRIO_KEY", "from-env")

    assert APIKeys.get("NARRASCAPE_PRIO_KEY") == "from-env"


def test_env_file_value_used_when_env_var_missing(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("NARRASCAPE_FILE_KEY=from-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NARRASCAPE_FILE_KEY", raising=False)

    assert APIKeys.get("NARRASCAPE_FILE_KEY") == "from-file"


def test_env_cache_reloads_when_file_changes(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("NARRASCAPE_WATCHED_KEY=one\n", encoding="utf-8")
    first_mtime = env_path.stat().st_mtime
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NARRASCAPE_WATCHED_KEY", raising=False)

    assert APIKeys.get("NARRASCAPE_WATCHED_KEY") == "one"

    env_path.write_text("NARRASCAPE_WATCHED_KEY=two\n", encoding="utf-8")
    # Force a distinct mtime so the change is visible on any filesystem.
    os.utime(env_path, (first_mtime + 10, first_mtime + 10))

    assert APIKeys.get("NARRASCAPE_WATCHED_KEY") == "two"


def test_env_file_load_logs_resolved_path(tmp_path, monkeypatch, caplog):
    env_path = tmp_path / ".env"
    env_path.write_text("LOGGED_KEY=value\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.DEBUG, logger="narrascape.api_keys"):
        assert load_env_file() == {"LOGGED_KEY": "value"}

    assert str(env_path) in caplog.text
