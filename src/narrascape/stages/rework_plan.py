from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult


class ReworkPlanStage(Stage):
    """Merge director, editing, and continuity reviews into an executable rework plan."""

    name = "rework_plan"
    depends_on = ["director_review", "editing_review", "continuity_bible"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        required = [
            context.config.pipeline_dir / "director_review.yaml",
            context.config.pipeline_dir / "editing_review.yaml",
            context.config.pipeline_dir / "continuity_bible.yaml",
        ]
        missing = [path.name for path in required if not path.exists()]
        if missing:
            return False, f"Missing director artifact(s): {', '.join(missing)}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "rework_plan.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        director_review = self._load_yaml(config.pipeline_dir / "director_review.yaml")
        editing_review = self._load_yaml(config.pipeline_dir / "editing_review.yaml")
        continuity_bible = self._load_yaml(config.pipeline_dir / "continuity_bible.yaml")

        actions: list[dict[str, Any]] = []
        actions.extend(self._from_director_review(director_review))
        actions.extend(self._from_editing_review(editing_review))
        actions.extend(self._from_continuity_bible(continuity_bible))
        actions = self._dedupe_and_prioritize(actions)
        plan = {
            "schema_version": "rework_plan.v1",
            "project": {
                "name": config.project.name,
                "title": config.project.title,
            },
            "status": "needs_rework" if actions else "approved",
            "sources": {
                "director_review": (config.pipeline_dir / "director_review.yaml").as_posix(),
                "editing_review": (config.pipeline_dir / "editing_review.yaml").as_posix(),
                "continuity_bible": (config.pipeline_dir / "continuity_bible.yaml").as_posix(),
            },
            "actions": actions,
            "actions_by_type": self._actions_by_type(actions),
        }
        validate_artifact("rework_plan", plan)
        output.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(actions)} planned rework action(s)" if actions else "no rework needed",
            metadata={"action_count": len(actions), "plan": output.as_posix()},
        )

    def _from_director_review(self, review: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []
        for item in review.get("rework_queue", []) or []:
            actions.append(
                {
                    "segment_id": int(item["segment_id"]),
                    "action": item.get("action", "regenerate_video"),
                    "reason": item.get("reason", "director_review"),
                    "priority": self._priority_for(item.get("reason", ""), item.get("action", "")),
                    "source": "director_review",
                }
            )
        return actions

    def _from_editing_review(self, review: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []
        for item in review.get("recommendations", []) or []:
            actions.append(
                {
                    "segment_id": int(item["segment_id"]),
                    "action": item.get("action", "recut"),
                    "reason": item.get("reason", "editing_review"),
                    "priority": item.get("priority")
                    or self._priority_for(item.get("reason", ""), item.get("action", "")),
                    "source": "editing_review",
                }
            )
        return actions

    def _from_continuity_bible(self, bible: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []
        for risk in bible.get("continuity_risks", []) or []:
            actions.append(
                {
                    "segment_id": int(risk["segment_id"]),
                    "action": "regenerate_video",
                    "reason": risk.get("risk_type", "continuity_risk"),
                    "priority": "high",
                    "source": "continuity_bible",
                }
            )
        return actions

    def _dedupe_and_prioritize(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[tuple[int, str, str], dict[str, Any]] = {}
        priority_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        for action in actions:
            key = (int(action["segment_id"]), action["action"], action["reason"])
            existing = merged.get(key)
            if not existing:
                merged[key] = action
                continue
            existing_sources = set(str(existing.get("source", "")).split("+"))
            existing_sources.add(str(action.get("source", "")))
            existing["source"] = "+".join(sorted(source for source in existing_sources if source))
            if priority_rank.get(action.get("priority", "low"), 0) > priority_rank.get(
                existing.get("priority", "low"), 0
            ):
                existing["priority"] = action["priority"]
        return sorted(
            merged.values(),
            key=lambda item: (
                -priority_rank.get(item.get("priority", "low"), 0),
                int(item["segment_id"]),
                item["action"],
            ),
        )

    def _actions_by_type(self, actions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped = {
            "regenerate_video": [],
            "recut": [],
            "replace_source_media": [],
        }
        for action in actions:
            grouped.setdefault(action["action"], []).append(action)
        return grouped

    def _priority_for(self, reason: str, action: str) -> str:
        if reason in {
            "missing_visual",
            "missing_video_clip",
            "continuity_risk",
            "wardrobe_jump",
            "screen_axis_flip",
        }:
            return "high"
        if action == "recut" or reason in {"pacing_risk", "repeated_visual_asset"}:
            return "medium"
        return "low"

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
