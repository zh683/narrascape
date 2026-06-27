#!/usr/bin/env python3
"""
Unified FFmpeg wrapper with retry, validation, and cross-platform path resolution.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("narrascape.ffmpeg")


# ═══════════════════════════════════════════
# FFmpeg Discovery
# ═══════════════════════════════════════════

_FFMPEG_EXE: Path | None = None
_FFPROBE_EXE: Path | None = None
_MEDIA_EXTENSIONS = (".mp4", ".mp3", ".wav", ".mov", ".mkv", ".m4a", ".aac", ".flac")


def safe_media_arg(path: str | Path) -> str:
    """Return a media path argument that cannot be mistaken for an ffmpeg option."""
    p = Path(path)
    if str(path).startswith("-") or p.name.startswith("-"):
        return str(p.resolve())
    return str(p)


def _normalize_ffmpeg_args(args: list[str]) -> list[str]:
    normalized: list[str] = []
    input_next = False
    for arg in args:
        if input_next:
            normalized.append(safe_media_arg(arg))
            input_next = False
            continue
        normalized.append(arg)
        if arg == "-i":
            input_next = True
    if normalized and _is_media_path(normalized[-1]):
        normalized[-1] = safe_media_arg(normalized[-1])
    return normalized


def _is_media_path(value: str) -> bool:
    return Path(value).suffix.lower() in _MEDIA_EXTENSIONS


def find_ffmpeg() -> Path:
    """Locate ffmpeg executable. Cached after first call."""
    global _FFMPEG_EXE
    if _FFMPEG_EXE is not None:
        return _FFMPEG_EXE

    # 1. NARRASCAPE_FFMPEG environment variable (MONTAGE_FFMPEG deprecated)
    env_override = os.environ.get("NARRASCAPE_FFMPEG") or os.environ.get("MONTAGE_FFMPEG")
    if env_override:
        p = Path(env_override)
        if p.exists():
            _FFMPEG_EXE = p
            logger.debug(f"ffmpeg found via NARRASCAPE_FFMPEG: {_FFMPEG_EXE}")
            return _FFMPEG_EXE

    # 2. PATH
    env_path = shutil.which("ffmpeg")
    if env_path:
        _FFMPEG_EXE = Path(env_path)
        logger.debug(f"ffmpeg found via PATH: {_FFMPEG_EXE}")
        return _FFMPEG_EXE

    # 3. Common Windows locations
    for candidate in [
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"D:\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe",
    ]:
        p = Path(candidate)
        if p.exists():
            _FFMPEG_EXE = p
            logger.debug(f"ffmpeg found at: {_FFMPEG_EXE}")
            return _FFMPEG_EXE

    raise RuntimeError(
        "ffmpeg not found. Please install ffmpeg and ensure it's in PATH, "
        "or set NARRASCAPE_FFMPEG environment variable to the full path."
    )


def find_ffprobe() -> Path:
    """Locate ffprobe executable. Cached after first call."""
    global _FFPROBE_EXE
    if _FFPROBE_EXE is not None:
        return _FFPROBE_EXE

    # Derive from ffmpeg location
    ffmpeg = find_ffmpeg()
    probe = ffmpeg.parent / "ffprobe.exe" if ffmpeg.suffix == ".exe" else ffmpeg.parent / "ffprobe"
    if probe.exists():
        _FFPROBE_EXE = probe
        return _FFPROBE_EXE

    # Fallback to PATH
    env_path = shutil.which("ffprobe")
    if env_path:
        _FFPROBE_EXE = Path(env_path)
        return _FFPROBE_EXE

    raise RuntimeError("ffprobe not found. Please install ffmpeg (ffprobe is bundled with it).")


# ═══════════════════════════════════════════
# Media Metadata
# ═══════════════════════════════════════════


def get_duration(path: Path) -> float:
    """Get media duration in seconds using ffprobe."""
    probe = find_ffprobe()
    media_path = safe_media_arg(path)
    r = subprocess.run(
        [
            str(probe),
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            media_path,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"Cannot get duration for {path}: {r.stderr}")
    return float(r.stdout.strip())


def get_media_info(path: Path) -> dict[str, Any]:
    """Get comprehensive media metadata as JSON."""
    probe = find_ffprobe()
    media_path = safe_media_arg(path)
    r = subprocess.run(
        [
            str(probe),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            media_path,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {r.stderr}")
    import json

    return json.loads(r.stdout)


def validate_video(path: Path) -> bool:
    """Validate that a video file exists and has positive duration."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        dur = get_duration(path)
        return dur > 0
    except Exception:
        return False


def get_video_resolution(path: Path) -> tuple[int, int]:
    """Get video resolution (width, height)."""
    info = get_media_info(path)
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            return int(stream["width"]), int(stream["height"])
    raise RuntimeError(f"No video stream found in {path}")


# ═══════════════════════════════════════════
# FFmpeg Execution
# ═══════════════════════════════════════════


def run_ffmpeg(
    args: list[str],
    *,
    desc: str = "",
    retries: int = 2,
    validate_output: bool = True,
    timeout: int | None = None,
    capture_output: bool = True,
) -> bool:
    """Execute ffmpeg with retry logic and optional output validation.

    Args:
        args: ffmpeg arguments (without the 'ffmpeg' executable itself)
        desc: Human-readable description for logging
        retries: Number of retry attempts on failure
        validate_output: Whether to ffprobe-validate the output file
        timeout: Max execution time in seconds (None = no limit)
        capture_output: Whether to capture stdout/stderr

    Returns:
        True if successful, False otherwise
    """
    ffmpeg = find_ffmpeg()
    normalized_args = _normalize_ffmpeg_args(args)
    cmd = [str(ffmpeg), "-y"] + normalized_args

    # Detect output file path from args
    output_path: Path | None = None
    for i in range(len(normalized_args) - 1, -1, -1):
        a = normalized_args[i]
        if not a.startswith("-") and _is_media_path(a):
            output_path = Path(a)
            break

    for attempt in range(retries + 1):
        logger.info(f"[ffmpeg] {desc or 'cmd'} (attempt {attempt + 1}/{retries + 1})")
        start = time.monotonic()

        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=capture_output,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"[ffmpeg] TIMEOUT after {timeout}s: {desc}")
            if attempt < retries:
                time.sleep(1)
                continue
            return False

        if result.returncode != 0:
            stderr = (result.stderr or "")[:500] if capture_output else "(output not captured)"
            logger.error(f"[ffmpeg] ERROR: {stderr}")
            if attempt < retries:
                logger.info("[ffmpeg] Retrying in 1s...")
                time.sleep(1)
                continue
            return False

        elapsed = time.monotonic() - start

        # Validate output
        if validate_output and output_path and output_path.exists():
            if not validate_video(output_path):
                logger.error(f"[ffmpeg] Output validation failed: {output_path.name}")
                if attempt < retries:
                    continue
                return False
            logger.info(f"[ffmpeg] OK {elapsed:.1f}s: {output_path.name}")
        else:
            logger.info(f"[ffmpeg] OK {elapsed:.1f}s: {desc}")

        return True

    return False


def run_ffmpeg_silent(args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    """Run ffmpeg silently, returning the full result. For internal use."""
    ffmpeg = find_ffmpeg()
    cmd = [str(ffmpeg), "-y", "-loglevel", "error"] + _normalize_ffmpeg_args(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ═══════════════════════════════════════════
# Content Hashing for Cache Keys
# ═══════════════════════════════════════════


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    """Compute hash of file contents."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def config_hash(config: Any, algorithm: str = "sha256") -> str:
    """Compute hash of a Pydantic model (or any JSON-serializable object)."""
    import json

    if isinstance(config, BaseModel):
        data = config.model_dump_json(exclude={"project_dir"})
    else:
        data = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.new(algorithm, data.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════
# Cross-Platform Font Discovery
# ═══════════════════════════════════════════


def get_system_font() -> str:
    """Return a font file path suitable for ffmpeg drawtext, cross-platform.

    Tries well-known system font paths per OS. Falls back to finding any .ttf.
    """
    import sys

    candidates = {
        "win32": [
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\arial.ttf",
        ],
        "darwin": [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Helvetica.ttc",
        ],
        "linux": [
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ],
    }

    for path in candidates.get(sys.platform, candidates["linux"]):
        if Path(path).exists():
            return path

    # Fallback: search for any .ttf or .ttc in common dirs
    search_dirs = []
    if sys.platform == "win32":
        search_dirs = [Path(r"C:\Windows\Fonts")]
    elif sys.platform == "darwin":
        search_dirs = [Path("/System/Library/Fonts"), Path("/Library/Fonts")]
    else:
        search_dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]

    for d in search_dirs:
        if d.exists():
            for ext in ("*.ttf", "*.ttc"):
                for f in d.rglob(ext):
                    return str(f)

    raise RuntimeError(
        "No suitable font file found for ffmpeg drawtext. "
        "Please install a TrueType font (e.g., DejaVu, WenQuanYi, or Microsoft YaHei)."
    )


def get_system_font_name() -> str:
    """Return a font name suitable for ffmpeg subtitles force_style FontName, cross-platform."""
    import sys

    names = {
        "win32": ["Microsoft YaHei", "SimHei", "Arial"],
        "darwin": ["PingFang SC", "Heiti SC", "Helvetica"],
        "linux": ["WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "DejaVu Sans", "Liberation Sans"],
    }

    return names.get(sys.platform, names["linux"])[0]
