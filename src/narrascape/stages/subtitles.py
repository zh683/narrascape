from __future__ import annotations

import logging

from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import get_system_font_name, run_ffmpeg

logger = logging.getLogger("narrascape.stages.subtitles")


class SubtitleStage(Stage):
    """Generate SRT subtitles and burn them into the final video."""

    name = "subtitles"
    depends_on = ["audio"]
    outputs = ["final_subtitled.mp4"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        clean = context.config.output_dir / f"{context.config.project.name}-clean.mp4"
        if not clean.exists():
            return False, "clean.mp4 not found"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        script = context.script
        sub_cfg = config.subtitles

        # Build SRT
        srt_path = config.pipeline_dir / "subtitles.srt"
        timing_path = config.pipeline_dir / "timing.json"

        import json

        durations = (
            json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else {}
        )

        srt_entries = self._build_srt(
            script, durations, sub_cfg, config.visual.gap_map, config.visual.segment_gap
        )
        srt_path.write_text(srt_entries, encoding="utf-8")
        logger.info(f"SRT: {srt_entries.count(chr(10)+chr(10))} entries")

        # Burn subtitles
        clean = config.output_dir / f"{config.project.name}-clean.mp4"
        sub_out = config.output_dir / f"{config.project.name}-sub.mp4"

        # Use platform-aware font name for subtitles
        font_name = sub_cfg.font
        if font_name == "Microsoft YaHei":
            font_name = get_system_font_name()

        srt_ff = str(srt_path).replace("\\", "/").replace(":", "\\:")
        vf = (
            f"subtitles='{srt_ff}':"
            f"force_style='FontName={font_name},FontSize={sub_cfg.font_size},"
            f"PrimaryColour={sub_cfg.primary_color},OutlineColour={sub_cfg.outline_color},"
            f"Outline={sub_cfg.outline},Shadow={sub_cfg.shadow},"
            f"MarginV={sub_cfg.margin_v},Alignment={sub_cfg.alignment}'"
        )

        ok = run_ffmpeg(
            [
                "-i",
                str(clean),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                str(sub_out),
            ],
            desc="burn subtitles",
            validate_output=True,
        )

        if ok and sub_out.exists():
            size_mb = sub_out.stat().st_size / 1024 / 1024
            return StageResult(
                self.name,
                True,
                outputs=[sub_out],
                message=f"{sub_out.name}: {size_mb:.1f} MB",
            )

        return StageResult(self.name, False, message="subtitle burn failed")

    def _build_srt(self, script, durations, sub_cfg, gap_map, gap_default) -> str:
        """Build SRT content from script segments and durations."""
        max_chars = sub_cfg.max_chars_per_line
        entries = []
        idx = 1
        cumulative = 0.0

        for seg in script.segments:
            sid = seg.id
            dur = durations.get(str(sid), 30.0)
            text = seg.text.replace("\n", " ").strip()
            t0, t1 = cumulative, cumulative + dur

            chunks = self._split_text(text, max_chars)
            total_chars = sum(len(c) for c in chunks)
            if total_chars == 0:
                cumulative += dur + gap_map.get(sid, gap_default)
                continue

            elapsed = t0
            for chunk in chunks:
                cd = max(0.5, (t1 - t0) * len(chunk) / total_chars)
                entries.append(
                    f"{idx}\n" f"{self._ts(elapsed)} --> {self._ts(elapsed + cd)}\n" f"{chunk}\n"
                )
                idx += 1
                elapsed += cd

            cumulative += dur + gap_map.get(sid, gap_default)

        return "\n".join(entries)

    def _split_text(self, text: str, max_chars: int) -> list[str]:
        """Split text into chunks respecting punctuation boundaries."""
        chars = list(text)
        i = 0
        chunks = []
        punctuation = "，。！？；：、"

        while i < len(chars):
            end = min(i + max_chars, len(chars))
            if end < len(chars) and chars[end - 1] not in punctuation:
                for j in range(end - 1, i, -1):
                    if chars[j] in punctuation:
                        end = j + 1
                        break
            strip_chars = (
                punctuation
                + chr(34)
                + chr(39)
                + chr(8220)
                + chr(8221)
                + chr(40)
                + chr(41)
                + chr(12298)
                + chr(12299)
                + " 	"
            )
            chunk = "".join(chars[i:end]).strip(strip_chars)
            if chunk:
                chunks.append(chunk)
            i = end

        return chunks

    def _ts(self, seconds: float) -> str:
        """Format seconds as SRT timestamp."""
        h, rem = divmod(seconds, 3600)
        m, rs = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(rs):02d},{int((rs - int(rs)) * 1000):03d}"
