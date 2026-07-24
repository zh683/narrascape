from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from narrascape.pipeline import PipelineState, get_stage_map
from narrascape.pipeline_approval import PipelineApproval
from narrascape.utils.safe_io import ArtifactLoadError, load_yaml_mapping


def load_stage_dashboard(project_dir: Path, pipeline_dir: Path) -> dict[str, Any]:
    """Load canonical stage status data for product dashboards."""

    stage_map = get_stage_map()
    state = PipelineState(pipeline_dir / "state.json")
    approval = PipelineApproval(pipeline_dir)
    approvals = approval.list_all()
    stages: list[dict[str, Any]] = []
    counts = {
        "completed": 0,
        "running": 0,
        "failed": 0,
        "skipped": 0,
        "pending": 0,
    }

    for index, (stage_name, stage_cls) in enumerate(stage_map.items(), 1):
        stage = stage_cls()
        status = state.get_stage_status(stage_name)
        if status not in counts:
            counts[status] = 0
        counts[status] += 1
        recorded_outputs = state.get_stage_outputs(stage_name)
        expected_outputs = _expected_stage_outputs(project_dir, pipeline_dir.name, stage.outputs)
        output_paths = recorded_outputs or [path.as_posix() for path in expected_outputs]
        output_files = _output_file_rows(output_paths)
        output_size = sum(int(row["size_bytes"]) for row in output_files)
        output_complete = bool(output_paths) and all(
            bool(row["exists"]) for row in _output_rows(output_paths)
        )
        stages.append(
            {
                "index": index,
                "name": stage_name,
                "label": _stage_label(stage_name),
                "status": status,
                "done": status == "completed",
                "approval": approvals.get(stage_name, "unknown"),
                "depends_on": list(stage.depends_on),
                "outputs": output_paths,
                "output_files": output_files,
                "output_count": len(output_files),
                "output_size": output_size,
                "output_complete": output_complete,
            }
        )

    completed = counts.get("completed", 0)
    total = len(stages)
    current = next(
        (stage for stage in stages if stage["status"] in {"running", "failed"}),
        next((stage for stage in stages if stage["status"] == "pending"), None),
    )
    return {
        "project_dir": project_dir.as_posix(),
        "pipeline_dir": pipeline_dir.as_posix(),
        "state_file": (pipeline_dir / "state.json").as_posix(),
        "total": total,
        "completed": completed,
        "progress": int(completed / total * 100) if total else 0,
        "counts": counts,
        "stages": stages,
        "stage_by_name": {stage["name"]: stage for stage in stages},
        "current_stage": current,
    }


def load_timeline_dashboard(project_dir: Path, pipeline_dir: Path) -> dict[str, Any]:
    """Load film timeline and Remotion preview data for product dashboards."""

    timeline_path = project_dir / "film_timeline.yaml"
    if not timeline_path.exists():
        return {
            "status": "missing_timeline",
            "timeline_path": timeline_path.as_posix(),
            "duration": 0.0,
            "coverage": {},
            "visual": [],
            "source_counts": {},
            "missing_assets": [],
            "remotion": _load_remotion_preview(pipeline_dir),
            "rework_loop": load_rework_loop_summary(pipeline_dir),
        }

    timeline = load_yaml_mapping(timeline_path)
    visual = [
        _normalize_visual_clip(project_dir, item)
        for item in timeline.get("tracks", {}).get("visual", []) or []
        if isinstance(item, dict)
    ]
    source_counts = Counter(str(item.get("source") or "unknown") for item in visual)
    missing_assets = [
        {
            "id": item["id"],
            "source": item["source"],
            "path": item["path"],
            "segment_id": item.get("segment_id"),
        }
        for item in visual
        if item["requires_asset"] and not item["asset_exists"]
    ]

    return {
        "status": "ready" if not missing_assets else "missing_assets",
        "timeline_path": timeline_path.as_posix(),
        "duration": float(timeline.get("duration") or 0.0),
        "project": timeline.get("project", {}),
        "coverage": timeline.get("coverage", {}),
        "visual": visual,
        "source_counts": dict(source_counts),
        "missing_assets": missing_assets,
        "remotion": _load_remotion_preview(pipeline_dir),
        "rework_loop": load_rework_loop_summary(pipeline_dir),
    }


def load_rework_loop_summary(pipeline_dir: Path) -> dict[str, Any]:
    """Summarize QA, director review, rework execution, and supervisor routing."""

    rework_plan = _load_yaml_or_empty(pipeline_dir / "rework_plan.yaml")
    supervisor = _load_yaml_or_empty(pipeline_dir / "film_supervisor.yaml")
    execution = _load_yaml_or_empty(pipeline_dir / "rework_execution.yaml")
    render_report = _load_yaml_or_empty(pipeline_dir / "render_report.yaml")
    creative_review = _load_yaml_or_empty(pipeline_dir / "creative_review.yaml")
    visual_report = _load_yaml_or_empty(pipeline_dir / "visual_semantic_report.yaml")

    actions = [item for item in rework_plan.get("actions", []) or [] if isinstance(item, dict)]
    next_stages = [str(item) for item in supervisor.get("next_stages", []) or []]
    executed = [
        item for item in execution.get("executed_actions", []) or [] if isinstance(item, dict)
    ]
    qa_errors = [str(item) for item in render_report.get("errors", []) or []]
    qa_warnings = [str(item) for item in render_report.get("warnings", []) or []]
    creative_recommendations = [
        item for item in creative_review.get("recommendations", []) or [] if isinstance(item, dict)
    ]
    visual_findings = [
        item for item in visual_report.get("findings", []) or [] if isinstance(item, dict)
    ]

    if next_stages:
        status = "needs_rework"
    elif supervisor.get("status"):
        status = str(supervisor.get("status"))
    elif actions or qa_errors or creative_recommendations or visual_findings:
        status = "pending_supervisor"
    else:
        status = "not_started"

    return {
        "status": status,
        "rework_status": str(rework_plan.get("status") or "missing"),
        "supervisor_status": str(supervisor.get("status") or "missing"),
        "execution_status": str(execution.get("status") or "missing"),
        "action_count": len(actions),
        "actions_by_type": _action_counts(actions),
        "next_stages": next_stages,
        "executed_count": len(executed),
        "qa_error_count": len(qa_errors),
        "qa_warning_count": len(qa_warnings),
        "creative_recommendation_count": len(creative_recommendations),
        "visual_finding_count": len(visual_findings),
        "blocking": bool(next_stages or qa_errors),
        "sources": {
            "rework_plan": (pipeline_dir / "rework_plan.yaml").as_posix(),
            "film_supervisor": (pipeline_dir / "film_supervisor.yaml").as_posix(),
            "rework_execution": (pipeline_dir / "rework_execution.yaml").as_posix(),
            "render_report": (pipeline_dir / "render_report.yaml").as_posix(),
            "creative_review": (pipeline_dir / "creative_review.yaml").as_posix(),
            "visual_semantic_report": (pipeline_dir / "visual_semantic_report.yaml").as_posix(),
        },
    }


def _normalize_visual_clip(project_dir: Path, clip: dict[str, Any]) -> dict[str, Any]:
    source = str(clip.get("source") or "unknown")
    timeline_path = str(clip.get("path") or "")
    requires_asset = source not in {"ending_card"} and bool(timeline_path)
    asset_path = project_dir / timeline_path if timeline_path else None
    return {
        "id": str(clip.get("id") or ""),
        "segment_id": clip.get("segment_id"),
        "source": source,
        "asset_ref": clip.get("asset_ref"),
        "path": timeline_path,
        "start": float(clip.get("start") or 0.0),
        "duration": float(clip.get("duration") or 0.0),
        "shot_type": clip.get("shot_type"),
        "movement": clip.get("movement"),
        "emotion": clip.get("emotion"),
        "character_ids": list(clip.get("character_ids") or []),
        "storyboard_frame_ids": list(clip.get("storyboard_frame_ids") or []),
        "composition": clip.get("composition"),
        "requires_asset": requires_asset,
        "asset_exists": bool(asset_path and asset_path.exists()) if requires_asset else True,
    }


def _load_remotion_preview(pipeline_dir: Path) -> dict[str, Any]:
    path = pipeline_dir / "remotion_preview.yaml"
    if not path.exists():
        return {
            "status": "missing",
            "path": path.as_posix(),
            "root": "",
            "missing": [],
            "commands": {},
        }
    report = load_yaml_mapping(path)
    project = report.get("project", {}) if isinstance(report.get("project"), dict) else {}
    assets = report.get("assets", {}) if isinstance(report.get("assets"), dict) else {}
    commands = report.get("commands", {}) if isinstance(report.get("commands"), dict) else {}
    return {
        "status": str(report.get("status") or "unknown"),
        "path": path.as_posix(),
        "root": str(project.get("root") or ""),
        "missing": list(assets.get("missing") or []),
        "commands": commands,
    }


def _load_yaml_or_empty(path: Path) -> dict[str, Any]:
    try:
        return load_yaml_mapping(path)
    except ArtifactLoadError:
        return {}


def _action_counts(actions: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(item.get("action") or "unknown") for item in actions)
    return dict(counts)


def _stage_label(stage_name: str) -> str:
    return stage_name.replace("_", " ").title()


def _expected_stage_outputs(project_dir: Path, project_name: str, outputs: Any) -> list[Path]:
    result: list[Path] = []
    for item in _flatten_output_values(outputs):
        text = str(item)
        if not text or text.endswith("/"):
            continue
        text = text.format(name=project_name)
        path = Path(text)
        if not path.is_absolute():
            path = project_dir / path
        result.append(path)
    return result


def _flatten_output_values(value: Any) -> list[str | Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [value]
    if isinstance(value, dict):
        flattened: list[str | Path] = []
        for item in value.values():
            flattened.extend(_flatten_output_values(item))
        return flattened
    if isinstance(value, (list, tuple, set)):
        flattened = []
        for item in value:
            flattened.extend(_flatten_output_values(item))
        return flattened
    return []


def _output_rows(paths: list[str]) -> list[dict[str, Any]]:
    rows = []
    for item in paths:
        path = Path(item)
        rows.append(
            {
                "path": path.as_posix(),
                "name": path.name,
                "exists": path.exists(),
                "is_dir": path.is_dir(),
                "size_bytes": _path_size(path) if path.is_file() else 0,
            }
        )
    return rows


def _output_file_rows(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _output_rows(paths):
        path = Path(str(row["path"]))
        if path.is_file():
            rows.append(row)
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    rows.append(
                        {
                            "path": child.as_posix(),
                            "name": child.name,
                            "exists": True,
                            "is_dir": False,
                            "size_bytes": _path_size(child),
                        }
                    )
    return rows


def _path_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
