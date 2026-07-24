"""Frame-sampling video quality signals for deterministic take scoring.

Pure functions built on ``utils/ffmpeg`` (ffprobe/ffmpeg with timeouts) and
PIL — no instance state, no new dependencies. ``TakeSelectStage`` uses these
to replace byte-size proxy scoring with real quality signals:

- **sharpness**: Laplacian variance of sampled frames (blur detection)
- **brightness**: mean luminance of sampled frames (black/dark-frame detection)
- **duration**: ffprobe duration vs the director-contract expected duration
- **stability**: average-hash agreement between sampled frames (frozen video)

Every function raises on failure; callers own the fallback policy.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat

from narrascape.utils.ffmpeg import get_duration, run_ffmpeg_raw

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────
# Tunables
# ───────────────────────────────────────────

SAMPLE_FRAME_COUNT = 3
SAMPLE_WIDTH = 160
SAMPLE_HEIGHT = 90
FRAME_TIMEOUT = 30

# Laplacian variance at/above this reads as fully sharp for a 160x90 sample.
# Natural/generated video typically lands in the low thousands; heavily
# blurred video drops into the low hundreds.
_SHARPNESS_REFERENCE = 1000.0
# Mean luminance (0-255): at/below _BLACK_CEILING a frame reads as black;
# at/above _BRIGHT_FLOOR it earns full brightness credit. qa.py's blackdetect
# threshold (pix_th=0.10 ≈ 26/255) sits between the two.
_BLACK_CEILING = 8.0
_BRIGHT_FLOOR = 48.0
# Relative duration deviation that zeroes the duration score.
_DURATION_TOLERANCE = 0.5
# Average-hash Hamming distance at/below which two frames read as identical.
_FROZEN_HASH_TOLERANCE = 1

WEIGHT_SHARPNESS = 0.35
WEIGHT_BRIGHTNESS = 0.25
WEIGHT_DURATION = 0.25
WEIGHT_STABILITY = 0.15


# ───────────────────────────────────────────
# Frame extraction
# ───────────────────────────────────────────


def extract_sample_frames(
    path: Path,
    work_dir: Path,
    *,
    duration: float,
    frame_count: int = SAMPLE_FRAME_COUNT,
    timeout: int = FRAME_TIMEOUT,
) -> list[Path]:
    """Extract up to ``frame_count`` evenly spaced frames as small JPEGs.

    The ``fps`` filter resamples to ``frame_count / duration`` fps so frames
    are spread across the whole clip regardless of source frame rate.
    """
    if duration <= 0:
        raise RuntimeError(f"cannot sample frames from {path}: non-positive duration")
    fps = frame_count / duration
    pattern = f"{path.stem}_%02d.jpg"
    result = run_ffmpeg_raw(
        [
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vf",
            f"fps={fps:.6f},scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}",
            "-frames:v",
            str(frame_count),
            str(work_dir / pattern),
        ],
        timeout=timeout,
    )
    frames = sorted(work_dir.glob(f"{path.stem}_*.jpg"))
    if result.returncode != 0 or not frames:
        raise RuntimeError(f"frame extraction failed for {path}: {(result.stderr or '')[:200]}")
    return frames[:frame_count]


# ───────────────────────────────────────────
# Per-frame measurements
# ───────────────────────────────────────────

_LAPLACIAN_KERNEL = ImageFilter.Kernel(
    (3, 3),
    (-1, -1, -1, -1, 8, -1, -1, -1, -1),
    scale=1,
    offset=128,
)


def frame_mean_luminance(image: Image.Image) -> float:
    """Mean grayscale luminance (0-255) of a frame."""
    return float(ImageStat.Stat(image.convert("L")).mean[0])


def frame_laplacian_variance(image: Image.Image) -> float:
    """Laplacian variance of a frame — higher means sharper."""
    edges = image.convert("L").filter(_LAPLACIAN_KERNEL)
    return float(ImageStat.Stat(edges).var[0])


def average_hash(image: Image.Image, size: int = 8) -> str:
    """8x8 average hash of a frame for frozen/duplicate detection."""
    gray = image.convert("L").resize((size, size))
    if hasattr(gray, "get_flattened_data"):
        pixels = list(gray.get_flattened_data())
    else:
        pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    return "".join("1" if pixel >= mean else "0" for pixel in pixels)


def _hamming(first: str, second: str) -> int:
    return sum(1 for a, b in zip(first, second, strict=True) if a != b)


# ───────────────────────────────────────────
# Signal scores (each 0-100)
# ───────────────────────────────────────────


def sharpness_score(laplacian_variance: float) -> float:
    """Log-scale mapping: 0 at variance 0, 100 at/above the reference."""
    if laplacian_variance <= 0:
        return 0.0
    score = 100.0 * math.log10(laplacian_variance + 1.0) / math.log10(_SHARPNESS_REFERENCE + 1.0)
    return round(min(100.0, score), 3)


def brightness_score(mean_luminance: float) -> float:
    """Linear ramp from black ceiling to bright floor, clamped to 0-100."""
    score = 100.0 * (mean_luminance - _BLACK_CEILING) / (_BRIGHT_FLOOR - _BLACK_CEILING)
    return round(min(100.0, max(0.0, score)), 3)


def duration_score(actual_seconds: float, expected_seconds: float | None) -> float:
    """100 on target; linearly to 0 at ±50% deviation; neutral without contract."""
    if expected_seconds is None or expected_seconds <= 0 or actual_seconds <= 0:
        return 100.0
    deviation = abs(actual_seconds - expected_seconds) / expected_seconds
    return round(max(0.0, 100.0 * (1.0 - deviation / _DURATION_TOLERANCE)), 3)


def stability_score(frame_hashes: list[str]) -> float:
    """100 when sampled frames differ; 0 when every pair reads as frozen."""
    if len(frame_hashes) < 2:
        return 100.0
    pairs = [
        (first, second)
        for index, first in enumerate(frame_hashes)
        for second in frame_hashes[index + 1 :]
    ]
    frozen = sum(1 for first, second in pairs if _hamming(first, second) <= _FROZEN_HASH_TOLERANCE)
    return round(100.0 * (1.0 - frozen / len(pairs)), 3)


# ───────────────────────────────────────────
# Take analysis
# ───────────────────────────────────────────


def analyze_take(
    path: Path,
    *,
    expected_duration: float | None,
    work_dir: Path,
    timeout: int = FRAME_TIMEOUT,
) -> dict[str, Any]:
    """Analyze one take: duration probe + sampled-frame signals.

    Returns a quality dict with ``composite`` (0-100) and per-signal scores
    for auditability. Raises RuntimeError on any ffprobe/ffmpeg failure —
    the caller decides the fallback policy.
    """
    actual_duration = get_duration(path, timeout=timeout)
    frames = extract_sample_frames(path, work_dir, duration=actual_duration, timeout=timeout)

    luminances: list[float] = []
    variances: list[float] = []
    hashes: list[str] = []
    for frame in frames:
        with Image.open(frame) as image:
            luminances.append(frame_mean_luminance(image))
            variances.append(frame_laplacian_variance(image))
            hashes.append(average_hash(image))

    mean_luminance = sum(luminances) / len(luminances)
    mean_variance = sum(variances) / len(variances)
    sharpness = sharpness_score(mean_variance)
    brightness = brightness_score(mean_luminance)
    duration = duration_score(actual_duration, expected_duration)
    stability = stability_score(hashes)
    composite = round(
        WEIGHT_SHARPNESS * sharpness
        + WEIGHT_BRIGHTNESS * brightness
        + WEIGHT_DURATION * duration
        + WEIGHT_STABILITY * stability,
        3,
    )
    return {
        "status": "ok",
        "composite": composite,
        "sharpness": sharpness,
        "brightness": brightness,
        "duration_score": duration,
        "stability": stability,
        "mean_luminance": round(mean_luminance, 3),
        "laplacian_variance": round(mean_variance, 3),
        "duration_seconds": round(actual_duration, 3),
        "expected_duration_seconds": expected_duration,
        "frames_analyzed": len(frames),
    }
