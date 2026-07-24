from __future__ import annotations

import math
import subprocess
import tempfile
from array import array
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from narrascape.utils.ffmpeg import find_ffmpeg, get_duration, safe_media_arg

DEFAULT_FRAME_COUNT = 8
DEFAULT_AUDIO_SAMPLE_RATE = 8_000
MAX_AUDIO_SECONDS = 600


def analyze_frame_images(frames: Iterable[Image.Image]) -> dict[str, Any]:
    """Calculate deterministic visual metrics from an ordered frame sample."""
    luminances: list[float] = []
    entropies: list[float] = []
    hashes: list[int] = []
    for frame in frames:
        gray = frame.convert("L")
        luminances.append(float(ImageStat.Stat(gray).mean[0]) / 255.0)
        entropies.append(float(gray.entropy()))
        hashes.append(_average_hash(gray))

    sample_count = len(luminances)
    if sample_count == 0:
        raise ValueError("frame sample is empty")

    frozen_pairs = 0
    for index in range(1, sample_count):
        hash_distance = (hashes[index - 1] ^ hashes[index]).bit_count()
        luminance_delta = abs(luminances[index - 1] - luminances[index])
        if hash_distance <= 2 and luminance_delta <= 0.02:
            frozen_pairs += 1

    pair_count = max(sample_count - 1, 0)
    return {
        "sample_count": sample_count,
        "mean_luminance": round(sum(luminances) / sample_count, 6),
        "mean_entropy": round(sum(entropies) / sample_count, 6),
        "dark_frame_ratio": round(sum(value < 0.08 for value in luminances) / sample_count, 6),
        "low_detail_ratio": round(sum(value < 1.0 for value in entropies) / sample_count, 6),
        "frozen_pair_ratio": round(frozen_pairs / pair_count, 6) if pair_count else 0.0,
    }


def analyze_audio_samples(raw_pcm: bytes, *, sample_rate: int) -> dict[str, Any]:
    """Calculate normalized audio metrics from mono little-endian signed 16-bit PCM."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if len(raw_pcm) % 2:
        raw_pcm = raw_pcm[:-1]
    samples = array("h")
    samples.frombytes(raw_pcm)
    if not samples:
        raise ValueError("audio sample is empty")
    if samples.itemsize != 2:
        raise RuntimeError("16-bit PCM analysis requires two-byte signed shorts")
    if __import__("sys").byteorder != "little":
        samples.byteswap()

    sample_count = len(samples)
    square_total = 0
    peak = 0
    clipping = 0
    silence = 0
    for sample in samples:
        absolute = abs(sample)
        square_total += sample * sample
        peak = max(peak, absolute)
        clipping += absolute >= 32_767
        silence += absolute <= 327
    rms = math.sqrt(square_total / sample_count) / 32_768.0
    return {
        "sample_rate": sample_rate,
        "sample_count": sample_count,
        "duration_seconds": round(sample_count / sample_rate, 6),
        "rms": round(rms, 6),
        "peak": round(peak / 32_768.0, 6),
        "clipping_ratio": round(clipping / sample_count, 6),
        "silence_ratio": round(silence / sample_count, 6),
    }


def analyze_media(
    path: Path,
    *,
    frame_count: int = DEFAULT_FRAME_COUNT,
    timeout: int = 60,
) -> dict[str, Any]:
    """Sample real decoded frames and PCM audio with bounded FFmpeg subprocesses."""
    target = Path(path)
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    errors: dict[str, str] = {}
    report: dict[str, Any] = {}

    try:
        report["frames"] = _analyze_video_frames(target, frame_count=frame_count, timeout=timeout)
    except Exception as exc:
        errors["frames"] = str(exc)
    try:
        report["audio"] = _analyze_audio_track(target, timeout=timeout)
    except Exception as exc:
        errors["audio"] = str(exc)

    report["status"] = "ok" if not errors else ("partial" if len(errors) == 1 else "unavailable")
    if errors:
        report["errors"] = errors
    return report


def _analyze_video_frames(path: Path, *, frame_count: int, timeout: int) -> dict[str, Any]:
    duration = get_duration(path, timeout=min(timeout, 30))
    if duration <= 0:
        raise RuntimeError("media duration is not positive")
    sample_rate = frame_count / duration
    with tempfile.TemporaryDirectory(prefix="narrascape-qa-") as temp_dir:
        pattern = Path(temp_dir) / "frame-%03d.png"
        command = [
            str(find_ffmpeg()),
            "-y",
            "-loglevel",
            "error",
            "-i",
            safe_media_arg(path),
            "-vf",
            f"fps={sample_rate:.12f},scale=160:90:force_original_aspect_ratio=decrease,"
            "pad=160:90:(ow-iw)/2:(oh-ih)/2",
            "-frames:v",
            str(frame_count),
            str(pattern),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"frame extraction failed: {result.stderr.strip()[:300]}")
        frame_paths = sorted(Path(temp_dir).glob("frame-*.png"))
        if not frame_paths:
            raise RuntimeError("frame extraction produced no frames")
        images: list[Image.Image] = []
        for frame_path in frame_paths:
            with Image.open(frame_path) as image:
                images.append(image.convert("RGB"))
        metrics = analyze_frame_images(images)
        metrics["requested_sample_count"] = frame_count
        return metrics


def _analyze_audio_track(path: Path, *, timeout: int) -> dict[str, Any]:
    command = [
        str(find_ffmpeg()),
        "-v",
        "error",
        "-i",
        safe_media_arg(path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(DEFAULT_AUDIO_SAMPLE_RATE),
        "-t",
        str(MAX_AUDIO_SECONDS),
        "-f",
        "s16le",
        "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        reason = result.stderr.decode("utf-8", errors="replace").strip()[:300]
        raise RuntimeError(f"audio decoding failed: {reason}")
    return analyze_audio_samples(result.stdout, sample_rate=DEFAULT_AUDIO_SAMPLE_RATE)


def _average_hash(gray: Image.Image) -> int:
    resized = gray.resize((8, 8))
    if hasattr(resized, "get_flattened_data"):
        pixels = list(resized.get_flattened_data())
    else:
        pixels = list(resized.getdata())
    average = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= average)
    return value
