from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import run_ffmpeg, validate_video


class FootageEditStage(Stage):
    """Render a rough cut from source-media edit decisions."""

    name = "footage_edit"
    depends_on = ["source_media"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        timeline_path = context.config.project_dir / "footage_timeline.yaml"
        if not timeline_path.exists():
            return False, f"footage_timeline.yaml not found: {timeline_path}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        timeline_path = config.project_dir / "footage_timeline.yaml"
        timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8")) or {}
        edits = timeline.get("edits", [])
        if not edits:
            return StageResult(
                self.name, False, message="No footage edits in footage_timeline.yaml"
            )

        segment_dir = config.pipeline_dir / "source_media_segments"
        segment_dir.mkdir(parents=True, exist_ok=True)
        rendered: list[Path] = []
        failures: list[str] = []

        for edit in edits:
            out = segment_dir / f"{edit['id']}.mp4"
            ok = self._render_edit(edit, context, out)
            if ok:
                rendered.append(out)
            else:
                failures.append(edit.get("id", "unknown"))

        if failures:
            return StageResult(
                self.name,
                False,
                outputs=rendered,
                message=f"Footage edits failed: {failures}",
            )

        concat_file = config.pipeline_dir / "footage_roughcut.txt"
        concat_file.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in rendered),
            encoding="utf-8",
        )
        roughcut = config.pipeline_dir / "footage_roughcut.mp4"
        ok = run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                str(roughcut),
            ],
            desc="source media roughcut",
            validate_output=True,
        )
        if ok and roughcut.exists():
            return StageResult(
                self.name,
                True,
                outputs=[roughcut],
                message=f"{len(rendered)} footage edit(s) rendered",
                metadata={"edit_count": len(rendered), "timeline": timeline_path.as_posix()},
            )
        return StageResult(
            self.name, False, outputs=rendered, message="footage roughcut render failed"
        )

    def _render_edit(self, edit: dict[str, Any], context: StageContext, out: Path) -> bool:
        config = context.config
        source = config.project_dir / edit["source_path"]
        if not source.exists():
            return False
        duration = float(edit.get("duration") or 1.0)
        source_in = float(edit.get("source_in") or 0.0)
        source_type = edit.get("source_type", "video")
        width, height = config.encode.width, config.encode.height
        fps = config.encode.fps

        if out.exists() and validate_video(out):
            return True

        if source_type == "image":
            return run_ffmpeg(
                [
                    "-loop",
                    "1",
                    "-t",
                    f"{duration:.3f}",
                    "-i",
                    str(source),
                    "-vf",
                    self._fit_filter(width, height),
                    "-r",
                    str(fps),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    str(out),
                ],
                desc=f"source media edit {edit['id']}",
                validate_output=True,
            )

        return run_ffmpeg(
            [
                "-ss",
                f"{source_in:.3f}",
                "-t",
                f"{duration:.3f}",
                "-i",
                str(source),
                "-vf",
                self._fit_filter(width, height),
                "-an",
                "-r",
                str(fps),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(out),
            ],
            desc=f"source media edit {edit['id']}",
            validate_output=True,
        )

    def _fit_filter(self, width: int, height: int) -> str:
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1"
        )
