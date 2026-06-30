from __future__ import annotations

from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, PipelineConfig, ProjectConfig, load_script
from narrascape.stages.base import StageContext


def _config(
    tmp_path: Path,
    *,
    video_generation: str = "auto",
) -> NarrascapeConfig:
    project_dir = tmp_path / "readiness_project"
    (project_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (project_dir / "pipeline" / "readiness_project").mkdir(parents=True, exist_ok=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump({"segments": [{"id": 1, "text": "A test scene."}]}),
        encoding="utf-8",
    )
    return NarrascapeConfig(
        project=ProjectConfig(
            name="readiness_project",
            title="Production Readiness Test",
            script_file="scripts/script.yaml",
        ),
        pipeline=PipelineConfig(video_generation=video_generation),
        project_dir=project_dir,
    )


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )


def _write_gate(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_production_readiness_blocks_until_prep_artifacts_are_clean(tmp_path):
    from narrascape.stages.production_readiness import ProductionReadinessStage

    config = _config(tmp_path)
    pipe_dir = config.pipeline_dir

    _write_gate(
        pipe_dir / "reference_plates.yaml",
        {
            "schema_version": "reference_plates.v1",
            "status": "blocked",
            "blocking": False,
            "plate_count": 1,
            "plates": [{"segment_id": 1, "shot_id": "shot_001"}],
            "findings": [
                {
                    "segment_id": 1,
                    "risk_type": "reference_asset_missing",
                    "severity": "high",
                    "evidence": "missing storyboard reference",
                }
            ],
        },
    )
    _write_gate(
        pipe_dir / "storyboard_sheet.yaml",
        {
            "schema_version": "storyboard_sheet.v1",
            "status": "degraded",
            "project": {"name": "readiness_project", "title": "Production Readiness Test"},
            "shot_count": 1,
            "page_count": 1,
            "pages": [],
            "findings": [
                {
                    "frame_id": "sb_01_01",
                    "segment_id": 1,
                    "risk_type": "storyboard_preview_missing",
                    "severity": "medium",
                    "evidence": "no local preview image",
                }
            ],
        },
    )
    _write_gate(
        pipe_dir / "animatic.yaml",
        {
            "schema_version": "animatic.v1",
            "status": "blocked",
            "panel_count": 1,
            "panels": [{"segment_id": 1, "storyboard_frame_id": "sb_01_01"}],
            "findings": [
                {
                    "segment_id": 1,
                    "storyboard_frame_id": "sb_01_01",
                    "risk_type": "animatic_source_missing",
                    "severity": "high",
                    "evidence": "animatic source image not found",
                }
            ],
        },
    )

    result = ProductionReadinessStage().run(_context(config))

    assert result.success is True
    report = yaml.safe_load(
        (config.pipeline_dir / "production_readiness.yaml").read_text(encoding="utf-8")
    )
    assert report["schema_version"] == "production_readiness.v1"
    assert report["status"] == "blocked"
    assert report["blocking"] is False
    assert report["video_generation_policy"] == "auto"
    stage_names = {gate["stage"] for gate in report["gates"]}
    assert stage_names == {"reference_plates", "storyboard_sheet", "animatic"}
    risks = {(item["stage"], item["risk_type"]) for item in report["findings"]}
    assert ("reference_plates", "reference_plates_not_ready") in risks
    assert ("storyboard_sheet", "storyboard_sheet_not_ready") in risks
    assert ("animatic", "animatic_not_ready") in risks


def test_production_readiness_blocks_required_video_generation(tmp_path):
    from narrascape.stages.production_readiness import ProductionReadinessStage

    config = _config(tmp_path, video_generation="required")
    pipe_dir = config.pipeline_dir

    _write_gate(
        pipe_dir / "reference_plates.yaml",
        {
            "schema_version": "reference_plates.v1",
            "status": "blocked",
            "blocking": True,
            "plate_count": 1,
            "plates": [{"segment_id": 1, "shot_id": "shot_001"}],
            "findings": [
                {
                    "segment_id": 1,
                    "risk_type": "reference_asset_missing",
                    "severity": "high",
                    "evidence": "missing storyboard reference",
                }
            ],
        },
    )
    _write_gate(
        pipe_dir / "storyboard_sheet.yaml",
        {
            "schema_version": "storyboard_sheet.v1",
            "status": "ready",
            "project": {"name": "readiness_project", "title": "Production Readiness Test"},
            "shot_count": 1,
            "page_count": 1,
            "pages": [{"page_index": 1, "card_count": 1, "cards": []}],
            "findings": [],
        },
    )
    _write_gate(
        pipe_dir / "animatic.yaml",
        {
            "schema_version": "animatic.v1",
            "status": "ready",
            "panel_count": 1,
            "panels": [{"segment_id": 1, "storyboard_frame_id": "sb_01_01"}],
            "findings": [],
        },
    )

    result = ProductionReadinessStage().run(_context(config))

    assert result.success is False
    report = yaml.safe_load(
        (config.pipeline_dir / "production_readiness.yaml").read_text(encoding="utf-8")
    )
    assert report["status"] == "blocked"
    assert report["blocking"] is True
    assert report["video_generation_policy"] == "required"


def test_production_readiness_passes_when_prep_artifacts_are_ready(tmp_path):
    from narrascape.stages.production_readiness import ProductionReadinessStage

    config = _config(tmp_path)
    pipe_dir = config.pipeline_dir

    _write_gate(
        pipe_dir / "reference_plates.yaml",
        {
            "schema_version": "reference_plates.v1",
            "status": "ready",
            "blocking": False,
            "plate_count": 1,
            "plates": [{"segment_id": 1, "shot_id": "shot_001"}],
            "findings": [],
        },
    )
    _write_gate(
        pipe_dir / "storyboard_sheet.yaml",
        {
            "schema_version": "storyboard_sheet.v1",
            "status": "ready",
            "project": {"name": "readiness_project", "title": "Production Readiness Test"},
            "shot_count": 1,
            "page_count": 1,
            "pages": [{"page_index": 1, "card_count": 1, "cards": []}],
            "findings": [],
        },
    )
    _write_gate(
        pipe_dir / "animatic.yaml",
        {
            "schema_version": "animatic.v1",
            "status": "ready",
            "panel_count": 1,
            "panels": [{"segment_id": 1, "storyboard_frame_id": "sb_01_01"}],
            "findings": [],
        },
    )

    result = ProductionReadinessStage().run(_context(config))

    assert result.success is True
    report = yaml.safe_load(
        (config.pipeline_dir / "production_readiness.yaml").read_text(encoding="utf-8")
    )
    assert report["schema_version"] == "production_readiness.v1"
    assert report["status"] == "ready"
    assert report["findings"] == []
