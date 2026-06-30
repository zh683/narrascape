from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from narrascape.utils.safe_io import ArtifactLoadError, load_yaml_mapping


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
