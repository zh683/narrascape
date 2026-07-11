from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import atomic_write_yaml


class CreativeReviewStage(Stage):
    """LLM-backed creative review for story, rhythm, and cinematic intent."""

    name = "creative_review"
    depends_on = ["editing_review", "continuity_bible"]

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        timeline = context.config.project_dir / "film_timeline.yaml"
        if not timeline.exists():
            return False, f"film_timeline.yaml not found: {timeline}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "creative_review.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        timeline = self._load_yaml(config.project_dir / "film_timeline.yaml")
        editing = self._load_yaml(config.pipeline_dir / "editing_review.yaml")
        continuity = self._load_yaml(config.pipeline_dir / "continuity_bible.yaml")
        render_report = self._load_yaml(config.pipeline_dir / "render_report.yaml")

        llm_status = "not_configured"
        llm_error = ""
        if self.llm_client:
            try:
                result = self._ask_llm(timeline, editing, continuity, render_report, context)
                findings = list(result.get("findings", []) or [])
                recommendations = list(result.get("recommendations", []) or [])
                status = result.get("status") or ("needs_rework" if recommendations else "approved")
                llm_status = "used"
            except Exception as exc:
                findings, recommendations = self._fallback_findings(
                    editing, continuity, render_report
                )
                status = "needs_rework" if recommendations else "approved"
                llm_status = "fallback_after_error"
                llm_error = str(exc)
        else:
            findings, recommendations = self._fallback_findings(editing, continuity, render_report)
            status = "needs_rework" if recommendations else "approved"

        review = {
            "schema_version": "creative_review.v1",
            "project": {"name": config.project.name, "title": config.project.title},
            "status": status,
            "review_process": {
                "mode": "llm_creative_review" if llm_status == "used" else "deterministic_fallback",
                "llm_status": llm_status,
                "llm_error": llm_error,
            },
            "findings": findings,
            "recommendations": recommendations,
        }
        validate_artifact("creative_review", review)
        atomic_write_yaml(output, review)
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(recommendations)} creative recommendation(s)",
            metadata={"status": status, "recommendation_count": len(recommendations)},
        )

    def _ask_llm(
        self,
        timeline: dict[str, Any],
        editing: dict[str, Any],
        continuity: dict[str, Any],
        render_report: dict[str, Any],
        context: StageContext,
    ) -> dict[str, Any]:
        prompt = (
            "You are the creative supervising director for an AI film pipeline. "
            "Review story clarity, cinematic intent, pacing, emotional arc, and continuity. "
            "Return only JSON with status, findings, and recommendations.\n\n"
            f"Project: {context.config.project.title}\n"
            f"Script segments: {json.dumps([s.model_dump() for s in context.script.segments], ensure_ascii=False)}\n"
            f"film_timeline: {json.dumps(self._compact_timeline(timeline), ensure_ascii=False)}\n"
            f"editing_review: {json.dumps(editing, ensure_ascii=False)}\n"
            f"continuity_bible: {json.dumps(continuity, ensure_ascii=False)}\n"
            f"render_report: {json.dumps(render_report, ensure_ascii=False)}\n\n"
            'Return JSON only: {"status":"approved|needs_rework","findings":[],"recommendations":[]}.'
        )
        response = self.llm_client.complete(prompt, json_mode=True)
        if hasattr(response, "extract_json_safe"):
            data = response.extract_json_safe(default={})
        else:
            data = json.loads(getattr(response, "content", "{}"))
        if not isinstance(data, dict):
            raise ValueError("LLM returned non-object JSON")
        return data

    def _fallback_findings(
        self,
        editing: dict[str, Any],
        continuity: dict[str, Any],
        render_report: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        findings: list[dict[str, Any]] = []
        recommendations: list[dict[str, Any]] = []
        for item in editing.get("recommendations", []) or []:
            segment_id = int(item.get("segment_id"))
            findings.append(
                {
                    "segment_id": segment_id,
                    "issue": item.get("reason", "editing_review"),
                    "severity": item.get("priority", "medium"),
                    "source": "editing_review",
                }
            )
            recommendations.append(
                {
                    "segment_id": segment_id,
                    "action": item.get("action", "recut"),
                    "reason": item.get("reason", "editing_review"),
                }
            )
        for risk in continuity.get("continuity_risks", []) or []:
            segment_id = int(risk.get("segment_id"))
            findings.append(
                {
                    "segment_id": segment_id,
                    "issue": risk.get("risk_type", "continuity_risk"),
                    "severity": risk.get("severity", "high"),
                    "source": "continuity_bible",
                }
            )
            recommendations.append(
                {
                    "segment_id": segment_id,
                    "action": "regenerate_video",
                    "reason": risk.get("risk_type", "continuity_risk"),
                }
            )
        for error in render_report.get("errors", []) or []:
            findings.append(
                {"segment_id": None, "issue": error, "severity": "high", "source": "render_report"}
            )
        return findings, self._dedupe_recommendations(recommendations)

    def _dedupe_recommendations(
        self, recommendations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen = set()
        for item in recommendations:
            key = (item.get("segment_id"), item.get("action"), item.get("reason"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _compact_timeline(self, timeline: dict[str, Any]) -> dict[str, Any]:
        tracks = timeline.get("tracks", {})
        return {
            "duration": timeline.get("duration"),
            "coverage": timeline.get("coverage", {}),
            "visual": tracks.get("visual", []),
        }

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return super()._load_yaml(path)
