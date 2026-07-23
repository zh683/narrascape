#!/usr/bin/env python3
"""Tests for opt-in submit-all -> poll-all video pipelining (video.max_concurrency > 1).

Covers the invariants that distinguish the pipelined path from the serial
per-take lifecycle: batch submission, unified polling, failure isolation,
exactly-once cost accounting, fingerprint cache / free re-download, crash
resume, budget-cap rechecks, Agnes creation cadence, and 429 exemption.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import yaml

from narrascape.config import (
    AudioConfig,
    ImageConfig,
    ImageProvider,
    MusicAudioConfig,
    MusicProvider,
    NarrascapeConfig,
    ProjectConfig,
    TTSConfig,
    TTSProvider,
    VideoConfig,
    load_script,
)
from narrascape.stages.base import StageContext
from narrascape.stages.generate_video import GenerateVideoStage
from narrascape.utils.budget import BudgetTracker


def _write_project(project_dir: Path) -> None:
    (project_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump({"segments": [{"id": 1, "text": "One."}, {"id": 2, "text": "Two."}]}),
        encoding="utf-8",
    )
    (project_dir / "image_prompts.yaml").write_text(
        yaml.safe_dump(
            {
                "prompts": [
                    {"id": "img_01", "shot_type": "medium", "description": "First shot."},
                    {"id": "img_02", "shot_type": "medium", "description": "Second shot."},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(
            {
                "project_title": "Pipelined Test",
                "segments": [
                    {"segment_id": 1, "shot_type": "medium", "image_prompt": "First shot."},
                    {"segment_id": 2, "shot_type": "medium", "image_prompt": "Second shot."},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _fake_download(url, dest, **kwargs):
    dest.write_bytes(b"\x00\x00\x00\x18ftypmp42")


def _make_stage(tmp_path, monkeypatch, *, max_concurrency=4, video_max_poll_time=None, **kwargs):
    project_dir = tmp_path / "project"
    _write_project(project_dir)
    video_kwargs: dict = {"max_concurrency": max_concurrency}
    if video_max_poll_time is not None:
        video_kwargs["max_poll_time"] = video_max_poll_time
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="project",
            title="Pipelined Test",
            script_file="scripts/script.yaml",
        ),
        images=ImageConfig(provider=ImageProvider.LOCAL, width=640, height=480),
        tts=TTSConfig(provider=TTSProvider.LOCAL),
        audio=AudioConfig(music=MusicAudioConfig(provider=MusicProvider.LOCAL)),
        video=VideoConfig(**video_kwargs),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True, exist_ok=True)
    config.images_dir.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("api_key", "fake")
    kwargs.setdefault("poll_interval", 0)
    kwargs.setdefault("sleep_between", 0)
    stage = GenerateVideoStage(**kwargs)
    monkeypatch.setattr(stage, "_resolve_first_frame", lambda *a, **k: None)
    monkeypatch.setattr("narrascape.stages.generate_video.download_to_path", _fake_download)
    monkeypatch.setattr("narrascape.stages.generate_video.validate_video", lambda path: True)
    context = StageContext(config=config, script=load_script(config.script_path))
    return config, stage, context


class _FakeRemote:
    """Stateful fake of the Seedance create/status-query pair.

    ``behavior`` maps task_id -> list of (status, url, hint) responses; each
    poll pops the head, the last response sticks.
    """

    def __init__(self, stage, monkeypatch, behavior):
        self.created: list[str] = []
        self.create_threads: list[int] = []
        self.queries: list[str] = []
        self.created_at_first_query: int | None = None
        self.behavior = behavior
        monkeypatch.setattr(stage, "_create_task", self.create)
        monkeypatch.setattr(stage, "_query_task_status_detailed", self.query)

    def create(self, prompt, model, resolution, first_frame, last_frame, reference_images=None):
        self.created_threads_append()
        task_id = f"task-{len(self.created) + 1}"
        self.created.append(task_id)
        return task_id

    def created_threads_append(self):
        self.create_threads.append(threading.get_ident())

    def query(self, task_id):
        if not self.queries:
            self.created_at_first_query = len(self.created)
        self.queries.append(task_id)
        responses = self.behavior[task_id]
        if len(responses) > 1:
            return responses.pop(0)
        return responses[0]


def _ledger(config) -> dict:
    path = config.pipeline_dir / "video_tasks.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("tasks", {})


def _budget(config) -> dict:
    path = config.pipeline_dir / "budget_state.json"
    if not path.exists():
        return {"spent": 0.0, "entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _videos_dir(config) -> Path:
    return config.project_dir / "assets" / "videos"


class TestBatchSubmissionAndUnifiedPolling:
    def test_submit_all_before_polling_and_polls_interleave(self, tmp_path, monkeypatch):
        config, stage, context = _make_stage(tmp_path, monkeypatch)
        behavior = {
            "task-1": [("running", None, None), ("succeeded", "https://v/1.mp4", None)],
            "task-2": [("running", None, None), ("succeeded", "https://v/2.mp4", None)],
        }
        remote = _FakeRemote(stage, monkeypatch, behavior)

        result = stage.run(context)

        assert result.success is True
        assert result.metadata["pipelined"] is True
        assert sorted(remote.created) == ["task-1", "task-2"]
        # 全部任务在第一次轮询查询之前已提交（submit-all）
        assert remote.created_at_first_query == 2
        # 统一轮询：首轮查询覆盖两个不同任务（poll-all，非逐任务串行）
        assert set(remote.queries[:2]) == {"task-1", "task-2"}
        ledger = _ledger(config)
        assert {r["status"] for r in ledger.values()} == {"succeeded"}
        assert (_videos_dir(config) / "vid_01.mp4").exists()
        assert (_videos_dir(config) / "vid_02.mp4").exists()

    def test_default_config_keeps_serial_path(self, tmp_path, monkeypatch):
        config, stage, context = _make_stage(tmp_path, monkeypatch, max_concurrency=1)
        remote = _FakeRemote(
            stage,
            monkeypatch,
            {"task-1": [("succeeded", "https://v/1.mp4", None)]},
        )
        # 串行路径：任务 2 要等到任务 1 完整结束后才创建
        created_before_second_create = []
        original_create = remote.create

        def tracking_create(*args, **kwargs):
            created_before_second_create.append(list(remote.queries))
            return original_create(*args, **kwargs)

        monkeypatch.setattr(stage, "_create_task", tracking_create)
        monkeypatch.setattr(stage, "_poll_task", lambda task_id: f"https://v/{task_id}.mp4")

        result = stage.run(context)

        assert result.success is True
        assert "pipelined" not in result.metadata
        assert len(remote.created) == 2


class TestFailureIsolationAndAccounting:
    def test_one_failure_does_not_block_others_and_accounts_exactly_once(
        self, tmp_path, monkeypatch
    ):
        config, stage, context = _make_stage(tmp_path, monkeypatch)
        behavior = {
            "task-1": [("failed", None, None)],
            "task-2": [("succeeded", "https://v/2.mp4", None)],
        }
        _FakeRemote(stage, monkeypatch, behavior)

        result = stage.run(context)

        assert result.success is False
        assert result.metadata["ok_count"] == 1
        assert result.metadata["fail_count"] == 1

        ledger = _ledger(config)
        statuses = {name: r["status"] for name, r in ledger.items()}
        assert sorted(statuses.values()) == ["failed", "succeeded"]
        failed_out = next(name for name, s in statuses.items() if s == "failed")
        ok_out = next(name for name, s in statuses.items() if s == "succeeded")

        # 恰好一次记账：失败任务一条 record_actual(failed)，成功任务一条 try_spend
        entries = _budget(config)["entries"]
        failed_entries = [e for e in entries if e["status"] == "failed"]
        success_entries = [e for e in entries if e["status"] == "success"]
        assert len(failed_entries) == 1
        assert failed_entries[0]["detail"] == failed_out
        assert failed_entries[0]["kind"] == "video"
        assert len(success_entries) == 1
        assert success_entries[0]["detail"] == ok_out

    def test_creation_failure_fails_only_its_take_without_billing(self, tmp_path, monkeypatch):
        config, stage, context = _make_stage(tmp_path, monkeypatch)
        calls = []

        def flaky_create(prompt, model, resolution, first_frame, last_frame, reference_images=None):
            calls.append(1)
            if len(calls) == 1:
                return None  # 网络失败：任务不存在，未计费
            return "task-9"

        monkeypatch.setattr(stage, "_create_task", flaky_create)
        monkeypatch.setattr(
            stage,
            "_query_task_status_detailed",
            lambda task_id: ("succeeded", "https://v/9.mp4", None),
        )

        result = stage.run(context)

        assert result.success is False
        assert result.metadata["ok_count"] == 1
        assert result.metadata["fail_count"] == 1
        # 创建失败零计费：只有成功 take 的一条记账
        entries = _budget(config)["entries"]
        assert len(entries) == 1
        assert entries[0]["status"] == "success"


class TestCacheFingerprintAndRedownload:
    def test_cached_skip_and_free_redownload_in_pipelined_mode(self, tmp_path, monkeypatch):
        # Run 1：正常生成成功
        config, stage, context = _make_stage(tmp_path, monkeypatch)
        _FakeRemote(
            stage,
            monkeypatch,
            {
                "task-1": [("succeeded", "https://v/1.mp4", None)],
                "task-2": [("succeeded", "https://v/2.mp4", None)],
            },
        )
        assert stage.run(context).success is True

        forbidden = lambda *a, **k: (_ for _ in ()).throw(  # noqa: E731
            AssertionError("must not create/poll paid tasks")
        )

        # Run 2：指纹匹配 + 文件存在 + done → 全部 cached skip
        config2, stage2, context2 = _make_stage(tmp_path, monkeypatch)
        monkeypatch.setattr(stage2, "_create_task", forbidden)
        monkeypatch.setattr(stage2, "_query_task_status_detailed", forbidden)
        downloads = []
        monkeypatch.setattr(
            "narrascape.stages.generate_video.download_to_path",
            lambda url, dest, **kw: downloads.append(url) or _fake_download(url, dest),
        )
        result2 = stage2.run(context2)
        assert result2.success is True
        assert downloads == []

        # 删掉产物 → Run 3：台账 succeeded 记录支持免费重下载，不重新付费
        for mp4 in _videos_dir(config2).glob("*.mp4"):
            mp4.unlink()
        config3, stage3, context3 = _make_stage(tmp_path, monkeypatch)
        monkeypatch.setattr(stage3, "_create_task", forbidden)
        monkeypatch.setattr(stage3, "_query_task_status_detailed", forbidden)
        downloads3 = []
        monkeypatch.setattr(
            "narrascape.stages.generate_video.download_to_path",
            lambda url, dest, **kw: downloads3.append(url) or _fake_download(url, dest),
        )
        result3 = stage3.run(context3)
        assert result3.success is True
        assert sorted(downloads3) == ["https://v/1.mp4", "https://v/2.mp4"]


class TestCrashResume:
    def test_crash_after_submit_resumes_without_repaid_creation(self, tmp_path, monkeypatch):
        # Run 1：提交后轮询超时（模拟崩溃/超时），台账保持可续跑
        config, stage, context = _make_stage(tmp_path, monkeypatch, video_max_poll_time=0.05)
        remote1 = _FakeRemote(
            stage,
            monkeypatch,
            {
                "task-1": [("running", None, None)],
                "task-2": [("running", None, None)],
            },
        )
        result1 = stage.run(context)
        assert result1.success is False
        assert result1.metadata["fail_count"] == 2
        ledger1 = _ledger(config)
        assert {r["status"] for r in ledger1.values()} == {"polling"}
        original_tasks = {name: r["task_id"] for name, r in ledger1.items()}

        # Run 2：已提交任务走续跑路径，绝不重新付费创建
        config2, stage2, context2 = _make_stage(tmp_path, monkeypatch)

        def forbidden_create(*a, **k):
            raise AssertionError("must not create a new paid task")

        monkeypatch.setattr(stage2, "_create_task", forbidden_create)
        queried: list[str] = []

        def resume_query(task_id):
            queried.append(task_id)
            return "succeeded", f"https://v/{task_id}.mp4", None

        monkeypatch.setattr(stage2, "_query_task_status_detailed", resume_query)
        result2 = stage2.run(context2)

        assert result2.success is True
        # 续跑用的正是 Run 1 的原始 task_id
        assert set(queried) == set(original_tasks.values())
        ledger2 = _ledger(config2)
        assert {r["status"] for r in ledger2.values()} == {"succeeded"}
        # 崩溃恢复恰好一次：本轮只有两条成功记账（无失败补记）
        entries = _budget(config2)["entries"]
        assert len([e for e in entries if e["status"] == "failed"]) == 0
        assert len([e for e in entries if e["status"] == "success"]) == 2


class TestBudgetCap:
    def test_submit_recheck_blocks_creation_when_capped(self, tmp_path, monkeypatch):
        config, stage, context = _make_stage(tmp_path, monkeypatch)
        can_spend_calls = []

        original_can_spend = BudgetTracker.can_spend

        def capped_can_spend(self, estimated_cost):
            can_spend_calls.append(1)
            if len(can_spend_calls) == 1:
                return original_can_spend(self, estimated_cost)  # 总预检放行
            return False, "budget cap exceeded"  # 提交前复查拦截

        monkeypatch.setattr(BudgetTracker, "can_spend", capped_can_spend)
        forbidden = lambda *a, **k: (_ for _ in ()).throw(  # noqa: E731
            AssertionError("must not create paid tasks over the cap")
        )
        monkeypatch.setattr(stage, "_create_task", forbidden)

        result = stage.run(context)

        assert result.success is False
        assert "budget cap exceeded" in result.message
        assert _ledger(config) == {}


class TestAgnesPipelined:
    def _agnes_selection(self):
        return SimpleNamespace(
            tool=SimpleNamespace(
                name="agnes_video",
                provider="agnes",
                requires=[],
                capability=SimpleNamespace(value="video_generation"),
            ),
            alternatives=[],
            score=1.0,
            reason="test",
        )

    def test_agnes_submissions_are_serialized_with_creation_cadence(self, tmp_path, monkeypatch):
        config, stage, context = _make_stage(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "narrascape.stages.generate_video.select_provider",
            lambda *a, **k: self._agnes_selection(),
        )
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

        create_threads: list[int] = []
        created: list[str] = []

        def fake_create_agnes(prompt, model, resolution, first_frame, last_frame, **kwargs):
            create_threads.append(threading.get_ident())
            n = len(created) + 1
            created.append(f"agnes-task-{n}")
            return f"agnes-task-{n}", f"video-{n}"

        monkeypatch.setattr(stage, "_create_agnes_task", fake_create_agnes)
        monkeypatch.setattr(
            stage,
            "_query_agnes_task_status_detailed",
            lambda task_id=None, video_id=None: (
                "succeeded",
                f"https://v/{video_id}.mp4",
                None,
            ),
        )

        result = stage.run(context)

        assert result.success is True
        assert len(created) == 2
        # 串行提交（同一线程）+ ≥65s 创建间隔在提交阶段保留
        assert len(set(create_threads)) == 1
        assert 65.0 in sleeps
        ledger = _ledger(config)
        assert {r["status"] for r in ledger.values()} == {"succeeded"}


class TestRateLimitExemption:
    def test_429_backoff_does_not_count_as_error(self, tmp_path, monkeypatch):
        # max_poll_errors=1：任何被计数的错误都会立即中止任务
        config, stage, context = _make_stage(tmp_path, monkeypatch, max_poll_errors=1)
        behavior = {
            "task-1": [("rate_limited", None, 0.2), ("succeeded", "https://v/1.mp4", None)],
            "task-2": [("succeeded", "https://v/2.mp4", None)],
        }
        remote = _FakeRemote(stage, monkeypatch, behavior)

        result = stage.run(context)

        # 429 豁免错误计数：任务最终成功而非被 max_poll_errors=1 中止
        assert result.success is True
        assert remote.queries.count("task-1") == 2
        assert {r["status"] for r in _ledger(config).values()} == {"succeeded"}
