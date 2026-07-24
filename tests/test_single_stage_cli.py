"""Single-stage CLI commands persist their outcome to state.json.

research/write/humanize/pre_production/design historically bypassed the
Pipeline executor, so `narrascape status` never learned about their results.
``run_single_stage`` records exactly what build records for a completed
stage (status + normalized outputs), without creating approval files.
"""

from pathlib import Path

from narrascape.cli import run_single_stage
from narrascape.config import NarrascapeConfig, ProjectConfig
from narrascape.pipeline import Pipeline, PipelineState, record_stage_result
from narrascape.stages.base import StageContext, StageResult


def _make_config(tmp_path: Path, name: str = "single-stage-test") -> NarrascapeConfig:
    config = NarrascapeConfig(
        project=ProjectConfig(
            name=name,
            title="Single Stage Test",
            script_file="scripts/script.yaml",
        ),
        project_dir=tmp_path,
    )
    config.pipeline_dir.mkdir(parents=True, exist_ok=True)
    return config


class _FakeStage:
    def __init__(self, name: str, result: StageResult):
        self.name = name
        self.depends_on: list[str] = []
        self._result = result
        self.seen_context: StageContext | None = None

    def run(self, context: StageContext) -> StageResult:
        self.seen_context = context
        return self._result


def test_run_single_stage_records_completed_status_and_outputs(tmp_path):
    config = _make_config(tmp_path)
    output = config.pipeline_dir / "research_report.md"
    output.write_text("# report", encoding="utf-8")
    stage = _FakeStage("research", StageResult("research", True, outputs=[output]))

    result = run_single_stage(stage, config)

    assert result.success
    state = PipelineState(config.pipeline_dir / "state.json")
    assert state.get_stage_status("research") == "completed"
    assert state.get_stage_outputs("research") == [
        f"pipeline/{config.project.name}/research_report.md"
    ]


def test_run_single_stage_records_match_build_completion_check(tmp_path):
    """The recorded state satisfies build's completed-outputs check, so the
    single-stage run is visible to the incremental/approval machinery."""
    config = _make_config(tmp_path)
    output = config.project_dir / "scripts" / "script.yaml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("segments:\n  - id: 1\n    text: hello\n", encoding="utf-8")
    stage = _FakeStage("write", StageResult("write", True, outputs={"script": str(output)}))

    run_single_stage(stage, config)

    pipeline = Pipeline(config)
    assert pipeline.state.is_completed("write")
    assert pipeline._completed_outputs_present("write", stage)


def test_run_single_stage_records_failure_without_outputs(tmp_path):
    config = _make_config(tmp_path)
    stage = _FakeStage("design", StageResult("design", False, message="boom"))

    result = run_single_stage(stage, config)

    assert not result.success
    state = PipelineState(config.pipeline_dir / "state.json")
    assert state.get_stage_status("design") == "failed"
    assert state.get_stage_outputs("design") == []


def test_run_single_stage_creates_no_approval_files(tmp_path):
    config = _make_config(tmp_path)
    stage = _FakeStage("humanize", StageResult("humanize", True, outputs=[]))

    run_single_stage(stage, config)

    approvals_dir = config.pipeline_dir / "approvals"
    leftovers = list(approvals_dir.iterdir()) if approvals_dir.exists() else []
    assert leftovers == [], "single-stage commands must not enter the approval gate"


def test_run_single_stage_defaults_to_existing_script(tmp_path):
    config = _make_config(tmp_path)
    script_path = config.project_dir / "scripts" / "script.yaml"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("segments:\n  - id: 1\n    text: hello\n", encoding="utf-8")
    stage = _FakeStage("humanize", StageResult("humanize", True, outputs=[]))

    run_single_stage(stage, config)

    assert stage.seen_context is not None
    assert [segment.text for segment in stage.seen_context.script.segments] == ["hello"]


def test_record_stage_result_flattens_nested_outputs(tmp_path):
    config = _make_config(tmp_path)
    primary = config.pipeline_dir / "a.yaml"
    alternate = config.pipeline_dir / "b.yaml"
    result = StageResult(
        "design",
        True,
        outputs={"primary": primary, "alternates": [alternate, None, ""], "n": 42},
    )

    record_stage_result(config, "design", result)

    state = PipelineState(config.pipeline_dir / "state.json")
    recorded = state.get_stage_outputs("design")
    assert recorded == [
        f"pipeline/{config.project.name}/a.yaml",
        f"pipeline/{config.project.name}/b.yaml",
    ]


def test_record_stage_result_accepts_outside_project_outputs(tmp_path):
    config = _make_config(tmp_path)
    outside = Path("C:/outside-absolute/report.md")
    result: StageResult = StageResult("research", True, outputs=[outside])

    record_stage_result(config, "research", result)

    state = PipelineState(config.pipeline_dir / "state.json")
    assert state.get_stage_outputs("research") == [str(outside)]


def test_run_single_stage_passes_dry_run_false_and_empty_state(tmp_path):
    config = _make_config(tmp_path)
    stage = _FakeStage("research", StageResult("research", True, outputs=[]))

    run_single_stage(stage, config)

    assert stage.seen_context is not None
    assert stage.seen_context.dry_run is False
    assert stage.seen_context.state == {}
    assert isinstance(stage.seen_context.config, NarrascapeConfig)
