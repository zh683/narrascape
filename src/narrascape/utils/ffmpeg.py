#!/usr/bin/env python3
"""
Unified FFmpeg wrapper with retry, validation, and cross-platform path resolution.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from narrascape.utils.safe_io import atomic_promote_file

logger = logging.getLogger("narrascape.ffmpeg")


# ═══════════════════════════════════════════
# FFmpeg Discovery
# ═══════════════════════════════════════════

_FFMPEG_EXE: Path | None = None
_FFPROBE_EXE: Path | None = None
DEFAULT_FFPROBE_TIMEOUT = int(os.environ.get("NARRASCAPE_FFPROBE_TIMEOUT", "30"))
DEFAULT_FFMPEG_TIMEOUT = int(os.environ.get("NARRASCAPE_FFMPEG_TIMEOUT", "1800"))
_MEDIA_EXTENSIONS = (
    ".mp4",
    ".mp3",
    ".wav",
    ".mov",
    ".mkv",
    ".m4a",
    ".aac",
    ".flac",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
)


def safe_media_arg(path: str | Path) -> str:
    """Return a media path argument that cannot be mistaken for an ffmpeg option."""
    p = Path(path)
    if str(path).startswith("-") or p.name.startswith("-"):
        return str(p.resolve())
    return str(p)


def safe_output_arg(path: str | Path) -> str:
    """Return a final ffmpeg output argument guarded from option parsing."""
    return safe_media_arg(path)


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

    # 4. Versioned Windows archives, e.g. D:\ffmpeg-2026...\bin\ffmpeg.exe
    for root in (Path("C:/"), Path("D:/")):
        if not root.exists():
            continue
        try:
            for archive_candidate in root.glob("ffmpeg*/bin/ffmpeg.exe"):
                if archive_candidate.exists():
                    _FFMPEG_EXE = archive_candidate
                    logger.debug(f"ffmpeg found by versioned scan: {_FFMPEG_EXE}")
                    return _FFMPEG_EXE
        except OSError:
            continue

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
    derived_probe = (
        ffmpeg.parent / "ffprobe.exe" if ffmpeg.suffix == ".exe" else ffmpeg.parent / "ffprobe"
    )
    if derived_probe.exists():
        _FFPROBE_EXE = derived_probe
        return _FFPROBE_EXE

    # Fallback to PATH
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        _FFPROBE_EXE = Path(ffprobe_path)
        return _FFPROBE_EXE

    raise RuntimeError("ffprobe not found. Please install ffmpeg (ffprobe is bundled with it).")


# ═══════════════════════════════════════════
# Media Metadata
# ═══════════════════════════════════════════


def get_duration(path: Path, *, timeout: int | None = None) -> float:
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
        timeout=DEFAULT_FFPROBE_TIMEOUT if timeout is None else timeout,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"Cannot get duration for {path}: {r.stderr}")
    raw = r.stdout.strip()
    try:
        duration = float(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Cannot get duration for {path}: invalid ffprobe duration {raw!r}"
        ) from exc
    if not math.isfinite(duration):
        raise RuntimeError(f"Cannot get duration for {path}: invalid ffprobe duration {raw!r}")
    return duration


def get_media_info(path: Path, *, timeout: int | None = None) -> dict[str, Any]:
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
        timeout=DEFAULT_FFPROBE_TIMEOUT if timeout is None else timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {r.stderr}")
    import json

    data = json.loads(r.stdout)
    return data if isinstance(data, dict) else {}


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
        timeout: Max execution time in seconds (None uses the bounded project default)
        capture_output: Whether to capture stdout/stderr

    Returns:
        True if successful, False otherwise
    """
    ffmpeg = find_ffmpeg()
    normalized_args, output_path, temporary_path = _atomic_output_args(args)
    cmd = [str(ffmpeg), "-y"] + normalized_args
    effective_timeout = DEFAULT_FFMPEG_TIMEOUT if timeout is None else timeout

    for attempt in range(retries + 1):
        logger.info(f"[ffmpeg] {desc or 'cmd'} (attempt {attempt + 1}/{retries + 1})")
        start = time.monotonic()

        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=capture_output,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired:
            _remove_temporary_output(temporary_path)
            logger.error(f"[ffmpeg] TIMEOUT after {effective_timeout}s: {desc}")
            if attempt < retries:
                time.sleep(1)
                continue
            return False

        if result.returncode != 0:
            _remove_temporary_output(temporary_path)
            stderr = (result.stderr or "")[:500] if capture_output else "(output not captured)"
            logger.error(f"[ffmpeg] ERROR: {stderr}")
            if attempt < retries:
                logger.info("[ffmpeg] Retrying in 1s...")
                time.sleep(1)
                continue
            return False

        elapsed = time.monotonic() - start

        # Validate output
        produced_path = temporary_path or output_path
        if validate_output and produced_path is not None:
            output_name = (output_path or produced_path).name
            if not _validate_media_output(produced_path):
                _remove_temporary_output(temporary_path)
                logger.error(f"[ffmpeg] Output validation failed: {output_name}")
                if attempt < retries:
                    continue
                return False
            logger.info(f"[ffmpeg] OK {elapsed:.1f}s: {output_name}")
        else:
            logger.info(f"[ffmpeg] OK {elapsed:.1f}s: {desc}")

        if temporary_path is not None and output_path is not None:
            atomic_promote_file(temporary_path, output_path)

        return True

    return False


def run_ffmpeg_silent(
    args: list[str], timeout: int | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ffmpeg silently, returning the full result. For internal use."""
    ffmpeg = find_ffmpeg()
    normalized, output_path, temporary_path = _atomic_output_args(args)
    cmd = [str(ffmpeg), "-y", "-loglevel", "error"] + normalized
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=DEFAULT_FFMPEG_TIMEOUT if timeout is None else timeout,
    )
    _promote_completed_output(result, output_path, temporary_path)
    return result


def run_ffmpeg_raw(
    args: list[str],
    *,
    timeout: int | None = None,
    loglevel: str = "error",
) -> subprocess.CompletedProcess[str]:
    """Run ffmpeg with normalized media path arguments and return process output."""
    ffmpeg = find_ffmpeg()
    normalized, output_path, temporary_path = _atomic_output_args(args)
    cmd = [str(ffmpeg), "-y", "-loglevel", loglevel] + normalized
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=DEFAULT_FFMPEG_TIMEOUT if timeout is None else timeout,
    )
    _promote_completed_output(result, output_path, temporary_path)
    return result


def _atomic_output_args(args: list[str]) -> tuple[list[str], Path | None, Path | None]:
    normalized = _normalize_ffmpeg_args(args)
    if not normalized or not _is_media_path(normalized[-1]):
        return normalized, None, None
    output_path = Path(normalized[-1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(
        f".{output_path.stem}.{uuid.uuid4().hex}.render{output_path.suffix}"
    )
    normalized[-1] = safe_output_arg(temporary_path)
    return normalized, output_path, temporary_path


def _validate_media_output(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        try:
            from PIL import Image

            with Image.open(path) as image:
                image.verify()
            return True
        except Exception:
            return False
    return validate_video(path)


def _remove_temporary_output(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def _promote_completed_output(
    result: subprocess.CompletedProcess[str],
    output_path: Path | None,
    temporary_path: Path | None,
) -> None:
    if temporary_path is None or output_path is None:
        return
    if result.returncode == 0 and _validate_media_output(temporary_path):
        atomic_promote_file(temporary_path, output_path)
        return
    _remove_temporary_output(temporary_path)


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
