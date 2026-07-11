from __future__ import annotations

from pathlib import Path
from typing import Any

from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import run_ffmpeg, validate_video
from narrascape.utils.safe_io import atomic_write_text


class FilmAssembleStage(Stage):
    """Render the visual track from film_timeline.yaml."""

    name = "film_assemble"
    depends_on = ["remotion_preview"]
    VALID_SOURCES = {"generated_video", "source_media", "generated_image", "ending_card"}

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        timeline_path = context.config.project_dir / "film_timeline.yaml"
        if not timeline_path.exists():
            return False, f"film_timeline.yaml not found: {timeline_path}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        timeline_path = config.project_dir / "film_timeline.yaml"
        timeline = self._load_yaml(timeline_path)
        clips = timeline.get("tracks", {}).get("visual", [])
        if not clips:
            return StageResult(self.name, False, message="No visual clips in film_timeline.yaml")
        invalid_sources = [
            str(clip.get("id", "unknown"))
            for clip in clips
            if str(clip.get("source") or "") not in self.VALID_SOURCES
        ]
        if invalid_sources:
            return StageResult(
                self.name,
                False,
                message=f"Unknown timeline clip source: {invalid_sources}",
            )

        segment_dir = config.pipeline_dir / "timeline_segments"
        segment_dir.mkdir(parents=True, exist_ok=True)
        rendered: list[Path] = []
        failures: list[str] = []

        cursor = 0.0
        gap_index = 1
        for clip in sorted(clips, key=lambda item: float(item.get("start", 0.0))):
            start = float(clip.get("start") or cursor)
            if start > cursor + 0.01:
                gap_out = segment_dir / f"gap_{gap_index:03d}.mp4"
                if self._render_gap(start - cursor, context, gap_out):
                    rendered.append(gap_out)
                    gap_index += 1
                else:
                    failures.append(f"gap_{gap_index:03d}")
                    gap_index += 1

            out = segment_dir / f"{clip['id']}.mp4"
            if self._render_clip(clip, context, out):
                rendered.append(out)
            else:
                failures.append(str(clip.get("id", "unknown")))
            cursor = max(cursor, start + float(clip.get("duration") or 0.0))

        if failures:
            return StageResult(
                self.name,
                False,
                outputs=rendered,
                message=f"Timeline clip render failed: {failures}",
            )

        concat_file = config.pipeline_dir / "film_assemble.txt"
        atomic_write_text(
            concat_file,
            "\n".join(f"file '{path.resolve().as_posix()}'" for path in rendered),
        )
        assembled = config.pipeline_dir / "film_assembled.mp4"
        ok = run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c:v",
                config.encode.codec,
                "-preset",
                config.encode.preset,
                "-crf",
                str(config.encode.crf),
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(assembled),
            ],
            desc="film timeline assemble",
            validate_output=True,
        )
        if ok and assembled.exists():
            return StageResult(
                self.name,
                True,
                outputs=[assembled],
                message=f"{len(rendered)} timeline clip(s) assembled",
                metadata={"clip_count": len(rendered), "timeline": timeline_path.as_posix()},
            )
        return StageResult(
            self.name, False, outputs=rendered, message="film timeline assemble failed"
        )

    def _render_clip(self, clip: dict[str, Any], context: StageContext, out: Path) -> bool:
        config = context.config
        if out.exists() and validate_video(out):
            return True

        source_type = str(clip.get("source") or "")
        if source_type not in self.VALID_SOURCES:
            return False

        if source_type == "ending_card":
            return self._render_ending_card(clip, context, out)

        source = config.project_dir / clip["path"]
        if not source.exists():
            return False

        duration = float(clip.get("duration") or 1.0)
        source_in = float(clip.get("source_in") or 0.0)
        width, height = config.encode.width, config.encode.height
        fps = config.encode.fps
        fit_filter = self._fit_filter(width, height)

        if source_type == "generated_image":
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
                desc=f"film timeline image {clip['id']}",
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
                fit_filter,
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
            desc=f"film timeline video {clip['id']}",
            validate_output=True,
        )

    def _render_ending_card(self, clip: dict[str, Any], context: StageContext, out: Path) -> bool:
        config = context.config
        duration = float(clip.get("duration") or config.ending.duration)
        return self._render_black(duration, context, out, "film timeline ending card")

    def _render_gap(self, duration: float, context: StageContext, out: Path) -> bool:
        return self._render_black(duration, context, out, "film timeline gap")

    def _render_black(self, duration: float, context: StageContext, out: Path, desc: str) -> bool:
        config = context.config
        return run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={config.encode.width}x{config.encode.height}:d={duration:.3f}:r={config.encode.fps}",
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
            desc=desc,
            validate_output=True,
        )

    def _fit_filter(self, width: int, height: int) -> str:
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1"
        )
