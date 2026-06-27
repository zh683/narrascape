from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult


class FilmSupervisorStage(Stage):
    """Top-level production supervisor that decides the next pipeline cycle."""

    name = "film_supervisor"
    depends_on = ["rework_plan", "creative_review", "visual_semantic_qa"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        required = [
            context.config.pipeline_dir / "rework_plan.yaml",
            context.config.pipeline_dir / "creative_review.yaml",
            context.config.pipeline_dir / "visual_semantic_report.yaml",
        ]
        missing = [path.name for path in required if not path.exists()]
        if missing:
            return False, f"Missing supervisor input(s): {', '.join(missing)}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "film_supervisor.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        rework_plan = self._load_yaml(config.pipeline_dir / "rework_plan.yaml")
        creative_review = self._load_yaml(config.pipeline_dir / "creative_review.yaml")
        visual_report = self._load_yaml(config.pipeline_dir / "visual_semantic_report.yaml")
        render_report = self._load_yaml(config.pipeline_dir / "render_report.yaml")

        actions = list(rework_plan.get("actions", []) or [])
        creative_recommendations = list(creative_review.get("recommendations", []) or [])
        visual_findings = list(visual_report.get("findings", []) or [])
        blocking_errors = list(render_report.get("errors", []) or [])
        next_stages = self._next_stages(actions, creative_recommendations, visual_findings, blocking_errors)
        status = "needs_rework" if next_stages else "approved"
        report = {
            "schema_version": "film_supervisor.v1",
            "project": {"name": config.project.name, "title": config.project.title},
            "status": status,
            "decision": {
                "rework_action_count": len(actions),
                "creative_recommendation_count": len(creative_recommendations),
                "visual_finding_count": len(visual_findings),
                "blocking_error_count": len(blocking_errors),
            },
            "next_stages": next_stages,
            "sources": {
                "rework_plan": (config.pipeline_dir / "rework_plan.yaml").as_posix(),
                "creative_review": (config.pipeline_dir / "creative_review.yaml").as_posix(),
                "visual_semantic_report": (config.pipeline_dir / "visual_semantic_report.yaml").as_posix(),
                "render_report": (config.pipeline_dir / "render_report.yaml").as_posix(),
            },
        }
        validate_artifact("film_supervisor", report)
        output.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"supervisor status: {status}",
            metadata={"status": status, "next_stages": next_stages},
        )

    def _next_stages(
        self,
        actions: list[dict[str, Any]],
        creative_recommendations: list[dict[str, Any]],
        visual_findings: list[dict[str, Any]],
        blocking_errors: list[str],
    ) -> list[str]:
        stages: list[str] = []
        if actions or creative_recommendations or visual_findings or blocking_errors:
            stages.append("rework_execute")
        all_actions = actions + creative_recommendations
        if any(item.get("action") == "regenerate_video" for item in all_actions) or visual_findings:
            stages.extend(["generate_video", "take_select", "film_timeline"])
        if any(item.get("action") == "replace_source_media" for item in all_actions):
            stages.extend(["source_media", "film_timeline"])
        if any(item.get("action") == "recut" for item in all_actions):
            stages.extend(["film_timeline", "film_assemble"])
        if stages:
            stages.extend(["film_assemble", "audio", "subtitles", "qa", "continuity_bible", "editing_review", "director_review", "rework_plan", "creative_review", "visual_semantic_qa", "film_supervisor"])
        return self._dedupe(stages)

    def _dedupe(self, stages: list[str]) -> list[str]:
        result: list[str] = []
        seen = set()
        for stage in stages:
            if stage in seen:
                continue
            seen.add(stage)
            result.append(stage)
        return result

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
