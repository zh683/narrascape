from __future__ import annotations

import logging
from pathlib import Path

from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import get_system_font, run_ffmpeg, validate_video

logger = logging.getLogger("narrascape.stages.concat")


class ConcatStage(Stage):
    """Concatenate Ken Burns segments with inter-segment gaps and ending card."""

    name = "concat"
    depends_on = ["kenburns"]
    outputs = ["concat.mp4"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        seg_dir = context.pipeline_dir / "video_segments"
        if not seg_dir.exists():
            return False, "video_segments directory not found"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        script = context.script
        seg_dir = config.pipeline_dir / "video_segments"
        gap_dir = config.pipeline_dir / "gaps"
        gap_dir.mkdir(exist_ok=True)

        # Build gap videos
        for i in range(len(script.segments) - 1):
            seg_id = script.segments[i].id
            gap_dur = config.visual.gap_map.get(seg_id, config.visual.segment_gap)
            dur_key = str(gap_dur).replace('.', '_')
            gv = gap_dir / f"gap_{i:02d}_{dur_key}s.mp4"
            if not gv.exists() or not validate_video(gv):
                if gv.exists():
                    gv.unlink()
                run_ffmpeg(
                    [
                        "-f", "lavfi",
                        "-i", f"color=c=black:s={config.encode.width}x{config.encode.height}:d={gap_dur}:r={config.encode.fps}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                        "-pix_fmt", "yuv420p",
                        str(gv),
                    ],
                    desc=f"gap {i} ({gap_dur}s)",
                    validate_output=True,
                )

        # Build concat list
        lines = []
        missing = []
        for i, seg in enumerate(script.segments):
            sv = seg_dir / f"seg_{seg.id:02d}.mp4"
            if sv.exists() and validate_video(sv):
                lines.append(f"file '{sv.as_posix()}'")
            else:
                missing.append(seg.id)
            if i < len(script.segments) - 1:
                seg_id = script.segments[i].id
                gap_dur = config.visual.gap_map.get(seg_id, config.visual.segment_gap)
                dur_key = str(gap_dur).replace('.', '_')
                gv = gap_dir / f"gap_{i:02d}_{dur_key}s.mp4"
                if gv.exists() and validate_video(gv):
                    lines.append(f"file '{gv.as_posix()}'")

        concat_file = config.pipeline_dir / "concat_body.txt"
        concat_file.write_text("\n".join(lines), encoding="utf-8")

        body_video = config.pipeline_dir / "body_concat.mp4"
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(body_video)],
            desc="concat body",
            validate_output=True,
        )

        # Ending card (if enabled)
        ending = config.ending
        final_video = config.pipeline_dir / "final_nosub.mp4"

        if ending.enabled:
            ending_card = config.pipeline_dir / "ending_card.mp4"
            if not ending_card.exists() or not validate_video(ending_card):
                if ending_card.exists():
                    ending_card.unlink()
                self._build_ending_card(ending, config, ending_card)

            if ending_card.exists() and validate_video(ending_card):
                fc = config.pipeline_dir / "concat_with_ending.txt"
                fc_lines = [f"file '{body_video.as_posix()}'", f"file '{ending_card.as_posix()}'"]
                fc.write_text("\n".join(fc_lines), encoding="utf-8")
                run_ffmpeg(
                    ["-f", "concat", "-safe", "0", "-i", str(fc), "-c", "copy", str(final_video)],
                    desc="concat with ending",
                    validate_output=True,
                )
            else:
                # Fallback: just body
                import shutil
                shutil.copy(str(body_video), str(final_video))
        else:
            import shutil
            shutil.copy(str(body_video), str(final_video))

        if validate_video(final_video):
            from narrascape.utils.ffmpeg import get_duration
            dur = get_duration(final_video)
            return StageResult(
                self.name,
                True,
                outputs=[final_video],
                message=f"final_nosub.mp4: {dur:.1f}s",
            )

        return StageResult(self.name, False, message="final_nosub.mp4 validation failed")

    def _build_ending_card(self, ending, config, output_path: Path) -> bool:
        """Build a simple ending card with text overlays."""
        EDUR = ending.duration
        yp = 320
        lines = ending.lines
        drawtexts = []
        font_path = get_system_font()
        for i, line in enumerate(lines):
            alpha_expr = f"if(lt(t,{0.5+i}),0,if(lt(t,{1.5+i}),(t-{0.5+i}),1))"
            drawtexts.append(
                f"drawtext=text='{line.text}':fontsize={line.size}:fontcolor=#D4AF37:"
                f"x=(w-text_w)/2:y={yp + i*60}:fontfile={font_path}:"
                f"alpha='{alpha_expr}'"
            )

        if ending.quote:
            quote_alpha = (
                f"if(lt(t,3),0,if(lt(t,6),(t-3)/3,if(gt(t,12),1-(t-12)/3,1)))"
            )
            drawtexts.append(
                f"drawtext=text='{ending.quote}':fontsize={ending.quote_size}:fontcolor=#F0E8D8:"
                f"x=(w-text_w)/2:y={yp + len(lines)*60 + 20}:fontfile={font_path}:"
                f"alpha='{quote_alpha}'"
            )

        drawtexts.extend([f"fade=t=in:st=0:d=1", f"fade=t=out:st={max(0, EDUR-2)}:d=2"])
        vf = ",".join(drawtexts)
        return run_ffmpeg(
            [
                "-f", "lavfi",
                "-i", f"color=c=black:s={config.encode.width}x{config.encode.height}:d={EDUR}:r={config.encode.fps}",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ],
            desc="ending card",
            validate_output=True,
        )
