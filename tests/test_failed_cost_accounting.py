#!/usr/bin/env python3
"""Integration tests for failure-aware cost accounting (P1-10)."""

from __future__ import annotations

import json
import time
import urllib.error
from types import SimpleNamespace

from narrascape.config import BudgetConfig, NarrascapeConfig, ProjectConfig, Script
from narrascape.stages.base import StageContext
from narrascape.stages.generate_tts import GenerateTTSStage
from narrascape.stages.generate_video import GenerateVideoStage
from narrascape.stages.generate_video_services import VideoTaskLedger
from narrascape.utils.budget import BudgetTracker


def _config(tmp_path, name="failed-cost-test"):
    config = NarrascapeConfig(
        project=ProjectConfig(
            name=name,
            title="Failed Cost Test",
            script_file="scripts/script.yaml",
        ),
        project_dir=tmp_path,
    )
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "script.yaml").write_text(
        "segments:\n- id: 1\n  text: Hello world.\n",
        encoding="utf-8",
    )
    return config


def _context(config):
    return StageContext(
        config=config,
        script=Script.model_construct(segments=[]),
    )


def _fake_tts_selection():
    return SimpleNamespace(
        tool=SimpleNamespace(
            name="minimax_tts",
            provider="minimax",
            requires=["MINIMAX_API_KEY"],
            capability=SimpleNamespace(value="tts"),
        ),
        alternatives=[],
        score=1.0,
        reason="test",
    )


def _read_budget(tmp_path):
    return json.loads(
        (tmp_path / "pipeline" / "failed-cost-test" / "budget_state.json").read_text()
    )


class TestTTSFailureAccounting:
    def test_business_failure_records_failed_cost(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        stage = GenerateTTSStage(api_key="fake")
        monkeypatch.setattr(
            "narrascape.stages.generate_tts.select_provider",
            lambda *args, **kwargs: _fake_tts_selection(),
        )
        body = json.dumps(
            {"base_resp": {"status_code": 1002, "status_msg": "bad request"}, "data": {}}
        ).encode()
        monkeypatch.setattr(
            "narrascape.stages.generate_tts.urllib.request.urlopen",
            lambda req, timeout=None: SimpleNamespace(read=lambda: body),
        )
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

        result = stage.run(_context(config))

        assert result.success is False
        data = _read_budget(tmp_path)
        assert data["spent"] == 0.001  # default tts estimate charged once
        assert len(data["entries"]) == 1
        entry = data["entries"][0]
        assert entry["kind"] == "tts"
        assert entry["status"] == "failed"
        assert entry["provider"] == "minimax"
        assert entry["detail"] == "seg_1"

    def test_network_failure_records_zero_cost_entry(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        stage = GenerateTTSStage(api_key="fake")
        monkeypatch.setattr(
            "narrascape.stages.generate_tts.select_provider",
            lambda *args, **kwargs: _fake_tts_selection(),
        )

        def raise_network(req, timeout=None):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("narrascape.stages.generate_tts.urllib.request.urlopen", raise_network)
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

        result = stage.run(_context(config))

        assert result.success is False
        data = _read_budget(tmp_path)
        assert data["spent"] == 0.0  # never reached the server: not billed
        assert len(data["entries"]) == 1
        assert data["entries"][0]["status"] == "network_error"


class TestVideoFailureAccounting:
    def _stage(self, tmp_path):
        stage = GenerateVideoStage(api_key="fake", poll_interval=0)
        stage._task_ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
        stage._budget_tracker = BudgetTracker(
            BudgetConfig(total_usd=10.0), tmp_path / "budget_state.json"
        )
        stage._per_task_cost_estimate = 0.5
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        return stage, videos_dir

    def _budget_data(self, tmp_path):
        return json.loads((tmp_path / "budget_state.json").read_text(encoding="utf-8"))

    def test_terminal_failed_task_records_failed_cost(self, tmp_path, monkeypatch):
        stage, videos_dir = self._stage(tmp_path)
        monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task-1")
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: None)
        monkeypatch.setattr(stage, "_query_task_status", lambda task_id: "failed")

        ok = stage._generate_one("p", "vid_01", "model-x", "720p", None, None, videos_dir)

        assert ok is False
        data = self._budget_data(tmp_path)
        assert data["spent"] == 0.5
        assert len(data["entries"]) == 1
        entry = data["entries"][0]
        assert entry["kind"] == "video"
        assert entry["status"] == "failed"
        assert entry["detail"] == "vid_01"

    def test_failed_task_charged_exactly_once_across_reruns(self, tmp_path, monkeypatch):
        stage, videos_dir = self._stage(tmp_path)

        # Run 1: task created but still running at poll timeout — not charged.
        monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task-1")
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: None)
        monkeypatch.setattr(stage, "_query_task_status", lambda task_id: "running")
        assert (
            stage._generate_one("p", "vid_01", "model-x", "720p", None, None, videos_dir) is False
        )
        assert stage._budget_tracker.spent == 0.0

        # Run 2: resume the old paid task — it has failed (charged once).
        # The replacement task succeeds; its success charge happens in run(),
        # not in _generate_one, so it must not appear here.
        monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task-2")
        monkeypatch.setattr(
            stage,
            "_poll_task",
            lambda task_id: None if task_id == "task-1" else "https://example.com/v.mp4",
        )
        monkeypatch.setattr(stage, "_query_task_status", lambda task_id: "failed")

        def fake_download(url, dest, **kwargs):
            dest.write_bytes(b"\x00\x00\x00\x18ftypmp42")

        monkeypatch.setattr("narrascape.stages.generate_video.download_to_path", fake_download)
        monkeypatch.setattr("narrascape.stages.generate_video.validate_video", lambda path: True)

        assert stage._generate_one("p", "vid_01", "model-x", "720p", None, None, videos_dir) is True

        data = self._budget_data(tmp_path)
        assert data["spent"] == 0.5
        assert len(data["entries"]) == 1
        assert data["entries"][0]["status"] == "failed"

    def test_success_path_uses_try_spend_not_failed_entry(self, tmp_path, monkeypatch):
        stage, videos_dir = self._stage(tmp_path)
        monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task-1")
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: None)
        monkeypatch.setattr(stage, "_query_task_status", lambda task_id: "expired")

        ok = stage._generate_one("p", "vid_01", "model-x", "720p", None, None, videos_dir)

        assert ok is False
        data = self._budget_data(tmp_path)
        assert data["entries"][0]["status"] == "failed"
        assert data["entries"][0]["cost"] == 0.5
