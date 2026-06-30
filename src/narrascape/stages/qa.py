from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import get_media_info, run_ffmpeg_raw, validate_video
from narrascape.utils.safe_io import atomic_write_yaml, load_yaml_mapping


class QAStage(Stage):
    """Validate final render deliverables and write a render report."""

    name = "qa"
    depends_on = ["subtitles"]
    continue_on_failure = True

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        final = self._final_video(context)
        if not final.exists():
            return False, f"Final subtitled video not found: {final}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        final = self._final_video(context)
        report_path = context.config.pipeline_dir / "render_report.yaml"
        context.config.pipeline_dir.mkdir(parents=True, exist_ok=True)

        checks: dict[str, Any] = {
            "file_exists": final.exists(),
            "non_empty": final.exists() and final.stat().st_size > 0,
            "ffprobe_valid": False,
            "has_video_stream": False,
            "has_audio_stream": False,
            "duration_seconds": 0.0,
            "resolution": None,
            "subtitle_output_present": self._subtitle_output_present(context),
            "subtitle_source_present": self._subtitle_source_present(context),
            "expected_duration_seconds": self._expected_duration(context),
            "duration_within_tolerance": None,
            "audio_not_silent": None,
            "audio_analysis": {},
            "black_frame_risk": None,
            "black_frame_analysis": {},
            "repeated_shot_risk": self._detect_repeated_shots(context),
            "placeholder_residue": self._detect_placeholder_residue(context),
        }
        checks.update(self._film_timeline_checks(context))
        errors: list[str] = []
        warnings: list[str] = []

        if not checks["file_exists"]:
            errors.append("output file missing")
        elif not checks["non_empty"]:
            errors.append("output file is empty")
        else:
            checks["ffprobe_valid"] = validate_video(final)
            if not checks["ffprobe_valid"]:
                errors.append("ffprobe validation failed")
            else:
                info = get_media_info(final)
                self._populate_stream_checks(info, checks)
                if not checks["has_video_stream"]:
                    errors.append("no video stream")
                if not checks["has_audio_stream"]:
                    errors.append("no audio stream")
                self._populate_deep_quality_checks(final, checks, errors, warnings, context)

        if not checks["subtitle_output_present"]:
            errors.append("subtitled output missing")
        if not checks["subtitle_source_present"]:
            errors.append("subtitle source missing")
        if checks["repeated_shot_risk"]:
            warnings.append("repeated source shots detected")
        if checks["placeholder_residue"]:
            warnings.append("local placeholder imagery remains in render inputs")
        if checks.get("shot_coverage_ratio") is not None and checks["shot_coverage_ratio"] < 1.0:
            errors.append("shot coverage incomplete")
        if checks.get("missing_generated_video_segments"):
            warnings.append("generated video coverage incomplete")
        if checks.get("missing_video_clips"):
            errors.append("timeline video clips missing")
        if checks.get("continuity_risk"):
            warnings.append("character or location continuity risk")
        if checks.get("pacing_risk"):
            warnings.append("narrative pacing risk")

        report = {
            "output": final.as_posix(),
            "checks": checks,
            "errors": errors,
            "warnings": warnings,
        }
        validate_artifact("render_report", report)
        atomic_write_yaml(report_path, report)

        return StageResult(
            self.name,
            not errors,
            outputs=[report_path],
            message="render QA passed" if not errors else "; ".join(errors),
            metadata={"errors": errors, "warnings": warnings, "report": report},
        )

    def _final_video(self, context: StageContext) -> Path:
        return context.config.output_dir / f"{context.config.project.name}-sub.mp4"

    def _populate_stream_checks(self, info: dict[str, Any], checks: dict[str, Any]) -> None:
        try:
            checks["duration_seconds"] = float(info.get("format", {}).get("duration", 0.0))
        except (TypeError, ValueError):
            checks["duration_seconds"] = 0.0

        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                checks["has_video_stream"] = True
                if stream.get("width") and stream.get("height"):
                    checks["resolution"] = [int(stream["width"]), int(stream["height"])]
            if stream.get("codec_type") == "audio":
                checks["has_audio_stream"] = True

    def _populate_deep_quality_checks(
        self,
        final: Path,
        checks: dict[str, Any],
        errors: list[str],
        warnings: list[str],
        context: StageContext,
    ) -> None:
        expected = checks.get("expected_duration_seconds")
        actual = float(checks.get("duration_seconds") or 0.0)
        if expected:
            tolerance = max(2.0, expected * 0.15)
            checks["duration_within_tolerance"] = abs(actual - expected) <= tolerance
            checks["duration_delta_seconds"] = round(actual - expected, 3)
            if not checks["duration_within_tolerance"]:
                errors.append(f"duration mismatch: expected {expected:.1f}s, got {actual:.1f}s")

        audio = self._detect_silence(final)
        checks["audio_analysis"] = audio
        if "ok" in audio:
            checks["audio_not_silent"] = bool(audio["ok"])
            if not checks["audio_not_silent"]:
                errors.append("audio appears silent")

        checks["intentional_black_seconds"] = self._expected_intentional_black_seconds(context)
        self._black_frame_allowed_seconds = self._black_frame_allowance(
            actual,
            checks["intentional_black_seconds"],
        )
        black = self._detect_black_frames(final, actual)
        checks["black_frame_analysis"] = black
        if "risk" in black:
            checks["black_frame_risk"] = bool(black["risk"])
            if checks["black_frame_risk"]:
                errors.append("black frame risk detected")
        elif black.get("status") == "unavailable":
            warnings.append("black frame analysis unavailable")

    def _subtitle_output_present(self, context: StageContext) -> bool:
        return self._final_video(context).exists()

    def _subtitle_source_present(self, context: StageContext) -> bool:
        return (context.config.pipeline_dir / "subtitles.srt").exists()

    def _expected_duration(self, context: StageContext) -> float | None:
        timing_path = context.config.pipeline_dir / "timing.json"
        if not timing_path.exists():
            return None
        try:
            durations = json.loads(timing_path.read_text(encoding="utf-8"))
            total = sum(float(value) for value in durations.values())
            segments = list(context.script.segments)
            for seg in segments[:-1]:
                total += context.config.visual.gap_map.get(
                    seg.id, context.config.visual.segment_gap
                )
            if context.config.ending.enabled:
                total += context.config.ending.duration
            return round(total, 3)
        except Exception:
            return None

    def _expected_intentional_black_seconds(self, context: StageContext) -> float:
        segments = list(context.script.segments)
        total = 0.0
        for seg in segments[:-1]:
            total += context.config.visual.gap_map.get(seg.id, context.config.visual.segment_gap)
        if context.config.ending.enabled:
            total += context.config.ending.duration
        return round(total, 3)

    def _black_frame_allowance(self, duration: float, intentional_black_seconds: float) -> float:
        incidental = min(2.0, max(duration * 0.05, 0.5)) if duration else 0.5
        return round(intentional_black_seconds + incidental, 3)

    def _detect_silence(self, final: Path) -> dict[str, Any]:
        try:
            result = run_ffmpeg_raw(
                [
                    "-hide_banner",
                    "-nostats",
                    "-i",
                    str(final),
                    "-af",
                    "volumedetect",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=60,
                loglevel="info",
            )
            output = f"{result.stdout}\n{result.stderr}"
            mean_volume = self._parse_volume(output, "mean_volume")
            max_volume = self._parse_volume(output, "max_volume")
            if mean_volume is None and max_volume is None:
                return {"status": "unavailable", "reason": "volumedetect produced no volume"}
            loudest = max_volume if max_volume is not None else mean_volume
            return {
                "ok": loudest is not None and loudest > -55.0,
                "mean_volume_db": mean_volume,
                "max_volume_db": max_volume,
            }
        except Exception as exc:
            return {"status": "unavailable", "reason": str(exc)}

    def _detect_black_frames(self, final: Path, duration: float) -> dict[str, Any]:
        try:
            result = run_ffmpeg_raw(
                [
                    "-hide_banner",
                    "-nostats",
                    "-i",
                    str(final),
                    "-vf",
                    "blackdetect=d=0.5:pix_th=0.10",
                    "-an",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=60,
                loglevel="info",
            )
            output = f"{result.stdout}\n{result.stderr}"
            black_seconds = self._sum_blackdetect_seconds(output)
            allowed = getattr(
                self,
                "_black_frame_allowed_seconds",
                min(1.5, max(duration * 0.1, 0.5)) if duration else 0.5,
            )
            return {
                "risk": black_seconds > allowed,
                "black_seconds": round(black_seconds, 3),
                "allowed_seconds": round(allowed, 3),
            }
        except Exception as exc:
            return {"status": "unavailable", "reason": str(exc)}

    def _detect_repeated_shots(self, context: StageContext) -> bool:
        media_files = sorted(
            list(context.config.images_dir.glob("*.png"))
            + list((context.config.pipeline_dir / "video_segments").glob("*.mp4"))
            + list((context.config.pipeline_dir / "timeline_segments").glob("*.mp4"))
        )
        hashes: dict[str, Path] = {}
        perceptual_hashes: dict[str, Path] = {}
        for path in media_files:
            try:
                digest = self._file_sha256(path)
            except Exception:
                continue
            if digest in hashes:
                return True
            hashes[digest] = path
            perceptual = self._media_average_hash(path)
            if perceptual:
                if perceptual in perceptual_hashes:
                    return True
                perceptual_hashes[perceptual] = path
        return False

    def _file_sha256(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _media_average_hash(self, path: Path) -> str | None:
        image_path = path
        temp_frame: Path | None = None
        if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
            temp_frame = path.with_suffix(".qa-frame.jpg")
            try:
                result = run_ffmpeg_raw(
                    [
                        "-hide_banner",
                        "-nostats",
                        "-y",
                        "-i",
                        str(path),
                        "-frames:v",
                        "1",
                        str(temp_frame),
                    ],
                    timeout=30,
                    loglevel="error",
                )
                if result.returncode != 0 or not temp_frame.exists():
                    return None
                image_path = temp_frame
            except Exception:
                return None
        try:
            with Image.open(image_path) as image:
                gray = image.convert("L").resize((8, 8))
                if hasattr(gray, "get_flattened_data"):
                    pixels = list(gray.get_flattened_data())
                else:
                    pixels = list(gray.getdata())
                mean = ImageStat.Stat(gray).mean[0]
                return "".join("1" if value >= mean else "0" for value in pixels)
        except Exception:
            return None
        finally:
            if temp_frame and temp_frame.exists():
                try:
                    temp_frame.unlink()
                except Exception:
                    pass

    def _detect_placeholder_residue(self, context: StageContext) -> bool:
        state_path = context.config.pipeline_dir / "image_gen_state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                selection = state.get("provider_selection", {})
                if selection.get("name") == "local_image":
                    return True
            except Exception:
                pass
        return False

    def _film_timeline_checks(self, context: StageContext) -> dict[str, Any]:
        timeline_path = context.config.project_dir / "film_timeline.yaml"
        if not timeline_path.exists():
            return {
                "shot_coverage_ratio": None,
                "missing_visual_segments": [],
                "missing_generated_video_segments": [],
                "missing_video_clips": [],
                "continuity_risk": False,
                "continuity_risk_segments": [],
                "pacing_risk": False,
                "pacing_risk_segments": [],
            }
        try:
            timeline = load_yaml_mapping(timeline_path)
        except Exception:
            return {
                "shot_coverage_ratio": None,
                "missing_visual_segments": [],
                "missing_generated_video_segments": [],
                "missing_video_clips": [],
                "continuity_risk": False,
                "continuity_risk_segments": [],
                "pacing_risk": False,
                "pacing_risk_segments": [],
            }

        segment_ids = [int(seg.id) for seg in context.script.segments]
        visual_clips = timeline.get("tracks", {}).get("visual", [])
        covered_segments = {
            int(clip.get("segment_id"))
            for clip in visual_clips
            if clip.get("segment_id") is not None
        }
        missing_visual = sorted(set(segment_ids) - covered_segments)
        generated_video_segments = set(
            timeline.get("coverage", {}).get("generated_video_segments", [])
        )
        missing_generated_video = sorted(set(segment_ids) - generated_video_segments)
        missing_video_clips = self._missing_video_clip_segments(context, visual_clips)
        continuity_segments = self._continuity_risk_segments(visual_clips)
        pacing_segments = self._pacing_risk_segments(visual_clips)

        return {
            "shot_coverage_ratio": len(covered_segments) / max(len(segment_ids), 1),
            "missing_visual_segments": missing_visual,
            "missing_generated_video_segments": missing_generated_video,
            "missing_video_clips": missing_video_clips,
            "continuity_risk": bool(continuity_segments),
            "continuity_risk_segments": continuity_segments,
            "pacing_risk": bool(pacing_segments),
            "pacing_risk_segments": pacing_segments,
        }

    def _missing_video_clip_segments(
        self, context: StageContext, clips: list[dict[str, Any]]
    ) -> list[int]:
        missing: list[int] = []
        for clip in clips:
            if clip.get("source") not in ("generated_video", "source_media"):
                continue
            segment_id = self._to_int(clip.get("segment_id"))
            if segment_id is None:
                continue
            rel_path = clip.get("path")
            if not rel_path or not (context.config.project_dir / rel_path).exists():
                missing.append(segment_id)
        return sorted(set(missing))

    def _continuity_risk_segments(self, clips: list[dict[str, Any]]) -> list[int]:
        risks: list[int] = []
        previous: dict[str, Any] | None = None
        for clip in sorted(clips, key=lambda item: float(item.get("start", 0.0))):
            if previous:
                previous_chars = set(previous.get("character_ids") or [])
                current_chars = set(clip.get("character_ids") or [])
                same_characters = (
                    previous_chars and current_chars and previous_chars == current_chars
                )
                location_changed = (
                    previous.get("location_id")
                    and clip.get("location_id")
                    and previous.get("location_id") != clip.get("location_id")
                )
                if same_characters and location_changed:
                    segment_id = self._to_int(clip.get("segment_id"))
                    if segment_id is not None:
                        risks.append(segment_id)
            previous = clip
        return sorted(set(risks))

    def _pacing_risk_segments(self, clips: list[dict[str, Any]]) -> list[int]:
        risks: list[int] = []
        for clip in clips:
            try:
                duration = float(clip.get("duration") or 0.0)
            except (TypeError, ValueError):
                continue
            segment_id = self._to_int(clip.get("segment_id"))
            if segment_id is None:
                continue
            if duration < 2.5 or duration > 10.0:
                risks.append(segment_id)
        return sorted(set(risks))

    def _to_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_volume(self, output: str, key: str) -> float | None:
        marker = f"{key}:"
        for line in output.splitlines():
            if marker not in line:
                continue
            try:
                value = line.split(marker, 1)[1].strip().split(" ", 1)[0]
                return float(value)
            except (IndexError, ValueError):
                return None
        return None

    def _sum_blackdetect_seconds(self, output: str) -> float:
        total = 0.0
        for line in output.splitlines():
            if "black_duration:" not in line:
                continue
            try:
                total += float(line.rsplit("black_duration:", 1)[1].split()[0])
            except (IndexError, ValueError):
                continue
        return total
