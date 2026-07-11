from __future__ import annotations

import json
from pathlib import Path

import yaml

from narrascape.dashboard_workbench import load_workbench_dashboard
from narrascape.pipeline import get_stage_map


def test_workbench_dashboard_tracks_missing_key_artifacts(tmp_path: Path):
    project_dir = tmp_path / "project"
    pipeline_dir = project_dir / "pipeline" / "project"
    pipeline_dir.mkdir(parents=True)
    (project_dir / "film_timeline.yaml").write_text(
        yaml.safe_dump({"schema_version": "film_timeline.v1", "status": "ready"}),
        encoding="utf-8",
    )
    (pipeline_dir / "director_contract.yaml").write_text(
        yaml.safe_dump({"schema_version": "director_contract.v1", "shots": []}),
        encoding="utf-8",
    )

    data = load_workbench_dashboard(project_dir, pipeline_dir)

    artifacts = {item["id"]: item for item in data["artifacts"]}
    assert artifacts["director_contract"]["status"] == "present"
    assert artifacts["director_contract"]["relative_path"] == (
        "pipeline/project/director_contract.yaml"
    )
    assert artifacts["film_timeline"]["exists"] is True
    assert artifacts["film_timeline"]["kind"] == "text"
    assert artifacts["film_timeline"]["modified"] > 0
    assert artifacts["reference_plates"]["status"] == "missing"
    assert data["artifact_counts"]["total"] == 26
    assert data["artifact_counts"]["missing"] == 24
    assert data["artifact_counts"]["attention"] >= 24
    assert any(item["stage"] == "reference_plate" for item in data["command_suggestions"])
    assert data["canvas"]["width"] >= 1400
    assert data["canvas"]["summary"]["total"] >= len(get_stage_map())
    canvas_nodes = {item["id"]: item for item in data["canvas"]["nodes"]}
    assert set(get_stage_map()).issubset(canvas_nodes)
    assert canvas_nodes["write"]["artifact"]["id"] == "script"
    assert canvas_nodes["director_contract"]["state"] == "done"
    assert canvas_nodes["film_timeline"]["artifact"]["relative_path"] == "film_timeline.yaml"
    assert canvas_nodes["generate_video"]["stage_doc"] == "docs/agent-stages/generate_video.md"
    assert any(
        edge["from"] == "director_contract" and edge["to"] == "reference_plate"
        for edge in data["canvas"]["edges"]
    )
    assert any(
        edge["from"] == "rework_plan" and edge["to"] == "film_supervisor"
        for edge in data["canvas"]["edges"]
    )
    assert any(
        edge["from"] == "creative_review" and edge["to"] == "film_supervisor"
        for edge in data["canvas"]["edges"]
    )
    assert any(
        edge["from"] == "visual_semantic_qa" and edge["to"] == "film_supervisor"
        for edge in data["canvas"]["edges"]
    )
    assert data["workflow_session"]["status"] == "stage_ready"
    assert data["workflow_session"]["polling"]["status_command"].startswith("narrascape status")
    assert data["workflow_session"]["required_reading"][0]["path"] == "README.md"
    assert data["workflow_session"]["lifecycle"][2]["id"] == "execute"
    assert data["workflow_session"]["lifecycle"][2]["state"] == "active"
    inspector = data["node_inspector"]["director_contract"]
    assert inspector["stage_doc"] == "docs/agent-stages/director_contract.md"
    assert "Screenplay Structure" in inspector["upstream"]
    assert "Reference Plate" in inspector["downstream"]
    assert any(action["mode"] == "build" for action in inspector["actions"])
    assert any(event["artifact"] == "Film Timeline" for event in data["artifact_events"])


def test_workbench_dashboard_surfaces_supervisor_queue(tmp_path: Path):
    project_dir = tmp_path / "project"
    pipeline_dir = project_dir / "pipeline" / "project"
    pipeline_dir.mkdir(parents=True)
    (pipeline_dir / "state.json").write_text(
        json.dumps(
            {
                "version": "2.0",
                "stages": {
                    "rework_execute": "pending",
                    "generate_video": "pending",
                    "film_timeline": "completed",
                },
                "segments": {},
                "stage_outputs": {},
            }
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "rework_plan.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "rework_plan.v1",
                "status": "needs_rework",
                "actions": [{"segment_id": 1, "action": "regenerate_video"}],
            }
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "film_supervisor.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "film_supervisor.v1",
                "status": "needs_rework",
                "next_stages": ["rework_execute", "generate_video", "film_timeline"],
            }
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "video_regen_queue.yaml").write_text(
        yaml.safe_dump({"actions": [{"segment_id": 2, "action": "regenerate_video"}]}),
        encoding="utf-8",
    )

    data = load_workbench_dashboard(project_dir, pipeline_dir)

    assert data["rework_loop"]["status"] == "needs_rework"
    assert [item["stage"] for item in data["production_queue"][:3]] == [
        "rework_execute",
        "generate_video",
        "film_timeline",
    ]
    assert data["production_queue"][0]["source"] == "supervisor"
    assert data["command_suggestions"][0]["command"].endswith("--stage rework_execute --approve")
    assert data["command_suggestions"][1]["stage"] == "generate_video"
    assert data["command_suggestions"][0]["action"] == "build"
    assert data["command_suggestions"][0]["primary"] == "true"
    assert any(item["stage"] == "assistant_handoff" for item in data["command_suggestions"])
    assert [item["stage"] for item in data["agent_queue"][:3]] == [
        "rework_execute",
        "generate_video",
        "film_timeline",
    ]
    assert data["agent_queue"][0]["source"] == "supervisor"
    assert data["agent_queue"][0]["primary"] == "true"
    canvas_nodes = {item["id"]: item for item in data["canvas"]["nodes"]}
    assert canvas_nodes["generate_video"]["queued"] is True
    assert canvas_nodes["generate_video"]["state"] == "active"
    assert canvas_nodes["film_timeline"]["queued"] is True
    assert canvas_nodes["queue:video_regen_queue"]["state"] == "active"
    assert any(
        edge["from"] == "rework_execute" and edge["to"] == "queue:video_regen_queue"
        for edge in data["canvas"]["edges"]
    )
    assert any(
        edge["from"] == "queue:video_regen_queue" and edge["to"] == "generate_video"
        for edge in data["canvas"]["edges"]
    )
    video_queue = next(item for item in data["rework_queues"] if item["id"] == "video_regen_queue")
    assert video_queue["action_count"] == 1
    assert video_queue["segment_ids"] == [2]
    assert data["workflow_session"]["status"] == "supervisor_routed"
    assert data["workflow_session"]["primary_action"]["stage"] == "rework_execute"
    assert data["node_inspector"]["generate_video"]["blocking_reason"] == (
        "Rework queue has concrete work for this stage."
    )
    assert data["node_inspector"]["generate_video"]["queue_items"][0]["id"] == "video_regen_queue"


def test_workbench_dashboard_uses_canonical_current_stage(tmp_path: Path):
    project_dir = tmp_path / "project"
    pipeline_dir = project_dir / "pipeline" / "project"
    pipeline_dir.mkdir(parents=True)
    (pipeline_dir / "state.json").write_text(
        json.dumps(
            {
                "version": "2.0",
                "stages": {"design": "completed", "director_contract": "failed"},
                "segments": {},
                "stage_outputs": {},
            }
        ),
        encoding="utf-8",
    )

    data = load_workbench_dashboard(project_dir, pipeline_dir)

    assert data["stage_summary"]["current_stage"]["name"] == "director_contract"
    assert data["production_queue"][0]["stage"] == "director_contract"
    assert data["production_queue"][0]["source"] == "current"
    assert data["command_suggestions"][0]["stage"] == "director_contract"
    assert data["command_suggestions"][0]["reason"] == "stage is failed"
    assert data["canvas"]["focus"]["stage"] == "director_contract"
    assert data["canvas"]["focus"]["state"] == "active"
    canvas_nodes = {item["id"]: item for item in data["canvas"]["nodes"]}
    assert canvas_nodes["director_contract"]["current"] is True
    assert canvas_nodes["director_contract"]["state"] == "active"
    assert data["workflow_session"]["focus_node_id"] == "director_contract"
    assert data["node_inspector"]["director_contract"]["blocking_reason"] == (
        "Current pipeline cursor is here."
    )


def test_workbench_dashboard_loads_handoff_as_session_handle(tmp_path: Path):
    project_dir = tmp_path / "project"
    pipeline_dir = project_dir / "pipeline" / "project"
    pipeline_dir.mkdir(parents=True)
    (pipeline_dir / "assistant_handoff.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "assistant_handoff.v1",
                "status": "needs_rework",
                "required_reading": ["README.md", "docs/ai-director.md"],
                "quality_gates": [{"name": "strict_director", "status": "pass"}],
                "next_actions": [{"stage": "generate_video", "intent": "rerun"}],
                "blocking_items": [{"stage": "qa", "message": "missing clips"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    data = load_workbench_dashboard(project_dir, pipeline_dir)

    assert data["workflow_session"]["handoff_ready"] is True
    assert data["workflow_session"]["handoff_status"] == "needs_rework"
    assert data["workflow_session"]["status"] == "handoff_routed"
    assert data["workflow_session"]["required_reading"][0]["path"] == "README.md"
    assert data["handoff"]["status"] == "needs_rework"
    assert data["handoff"]["next_actions"][0]["stage"] == "generate_video"
    assert data["agent_queue"][0]["source"] == "handoff"
    assert data["agent_queue"][0]["stage"] == "generate_video"
    assert data["node_inspector"]["generate_video"]["handoff_next_action"]["stage"] == (
        "generate_video"
    )
    assert any(
        handle["label"] == "Assistant Handoff" and handle["status"] == "available"
        for handle in data["workflow_session"]["result_handles"]
    )
