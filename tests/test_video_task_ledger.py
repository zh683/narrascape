#!/usr/bin/env python3
"""Regression tests for the paid video task ledger and resume-after-crash flow."""

from __future__ import annotations

import json

from narrascape.config import NarrascapeConfig, ProjectConfig, VideoConfig
from narrascape.stages.generate_video import GenerateVideoStage
from narrascape.stages.generate_video_services import (
    VideoTaskLedger,
    video_task_prompt_hash,
)


def _stage_with_ledger(tmp_path, **kwargs):
    kwargs.setdefault("api_key", "fake")
    kwargs.setdefault("poll_interval", 0)
    stage = GenerateVideoStage(**kwargs)
    stage._task_ledger = VideoTaskLedger(tmp_path / "video_tasks.json")
    return stage


def _mock_download(monkeypatch):
    def fake_download(url, dest, **kwargs):
        dest.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    monkeypatch.setattr("narrascape.stages.generate_video.download_to_path", fake_download)
    monkeypatch.setattr("narrascape.stages.generate_video.validate_video", lambda path: True)


def _videos_dir(tmp_path):
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(exist_ok=True)
    return videos_dir


def _hash(prompt, provider="seedance", model="model-x", resolution="720p"):
    return video_task_prompt_hash(
        provider=provider, model=model, resolution=resolution, prompt=prompt
    )


class TestLedgerPersistence:
    def test_record_created_writes_submitted_immediately(self, tmp_path):
        ledger = VideoTaskLedger(tmp_path / "video_tasks.json")

        ledger.record_created(
            "vid_02",
            task_id="task-9",
            provider="seedance",
            prompt_hash="h",
            model="m",
            resolution="720p",
            output_path="assets/videos/vid_02.mp4",
            cost_estimate=0.5,
        )

        path = tmp_path / "video_tasks.json"
        assert path.exists()
        record = json.loads(path.read_text(encoding="utf-8"))["tasks"]["vid_02"]
        assert record["task_id"] == "task-9"
        assert record["provider"] == "seedance"
        assert record["prompt_hash"] == "h"
        assert record["model"] == "m"
        assert record["resolution"] == "720p"
        assert record["status"] == "submitted"
        assert record["take"] == 1
        assert record["cost_estimate"] == 0.5
        assert record["output_path"] == "assets/videos/vid_02.mp4"
        assert record["created_at"]
        assert record["updated_at"]

    def test_take_number_parsed_from_multi_take_name(self, tmp_path):
        ledger = VideoTaskLedger(tmp_path / "video_tasks.json")

        ledger.record_created(
            "vid_01_take_03",
            task_id="task-t3",
            provider="seedance",
            prompt_hash="h",
            model="m",
            resolution="720p",
            output_path="assets/videos/vid_01_take_03.mp4",
        )

        assert ledger.get("vid_01_take_03")["take"] == 3

    def test_create_task_persists_ledger_record(self, tmp_path, monkeypatch):
        stage = _stage_with_ledger(tmp_path)
        stage._per_task_cost_estimate = 0.5
        monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task-123")
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: "https://example.com/v.mp4")
        _mock_download(monkeypatch)

        ok = stage._generate_one(
            "a prompt", "vid_01", "model-x", "720p", None, None, _videos_dir(tmp_path)
        )

        assert ok is True
        record = json.loads((tmp_path / "video_tasks.json").read_text(encoding="utf-8"))["tasks"][
            "vid_01"
        ]
        assert record["task_id"] == "task-123"
        assert record["prompt_hash"] == _hash("a prompt")
        assert record["status"] == "succeeded"
        assert record["video_url"] == "https://example.com/v.mp4"
        assert record["cost_estimate"] == 0.5


class TestResumeAfterCrash:
    def test_rerun_resumes_unfinished_task_without_creating(self, tmp_path, monkeypatch):
        stage = _stage_with_ledger(tmp_path)
        ledger = stage._task_ledger
        ledger.record_created(
            "vid_01",
            task_id="task-old",
            provider="seedance",
            prompt_hash=_hash("p"),
            model="model-x",
            resolution="720p",
            output_path="assets/videos/vid_01.mp4",
        )

        def forbidden_create(*args, **kwargs):
            raise AssertionError("must not create a new paid task")

        monkeypatch.setattr(stage, "_create_task", forbidden_create)
        polled = []
        monkeypatch.setattr(
            stage,
            "_poll_task",
            lambda task_id: polled.append(task_id) or "https://example.com/v.mp4",
        )
        _mock_download(monkeypatch)

        ok = stage._generate_one(
            "p", "vid_01", "model-x", "720p", None, None, _videos_dir(tmp_path)
        )

        assert ok is True
        assert polled == ["task-old"]
        assert ledger.get("vid_01")["status"] == "succeeded"

    def test_agnes_rerun_resumes_with_task_and_video_id(self, tmp_path, monkeypatch):
        stage = _stage_with_ledger(tmp_path)
        ledger = stage._task_ledger
        ledger.record_created(
            "vid_01",
            task_id="t-old",
            video_id="v-old",
            provider="agnes",
            prompt_hash=_hash("p", provider="agnes", model="agnes-video-v2.0"),
            model="agnes-video-v2.0",
            resolution="720p",
            output_path="assets/videos/vid_01.mp4",
        )

        def forbidden_create(*args, **kwargs):
            raise AssertionError("must not create a new paid task")

        monkeypatch.setattr(stage, "_create_agnes_task", forbidden_create)
        polled = []

        def fake_poll(task_id=None, video_id=None):
            polled.append((task_id, video_id))
            return "https://example.com/v.mp4"

        monkeypatch.setattr(stage, "_poll_agnes_task", fake_poll)
        _mock_download(monkeypatch)

        ok = stage._generate_one(
            "p",
            "vid_01",
            "agnes-video-v2.0",
            "720p",
            None,
            None,
            _videos_dir(tmp_path),
            provider="agnes",
        )

        assert ok is True
        assert polled == [("t-old", "v-old")]

    def test_failed_remote_task_is_cleaned_and_recreated(self, tmp_path, monkeypatch):
        stage = _stage_with_ledger(tmp_path)
        ledger = stage._task_ledger
        ledger.record_created(
            "vid_01",
            task_id="task-old",
            provider="seedance",
            prompt_hash=_hash("p"),
            model="model-x",
            resolution="720p",
            output_path="assets/videos/vid_01.mp4",
        )

        polls = []

        def fake_poll(task_id):
            polls.append(task_id)
            return None if task_id == "task-old" else "https://example.com/v.mp4"

        monkeypatch.setattr(stage, "_poll_task", fake_poll)
        monkeypatch.setattr(stage, "_query_task_status", lambda task_id: "failed")
        monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task-new")
        _mock_download(monkeypatch)

        ok = stage._generate_one(
            "p", "vid_01", "model-x", "720p", None, None, _videos_dir(tmp_path)
        )

        assert ok is True
        assert polls == ["task-old", "task-new"]
        record = ledger.get("vid_01")
        assert record["task_id"] == "task-new"
        assert record["status"] == "succeeded"

    def test_not_found_remote_task_is_cleaned_and_recreated(self, tmp_path, monkeypatch):
        stage = _stage_with_ledger(tmp_path)
        ledger = stage._task_ledger
        ledger.record_created(
            "vid_01",
            task_id="task-old",
            provider="seedance",
            prompt_hash=_hash("p"),
            model="model-x",
            resolution="720p",
            output_path="assets/videos/vid_01.mp4",
        )

        polls = []

        def fake_poll(task_id):
            polls.append(task_id)
            return None if task_id == "task-old" else "https://example.com/v.mp4"

        monkeypatch.setattr(stage, "_poll_task", fake_poll)
        monkeypatch.setattr(stage, "_query_task_status", lambda task_id: "not_found")
        monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task-new")
        _mock_download(monkeypatch)

        ok = stage._generate_one(
            "p", "vid_01", "model-x", "720p", None, None, _videos_dir(tmp_path)
        )

        assert ok is True
        assert polls == ["task-old", "task-new"]
        assert ledger.get("vid_01")["task_id"] == "task-new"

    def test_prompt_change_creates_new_task_and_supersedes_old(self, tmp_path, monkeypatch):
        stage = _stage_with_ledger(tmp_path)
        ledger = stage._task_ledger
        ledger.record_created(
            "vid_01",
            task_id="task-old",
            provider="seedance",
            prompt_hash=_hash("old prompt"),
            model="model-x",
            resolution="720p",
            output_path="assets/videos/vid_01.mp4",
        )

        monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task-new")
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: "https://example.com/v.mp4")
        _mock_download(monkeypatch)

        ok = stage._generate_one(
            "new prompt", "vid_01", "model-x", "720p", None, None, _videos_dir(tmp_path)
        )

        assert ok is True
        record = ledger.get("vid_01")
        assert record["task_id"] == "task-new"
        history = record["history"]
        assert len(history) == 1
        assert history[0]["task_id"] == "task-old"
        assert history[0]["status"] == "superseded"

    def test_poll_timeout_keeps_task_resumable_for_next_run(self, tmp_path, monkeypatch):
        stage = _stage_with_ledger(tmp_path)
        ledger = stage._task_ledger
        monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task-1")
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: None)  # timed out
        monkeypatch.setattr(stage, "_query_task_status", lambda task_id: "running")

        ok = stage._generate_one(
            "p", "vid_01", "model-x", "720p", None, None, _videos_dir(tmp_path)
        )

        assert ok is False
        record = ledger.get("vid_01")
        assert record["task_id"] == "task-1"
        assert record["status"] == "polling"

        # Next run resumes the same paid task instead of creating a new one.
        def forbidden_create(*args, **kwargs):
            raise AssertionError("must not create a new paid task")

        monkeypatch.setattr(stage, "_create_task", forbidden_create)
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: "https://example.com/v.mp4")
        _mock_download(monkeypatch)

        ok = stage._generate_one(
            "p", "vid_01", "model-x", "720p", None, None, _videos_dir(tmp_path)
        )

        assert ok is True

    def test_succeeded_record_redownloads_without_polling(self, tmp_path, monkeypatch):
        stage = _stage_with_ledger(tmp_path)
        ledger = stage._task_ledger
        ledger.record_created(
            "vid_01",
            task_id="task-old",
            provider="seedance",
            prompt_hash=_hash("p"),
            model="model-x",
            resolution="720p",
            output_path="assets/videos/vid_01.mp4",
        )
        ledger.update_status("vid_01", "succeeded", video_url="https://example.com/v.mp4")

        def forbidden(*args, **kwargs):
            raise AssertionError("must not contact the provider")

        monkeypatch.setattr(stage, "_create_task", forbidden)
        monkeypatch.setattr(stage, "_poll_task", forbidden)
        _mock_download(monkeypatch)

        ok = stage._generate_one(
            "p", "vid_01", "model-x", "720p", None, None, _videos_dir(tmp_path)
        )

        assert ok is True
        assert (tmp_path / "videos" / "vid_01.mp4").exists()


class TestMaxPollTimeConfig:
    def test_default_is_backward_compatible(self):
        assert VideoConfig().max_poll_time == 900.0

    def test_explicit_value_accepted(self):
        assert VideoConfig(max_poll_time=42.0).max_poll_time == 42.0

    def _config(self, tmp_path, **video_kwargs):
        return NarrascapeConfig(
            project=ProjectConfig(
                name="poll-config-test",
                title="Poll Config Test",
                script_file="scripts/script.yaml",
            ),
            video=VideoConfig(**video_kwargs),
            project_dir=tmp_path,
        )

    def test_stage_applies_default_from_config(self, tmp_path):
        stage = GenerateVideoStage(api_key="fake", max_poll_time=300.0)

        stage._apply_video_config(self._config(tmp_path), "seedance")

        assert stage.max_poll_time == 900.0

    def test_stage_applies_explicit_config_value(self, tmp_path):
        stage = GenerateVideoStage(api_key="fake")

        stage._apply_video_config(self._config(tmp_path, max_poll_time=120.0), "seedance")

        assert stage.max_poll_time == 120.0
