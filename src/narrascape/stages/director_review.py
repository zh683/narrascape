from __future__ import annotations

import json
from typing import Any

from narrascape.artifacts import write_artifact
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
        report = self._load_yaml(report_path)
        checks = report.get("checks", {})
        queue = self._build_rework_queue(checks, context)
        status = "needs_rework" if queue or report.get("errors") else "approved"
        review = {
            "schema_version": "director_review.v1",
            "status": status,
            "source_report": report_path.as_posix(),
            "rework_queue": queue,
            "notes": self._notes(report, queue),
        }
        output = context.config.pipeline_dir / "director_review.yaml"
        write_artifact("director_review", output, review)
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(queue)} rework action(s)" if queue else "director review approved",
            metadata={"status": status, "rework_count": len(queue)},
        )

    def _build_rework_queue(
        self, checks: dict[str, Any], context: StageContext | None = None
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        require_generated_video = self._requires_generated_video(context)
        for segment_id in checks.get("missing_visual_segments", []) or []:
            actions.append(
                {
                    "segment_id": int(segment_id),
                    "action": "regenerate_video",
                    "reason": "missing_visual",
                }
            )
        if require_generated_video:
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

    def _requires_generated_video(self, context: StageContext | None) -> bool:
        if context is None:
            return True
        policy = context.config.pipeline.video_generation
        if policy == "required":
            return True
        if policy == "off":
            return False
        state_path = context.config.pipeline_dir / "video_gen_state.json"
        if not state_path.exists():
            return False
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return bool(state.get("done") or state.get("task_map") or state.get("errors"))

    def _notes(self, report: dict[str, Any], queue: list[dict[str, Any]]) -> list[str]:
        notes = []
        if report.get("errors"):
            notes.append("QA reported blocking errors; rework is required before delivery.")
        if queue:
            notes.append(
                "Review each rework action, then regenerate video or recut the affected segment."
            )
        return notes
