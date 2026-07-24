"""Robustness tests for the bridge channel (P1-7).

Covers:

- stale bridge-lock recovery (crashed holder) via safe_io.file_lock
- live lock holders are never stolen (acquisition times out, lock survives)
- partially written (unparseable) responses are waited out, not fatal
- persistently incomplete responses produce a diagnostic timeout error
- semantic errors (parseable but missing/invalid content) keep failing fast
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import pytest

from narrascape.llm.bridge import BridgeLLMClient
from narrascape.llm.models import Message


def _client(task_dir: Path, timeout: int) -> BridgeLLMClient:
    return BridgeLLMClient(task_dir=task_dir, timeout=timeout)


def _task_and_response_files(client: BridgeLLMClient, task_dir: Path) -> tuple[str, Path]:
    task_id = client._task_id("## User\n\nhello", False, "")
    return task_id, task_dir / "completed" / f"response_{task_id}.json"


def _write_response(response_file: Path, payload: dict) -> None:
    response_file.parent.mkdir(parents=True, exist_ok=True)
    response_file.write_text(json.dumps(payload), encoding="utf-8")


# ─────────────────────────────────────────────
# Stale lock recovery
# ─────────────────────────────────────────────


def test_stale_lock_is_reclaimed(tmp_path):
    """A lock abandoned by a crashed process (old mtime) must not deadlock."""
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=5)
    task_id, response_file = _task_and_response_files(client, task_dir)
    _write_response(response_file, {"content": "done", "usage": {}})

    # Simulate a crashed holder: leftover lock with an old timestamp.
    task_dir.mkdir(parents=True, exist_ok=True)
    lock_path = task_dir / ".bridge.lock"
    lock_path.write_text(f"pid=999999\ncreated={time.time() - 3600}\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock_path, (old, old))

    response = client.chat([Message(role="user", content="hello")])

    assert response.content == "done"
    assert not lock_path.exists()


def test_recent_stale_format_lock_is_reclaimed_after_stale_after(tmp_path, monkeypatch):
    """Locks older than stale_after are reclaimed regardless of content format."""
    from narrascape.llm import bridge

    monkeypatch.setattr(bridge, "_BRIDGE_LOCK_STALE_AFTER", 0.5)
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=5)
    task_id, response_file = _task_and_response_files(client, task_dir)
    _write_response(response_file, {"content": "done", "usage": {}})

    task_dir.mkdir(parents=True, exist_ok=True)
    lock_path = task_dir / ".bridge.lock"
    # Legacy-format lock content (pid=/created= lines) must parse-free reclaim.
    lock_path.write_text("pid=12345\ncreated=0\n", encoding="utf-8")
    stale = time.time() - 5
    os.utime(lock_path, (stale, stale))

    response = client.chat([Message(role="user", content="hello")])

    assert response.content == "done"
    assert not lock_path.exists()


def test_live_lock_is_not_stolen(tmp_path):
    """A fresh lock (live holder) blocks acquisition and is never unlinked."""
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=1)  # acquire timeout = min(1, 5) = 1s
    _task_and_response_files(client, task_dir)

    task_dir.mkdir(parents=True, exist_ok=True)
    lock_path = task_dir / ".bridge.lock"
    lock_path.write_text(str(os.getpid()), encoding="utf-8")  # fresh mtime = live

    start = time.monotonic()
    with pytest.raises(RuntimeError, match="Bridge lock timeout"):
        client.chat([Message(role="user", content="hello")])

    assert time.monotonic() - start < 5.0
    # The live holder's lock must survive untouched.
    assert lock_path.exists()


# ─────────────────────────────────────────────
# Partial / incomplete response tolerance
# ─────────────────────────────────────────────


def test_partial_response_is_waited_out_not_fatal(tmp_path):
    """A half-written response that is completed later must succeed."""
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=10)
    task_id, response_file = _task_and_response_files(client, task_dir)
    response_file.parent.mkdir(parents=True, exist_ok=True)
    response_file.write_text('{"content": "partial', encoding="utf-8")

    def complete_the_write() -> None:
        time.sleep(1.5)
        _write_response(response_file, {"content": "finished", "usage": {}})

    threading.Thread(target=complete_the_write, daemon=True).start()

    response = client.chat([Message(role="user", content="hello")])

    assert response.content == "finished"
    assert (task_dir / "archive" / response_file.name).exists()


def test_persistent_incomplete_response_times_out_with_diagnostics(tmp_path, caplog):
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=2)
    task_id, response_file = _task_and_response_files(client, task_dir)
    response_file.parent.mkdir(parents=True, exist_ok=True)
    response_file.write_text('{"content": "never finished', encoding="utf-8")

    with (
        caplog.at_level(logging.DEBUG, logger="narrascape.llm.bridge"),
        pytest.raises(RuntimeError) as excinfo,
    ):
        client.chat([Message(role="user", content="hello")])

    message = str(excinfo.value)
    assert "Bridge timeout" in message
    assert f"Task id: {task_id}" in message
    assert "Waited: 2s" in message
    assert str(response_file) in message
    assert "Incomplete response observed: True" in message
    assert "atomically" in message
    # Partial-write note is logged once per task, not once per poll.
    assert caplog.text.count("not fully written yet") == 1


def test_clean_timeout_reports_no_incomplete_observation(tmp_path):
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=0)
    task_id, response_file = _task_and_response_files(client, task_dir)

    with pytest.raises(RuntimeError) as excinfo:
        client.chat([Message(role="user", content="hello")])

    message = str(excinfo.value)
    assert "Bridge timeout" in message
    assert f"Task id: {task_id}" in message
    assert str(response_file) in message
    assert "Incomplete response observed: False" in message


# ─────────────────────────────────────────────
# Semantic errors keep failing fast
# ─────────────────────────────────────────────


def test_parseable_response_missing_content_fails_fast(tmp_path):
    """Valid JSON without a string content field is a semantic error."""
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=30)
    _task_id, response_file = _task_and_response_files(client, task_dir)
    _write_response(response_file, {"usage": {"prompt_tokens": 1}})

    start = time.monotonic()
    with pytest.raises(RuntimeError, match="invalid"):
        client.chat([Message(role="user", content="hello")])

    assert time.monotonic() - start < 5.0


def test_non_object_response_fails_fast(tmp_path):
    task_dir = tmp_path / "bridge"
    client = _client(task_dir, timeout=30)
    _task_id, response_file = _task_and_response_files(client, task_dir)
    _write_response(response_file, ["not", "an", "object"])  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="invalid"):
        client.chat([Message(role="user", content="hello")])
