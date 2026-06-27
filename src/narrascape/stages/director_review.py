from __future__ import annotations

from typing import Any

import yaml

from narrascape.stages.base import Stage, StageContext, StageResult


class DirectorReviewStage(Stage):
    """Convert QA findings into director rework actions."""

    name = "director_review"
    depends_on = ["qa"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        report_path = context.config.pipeline_dir / "render_report.yaml"
        if not report_path.exists():
            return False, f"render_report.yaml not found: {report_path}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        report_path = context.config.pipeline_dir / "render_report.yaml"
        report = yaml.safe_load(report_path.read_text(encoding="utf-8")) or {}
        checks = report.get("checks", {})
        queue = self._build_rework_queue(checks)
        status = "needs_rework" if queue or report.get("errors") else "approved"
        review = {
            "status": status,
            "source_report": report_path.as_posix(),
            "rework_queue": queue,
            "notes": self._notes(report, queue),
        }
        output = context.config.pipeline_dir / "director_review.yaml"
        output.write_text(yaml.safe_dump(review, sort_keys=False), encoding="utf-8")
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(queue)} rework action(s)" if queue else "director review approved",
            metadata={"status": status, "rework_count": len(queue)},
        )

    def _build_rework_queue(self, checks: dict[str, Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for segment_id in checks.get("missing_visual_segments", []) or []:
            actions.append(
                {
                    "segment_id": int(segment_id),
                    "action": "regenerate_video",
                    "reason": "missing_visual",
                }
            )
        for segment_id in checks.get("missing_generated_video_segments", []) or []:
            actions.append(
                {
                    "segment_id": int(segment_id),
                    "action": "regenerate_video",
                    "reason": "missing_generated_video",
                }
            )
        for segment_id in checks.get("missing_video_clips", []) or []:
            actions.append(
                {
                    "segment_id": int(segment_id),
                    "action": "regenerate_video",
                    "reason": "missing_video_clip",
                }
            )
        for segment_id in checks.get("continuity_risk_segments", []) or []:
            actions.append(
                {
                    "segment_id": int(segment_id),
                    "action": "regenerate_video",
                    "reason": "continuity_risk",
                }
            )
        for segment_id in checks.get("pacing_risk_segments", []) or []:
            actions.append(
                {
                    "segment_id": int(segment_id),
                    "action": "recut",
                    "reason": "pacing_risk",
                }
            )

        deduped: list[dict[str, Any]] = []
        seen = set()
        for action in actions:
            key = (action["segment_id"], action["action"], action["reason"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(action)
        return deduped

    def _notes(self, report: dict[str, Any], queue: list[dict[str, Any]]) -> list[str]:
        notes = []
        if report.get("errors"):
            notes.append("QA reported blocking errors; rework is required before delivery.")
        if queue:
            notes.append("Review each rework action, then regenerate video or recut the affected segment.")
        return notes
