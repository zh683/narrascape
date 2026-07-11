from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TypedDict

from narrascape.config import BGMMap, NarrascapeConfig, Script
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import get_duration, run_ffmpeg, run_ffmpeg_raw
from narrascape.utils.safe_io import atomic_copy_file, atomic_write_text

logger = logging.getLogger("narrascape.stages.audio")


class AudioTimelineEntry(TypedDict):
    id: str
    start: float
    end: float
    file: Path


class AudioStage(Stage):
    """Mix narration with multi-zone background music, sidechain compression, and loudnorm."""

    name = "audio"
    depends_on = ["film_assemble", "remix_audio"]
    outputs = ["audio_final.mp3"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        mixed = context.pipeline_dir / "mixed_audio.mp3"
        if not mixed.exists():
            return False, "mixed_audio.mp3 not found. Run remix_audio.py first or generate BGM."
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        final_video = self._visual_input(config)
        mixed_audio = config.pipeline_dir / "mixed_audio.mp3"

        if not mixed_audio.exists():
            return StageResult(self.name, False, message="mixed_audio.mp3 not found")
        if not final_video.exists():
            return StageResult(self.name, False, message="final_nosub.mp4 not found")

        # Check alignment
        video_dur = get_duration(final_video)
        audio_dur = get_duration(mixed_audio)
        need = video_dur + 2
        pad = max(0, need - audio_dur)

        audio_aligned = config.pipeline_dir / "mixed_audio_aligned.mp3"
        if not audio_aligned.exists():
            if pad > 0:
                logger.info(f"Padding audio: {audio_dur:.1f}s -> {need:.1f}s (+{pad:.1f}s)")
                run_ffmpeg(
                    [
                        "-i",
                        str(mixed_audio),
                        "-af",
                        f"apad=pad_dur={pad}",
                        "-c:a",
                        "libmp3lame",
                        "-b:a",
                        "192k",
                        str(audio_aligned),
                    ],
                    desc="audio padding",
                    validate_output=False,
                )
            else:
                atomic_copy_file(mixed_audio, audio_aligned)
                logger.info(f"Audio OK: {audio_dur:.1f}s >= {need:.1f}s")

        # Ending volume envelope (optional, simplified)
        ending_enabled = config.ending.enabled
        audio_file = audio_aligned
        if ending_enabled:
            edur = config.ending.duration
            es = video_dur - edur
            # For now, use the aligned audio as-is. Advanced envelope can be added later.
            logger.info(f"Ending card enabled (duration={edur:.1f}s, start={es:.1f}s)")

        # Mux
        pname = config.project.name
        out = config.output_dir / f"{pname}-clean.mp4"
        config.output_dir.mkdir(parents=True, exist_ok=True)

        ok = run_ffmpeg(
            [
                "-i",
                str(final_video),
                "-i",
                str(audio_file),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-shortest",
                str(out),
            ],
            desc="mux clean",
            validate_output=True,
        )

        if ok and out.exists():
            size_mb = out.stat().st_size / 1024 / 1024
            return StageResult(
                self.name,
                True,
                outputs=[out],
                message=f"{out.name}: {size_mb:.1f} MB",
            )

        return StageResult(self.name, False, message="mux failed")

    def _visual_input(self, config: NarrascapeConfig) -> Path:
        film_assembled = config.pipeline_dir / "film_assembled.mp4"
        if film_assembled.exists():
            return film_assembled
        return config.pipeline_dir / "final_nosub.mp4"


class AudioRemixStage(Stage):
    """
    Full audio remix: TTS concatenation + gap insertion + BGM zone mixing + sidechain + loudnorm.
    This stage depends on generate_tts and generate_music to produce mixed_audio.mp3.
    """

    name = "remix_audio"
    depends_on = ["generate_tts", "generate_music"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        config = context.config
        # Check TTS files exist
        tts_dir = config.tts_dir
        script = context.script
        missing_tts = []
        for seg in script.segments:
            mp3 = tts_dir / f"seg_{seg.id:02d}.mp3"
            if not mp3.exists():
                missing_tts.append(seg.id)
        if missing_tts:
            return False, f"Missing TTS files for segments: {missing_tts}. Run generate_tts first."

        # Check BGM files exist
        music_dir = config.music_dir
        if config.bgm_map and config.bgm_map.zones:
            missing_bgm = []
            for zone in config.bgm_map.zones:
                mp3 = music_dir / f"{zone.id}.mp3"
                if not mp3.exists():
                    missing_bgm.append(zone.id)
            if missing_bgm:
                return False, f"Missing BGM files: {missing_bgm}. Run generate_music first."

        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        script = context.script
        audio_cfg = config.audio
        music_cfg = audio_cfg.music
        bgm_map = config.bgm_map
        gap_map = config.visual.gap_map
        gap_default = config.visual.segment_gap

        tts_dir = config.tts_dir
        music_dir = config.music_dir
        pipeline_dir = config.pipeline_dir

        # ── 1. Build narration with gaps ──
        narration_gapped = pipeline_dir / "narration_gapped.mp3"
        if not narration_gapped.exists():
            self._build_narration_gapped(script, tts_dir, pipeline_dir, gap_map, gap_default)

        narration_dur = get_duration(narration_gapped)
        ending_dur = config.ending.duration if config.ending.enabled else 0
        total_target = narration_dur + ending_dur + music_cfg.fade_out_seconds + 5

        # ── 2. Normalize narration ──
        narration_norm = pipeline_dir / "narration_norm.mp3"
        if not narration_norm.exists():
            run_ffmpeg(
                [
                    "-i",
                    str(narration_gapped),
                    "-af",
                    f"loudnorm=I={music_cfg.narration_lufs}:TP=-1.5:LRA=11",
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "192k",
                    str(narration_norm),
                ],
                desc="normalize narration",
                validate_output=False,
            )

        # ── 3. Build zone timeline ──
        timing_path = pipeline_dir / "timing.json"
        durations = (
            json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else {}
        )
        timeline = self._build_zone_timeline(
            script,
            bgm_map,
            durations,
            gap_map,
            gap_default,
            config.music_dir,
        )

        # Verify BGM files
        missing = []
        for z in timeline:
            if not z["file"].exists():
                missing.append(z["file"].name)
        if missing:
            return StageResult(self.name, False, message=f"Missing BGM: {missing}")

        # ── 4. Build filter chain and mix ──
        mixed = pipeline_dir / "mixed_audio.mp3"
        filter_lines = self._build_filter_chain(
            timeline, narration_dur, total_target, music_cfg, bgm_map
        )
        filter_graph = ";".join(filter_lines)

        args = ["-i", str(narration_norm)]
        for z in timeline:
            args.extend(["-i", str(z["file"])])
        args.extend(
            [
                "-filter_complex",
                filter_graph,
                "-map",
                "[final]",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(mixed),
            ]
        )

        logger.info(f"Mixing {len(timeline)} BGM zones + narration...")
        result = run_ffmpeg_raw(args)
        if result.returncode != 0:
            logger.error(f"Audio mix failed: {result.stderr[:500]}")
            return StageResult(self.name, False, message="ffmpeg filter_complex failed")

        mixed_dur = get_duration(mixed)
        logger.info(f"Mixed audio: {mixed_dur:.1f}s")
        return StageResult(self.name, True, outputs=[mixed], message=f"{mixed_dur:.1f}s")

    def _build_narration_gapped(
        self,
        script: Script,
        tts_dir: Path,
        pipeline_dir: Path,
        gap_map: dict[int, float],
        gap_default: float,
    ) -> None:
        """Concatenate TTS segments with silence gaps."""
        silences: dict[float, Path] = {}
        concat_lines: list[str] = []

        for i, seg in enumerate(script.segments):
            mp3 = tts_dir / f"seg_{seg.id:02d}.mp3"
            if mp3.exists():
                concat_lines.append(f"file '{mp3.as_posix()}'")
            if i >= len(script.segments) - 1:
                continue

            gap_dur = gap_map.get(seg.id, gap_default)
            dur_key = str(gap_dur).replace(".", "_")
            sf = pipeline_dir / f"silence_{dur_key}s.mp3"
            if gap_dur not in silences:
                if not sf.exists():
                    run_ffmpeg(
                        [
                            "-f",
                            "lavfi",
                            "-i",
                            "anullsrc=r=44100:cl=stereo",
                            "-t",
                            str(gap_dur),
                            "-c:a",
                            "libmp3lame",
                            "-b:a",
                            "128k",
                            str(sf),
                        ],
                        desc=f"silence {gap_dur}s",
                        validate_output=False,
                    )
                silences[gap_dur] = sf
            concat_lines.append(f"file '{sf.as_posix()}'")

        concat_file = pipeline_dir / "concat_gapped.txt"
        atomic_write_text(concat_file, "\n".join(concat_lines))

        # Use aconcat filter for gapless concatenation
        inputs = []
        for line in concat_lines:
            path = line.split("'")[1]
            inputs.extend(["-i", path])

        n = len(concat_lines)
        normalizes = ";".join(
            f"[{i}:a]aformat=sample_rates=44100:channel_layouts=mono,asetpts=PTS-STARTPTS[c{i}]"
            for i in range(n)
        )
        concat_filter = "".join(f"[c{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[narrated]"
        filter_graph = normalizes + ";" + concat_filter

        run_ffmpeg(
            inputs
            + [
                "-filter_complex",
                filter_graph,
                "-map",
                "[narrated]",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(pipeline_dir / "narration_gapped.mp3"),
            ],
            desc="concat narration",
            validate_output=False,
        )

    def _build_zone_timeline(
        self,
        script: Script,
        bgm_map: BGMMap,
        durations: dict[str, Any],
        gap_map: dict[int, float],
        gap_default: float,
        music_dir: Path,
    ) -> list[AudioTimelineEntry]:
        """Calculate time boundaries for each BGM zone."""
        timeline: list[AudioTimelineEntry] = []
        for zone in bgm_map.zones:
            start_id, end_id = zone.covers[0], (
                zone.covers[-1] if len(zone.covers) > 1 else zone.covers[0]
            )
            zone_start = timeline[-1]["end"] if timeline else 0.0
            zone_t = zone_start

            for seg in script.segments:
                sid = seg.id
                if sid < start_id or sid > end_id:
                    continue
                zone_t += durations.get(str(sid), 0)
                if sid < end_id:
                    zone_t += gap_map.get(sid, gap_default)

            timeline.append(
                {
                    "id": zone.id,
                    "start": zone_start,
                    "end": zone_t,
                    "file": music_dir / f"{zone.id}.mp3",
                }
            )
        return timeline

    def _build_filter_chain(
        self,
        timeline: list[AudioTimelineEntry],
        narration_dur: float,
        total_target: float,
        music_cfg: Any,
        bgm_map: BGMMap,
    ) -> list[str]:
        """Build ffmpeg -filter_complex for multi-zone BGM + sidechain."""
        n_zones = len(timeline)
        lines: list[str] = []
        xfade = bgm_map.zone_crossfade

        # Handle no BGM zones: just process narration
        if n_zones == 0:
            lines.append(
                f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,apad=whole_dur={total_target:.3f},atrim=0:{total_target:.3f}[narr]"
            )
            lines.append(f"[narr]loudnorm=I={music_cfg.target_lufs}:TP=-1.0:LRA=7[final]")
            return lines

        input_idx = 1

        # Step A: atrim each zone BGM
        for i, entry in enumerate(timeline):
            is_last = i == n_zones - 1
            if is_last:
                zone_dur = (total_target - entry["start"]) + xfade + music_cfg.fade_out_seconds
            else:
                zone_dur = (entry["end"] - entry["start"]) + xfade
            lines.append(
                f"[{input_idx}:a]aloop=loop=-1:size=2e9,atrim=0:{zone_dur:.3f},asetpts=PTS-STARTPTS[z{i}]"
            )
            input_idx += 1

        # Step B: chain acrossfade
        if n_zones == 1:
            last_bgm = "z0"
        else:
            lines.append(f"[z0][z1]acrossfade=d={xfade}:c1=tri:c2=tri[bgm01]")
            for i in range(2, n_zones):
                lines.append(f"[bgm0{i-1}][z{i}]acrossfade=d={xfade}:c1=tri:c2=tri[bgm0{i}]")
            last_bgm = f"bgm0{n_zones-1}"

        # Step C: fade out
        fade_start = total_target - music_cfg.fade_out_seconds
        lines.append(
            f"[{last_bgm}]afade=t=out:st={fade_start:.3f}:d={music_cfg.fade_out_seconds}[bgm_final]"
        )

        # Step D: Narration
        lines.append(
            f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,apad=whole_dur={total_target:.3f}[narr]"
        )

        # Step E: Sidechain
        lines.append(
            f"[bgm_final][narr]sidechaincompress="
            f"threshold={music_cfg.sidechain_threshold}:"
            f"ratio={music_cfg.sidechain_ratio}:"
            f"attack={music_cfg.sidechain_attack}:"
            f"release={music_cfg.sidechain_release}[bgm_ducked]"
        )

        # Step F: Mix
        lines.append(
            f"[bgm_ducked]volume={music_cfg.volume},volume={music_cfg.music_boost_db}dB[bgm_vol]"
        )
        lines.append("[narr][bgm_vol]amix=inputs=2:duration=longest:normalize=0[mixed]")

        # Step G: Loudnorm
        lines.append(f"[mixed]loudnorm=I={music_cfg.target_lufs}:TP=-1.0:LRA=7[final]")

        return lines
