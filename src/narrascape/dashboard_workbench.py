from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from narrascape.catalog import core_artifact_templates, stage_doc_path, stage_intent
from narrascape.dashboard_data import load_rework_loop_summary, load_stage_dashboard
from narrascape.pipeline import get_stage_map
from narrascape.utils.safe_io import ArtifactLoadError, load_yaml_mapping

CANVAS_NODE_WIDTH = 164
CANVAS_NODE_HEIGHT = 92
CANVAS_X_GAP = 218
CANVAS_Y_GAP = 124
CANVAS_ORIGIN_X = 48
CANVAS_ORIGIN_Y = 74

ARTIFACT_STAGE_HINTS: dict[str, tuple[str, str]] = {
    "script": ("write", "Source"),
    "pre_production": ("pre_production", "Pre-Production"),
    "design_report": ("design", "Director"),
    "screenplay_structure": ("screenplay_structure", "Director"),
    "director_contract": ("director_contract", "Visual Contract"),
    "reference_plates": ("reference_plate", "Visual Contract"),
    "storyboard_sheet": ("storyboard_sheet", "Visual Contract"),
    "animatic": ("animatic", "Visual Contract"),
    "production_readiness": ("production_readiness", "Generation Gate"),
    "video_prompt_quality": ("generate_video", "Generated Video"),
    "take_selection": ("take_select", "Generated Video"),
    "film_timeline": ("film_timeline", "Editorial"),
    "render_report": ("qa", "Review"),
    "continuity_bible": ("continuity_bible", "Review"),
    "editing_review": ("editing_review", "Review"),
    "director_review": ("director_review", "Review"),
    "rework_plan": ("rework_plan", "Review"),
    "creative_review": ("creative_review", "Review"),
    "visual_semantic_report": ("visual_semantic_qa", "Review"),
    "film_supervisor": ("film_supervisor", "Supervisor"),
    "assistant_handoff": ("assistant_handoff", "Handoff"),
    "rework_execution": ("rework_execute", "Rework"),
}

REWORK_QUEUE_SPECS: tuple[dict[str, str], ...] = (
    {
        "id": "director_contract_rewrite_queue",
        "file": "director_contract_rewrite_queue.yaml",
        "label": "Director Contract Rewrite Queue",
        "target_stage": "director_contract",
        "source_stage": "rework_execute",
    },
    {
        "id": "video_regen_queue",
        "file": "video_regen_queue.yaml",
        "label": "Video Regeneration Queue",
        "target_stage": "generate_video",
        "source_stage": "rework_execute",
    },
    {
        "id": "recut_queue",
        "file": "recut_queue.yaml",
        "label": "Recut Queue",
        "target_stage": "film_timeline",
        "source_stage": "rework_execute",
    },
    {
        "id": "source_media_replacement_queue",
        "file": "source_media_replacement_queue.yaml",
        "label": "Source Media Replacement Queue",
        "target_stage": "source_media",
        "source_stage": "rework_execute",
    },
)

STAGE_LANE_HINTS: dict[str, str] = {
    "research": "Source",
    "write": "Source",
    "humanize": "Source",
    "source_media": "Source Media",
    "footage_edit": "Source Media",
    "pre_production": "Pre-Production",
    "design": "AI Director",
    "screenplay_structure": "AI Director",
    "director_contract": "Visual Contract",
    "reference_plate": "Visual Contract",
    "generate_images": "Reference Assets",
    "storyboard_sheet": "Storyboard",
    "animatic": "Storyboard",
    "production_readiness": "Generation Gate",
    "generate_video": "Generated Video",
    "take_select": "Generated Video",
    "generate_tts": "Audio Source",
    "generate_music": "Audio Source",
    "remix_audio": "Audio Source",
    "kenburns": "Fallback Motion",
    "concat": "Fallback Motion",
    "film_timeline": "Editorial",
    "remotion_preview": "Editorial",
    "film_assemble": "Editorial",
    "audio": "Finishing",
    "subtitles": "Finishing",
    "qa": "QA",
    "continuity_bible": "Review",
    "editing_review": "Review",
    "director_review": "Review",
    "rework_plan": "Rework",
    "creative_review": "Review",
    "visual_semantic_qa": "Review",
    "film_supervisor": "Supervisor",
    "assistant_handoff": "Handoff",
    "rework_execute": "Rework",
}

PROVIDER_BOUNDARY_STAGES = {
    "generate_images",
    "generate_video",
    "generate_tts",
    "generate_music",
}

_ATTENTION_STATUSES = {
    "blocked",
    "failed",
    "has_errors",
    "invalid",
    "missing",
    "missing_assets",
    "needs_attention",
    "needs_rework",
    "pending_supervisor",
}


def load_workbench_dashboard(project_dir: Path, pipeline_dir: Path) -> dict[str, Any]:
    """Load artifact-first dashboard data for the creator workbench."""

    stage_dashboard = load_stage_dashboard(project_dir, pipeline_dir)
    rework_loop = load_rework_loop_summary(pipeline_dir)
    artifacts = _artifact_rows(project_dir, pipeline_dir)
    handoff = _load_handoff(pipeline_dir)
    rework_queues = _load_rework_queues(pipeline_dir)
    quality_gates = _quality_gates(project_dir, pipeline_dir, handoff)
    production_queue = _production_queue(stage_dashboard, rework_loop)
    command_suggestions = _recommended_commands(
        project_dir,
        stage_dashboard,
        artifacts,
        rework_loop,
    )
    agent_queue = _agent_queue(
        production_queue,
        command_suggestions,
        rework_loop,
        handoff,
        rework_queues,
    )
    canvas_nodes = _canvas_nodes(
        project_dir,
        pipeline_dir,
        stage_dashboard,
        artifacts,
        agent_queue,
        handoff,
        rework_queues,
    )
    canvas_edges = _canvas_edges(canvas_nodes)
    node_inspector = _node_inspector(
        project_dir,
        canvas_nodes,
        canvas_edges,
        command_suggestions,
    )

    return {
        "project_dir": project_dir.as_posix(),
        "pipeline_dir": pipeline_dir.as_posix(),
        "stage_dashboard": stage_dashboard,
        "stage_summary": {
            "total": stage_dashboard.get("total", 0),
            "completed": stage_dashboard.get("completed", 0),
            "progress": stage_dashboard.get("progress", 0),
            "counts": stage_dashboard.get("counts", {}),
            "current_stage": stage_dashboard.get("current_stage"),
        },
        "artifact_counts": _artifact_counts(artifacts),
        "artifacts": artifacts,
        "production_queue": production_queue,
        "rework_loop": rework_loop,
        "command_suggestions": command_suggestions,
        "canvas": {
            "width": 1484,
            "height": 540,
            "node_width": CANVAS_NODE_WIDTH,
            "node_height": CANVAS_NODE_HEIGHT,
            "nodes": canvas_nodes,
            "edges": canvas_edges,
            "lanes": _canvas_lanes(canvas_nodes),
            "summary": _canvas_summary(canvas_nodes),
            "focus": _focus_canvas_node(canvas_nodes),
            **_canvas_size(canvas_nodes),
        },
        "agent_queue": agent_queue,
        "rework_queues": rework_queues,
        "quality_gates": quality_gates,
        "workflow_session": _workflow_session(
            project_dir,
            pipeline_dir,
            stage_dashboard,
            rework_loop,
            handoff,
            agent_queue,
            canvas_nodes,
            quality_gates,
            rework_queues,
        ),
        "node_inspector": node_inspector,
        "artifact_events": _artifact_events(artifacts, stage_dashboard),
        "handoff": _handoff_summary(handoff),
        "interaction_model": _interaction_model(),
    }


def _artifact_rows(project_dir: Path, pipeline_dir: Path) -> list[dict[str, Any]]:
    templates = core_artifact_templates()
    rows: list[dict[str, Any]] = []
    for artifact_id in templates:
        stage, phase = ARTIFACT_STAGE_HINTS.get(artifact_id, (artifact_id, "Artifact"))
        rows.append(
            _artifact_record(
                project_dir,
                pipeline_dir,
                templates,
                {
                    "id": artifact_id,
                    "stage": stage,
                    "phase": phase,
                },
            )
        )
    for spec in REWORK_QUEUE_SPECS:
        path = pipeline_dir / spec["file"]
        rows.append(
            {
                "id": str(spec["id"]),
                "label": str(spec["label"]),
                "phase": "Rework Queue",
                "stage": str(spec["target_stage"]),
                "path": path.as_posix(),
                "relative_path": _relative_path(project_dir, path),
                "file": path.name,
                "exists": path.exists(),
                "status": _queue_file_status(path),
                "kind": "queue",
                "size_bytes": _path_size(path),
                "modified": _modified_time(path),
            }
        )
    return rows


def _artifact_record(
    project_dir: Path,
    pipeline_dir: Path,
    templates: dict[str, str],
    item: dict[str, str],
) -> dict[str, Any]:
    artifact_id = item["id"]
    path = _artifact_path(project_dir, pipeline_dir, templates.get(artifact_id, artifact_id))
    return {
        "id": artifact_id,
        "label": item.get("label") or _label(artifact_id),
        "phase": item["phase"],
        "stage": item["stage"],
        "path": path.as_posix(),
        "relative_path": _relative_path(project_dir, path),
        "file": path.name,
        "exists": path.exists(),
        "status": _artifact_status(path),
        "kind": _artifact_kind(path),
        "size_bytes": _path_size(path),
        "modified": _modified_time(path),
    }


def _artifact_path(project_dir: Path, pipeline_dir: Path, template: str) -> Path:
    rel = template.format(name=pipeline_dir.name)
    project_path = project_dir / rel
    if rel.startswith("pipeline/"):
        pipeline_path = pipeline_dir / Path(rel).name
        return (
            pipeline_path if pipeline_path.exists() or not project_path.exists() else project_path
        )
    return project_path


def _artifact_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.suffix.lower() not in {".yaml", ".yml"}:
        return "present"
    try:
        data = load_yaml_mapping(path)
    except ArtifactLoadError:
        return "invalid"
    status = data.get("status")
    if status:
        return str(status)
    if data.get("errors"):
        return "has_errors"
    return "present"


def _artifact_counts(artifacts: list[dict[str, Any]]) -> dict[str, int]:
    present = sum(1 for item in artifacts if item["exists"])
    missing = sum(1 for item in artifacts if not item["exists"])
    attention = sum(1 for item in artifacts if str(item["status"]) in _ATTENTION_STATUSES)
    return {
        "total": len(artifacts),
        "present": present,
        "missing": missing,
        "attention": attention,
    }


def _production_queue(
    stage_dashboard: dict[str, Any],
    rework_loop: dict[str, Any],
) -> list[dict[str, Any]]:
    stages_by_name = stage_dashboard.get("stage_by_name", {})
    queue: list[dict[str, Any]] = []
    seen: set[str] = set()

    for stage_name in rework_loop.get("next_stages", []) or []:
        stage = stages_by_name.get(stage_name, {})
        queue.append(_queue_item(str(stage_name), stage, "supervisor"))
        seen.add(str(stage_name))

    current_stage = stage_dashboard.get("current_stage")
    if isinstance(current_stage, dict) and not queue:
        stage_name = str(current_stage.get("name") or "")
        if stage_name and stage_name not in seen:
            queue.insert(0, _queue_item(stage_name, current_stage, "current"))
            seen.add(stage_name)

    if not queue:
        for stage in stage_dashboard.get("stages", []) or []:
            if not isinstance(stage, dict):
                continue
            status = str(stage.get("status") or "pending")
            if status in {"failed", "running"}:
                stage_name = str(stage.get("name") or "")
                if stage_name and stage_name not in seen:
                    queue.append(_queue_item(stage_name, stage, status))
                    seen.add(stage_name)

    return queue


def _canvas_nodes(
    project_dir: Path,
    pipeline_dir: Path,
    stage_dashboard: dict[str, Any],
    artifacts: list[dict[str, Any]],
    agent_queue: list[dict[str, Any]],
    handoff: dict[str, Any],
    rework_queues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stages_by_name = stage_dashboard.get("stage_by_name", {})
    current_stage = stage_dashboard.get("current_stage")
    current_name = str(current_stage.get("name") or "") if isinstance(current_stage, dict) else ""
    queued_stages = {str(item.get("stage") or "") for item in agent_queue}
    artifact_by_stage = _artifacts_by_stage(artifacts)
    queue_by_stage = _queues_by_stage(rework_queues)
    handoff_actions = _handoff_actions_by_stage(handoff)
    required_reading = _required_reading_rows(handoff)
    stage_map = get_stage_map()
    layout = _stage_layout(stage_map)
    nodes: list[dict[str, Any]] = []

    for index, (stage_name, stage_cls) in enumerate(stage_map.items(), 1):
        stage_instance = stage_cls()
        stage = stages_by_name.get(stage_name, {}) if isinstance(stages_by_name, dict) else {}
        stage_status = str(stage.get("status") or "pending")
        stage_artifacts = artifact_by_stage.get(stage_name, [])
        artifact = stage_artifacts[0] if stage_artifacts else {}
        exists = bool(artifact.get("exists")) if artifact else bool(stage.get("output_complete"))
        status = str(artifact.get("status") if artifact else stage_status)
        output_count = int(stage.get("output_count") or 0)
        output_size = int(stage.get("output_size") or 0)
        current = stage_name == current_name
        queued = stage_name in queued_stages
        stage_queues = queue_by_stage.get(stage_name, [])
        state = _canvas_node_state(
            status=status,
            exists=exists,
            stage_status=stage_status,
            current=current,
            queued=queued,
            has_artifact=bool(artifact),
        )
        x, y = layout.get(stage_name, (CANVAS_ORIGIN_X, CANVAS_ORIGIN_Y))
        depends_on = _stage_depends_on(stage, stage_instance.depends_on)
        outputs = _stage_outputs(stage, stage_instance.outputs)
        nodes.append(
            {
                "id": stage_name,
                "label": str(stage.get("label") or _label(stage_name)),
                "lane": STAGE_LANE_HINTS.get(stage_name, "Stage"),
                "stage": stage_name,
                "kind": _stage_kind(stage_name),
                "index": index,
                "x": x,
                "y": y,
                "width": CANVAS_NODE_WIDTH,
                "height": CANVAS_NODE_HEIGHT,
                "state": state,
                "status": status,
                "stage_status": stage_status,
                "approval": str(stage.get("approval") or "unknown"),
                "current": current,
                "queued": queued,
                "exists": exists,
                "output_count": output_count,
                "output_size": output_size,
                "artifact": artifact,
                "artifacts": stage_artifacts,
                "depends_on": depends_on,
                "outputs": outputs,
                "output_files": list(stage.get("output_files") or []),
                "stage_doc": stage_doc_path(stage_name),
                "production_boundary": stage_name in PROVIDER_BOUNDARY_STAGES,
                "queue_items": stage_queues,
                "handoff_next_action": handoff_actions.get(stage_name, {}),
                "required_reading": _stage_required_reading(stage_name, required_reading),
                "intent": stage_intent(stage_name),
            }
        )
    nodes.extend(_queue_canvas_nodes(nodes, rework_queues))
    return nodes


def _stage_depends_on(stage: dict[str, Any], fallback: list[str]) -> list[str]:
    value = stage.get("depends_on")
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(item) for item in fallback]


def _stage_outputs(stage: dict[str, Any], fallback: Any) -> list[str]:
    value = stage.get("outputs")
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(item) for item in fallback or []]


def _artifacts_by_stage(artifacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in artifacts:
        if str(artifact.get("kind") or "") == "queue":
            continue
        stage = str(artifact.get("stage") or "")
        if stage:
            grouped[stage].append(artifact)
    for rows in grouped.values():
        rows.sort(key=lambda item: (not bool(item.get("exists")), str(item.get("id") or "")))
    return dict(grouped)


def _queues_by_stage(rework_queues: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in rework_queues:
        stage = str(item.get("target_stage") or "")
        if stage:
            grouped[stage].append(item)
    return dict(grouped)


def _handoff_actions_by_stage(handoff: dict[str, Any]) -> dict[str, dict[str, Any]]:
    actions: dict[str, dict[str, Any]] = {}
    for item in handoff.get("next_actions", []) or []:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "")
        if stage and stage != "status" and stage not in actions:
            actions[stage] = item
    return actions


def _stage_required_reading(
    stage_name: str,
    required_reading: list[dict[str, str]],
) -> list[dict[str, str]]:
    doc_path = stage_doc_path(stage_name)
    if not doc_path:
        return []
    return [item for item in required_reading if item.get("path") == doc_path]


def _stage_kind(stage_name: str) -> str:
    if stage_name in PROVIDER_BOUNDARY_STAGES:
        return "provider"
    if stage_name in {"production_readiness"}:
        return "gate"
    if stage_name in {"qa", "visual_semantic_qa", "editing_review", "director_review"}:
        return "qa"
    if stage_name in {"film_supervisor", "assistant_handoff"}:
        return "agent"
    if stage_name in {"film_timeline", "remotion_preview", "film_assemble"}:
        return "timeline"
    return "stage"


def _stage_layout(stage_map: dict[str, Any]) -> dict[str, tuple[int, int]]:
    depths = _stage_depths(stage_map)
    columns: dict[int, list[str]] = defaultdict(list)
    for stage_name in stage_map:
        columns[depths.get(stage_name, 0)].append(stage_name)
    layout: dict[str, tuple[int, int]] = {}
    for depth, names in columns.items():
        for slot, stage_name in enumerate(names):
            layout[stage_name] = (
                CANVAS_ORIGIN_X + depth * CANVAS_X_GAP,
                CANVAS_ORIGIN_Y + slot * CANVAS_Y_GAP,
            )
    return layout


def _stage_depths(stage_map: dict[str, Any]) -> dict[str, int]:
    depth_cache: dict[str, int] = {}

    def depth(stage_name: str, seen: set[str]) -> int:
        if stage_name in depth_cache:
            return depth_cache[stage_name]
        if stage_name in seen or stage_name not in stage_map:
            return 0
        stage = stage_map[stage_name]()
        deps = [dep for dep in stage.depends_on if dep in stage_map]
        value = 0 if not deps else max(depth(dep, seen | {stage_name}) + 1 for dep in deps)
        depth_cache[stage_name] = value
        return value

    for stage_name in stage_map:
        depth(stage_name, set())
    return depth_cache


def _queue_canvas_nodes(
    stage_nodes: list[dict[str, Any]],
    rework_queues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stage_by_name = {str(node.get("stage") or ""): node for node in stage_nodes}
    existing_queue_nodes: list[dict[str, Any]] = []
    for index, queue_item in enumerate(rework_queues):
        if not queue_item.get("exists"):
            continue
        source_stage = str(queue_item.get("source_stage") or "")
        source_node = stage_by_name.get(source_stage, {})
        target_stage = str(queue_item.get("target_stage") or "")
        target_node = stage_by_name.get(target_stage, {})
        source_x = int(source_node.get("x") or CANVAS_ORIGIN_X)
        target_y = int(target_node.get("y") or CANVAS_ORIGIN_Y)
        action_count = int(queue_item.get("action_count") or 0)
        state = "active" if action_count else "done"
        artifact = _queue_artifact_record(queue_item)
        existing_queue_nodes.append(
            {
                "id": f"queue:{queue_item['id']}",
                "label": str(queue_item.get("label") or _label(str(queue_item["id"]))),
                "lane": "Rework Queue",
                "stage": target_stage,
                "kind": "queue",
                "index": len(stage_nodes) + index + 1,
                "x": source_x + CANVAS_X_GAP,
                "y": target_y + CANVAS_NODE_HEIGHT + 32,
                "width": CANVAS_NODE_WIDTH,
                "height": CANVAS_NODE_HEIGHT,
                "state": state,
                "status": str(queue_item.get("status") or "missing"),
                "stage_status": str(queue_item.get("status") or "missing"),
                "approval": "queue",
                "current": False,
                "queued": action_count > 0,
                "exists": True,
                "output_count": action_count,
                "output_size": int(queue_item.get("size_bytes") or 0),
                "artifact": artifact,
                "artifacts": [artifact],
                "depends_on": [],
                "outputs": [str(queue_item.get("path") or "")],
                "output_files": [],
                "stage_doc": stage_doc_path(target_stage),
                "production_boundary": target_stage in PROVIDER_BOUNDARY_STAGES,
                "queue_items": [queue_item],
                "handoff_next_action": {},
                "required_reading": [],
                "intent": f"feed queued rework into {target_stage}",
                "source_stage": source_stage,
                "target_stage": target_stage,
            }
        )
    return existing_queue_nodes


def _queue_artifact_record(queue_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(queue_item.get("id") or ""),
        "label": str(queue_item.get("label") or ""),
        "phase": "Rework Queue",
        "stage": str(queue_item.get("target_stage") or ""),
        "path": str(queue_item.get("path") or ""),
        "relative_path": str(queue_item.get("relative_path") or ""),
        "file": str(queue_item.get("file") or ""),
        "exists": bool(queue_item.get("exists")),
        "status": str(queue_item.get("status") or "missing"),
        "kind": "queue",
        "size_bytes": int(queue_item.get("size_bytes") or 0),
        "modified": float(queue_item.get("modified") or 0.0),
    }


def _canvas_node_state(
    *,
    status: str,
    exists: bool,
    stage_status: str,
    current: bool,
    queued: bool,
    has_artifact: bool,
) -> str:
    normalized = status.lower()
    if stage_status == "running" or current:
        return "active"
    if queued:
        return "active"
    if normalized in _ATTENTION_STATUSES or stage_status == "failed":
        return "attention"
    if has_artifact and not exists:
        return "missing"
    if stage_status == "completed" or normalized in {
        "approved",
        "completed",
        "executed",
        "ok",
        "passed",
        "present",
        "ready",
    }:
        return "done"
    return "pending"


def _canvas_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_by_id = {str(node["id"]): node for node in nodes}
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for node in nodes:
        to_id = str(node.get("id") or "")
        for dep in node.get("depends_on", []) or []:
            _append_canvas_edge(edges, seen, node_by_id, str(dep), to_id, "depends")
        if str(node.get("kind") or "") == "queue":
            queue_id = str(node.get("id") or "")
            source_stage = str(node.get("source_stage") or "")
            target_stage = str(node.get("target_stage") or node.get("stage") or "")
            _append_canvas_edge(edges, seen, node_by_id, source_stage, queue_id, "writes")
            _append_canvas_edge(edges, seen, node_by_id, queue_id, target_stage, "feeds")
    return edges


def _append_canvas_edge(
    edges: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    node_by_id: dict[str, dict[str, Any]],
    from_id: str,
    to_id: str,
    label: str,
) -> None:
    if not from_id or not to_id:
        return
    key = (from_id, to_id, label)
    if key in seen:
        return
    from_node = node_by_id.get(from_id)
    to_node = node_by_id.get(to_id)
    if not from_node or not to_node:
        return
    seen.add(key)
    edge_state = _edge_state(from_node, to_node)
    edges.append(
        {
            "from": from_id,
            "to": to_id,
            "label": label,
            "state": edge_state,
            "x1": int(from_node["x"]) + CANVAS_NODE_WIDTH,
            "y1": int(from_node["y"]) + CANVAS_NODE_HEIGHT // 2,
            "x2": int(to_node["x"]),
            "y2": int(to_node["y"]) + CANVAS_NODE_HEIGHT // 2,
        }
    )


def _edge_state(from_node: dict[str, Any], to_node: dict[str, Any]) -> str:
    if from_node.get("state") == "attention" or to_node.get("state") == "attention":
        return "attention"
    if from_node.get("queued") or to_node.get("queued"):
        return "active"
    if from_node.get("state") == "done" and to_node.get("state") == "done":
        return "done"
    return "idle"


def _canvas_summary(nodes: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(nodes),
        "done": sum(1 for node in nodes if node["state"] == "done"),
        "active": sum(1 for node in nodes if node["state"] == "active"),
        "attention": sum(1 for node in nodes if node["state"] == "attention"),
        "missing": sum(1 for node in nodes if node["state"] == "missing"),
        "pending": sum(1 for node in nodes if node["state"] == "pending"),
    }


def _canvas_size(nodes: list[dict[str, Any]]) -> dict[str, int]:
    if not nodes:
        return {"width": 1484, "height": 540}
    max_x = max(int(node.get("x") or 0) for node in nodes) + CANVAS_NODE_WIDTH + 96
    max_y = max(int(node.get("y") or 0) for node in nodes) + CANVAS_NODE_HEIGHT + 96
    return {"width": max(1484, max_x), "height": max(540, max_y)}


def _canvas_lanes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_x: dict[int, list[str]] = defaultdict(list)
    for node in nodes:
        x = int(node.get("x") or 0)
        lane = str(node.get("lane") or "Stage")
        if lane not in by_x[x]:
            by_x[x].append(lane)
    lanes: list[dict[str, Any]] = []
    for x in sorted(by_x):
        labels = by_x[x]
        label = labels[0] if len(labels) == 1 else " / ".join(labels[:2])
        lanes.append({"label": label, "left": x})
    return lanes


def _focus_canvas_node(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for node in nodes:
        if node.get("current"):
            return node
    for node in nodes:
        if node.get("queued"):
            return node
    priority = ("active", "attention", "missing", "done", "pending")
    for state in priority:
        for node in nodes:
            if node.get("state") == state:
                return node
    return None


def _agent_queue(
    production_queue: list[dict[str, Any]],
    command_suggestions: list[dict[str, str]],
    rework_loop: dict[str, Any],
    handoff: dict[str, Any],
    rework_queues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    commands_by_stage = {str(item.get("stage") or ""): item for item in command_suggestions}
    queue: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, action_item in enumerate(_handoff_next_actions(handoff)):
        stage_name = str(action_item.get("stage") or "")
        if not stage_name or stage_name == "status" or stage_name in seen:
            continue
        command = commands_by_stage.get(stage_name, {})
        queue.append(
            {
                "key": f"handoff:{stage_name}",
                "stage": stage_name,
                "action": "build",
                "label": _label(stage_name),
                "reason": str(action_item.get("intent") or stage_intent(stage_name)),
                "command": str(action_item.get("command") or command.get("command") or ""),
                "source": "handoff",
                "status": str(handoff.get("status") or "ready"),
                "primary": "true" if index == 0 else "false",
                "read_before": list(action_item.get("read_before") or []),
            }
        )
        seen.add(stage_name)

    for index, item in enumerate(production_queue):
        stage_name = str(item.get("stage") or "")
        if not stage_name or stage_name in seen:
            continue
        command = commands_by_stage.get(stage_name, {})
        queue.append(
            {
                "key": f"queue:{stage_name}",
                "stage": stage_name,
                "action": str(command.get("action") or "build"),
                "label": str(item.get("label") or _label(stage_name)),
                "reason": str(item.get("intent") or stage_intent(stage_name)),
                "command": str(command.get("command") or ""),
                "source": str(item.get("source") or "queue"),
                "status": str(item.get("status") or "pending"),
                "primary": "true" if not queue and index == 0 else "false",
            }
        )
        seen.add(stage_name)

    for queue_item in rework_queues:
        stage_name = str(queue_item.get("target_stage") or "")
        action_count = int(queue_item.get("action_count") or 0)
        if not stage_name or not action_count or stage_name in seen:
            continue
        command = commands_by_stage.get(stage_name, {})
        queue.append(
            {
                "key": f"rework_queue:{queue_item.get('id')}",
                "stage": stage_name,
                "action": "build",
                "label": _label(stage_name),
                "reason": (f"{queue_item.get('label')} has {action_count} queued action(s)"),
                "command": str(command.get("command") or ""),
                "source": "rework_queue",
                "status": str(queue_item.get("status") or "queued"),
                "primary": "true" if not queue else "false",
                "queue_id": str(queue_item.get("id") or ""),
                "work_items": action_count,
            }
        )
        seen.add(stage_name)

    for item in command_suggestions:
        stage_name = str(item.get("stage") or "")
        if not stage_name or stage_name in seen:
            continue
        queue.append(
            {
                "key": str(item.get("key") or f"command:{stage_name}"),
                "stage": stage_name,
                "action": str(item.get("action") or "build"),
                "label": str(item.get("label") or _label(stage_name)),
                "reason": str(item.get("reason") or ""),
                "command": str(item.get("command") or ""),
                "source": "suggested",
                "status": str(rework_loop.get("status") or "pending"),
                "primary": "true" if not queue and item.get("primary") == "true" else "false",
            }
        )
        seen.add(stage_name)

    return queue[:8]


def _handoff_next_actions(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in handoff.get("next_actions", []) or [] if isinstance(item, dict)]


def _load_handoff(pipeline_dir: Path) -> dict[str, Any]:
    try:
        return load_yaml_mapping(pipeline_dir / "assistant_handoff.yaml")
    except ArtifactLoadError:
        return {}


def _workflow_session(
    project_dir: Path,
    pipeline_dir: Path,
    stage_dashboard: dict[str, Any],
    rework_loop: dict[str, Any],
    handoff: dict[str, Any],
    agent_queue: list[dict[str, Any]],
    canvas_nodes: list[dict[str, Any]],
    quality_gates: list[dict[str, Any]],
    rework_queues: list[dict[str, Any]],
) -> dict[str, Any]:
    current_stage = stage_dashboard.get("current_stage")
    current_name = str(current_stage.get("name") or "") if isinstance(current_stage, dict) else ""
    completed = int(stage_dashboard.get("completed") or 0)
    total = int(stage_dashboard.get("total") or 0)
    primary_action = agent_queue[0] if agent_queue else {}
    session_status = _session_status(rework_loop, current_name, primary_action, handoff)
    focus = _focus_canvas_node(canvas_nodes) or {}
    return {
        "id": f"{pipeline_dir.name}:{completed}:{session_status}",
        "project_handle": pipeline_dir.name,
        "project_path": project_dir.as_posix(),
        "pipeline_path": pipeline_dir.as_posix(),
        "status": session_status,
        "lifecycle": _session_lifecycle(session_status, handoff, agent_queue),
        "takeover_protocol": _takeover_protocol(project_dir, handoff, primary_action),
        "required_reading": _required_reading_rows(handoff),
        "quality_gates": quality_gates,
        "rework_queue_summary": _rework_queue_summary(rework_queues),
        "polling": {
            "status_command": f"narrascape status -p {_quote(project_dir)}",
            "refresh_handoff_command": (
                f"narrascape build -p {_quote(project_dir)} " "--stage assistant_handoff --approve"
            ),
            "watching": [
                "state.json",
                "film_supervisor.yaml",
                "assistant_handoff.yaml",
                "video_regen_queue.yaml",
                "recut_queue.yaml",
                "source_media_replacement_queue.yaml",
                "director_contract_rewrite_queue.yaml",
            ],
        },
        "primary_action": primary_action,
        "focus_node_id": str(focus.get("id") or ""),
        "progress": {
            "completed": completed,
            "total": total,
            "percent": int(stage_dashboard.get("progress") or 0),
        },
        "handoff_ready": bool(handoff),
        "handoff_status": str(handoff.get("status") or "missing"),
        "result_handles": _result_handles(project_dir, pipeline_dir, handoff),
    }


def _session_status(
    rework_loop: dict[str, Any],
    current_stage: str,
    primary_action: dict[str, Any],
    handoff: dict[str, Any],
) -> str:
    if primary_action:
        source = str(primary_action.get("source") or "")
        if source == "handoff":
            return "handoff_routed"
        if source == "supervisor":
            return "supervisor_routed"
        if source == "current":
            return "stage_ready"
        if source == "rework_queue":
            return "queue_routed"
        return "awaiting_artifact"
    if rework_loop.get("blocking"):
        return "blocked"
    if handoff.get("status") == "approved":
        return "ready_for_handoff"
    if current_stage:
        return "stage_ready"
    return "idle"


def _session_lifecycle(
    session_status: str,
    handoff: dict[str, Any],
    agent_queue: list[dict[str, Any]],
) -> list[dict[str, str]]:
    phases = [
        ("takeover", "Read pipeline state and takeover packet"),
        ("plan", "Resolve supervisor route and blocking artifacts"),
        ("execute", "Run approved narrascape stages"),
        ("poll", "Refresh state, handoff, and generated artifacts"),
        ("handoff", "Expose updated project state for human or agent takeover"),
    ]
    active_index = {
        "idle": 0,
        "awaiting_artifact": 1,
        "stage_ready": 2,
        "supervisor_routed": 2,
        "handoff_routed": 2,
        "queue_routed": 2,
        "blocked": 1,
        "ready_for_handoff": 4,
    }.get(session_status, 0)
    if handoff:
        active_index = max(active_index, 4 if not agent_queue else 2)
    return [
        {
            "id": phase_id,
            "label": label,
            "state": (
                "done" if index < active_index else "active" if index == active_index else "pending"
            ),
        }
        for index, (phase_id, label) in enumerate(phases)
    ]


def _result_handles(
    project_dir: Path,
    pipeline_dir: Path,
    handoff: dict[str, Any],
) -> list[dict[str, str]]:
    handles = [
        {
            "label": "Pipeline Canvas",
            "kind": "local_project",
            "path": project_dir.as_posix(),
            "status": "available" if project_dir.exists() else "missing",
        },
        {
            "label": "Pipeline State",
            "kind": "state",
            "path": (pipeline_dir / "state.json").as_posix(),
            "status": "available" if (pipeline_dir / "state.json").exists() else "missing",
        },
        {
            "label": "Assistant Handoff",
            "kind": "handoff",
            "path": (pipeline_dir / "assistant_handoff.yaml").as_posix(),
            "status": "available" if handoff else "missing",
        },
    ]
    return handles


def _takeover_protocol(
    project_dir: Path,
    handoff: dict[str, Any],
    primary_action: dict[str, Any],
) -> list[dict[str, str]]:
    next_command = str(primary_action.get("command") or "")
    next_stage = str(primary_action.get("stage") or "")
    return [
        {
            "id": "status",
            "label": "Status",
            "command": f"narrascape status -p {_quote(project_dir)}",
            "state": "ready",
        },
        {
            "id": "refresh_handoff",
            "label": "Refresh Handoff",
            "command": (
                f"narrascape build -p {_quote(project_dir)} --stage assistant_handoff --approve"
            ),
            "state": "done" if handoff else "ready",
        },
        {
            "id": "read_required",
            "label": "Required Reading",
            "command": ", ".join(item["path"] for item in _required_reading_rows(handoff)),
            "state": "ready" if handoff else "pending",
        },
        {
            "id": "run_next",
            "label": _label(next_stage) if next_stage else "Next Stage",
            "command": next_command,
            "state": "ready" if next_command else "pending",
        },
        {
            "id": "qa_refresh",
            "label": "QA And Handoff",
            "command": (
                f"narrascape build -p {_quote(project_dir)} --stage qa --approve\n"
                f"narrascape build -p {_quote(project_dir)} --stage assistant_handoff --approve"
            ),
            "state": "pending",
        },
    ]


def _required_reading_rows(handoff: dict[str, Any]) -> list[dict[str, str]]:
    if handoff:
        rows: list[dict[str, str]] = []
        for item in handoff.get("required_reading", []) or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if path:
                rows.append(
                    {
                        "path": path,
                        "reason": str(item.get("reason") or ""),
                    }
                )
        if rows:
            return rows
    return [
        {
            "path": "README.md",
            "reason": "project positioning and production profile",
        },
        {
            "path": "docs/ai-director.md",
            "reason": "AI Director boundaries and fallback rules",
        },
        {
            "path": "docs/assistant-handoff.md",
            "reason": "standard AI assistant takeover flow",
        },
    ]


def _quality_gates(
    project_dir: Path,
    pipeline_dir: Path,
    handoff: dict[str, Any],
) -> list[dict[str, Any]]:
    if handoff.get("quality_gates"):
        return [item for item in handoff.get("quality_gates", []) or [] if isinstance(item, dict)]
    config = _load_project_config(project_dir)
    llm_config = config.get("llm", {}) if isinstance(config.get("llm"), dict) else {}
    pipeline_config = config.get("pipeline", {}) if isinstance(config.get("pipeline"), dict) else {}
    readiness = _load_yaml_or_empty(pipeline_dir / "production_readiness.yaml")
    render_report = _load_yaml_or_empty(pipeline_dir / "render_report.yaml")
    return [
        {
            "id": "llm_mode",
            "status": str(llm_config.get("mode") or "unknown"),
            "required": "ai_assistant, bridge, api, or auto for production video",
        },
        {
            "id": "video_generation",
            "status": str(pipeline_config.get("video_generation") or "unknown"),
            "required": "required for production generated-video films",
        },
        {
            "id": "strict_director",
            "status": bool(pipeline_config.get("strict_director", False)),
            "required": True,
        },
        {
            "id": "production_quality_gates",
            "status": bool(pipeline_config.get("production_quality_gates", False)),
            "required": True,
        },
        {
            "id": "production_readiness",
            "status": str(readiness.get("status") or "missing"),
            "required": "ready before generated-video production",
        },
        {
            "id": "qa_errors",
            "status": len(render_report.get("errors", []) or []),
            "required": 0,
        },
    ]


def _load_project_config(project_dir: Path) -> dict[str, Any]:
    for name in ("config.yaml", "narrascape.yaml"):
        try:
            return load_yaml_mapping(project_dir / name)
        except ArtifactLoadError:
            continue
    return {}


def _load_yaml_or_empty(path: Path) -> dict[str, Any]:
    try:
        return load_yaml_mapping(path)
    except ArtifactLoadError:
        return {}


def _load_rework_queues(pipeline_dir: Path) -> list[dict[str, Any]]:
    queues: list[dict[str, Any]] = []
    for spec in REWORK_QUEUE_SPECS:
        path = pipeline_dir / spec["file"]
        actions = _queue_actions(path)
        queues.append(
            {
                "id": str(spec["id"]),
                "label": str(spec["label"]),
                "file": path.name,
                "path": path.as_posix(),
                "relative_path": path.name,
                "exists": path.exists(),
                "status": _queue_file_status(path),
                "source_stage": str(spec["source_stage"]),
                "target_stage": str(spec["target_stage"]),
                "action_count": len(actions),
                "actions": actions,
                "segment_ids": _queue_segment_ids(actions),
                "size_bytes": _path_size(path),
                "modified": _modified_time(path),
            }
        )
    return queues


def _queue_actions(path: Path) -> list[dict[str, Any]]:
    try:
        data = load_yaml_mapping(path)
    except ArtifactLoadError:
        return []
    actions = data.get("actions", [])
    return [item for item in actions if isinstance(item, dict)] if isinstance(actions, list) else []


def _queue_file_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    actions = _queue_actions(path)
    return "queued" if actions else "empty"


def _queue_segment_ids(actions: list[dict[str, Any]]) -> list[int]:
    segment_ids: list[int] = []
    for action in actions:
        value = action.get("segment_id")
        if value is None:
            continue
        try:
            segment_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return segment_ids


def _rework_queue_summary(rework_queues: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(rework_queues),
        "available": sum(1 for item in rework_queues if item.get("exists")),
        "queued": sum(1 for item in rework_queues if int(item.get("action_count") or 0) > 0),
        "actions": sum(int(item.get("action_count") or 0) for item in rework_queues),
    }


def _node_inspector(
    project_dir: Path,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    command_suggestions: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    commands_by_stage = {str(item.get("stage") or ""): item for item in command_suggestions}
    nodes_by_id = {str(node.get("id") or ""): node for node in nodes}
    inspector: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        stage = str(node.get("stage") or "")
        artifact_value = node.get("artifact")
        artifact = artifact_value if isinstance(artifact_value, dict) else {}
        upstream_ids = [edge["from"] for edge in edges if edge.get("to") == node_id]
        downstream_ids = [edge["to"] for edge in edges if edge.get("from") == node_id]
        upstream = [nodes_by_id[item]["label"] for item in upstream_ids if item in nodes_by_id]
        downstream = [nodes_by_id[item]["label"] for item in downstream_ids if item in nodes_by_id]
        command = commands_by_stage.get(stage, {})
        queue_items = [item for item in node.get("queue_items", []) or [] if isinstance(item, dict)]
        required_reading = [
            item for item in node.get("required_reading", []) or [] if isinstance(item, dict)
        ]
        handoff_action = (
            node.get("handoff_next_action")
            if isinstance(node.get("handoff_next_action"), dict)
            else {}
        )
        inspector[node_id] = {
            "id": node_id,
            "label": str(node.get("label") or ""),
            "stage": stage,
            "kind": str(node.get("kind") or "stage"),
            "state": str(node.get("state") or "pending"),
            "status": str(node.get("status") or "pending"),
            "stage_status": str(node.get("stage_status") or "pending"),
            "approval": str(node.get("approval") or "unknown"),
            "intent": str(node.get("intent") or stage_intent(stage)),
            "artifact": artifact,
            "artifacts": list(node.get("artifacts") or []),
            "depends_on": list(node.get("depends_on") or []),
            "outputs": list(node.get("outputs") or []),
            "output_files": list(node.get("output_files") or []),
            "stage_doc": str(node.get("stage_doc") or ""),
            "production_boundary": bool(node.get("production_boundary")),
            "queue_items": queue_items,
            "handoff_next_action": handoff_action,
            "required_reading": required_reading,
            "upstream_ids": upstream_ids,
            "downstream_ids": downstream_ids,
            "upstream": upstream,
            "downstream": downstream,
            "blocking_reason": _blocking_reason(node, artifact),
            "actions": _node_actions(project_dir, node, command),
        }
    return inspector


def _blocking_reason(node: dict[str, Any], artifact: dict[str, Any]) -> str:
    if node.get("current"):
        return "Current pipeline cursor is here."
    if node.get("queued"):
        if node.get("handoff_next_action"):
            return "Assistant handoff selected this stage for the next run."
        if node.get("queue_items"):
            return "Rework queue has concrete work for this stage."
        return "Supervisor or queue selected this stage for the next run."
    approval = str(node.get("approval") or "")
    if approval in {"pending", "rejected"}:
        return f"Approval gate is {approval}."
    if artifact and not artifact.get("exists"):
        return f"{artifact.get('file')} has not been written yet."
    status = str(node.get("status") or "")
    if status in _ATTENTION_STATUSES:
        return f"Artifact status is {status}."
    if str(node.get("stage_status") or "") == "failed":
        return "Stage failed in pipeline state."
    if node.get("production_boundary"):
        return "Provider boundary: announce provider, model, stage, reason, and sample/batch before production calls."
    return ""


def _node_actions(
    project_dir: Path,
    node: dict[str, Any],
    command: dict[str, str],
) -> list[dict[str, str]]:
    stage = str(node.get("stage") or "")
    actions: list[dict[str, str]] = []
    if stage:
        actions.append(
            {
                "id": "run",
                "label": "Run Stage",
                "command": str(
                    command.get("command")
                    or f"narrascape build -p {_quote(project_dir)} --stage {stage} --approve"
                ),
                "mode": "build",
            }
        )
        actions.append(
            {
                "id": "approve",
                "label": "Approve Stage",
                "command": f"narrascape approve -p {_quote(project_dir)} --stage {stage}",
                "mode": "approve",
            }
        )
    artifact_value = node.get("artifact")
    artifact = artifact_value if isinstance(artifact_value, dict) else {}
    if artifact.get("path"):
        actions.append(
            {
                "id": "inspect",
                "label": "Inspect Artifact",
                "command": str(artifact.get("path") or ""),
                "mode": "inspect",
            }
        )
    return actions


def _artifact_events(
    artifacts: list[dict[str, Any]],
    stage_dashboard: dict[str, Any],
) -> list[dict[str, Any]]:
    stages_by_name = stage_dashboard.get("stage_by_name", {})
    events = []
    for artifact in sorted(
        artifacts,
        key=lambda item: float(item.get("modified") or 0.0),
        reverse=True,
    ):
        stage_name = str(artifact.get("stage") or "")
        stage = stages_by_name.get(stage_name, {}) if isinstance(stages_by_name, dict) else {}
        events.append(
            {
                "artifact": str(artifact.get("label") or artifact.get("id") or ""),
                "stage": stage_name,
                "status": str(artifact.get("status") or "missing"),
                "exists": bool(artifact.get("exists")),
                "path": str(artifact.get("relative_path") or artifact.get("path") or ""),
                "modified": float(artifact.get("modified") or 0.0),
                "stage_status": str(stage.get("status") or "pending"),
            }
        )
    return events[:10]


def _handoff_summary(handoff: dict[str, Any]) -> dict[str, Any]:
    if not handoff:
        return {
            "status": "missing",
            "required_reading": [],
            "next_actions": [],
            "blocking_items": [],
            "quality_gates": [],
            "commands": {},
            "director_decision": {},
        }
    return {
        "status": str(handoff.get("status") or "unknown"),
        "required_reading": list(handoff.get("required_reading") or []),
        "next_actions": list(handoff.get("next_actions") or []),
        "blocking_items": list(handoff.get("blocking_items") or []),
        "quality_gates": list(handoff.get("quality_gates") or []),
        "commands": dict(handoff.get("commands") or {}),
        "director_decision": dict(handoff.get("director_decision") or {}),
    }


def _interaction_model() -> list[dict[str, str]]:
    return [
        {
            "principle": "Agent session",
            "libtv": "Create a session, poll progress, surface downloadable results.",
            "narrascape": "Treat pipeline state plus assistant_handoff as the local session.",
        },
        {
            "principle": "Canvas takeover",
            "libtv": "Return a project URL so humans can continue editing on the canvas.",
            "narrascape": "Expose project path, state file, handoff, and node inspector as takeover handles.",
        },
        {
            "principle": "Reusable DAG",
            "libtv": "Nodes encode reusable media and model operations.",
            "narrascape": "Nodes encode stages, artifacts, upstream dependencies, and rerun commands.",
        },
        {
            "principle": "Result loop",
            "libtv": "Generated assets flow back into the canvas.",
            "narrascape": "Artifacts and rework queues flow back into timeline, QA, supervisor, and handoff.",
        },
    ]


def _queue_item(stage_name: str, stage: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "stage": stage_name,
        "label": _label(stage_name),
        "status": str(stage.get("status") or "pending"),
        "approval": str(stage.get("approval") or "unknown"),
        "source": source,
        "intent": stage_intent(stage_name),
    }


def _recommended_commands(
    project_dir: Path,
    stage_dashboard: dict[str, Any],
    artifacts: list[dict[str, Any]],
    rework_loop: dict[str, Any],
) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()

    for stage_name in rework_loop.get("next_stages", []) or []:
        _append_command(
            suggestions,
            seen,
            project_dir,
            str(stage_name),
            "film_supervisor requested this stage",
        )

    current_stage = stage_dashboard.get("current_stage")
    if isinstance(current_stage, dict):
        stage_name = str(current_stage.get("name") or "")
        if stage_name:
            status = str(current_stage.get("status") or "pending")
            _append_command(suggestions, seen, project_dir, stage_name, f"stage is {status}")

    for artifact in artifacts:
        if artifact.get("exists"):
            continue
        _append_command(
            suggestions,
            seen,
            project_dir,
            str(artifact["stage"]),
            f"{artifact['file']} is missing",
        )

    if not suggestions:
        suggestions.append(
            {
                "key": "status",
                "stage": "status",
                "action": "status",
                "label": "Inspect status",
                "reason": "all tracked workbench artifacts are present",
                "command": f"narrascape status -p {_quote(project_dir)}",
                "primary": "false",
            }
        )
    suggestions = [item for item in suggestions if item.get("stage") != "assistant_handoff"]
    seen.discard("assistant_handoff")
    suggestions = suggestions[:7]
    _append_command(
        suggestions,
        seen,
        project_dir,
        "assistant_handoff",
        "refresh the assistant takeover packet",
        action="build",
    )
    return suggestions[:8]


def _append_command(
    suggestions: list[dict[str, str]],
    seen: set[str],
    project_dir: Path,
    stage_name: str,
    reason: str,
    *,
    action: str = "build",
) -> None:
    if not stage_name or stage_name in seen:
        return
    seen.add(stage_name)
    index = len(suggestions)
    suggestions.append(
        {
            "key": f"{action}:{stage_name}",
            "stage": stage_name,
            "action": action,
            "label": _label(stage_name),
            "reason": reason,
            "command": (
                f"narrascape build -p {_quote(project_dir)} " f"--stage {stage_name} --approve"
            ),
            "primary": "true" if index == 0 else "false",
        }
    )


def _relative_path(project_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(project_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _path_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _modified_time(path: Path) -> float:
    try:
        return path.stat().st_mtime if path.exists() else 0.0
    except OSError:
        return 0.0


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml", ".json", ".md", ".txt"}:
        return "text"
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    if suffix in {".mp4", ".mov"}:
        return "video"
    if suffix in {".mp3", ".wav", ".aac"}:
        return "audio"
    return "file"


def _quote(value: Path) -> str:
    text = str(value)
    if not text or any(char.isspace() for char in text):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _label(value: str) -> str:
    return value.replace("_", " ").title()
