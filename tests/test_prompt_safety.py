#!/usr/bin/env python3
"""Tests for provider prompt sanitization visibility (warnings + audit trail)."""

from __future__ import annotations

import logging

import pytest
import yaml

from narrascape.prompt_safety import (
    drain_sanitize_events,
    sanitize_prompt_for_provider,
    write_sanitize_audit,
)


@pytest.fixture(autouse=True)
def _clean_sanitize_events():
    """The sanitize event buffer is process-global: isolate every test."""
    drain_sanitize_events()
    yield
    drain_sanitize_events()


def test_sanitize_warns_and_records_event_on_rewrite(caplog):
    with caplog.at_level(logging.WARNING, logger="narrascape.prompt_safety"):
        result = sanitize_prompt_for_provider("agnes", "the murderer with a knife")

    assert "morally tormented former student" in result
    assert "sharp prop" in result
    assert "murderer" not in result

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "'agnes'" in message
    assert "2 replacement(s)" in message
    assert "murderer" in message  # category labels are logged, not the prompt
    assert "knife" in message

    events = drain_sanitize_events()
    assert len(events) == 1
    event = events[0]
    assert event["provider"] == "agnes"
    assert event["replacement_count"] == 2
    counts = {item["replacement"]: item["count"] for item in event["replacements"]}
    assert counts == {"morally tormented former student": 1, "sharp prop": 1}


def test_sanitize_clean_prompt_stays_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="narrascape.prompt_safety"):
        result = sanitize_prompt_for_provider("agnes", "a calm morning in the garden")

    assert "a calm morning in the garden" in result
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert drain_sanitize_events() == []


def test_sanitize_other_provider_is_untouched_and_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="narrascape.prompt_safety"):
        result = sanitize_prompt_for_provider("volcengine", "the murderer with a knife")

    assert result == "the murderer with a knife"
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert drain_sanitize_events() == []


def test_drain_sanitize_events_is_idempotent():
    sanitize_prompt_for_provider("agnes", "a victim of theft")

    first = drain_sanitize_events()
    second = drain_sanitize_events()

    assert len(first) == 1
    assert second == []


def test_build_image_payload_records_sanitize_events():
    from narrascape.stages.generate_images import GenerateImagesStage

    stage = GenerateImagesStage()
    payload, _url = stage._build_image_payload(
        provider="agnes",
        prompt="the murderer with a knife",
        size="1024x1024",
        ref_image=None,
        negative_prompt="",
        model="agnes-image-2.1-flash",
        sample_strength=None,
        seed=None,
    )

    assert "morally tormented former student" in payload["prompt"]
    events = drain_sanitize_events()
    assert len(events) == 1
    assert events[0]["provider"] == "agnes"
    assert events[0]["replacement_count"] == 2


def test_write_sanitize_audit_appends_and_tags_stage(tmp_path):
    sanitize_prompt_for_provider("agnes", "the murderer with a knife")
    path = write_sanitize_audit(tmp_path, "generate_images")
    assert path == tmp_path / "prompt_safety.yaml"

    audit = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert audit["schema_version"] == "prompt_safety.v1"
    assert len(audit["events"]) == 1
    event = audit["events"][0]
    assert event["stage"] == "generate_images"
    assert event["provider"] == "agnes"
    assert event["replacement_count"] == 2
    patterns = {item["pattern"] for item in event["replacements"]}
    assert r"\bmurderer\b" in patterns
    assert r"\bknife\b" in patterns

    # A second stage appends to the same audit file.
    sanitize_prompt_for_provider("agnes", "a victim of theft")
    write_sanitize_audit(tmp_path, "generate_video")

    audit = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [e["stage"] for e in audit["events"]] == ["generate_images", "generate_video"]


def test_write_sanitize_audit_returns_none_when_clean(tmp_path):
    assert write_sanitize_audit(tmp_path, "generate_images") is None
    assert not (tmp_path / "prompt_safety.yaml").exists()
