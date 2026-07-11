from __future__ import annotations

import json
from pathlib import Path

import yaml

from narrascape.dashboard_data import (
    load_rework_loop_summary,
    load_stage_dashboard,
    load_timeline_dashboard,
)


def test_load_timeline_dashboard_summarizes_timeline_and_remotion_preview(tmp_path: Path):
    project_dir = tmp_path / "project"
    pipeline_dir = project_dir / "pipeline" / "project"
    (project_dir / "assets" / "videos").mkdir(parents=True)
    (project_dir / "assets" / "images").mkdir(parents=True)
    pipeline_dir.mkdir(parents=True)
    (project_dir / "assets" / "videos" / "vid_01.mp4").write_bytes(b"video")
    (project_dir / "film_timeline.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "film_timeline.v1",
                "project": {"name": "project", "title": "Project"},
                "duration": 7.0,
                "coverage": {
                    "generated_video_segments": [1],
                    "generated_image_segments": [2],
                    "source_media_segments": [],
                    "missing_visual_segments": [],
                },
                "tracks": {
                    "visual": [
                        {
                            "id": "v_001",
                            "segment_id": 1,
                            "source": "generated_video",
                            "asset_ref": "vid_01",
                            "path": "assets/videos/vid_01.mp4",
                            "start": 0.0,
                            "duration": 4.0,
                            "shot_type": "wide",
                            "movement": "slow push",
                        },
                        {
                            "id": "v_002",
                            "segment_id": 2,
                            "source": "generated_image",
                            "asset_ref": "img_02",
                            "path": "assets/images/img_02.png",
                            "start": 4.0,
                            "duration": 3.0,
                        },
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "remotion_preview.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "remotion_preview.v1",
                "status": "missing_assets",
                "project": {
                    "name": "project",
                    "title": "Project",
                    "root": (pipeline_dir / "remotion_preview").as_posix(),
                },
                "composition": {"id": "NarrascapeTimeline"},
                "assets": {
                    "copied": [{"clip_id": "v_001", "status": "copied"}],
                    "missing": [{"clip_id": "v_002", "timeline_path": "assets/images/img_02.png"}],
                },
                "commands": {"studio": "npx remotion studio"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    data = load_timeline_dashboard(project_dir, pipeline_dir)

    assert data["status"] == "missing_assets"
    assert data["duration"] == 7.0
    assert data["source_counts"] == {"generated_video": 1, "generated_image": 1}
    assert data["coverage"]["generated_video_segments"] == [1]
    assert data["visual"][0]["asset_exists"] is True
    assert data["visual"][1]["asset_exists"] is False
    assert data["missing_assets"][0]["id"] == "v_002"
    assert data["remotion"]["status"] == "missing_assets"
    assert data["remotion"]["commands"]["studio"] == "npx remotion studio"
    assert data["remotion"]["missing"][0]["clip_id"] == "v_002"


def test_load_stage_dashboard_uses_pipeline_state_and_registry(tmp_path: Path):
    project_dir = tmp_path / "project"
    pipeline_dir = project_dir / "pipeline" / "project"
    pipeline_dir.mkdir(parents=True)
    (project_dir / "assets" / "images").mkdir(parents=True)
    image = project_dir / "assets" / "images" / "img_01.png"
    image.write_bytes(b"image")
    (pipeline_dir / "state.json").write_text(
        json.dumps(
            {
                "version": "2.0",
                "stages": {"generate_images": "completed", "design": "failed"},
                "segments": {},
                "stage_outputs": {"generate_images": [image.as_posix()]},
            }
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "approvals").mkdir()
    (pipeline_dir / "approvals" / "generate_images.approved").write_text(
        "stage: generate_images\nstatus: approved\n",
        encoding="utf-8",
    )

    data = load_stage_dashboard(project_dir, pipeline_dir)

    assert data["total"] == 36
    assert data["completed"] == 1
    assert data["stage_by_name"]["generate_images"]["done"] is True
    assert data["stage_by_name"]["generate_images"]["approval"] == "approved"
    assert data["stage_by_name"]["generate_images"]["output_count"] == 1
    assert data["stage_by_name"]["generate_images"]["output_files"][0]["name"] == "img_01.png"
    assert data["stage_by_name"]["design"]["status"] == "failed"
    assert data["current_stage"]["name"] == "design"
    assert "director_contract" in data["stage_by_name"]


def test_load_timeline_dashboard_handles_missing_timeline(tmp_path: Path):
    project_dir = tmp_path / "project"
    pipeline_dir = project_dir / "pipeline" / "project"
    pipeline_dir.mkdir(parents=True)

    data = load_timeline_dashboard(project_dir, pipeline_dir)

    assert data["status"] == "missing_timeline"
    assert data["visual"] == []
    assert data["remotion"]["status"] == "missing"
    assert data["rework_loop"]["status"] == "not_started"


def test_load_rework_loop_summary_reads_supervisor_and_review_artifacts(tmp_path: Path):
    pipeline_dir = tmp_path / "pipeline" / "project"
    pipeline_dir.mkdir(parents=True)
    (pipeline_dir / "render_report.yaml").write_text(
        yaml.safe_dump(
            {
                "errors": ["shot coverage incomplete"],
                "warnings": ["narrative pacing risk"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "rework_plan.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "rework_plan.v1",
                "status": "needs_rework",
                "actions": [
                    {"segment_id": 1, "action": "regenerate_video", "reason": "qa"},
                    {"segment_id": 2, "action": "recut", "reason": "pacing"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "rework_execution.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "rework_execution.v1",
                "status": "executed",
                "executed_actions": [{"segment_id": 1, "operation": "invalidate_generated_video"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "creative_review.yaml").write_text(
        yaml.safe_dump({"recommendations": [{"segment_id": 2, "action": "recut"}]}),
        encoding="utf-8",
    )
    (pipeline_dir / "visual_semantic_report.yaml").write_text(
        yaml.safe_dump({"findings": [{"segment_id": 1, "risk_type": "identity_drift"}]}),
        encoding="utf-8",
    )
    (pipeline_dir / "film_supervisor.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "film_supervisor.v1",
                "status": "needs_rework",
                "next_stages": [
                    "rework_execute",
                    "generate_video",
                    "take_select",
                    "film_timeline",
                    "remotion_preview",
                    "film_supervisor",
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = load_rework_loop_summary(pipeline_dir)

    assert summary["status"] == "needs_rework"
    assert summary["blocking"] is True
    assert summary["action_count"] == 2
    assert summary["actions_by_type"] == {"regenerate_video": 1, "recut": 1}
    assert summary["executed_count"] == 1
    assert summary["qa_error_count"] == 1
    assert summary["qa_warning_count"] == 1
    assert summary["creative_recommendation_count"] == 1
    assert summary["visual_finding_count"] == 1
    assert summary["next_stages"][4] == "remotion_preview"
