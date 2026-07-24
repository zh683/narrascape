#!/usr/bin/env python3
"""Tests for opt-in layered parallel orchestration (max_workers > 1)."""

from __future__ import annotations

import threading
import time

from narrascape.config import NarrascapeConfig, PipelineConfig, ProjectConfig
from narrascape.pipeline import Pipeline, _resolve_dependency_levels
from narrascape.stages.base import StageResult


def _make_config(tmp_path, *, max_workers: int = 1) -> NarrascapeConfig:
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="parallel-test",
            title="Parallel Test",
            script_file="scripts/script.yaml",
        ),
        pipeline=PipelineConfig(max_workers=max_workers),
        project_dir=tmp_path,
    )
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "script.yaml").write_text(
        "segments:\n- id: 1\n  text: Test segment.\n",
        encoding="utf-8",
    )
    return config


def _fake_stage(name, depends_on=None, run_fn=None):
    attrs = {
        "name": name,
        "depends_on": depends_on or [],
        "can_run": lambda self, context: (True, ""),
        "run": run_fn or (lambda self, context: StageResult(name, True, message="ok")),
    }
    return type(f"Fake_{name}", (), attrs)


class TestDependencyLevels:
    def test_levels_grouping(self):
        stage_map = {
            "a": _fake_stage("a"),
            "b": _fake_stage("b", depends_on=["a"]),
            "c": _fake_stage("c", depends_on=["a"]),
            "d": _fake_stage("d", depends_on=["b", "c"]),
        }
        levels = _resolve_dependency_levels(["d"], stage_map)
        assert levels == [["a"], ["b", "c"], ["d"]]

    def test_levels_partial_target(self):
        stage_map = {
            "a": _fake_stage("a"),
            "b": _fake_stage("b", depends_on=["a"]),
            "c": _fake_stage("c", depends_on=["a"]),
        }
        # Only b requested: c is not pulled in.
        assert _resolve_dependency_levels(["b"], stage_map) == [["a"], ["b"]]

    def test_levels_detect_cycles(self):
        stage_map = {
            "a": _fake_stage("a", depends_on=["b"]),
            "b": _fake_stage("b", depends_on=["a"]),
        }
        try:
            _resolve_dependency_levels(["a"], stage_map)
        except RuntimeError as exc:
            assert "Circular" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected RuntimeError")


class TestWorkerConfig:
    def test_config_fallback_and_clamp(self, tmp_path):
        config = _make_config(tmp_path, max_workers=3)
        assert Pipeline(config).max_workers == 3
        assert Pipeline(config, max_workers=99).max_workers == 16
        assert Pipeline(config, max_workers=0).max_workers == 1

    def test_interactive_forces_serial(self, tmp_path):
        config = _make_config(tmp_path, max_workers=8)
        pipeline = Pipeline(config, interactive=True)
        assert pipeline.max_workers == 1


class TestParallelExecution:
    def test_same_layer_stages_run_concurrently(self, tmp_path, monkeypatch):
        barrier = threading.Barrier(2)
        calls: list[str] = []

        def make_run(stage_name):
            def run(self, context):
                calls.append(stage_name)
                # Broken barrier (i.e. serial execution) raises and fails the stage.
                barrier.wait(timeout=15)
                return StageResult(stage_name, True, message="ok")

            return run

        monkeypatch.setattr(
            "narrascape.pipeline.STAGE_MAP",
            {
                "s1": _fake_stage("s1", run_fn=make_run("s1")),
                "s2": _fake_stage("s2", run_fn=make_run("s2")),
            },
        )
        config = _make_config(tmp_path)
        results = Pipeline(config, auto_approve=True, max_workers=4).run(stages=["s1", "s2"])

        assert sorted(calls) == ["s1", "s2"]
        assert all(r.success for r in results.values())

    def test_results_ordered_by_execution_order_not_completion(self, tmp_path, monkeypatch):
        def slow_run(self, context):
            time.sleep(0.3)
            return StageResult("aaa", True, message="ok")

        monkeypatch.setattr(
            "narrascape.pipeline.STAGE_MAP",
            {
                "aaa": _fake_stage("aaa", run_fn=slow_run),
                "bbb": _fake_stage("bbb"),
            },
        )
        config = _make_config(tmp_path)
        results = Pipeline(config, auto_approve=True, max_workers=4).run(stages=["aaa", "bbb"])

        # aaa finishes last but must come first (registry/execution order).
        assert list(results.keys()) == ["aaa", "bbb"]

    def test_failure_halts_at_level_boundary(self, tmp_path, monkeypatch):
        ran: list[str] = []

        def failing_run(self, context):
            ran.append("bad")
            time.sleep(0.05)
            return StageResult("bad", False, message="boom")

        def slow_ok_run(self, context):
            ran.append("slow")
            time.sleep(0.3)
            return StageResult("slow", True, message="ok")

        def downstream_run(self, context):
            ran.append("downstream")
            return StageResult("downstream", True, message="ok")

        monkeypatch.setattr(
            "narrascape.pipeline.STAGE_MAP",
            {
                "bad": _fake_stage("bad", run_fn=failing_run),
                "slow": _fake_stage("slow", run_fn=slow_ok_run),
                "downstream": _fake_stage(
                    "downstream", depends_on=["bad", "slow"], run_fn=downstream_run
                ),
            },
        )
        config = _make_config(tmp_path)
        pipeline = Pipeline(config, auto_approve=True, max_workers=4)
        results = pipeline.run(stages=["downstream"])

        # Same-level sibling runs to completion despite the failure.
        assert sorted(ran) == ["bad", "slow"]
        assert results["bad"].success is False
        assert results["slow"].success is True
        # Later level never starts and is marked pending.
        assert "downstream" not in results
        assert pipeline.state.get_stage_status("downstream") == "pending"

    def test_review_request_covers_whole_level(self, tmp_path, monkeypatch):
        """Non-auto mode: every successful stage of the level gets a review
        request before the halt (serial stops after the first one)."""
        ran: list[str] = []

        def make_run(stage_name):
            def run(self, context):
                ran.append(stage_name)
                return StageResult(stage_name, True, message="ok")

            return run

        monkeypatch.setattr(
            "narrascape.pipeline.STAGE_MAP",
            {
                "s1": _fake_stage("s1", run_fn=make_run("s1")),
                "s2": _fake_stage("s2", run_fn=make_run("s2")),
            },
        )
        config = _make_config(tmp_path)
        results = Pipeline(config, max_workers=4).run(stages=["s1", "s2"])

        assert sorted(ran) == ["s1", "s2"]
        assert all(r.success for r in results.values())
        assert pipeline_approval_pending(config, "s1")
        assert pipeline_approval_pending(config, "s2")

    def test_pending_halt_pre_gate_skips_level_execution(self, tmp_path, monkeypatch):
        """A completed+pending stage halts the run in pre-gate; already-gated
        runnable stages of the same level are not executed."""
        ran: list[str] = []

        def make_run(stage_name):
            def run(self, context):
                ran.append(stage_name)
                output = context.config.pipeline_dir / f"{stage_name}.txt"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("ok", encoding="utf-8")
                return StageResult(stage_name, True, outputs=[output], message="ok")

            return run

        monkeypatch.setattr(
            "narrascape.pipeline.STAGE_MAP",
            {
                "s1": _fake_stage("s1", run_fn=make_run("s1")),
                "s2": _fake_stage("s2", run_fn=make_run("s2")),
            },
        )
        config = _make_config(tmp_path)
        # First build: both complete, both pending review.
        Pipeline(config, max_workers=4).run(stages=["s1", "s2"])
        assert sorted(ran) == ["s1", "s2"]

        # Approve only s1. Second build: s2 is completed+pending -> pre-gate
        # halt; s1 is skipped (cached+approved); nothing re-runs.
        pipeline = Pipeline(config, max_workers=4)
        pipeline.approval.approve("s1", reviewer="test")
        results = pipeline.run(stages=["s1", "s2"])

        assert sorted(ran) == ["s1", "s2"]  # no re-execution
        assert results["s1"].success is True
        assert results["s2"].metadata.get("awaiting_approval") is True

    def test_active_stage_attribution_is_thread_local(self, tmp_path, monkeypatch):
        barrier = threading.Barrier(2)
        holder: dict = {}
        seen: dict[str, str] = {}

        def make_run(stage_name):
            def run(self, context):
                barrier.wait(timeout=15)
                seen[stage_name] = holder["pipeline"]._current_active_stage()
                return StageResult(stage_name, True, message="ok")

            return run

        monkeypatch.setattr(
            "narrascape.pipeline.STAGE_MAP",
            {
                "s1": _fake_stage("s1", run_fn=make_run("s1")),
                "s2": _fake_stage("s2", run_fn=make_run("s2")),
            },
        )
        config = _make_config(tmp_path)
        pipeline = Pipeline(config, auto_approve=True, max_workers=4)
        holder["pipeline"] = pipeline
        results = pipeline.run(stages=["s1", "s2"])

        assert all(r.success for r in results.values())
        # Each worker thread saw its own stage, not the sibling's.
        assert seen == {"s1": "s1", "s2": "s2"}
        # Main-thread mirror is cleared after the run.
        assert pipeline._current_active_stage() == ""


def pipeline_approval_pending(config: NarrascapeConfig, stage_name: str) -> bool:
    from narrascape.pipeline_approval import PipelineApproval

    return PipelineApproval(config.pipeline_dir).get_status(stage_name) == "pending"
