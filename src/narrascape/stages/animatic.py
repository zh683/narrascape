from __future__ import annotations

from pathlib import Path
from typing import Any

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import run_ffmpeg, validate_video
from narrascape.utils.safe_io import (
    atomic_write_text,
    atomic_write_yaml,
    load_json_mapping,
    load_yaml_mapping,
)


class AnimaticStage(Stage):
    """Render a low-cost storyboard timing preview before video generation."""

    name = "animatic"
    depends_on = ["reference_plate", "generate_images"]
    outputs = ["pipeline/{name}/animatic.yaml", "pipeline/{name}/animatic.mp4"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        plate_path = context.config.pipeline_dir / "reference_plates.yaml"
        if not plate_path.exists():
            return False, f"reference_plates.yaml not found: {plate_path}"
        if not context.config.images_dir.exists():
            return False, f"Images directory not found: {context.config.images_dir}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        reference_plates = load_yaml_mapping(config.pipeline_dir / "reference_plates.yaml")
        pre_production = load_yaml_mapping(config.pipeline_dir / "pre_production.yaml")
        timing = load_json_mapping(config.pipeline_dir / "timing.json")

        plates_by_segment = self._plates_by_segment(reference_plates)
        frames_by_segment = self._storyboard_by_segment(pre_production)
        panels, findings = self._build_panels(context, frames_by_segment, plates_by_segment, timing)
        status = "blocked" if findings else "ready"
        report = {
            "schema_version": "animatic.v1",
            "status": status,
            "panel_count": len(panels),
            "panels": panels,
            "findings": findings,
        }

        out_yaml = config.pipeline_dir / "animatic.yaml"
        validate_artifact("animatic", report)
        atomic_write_yaml(out_yaml, report)
        if status != "ready":
            return StageResult(
                self.name,
                False,
                outputs=[out_yaml],
                message=f"animatic blocked: {len(findings)} finding(s)",
                metadata={"status": status, "panel_count": len(panels)},
            )

        ok = self._render_animatic(context, panels)
        outputs: list[Path] = [out_yaml]
        out_video = config.pipeline_dir / "animatic.mp4"
        if ok and out_video.exists():
            outputs.append(out_video)
            return StageResult(
                self.name,
                True,
                outputs=outputs,
                message=f"{len(panels)} animatic panel(s)",
                metadata={"status": status, "panel_count": len(panels)},
            )
        return StageResult(
            self.name,
            False,
            outputs=outputs,
            message="animatic render failed",
            metadata={"status": "render_failed", "panel_count": len(panels)},
        )

    def _build_panels(
        self,
        context: StageContext,
        frames_by_segment: dict[int, list[dict[str, Any]]],
        plates_by_segment: dict[int, dict[str, Any]],
        timing: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        panels: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        for segment in context.script.segments:
            segment_id = int(segment.id)
            frames = frames_by_segment.get(segment_id) or [
                {
                    "frame_id": f"sb_{segment_id:02d}_01",
                    "description": segment.text,
                    "duration_hint": float(timing.get(str(segment_id), 0.0)) or 3.0,
                }
            ]
            image_path = context.config.images_dir / f"img_{segment_id:02d}.png"
            plate = plates_by_segment.get(segment_id, {})
            for frame in frames:
                duration = float(frame.get("duration_hint") or 0.0)
                if duration <= 0:
                    duration = max(1.0, float(timing.get(str(segment_id), 0.0)) / len(frames))
                panel = {
                    "segment_id": segment_id,
                    "storyboard_frame_id": str(frame.get("frame_id") or ""),
                    "description": str(frame.get("description") or segment.text),
                    "duration": round(duration, 3),
                    "source_image": image_path.relative_to(context.config.project_dir).as_posix(),
                    "reference_plate_id": str(plate.get("shot_id") or ""),
                    "character_positions": list(frame.get("character_positions") or []),
                    "scene_ref": str(frame.get("scene_ref") or plate.get("scene_ref") or ""),
                    "composition_requirements": list(plate.get("composition_requirements") or []),
                }
                panels.append(panel)
                if not image_path.exists():
                    findings.append(
                        {
                            "segment_id": segment_id,
                            "storyboard_frame_id": panel["storyboard_frame_id"],
                            "risk_type": "animatic_source_missing",
                            "severity": "high",
                            "evidence": f"animatic source image not found: {panel['source_image']}",
                        }
                    )
        return panels, findings

    def _render_animatic(self, context: StageContext, panels: list[dict[str, Any]]) -> bool:
        config = context.config
        panel_dir = config.pipeline_dir / "animatic_panels"
        panel_dir.mkdir(parents=True, exist_ok=True)
        rendered: list[Path] = []
        for index, panel in enumerate(panels, start=1):
            out = panel_dir / f"panel_{index:03d}.mp4"
            if not out.exists() or not validate_video(out):
                source = config.project_dir / panel["source_image"]
                if not self._render_panel(source, float(panel["duration"]), context, out):
                    return False
            rendered.append(out)

        concat_file = config.pipeline_dir / "animatic.txt"
        atomic_write_text(
            concat_file,
            "\n".join(f"file '{path.resolve().as_posix()}'" for path in rendered),
        )
        out_video = config.pipeline_dir / "animatic.mp4"
        return run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                str(out_video),
            ],
            desc="animatic assemble",
            validate_output=True,
        )

    def _render_panel(
        self,
        source: Path,
        duration: float,
        context: StageContext,
        out: Path,
    ) -> bool:
        config = context.config
        fit_filter = (
            f"scale={config.encode.width}:{config.encode.height}:force_original_aspect_ratio=decrease,"
            f"pad={config.encode.width}:{config.encode.height}:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1"
        )
        return run_ffmpeg(
            [
                "-loop",
                "1",
                "-t",
                f"{duration:.3f}",
                "-i",
                str(source),
                "-vf",
                fit_filter,
                "-r",
                str(config.encode.fps),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                str(out),
            ],
            desc=f"animatic panel {out.stem}",
            validate_output=True,
        )

    def _storyboard_by_segment(
        self,
        pre_production: dict[str, Any],
    ) -> dict[int, list[dict[str, Any]]]:
        result: dict[int, list[dict[str, Any]]] = {}
        for frame in pre_production.get("storyboard", {}).get("frames", []) or []:
            try:
                segment_id = int(frame.get("segment_id"))
            except (TypeError, ValueError):
                continue
            result.setdefault(segment_id, []).append(frame)
        for frames in result.values():
            frames.sort(key=lambda item: int(item.get("frame_index") or 0))
        return result

    def _plates_by_segment(self, reference_plates: dict[str, Any]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for plate in reference_plates.get("plates", []) or []:
            try:
                result[int(plate.get("segment_id"))] = plate
            except (TypeError, ValueError):
                continue
        return result
