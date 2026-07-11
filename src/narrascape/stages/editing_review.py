from __future__ import annotations

from pathlib import Path
from typing import Any

from narrascape.artifacts import write_artifact
from narrascape.stages.base import Stage, StageContext, StageResult


class EditingReviewStage(Stage):
    """Review film_timeline.yaml for rhythm, repetition, and emotional curve."""

    name = "editing_review"
    depends_on = ["qa"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        timeline = context.config.project_dir / "film_timeline.yaml"
        if not timeline.exists():
            return False, f"film_timeline.yaml not found: {timeline}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "editing_review.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        timeline = self._load_yaml(config.project_dir / "film_timeline.yaml")
        render_report = self._load_yaml(config.pipeline_dir / "render_report.yaml")
        visual = self._story_clips(timeline)
        report_checks = render_report.get("checks", {})

        pacing = self._pacing(visual, report_checks)
        repetition = self._repetition(visual, report_checks)
        emotion_curve = self._emotion_curve(visual)
        recommendations = self._recommendations(pacing, repetition, emotion_curve)
        review = {
            "schema_version": "editing_review.v1",
            "project": {
                "name": config.project.name,
                "title": config.project.title,
            },
            "source_timeline": (config.project_dir / "film_timeline.yaml").as_posix(),
            "pacing": pacing,
            "repetition": repetition,
            "emotion_curve": emotion_curve,
            "recommendations": recommendations,
        }
        write_artifact("editing_review", output, review)
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(recommendations)} editing recommendation(s)",
            metadata={"recommendation_count": len(recommendations), "review": output.as_posix()},
        )

    def _story_clips(self, timeline: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            clip
            for clip in sorted(
                timeline.get("tracks", {}).get("visual", []),
                key=lambda item: float(item.get("start", 0.0)),
            )
            if clip.get("segment_id") is not None
        ]

    def _pacing(self, visual: list[dict[str, Any]], checks: dict[str, Any]) -> dict[str, Any]:
        risk_segments = {
            parsed
            for item in checks.get("pacing_risk_segments", []) or []
            if (parsed := self._to_int(item)) is not None
        }
        durations: list[dict[str, Any]] = []
        for clip in visual:
            segment_id = self._to_int(clip.get("segment_id"))
            if segment_id is None:
                continue
            duration = self._to_float(clip.get("duration"), default=0.0)
            durations.append({"segment_id": segment_id, "duration": round(duration, 3)})
            if duration < 2.5 or duration > 10.0:
                risk_segments.add(segment_id)
        average = sum(item["duration"] for item in durations) / max(len(durations), 1)
        return {
            "average_shot_seconds": round(average, 3),
            "durations": durations,
            "risk_segments": sorted(risk_segments),
            "diagnosis": "uneven" if risk_segments else "balanced",
        }

    def _repetition(self, visual: list[dict[str, Any]], checks: dict[str, Any]) -> dict[str, Any]:
        repeated: set[int] = set()
        seen_assets: dict[str, int] = {}
        repeated_assets: list[dict[str, Any]] = []
        for clip in visual:
            asset_ref = str(clip.get("asset_ref") or clip.get("path") or "")
            segment_id = self._to_int(clip.get("segment_id"))
            if segment_id is None:
                continue
            if asset_ref and asset_ref in seen_assets:
                repeated.add(segment_id)
                repeated_assets.append(
                    {
                        "asset_ref": asset_ref,
                        "first_segment_id": seen_assets[asset_ref],
                        "repeated_segment_id": segment_id,
                    }
                )
            elif asset_ref:
                seen_assets[asset_ref] = segment_id

        if checks.get("repeated_shot_risk") and not repeated:
            for segment_id in checks.get("repeated_shot_segments", []) or []:
                parsed = self._to_int(segment_id)
                if parsed is not None:
                    repeated.add(parsed)

        return {
            "risk": bool(repeated),
            "repeated_shot_segments": sorted(repeated),
            "repeated_assets": repeated_assets,
        }

    def _emotion_curve(self, visual: list[dict[str, Any]]) -> dict[str, Any]:
        beats = []
        for clip in visual:
            segment_id = self._to_int(clip.get("segment_id"))
            if segment_id is None:
                continue
            start = self._to_float(clip.get("start"), default=0.0)
            intensity = self._to_float(clip.get("intensity"), default=0.0)
            beats.append(
                {
                    "segment_id": segment_id,
                    "start": round(start, 3),
                    "emotion": clip.get("emotion") or "neutral",
                    "intensity": round(intensity, 3),
                }
            )
        intensity_values = [float(beat["intensity"]) for beat in beats]
        flatline = len(set(intensity_values)) <= 1 and len(intensity_values) > 1
        return {
            "beats": beats,
            "arc": self._arc(intensity_values),
            "flatline_risk": flatline,
        }

    def _recommendations(
        self,
        pacing: dict[str, Any],
        repetition: dict[str, Any],
        emotion_curve: dict[str, Any],
    ) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        for segment_id in pacing["risk_segments"]:
            recommendations.append(
                {
                    "segment_id": segment_id,
                    "action": "recut",
                    "reason": "pacing_risk",
                    "priority": "high",
                }
            )
        for segment_id in repetition["repeated_shot_segments"]:
            recommendations.append(
                {
                    "segment_id": segment_id,
                    "action": "replace_source_media",
                    "reason": "repeated_visual_asset",
                    "priority": "medium",
                }
            )
        if emotion_curve["flatline_risk"] and emotion_curve["beats"]:
            recommendations.append(
                {
                    "segment_id": int(emotion_curve["beats"][-1]["segment_id"]),
                    "action": "recut",
                    "reason": "emotion_curve_flatline",
                    "priority": "medium",
                }
            )
        return self._dedupe_actions(recommendations)

    def _arc(self, values: list[float]) -> str:
        if len(values) < 2:
            return "single_beat"
        if values[-1] > values[0]:
            return "rising"
        if values[-1] < values[0]:
            return "falling"
        return "steady"

    def _dedupe_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen = set()
        for action in actions:
            key = (action.get("segment_id"), action.get("action"), action.get("reason"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(action)
        return deduped

    def _to_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _to_float(self, value: Any, *, default: float) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return super()._load_yaml(path)
