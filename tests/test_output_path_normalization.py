#!/usr/bin/env python3
"""Regression tests for state.json output-path normalization.

Bug: with a relative-path project (``narrascape build -p sub/proj``), stage
results already carry cwd-relative display paths that include the project_dir
prefix; ``_recordable_outputs`` blindly joined project_dir again, recording
double-prefixed paths that never exist. Every subsequent build then reported
"Completed state ignored because recorded outputs are missing", silently
disabling incremental skips and the completed+pending approval halt.
"""

from __future__ import annotations

from pathlib import Path

from narrascape.config import NarrascapeConfig, ProjectConfig
from narrascape.pipeline import Pipeline
from narrascape.stages.base import StageResult


def _write_script(project_dir: Path) -> None:
    (project_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        "segments:\n- id: 1\n  text: Test segment.\n",
        encoding="utf-8",
    )


def _fake_stage_class(calls: list[str]):
    class FakeStage:
        name = "fake"
        depends_on = []

        def can_run(self, context):
            return True, ""

        def run(self, context):
            calls.append("fake")
            output = context.config.pipeline_dir / "fake.txt"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok", encoding="utf-8")
            return StageResult("fake", True, outputs=[output], message="ok")

    return FakeStage


def _relative_project_config(tmp_path: Path, monkeypatch, name: str = "rel-proj"):
    """Config whose project_dir is RELATIVE to the current cwd (like -p sub/proj)."""
    monkeypatch.chdir(tmp_path)
    project_dir = Path("proj")
    _write_script(project_dir)
    return NarrascapeConfig(
        project=ProjectConfig(name=name, title="Rel", script_file="scripts/script.yaml"),
        project_dir=project_dir,
    )


class TestRelativeProjectDirIncremental:
    def test_records_project_relative_and_skips_on_second_run(self, tmp_path, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr("narrascape.pipeline.STAGE_MAP", {"fake": _fake_stage_class(calls)})
        config = _relative_project_config(tmp_path, monkeypatch)

        first = Pipeline(config)
        results = first.run(stages=["fake"])
        assert results["fake"].success is True

        # Recorded as project_dir-relative (no duplicated prefix).
        recorded = first.state.get_stage_outputs("fake")
        assert recorded == ["pipeline/rel-proj/fake.txt"]

        first.approval.approve("fake", reviewer="test")

        # Fresh process: completed + approved must skip WITHOUT re-running.
        second = Pipeline(config)
        results = second.run(stages=["fake"])

        assert calls == ["fake"]
        assert results["fake"].success is True
        assert "skipped (cached + approved)" in results["fake"].message

    def test_completed_pending_halts_without_rerun(self, tmp_path, monkeypatch):
        """P1-1 halt linkage: completed + pending + outputs present must halt.

        Before the normalization fix, the recorded outputs never existed, so
        this branch was unreachable for relative-path projects with real
        outputs — the stage was silently re-run (repeating LLM calls).
        """
        calls: list[str] = []
        monkeypatch.setattr("narrascape.pipeline.STAGE_MAP", {"fake": _fake_stage_class(calls)})
        config = _relative_project_config(tmp_path, monkeypatch)

        results = Pipeline(config).run(stages=["fake"])
        assert results["fake"].success is True

        # Fresh process, no --approve: halt at the pending gate.
        results = Pipeline(config).run(stages=["fake"])

        assert calls == ["fake"]  # not re-run
        assert results["fake"].success is True
        assert results["fake"].metadata["awaiting_approval"] is True


class TestOutputPathForms:
    def test_absolute_project_dir_records_project_relative(self, tmp_path, monkeypatch):
        project_dir = tmp_path / "proj"
        _write_script(project_dir)
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="form-proj", title="Forms", script_file="scripts/script.yaml"
            ),
            project_dir=project_dir,
        )
        config.pipeline_dir.mkdir(parents=True)
        pipeline = Pipeline(config)

        inside = config.pipeline_dir / "a.txt"
        outside = tmp_path / "elsewhere.txt"
        recorded = pipeline._recordable_outputs(StageResult("s", True, outputs=[inside, outside]))

        assert recorded[0] == "pipeline/form-proj/a.txt"
        # Outputs outside the project keep their absolute form.
        assert recorded[1] == str(outside)

        inside.write_text("ok", encoding="utf-8")
        assert pipeline._recorded_output_exists(recorded[0]) is True

    def test_dot_project_dir_is_idempotent(self, tmp_path, monkeypatch):
        project_dir = tmp_path / "proj"
        _write_script(project_dir)
        monkeypatch.chdir(project_dir)
        config = NarrascapeConfig(
            project=ProjectConfig(name="dot-proj", title="Dot", script_file="scripts/script.yaml"),
            project_dir=Path("."),
        )
        config.pipeline_dir.mkdir(parents=True)
        pipeline = Pipeline(config)

        display = config.pipeline_dir / "a.txt"  # already relative: pipeline/dot-proj/a.txt
        recorded = pipeline._recordable_outputs(StageResult("s", True, outputs=[display]))

        assert recorded == ["pipeline/dot-proj/a.txt"]
        display.write_text("ok", encoding="utf-8")
        assert pipeline._recorded_output_exists(recorded[0]) is True

    def test_relative_project_dir_strips_display_prefix(self, tmp_path, monkeypatch):
        config = _relative_project_config(tmp_path, monkeypatch, name="disp-proj")
        config.pipeline_dir.mkdir(parents=True)
        pipeline = Pipeline(config)

        display = config.pipeline_dir / "a.txt"  # proj/pipeline/disp-proj/a.txt (relative)
        bare = Path("pipeline/disp-proj/b.txt")
        recorded = pipeline._recordable_outputs(StageResult("s", True, outputs=[display, bare]))

        assert recorded == ["pipeline/disp-proj/a.txt", "pipeline/disp-proj/b.txt"]

        display.parent.mkdir(parents=True, exist_ok=True)
        display.write_text("ok", encoding="utf-8")
        assert pipeline._recorded_output_exists(recorded[0]) is True


class TestLegacyDoublePrefixedRecords:
    def test_double_prefixed_record_passes_check_via_migration(self, tmp_path, monkeypatch):
        config = _relative_project_config(tmp_path, monkeypatch, name="legacy-proj")
        pipeline = Pipeline(config)

        real_file = config.pipeline_dir / "fake.txt"
        real_file.parent.mkdir(parents=True, exist_ok=True)
        real_file.write_text("ok", encoding="utf-8")

        # Legacy record written by the join bug: display path prefixed twice.
        legacy = "proj/proj/pipeline/legacy-proj/fake.txt"
        assert pipeline._recorded_output_exists(legacy) is True

    def test_double_prefixed_record_missing_file_still_missing(self, tmp_path, monkeypatch):
        config = _relative_project_config(tmp_path, monkeypatch, name="legacy-proj")
        pipeline = Pipeline(config)

        legacy = "proj/proj/pipeline/legacy-proj/gone.txt"
        # Nothing on disk anywhere: still reported missing (self-heal rerun path).
        assert pipeline._recorded_output_exists(legacy) is False

    def test_absolute_legacy_record_unchanged(self, tmp_path, monkeypatch):
        config = _relative_project_config(tmp_path, monkeypatch)
        pipeline = Pipeline(config)

        absolute = tmp_path / "some" / "artifact.yaml"
        absolute.parent.mkdir(parents=True)
        absolute.write_text("ok", encoding="utf-8")
        assert pipeline._recorded_output_exists(str(absolute)) is True
        absolute.unlink()
        assert pipeline._recorded_output_exists(str(absolute)) is False
