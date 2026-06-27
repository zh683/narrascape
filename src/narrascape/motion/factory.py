from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageFilter

from narrascape.config import MovementType, ShotType, SupersampleMode
from narrascape.motion.base import MotionEngine, MotionParams
from narrascape.motion.crop import CropEngine
from narrascape.motion.pil import PILEngine
from narrascape.motion.zoompan import ZoomPanEngine

logger = logging.getLogger("narrascape.motion.factory")


# ═══════════════════════════════════════════
# Hard Edge Detection (gradient-based)
# ═══════════════════════════════════════════

_HARDCACHE: dict[str, bool] = {}


def detect_hard_edges(
    img_path: Path,
    threshold: float = 0.12,
    downsample_width: int = 512,
    grad_threshold: int = 30,
) -> bool:
    """Detect if an image has hard edges (text, grids, geometry) vs soft edges (photos, paintings).

    Algorithm: compute horizontal and vertical pixel gradients, count high-gradient pixels.
    - Soft images (paintings, photos): typically < 8% high-gradient pixels
    - Hard images (text, grids, UI): typically > 20%
    - Threshold default: 12%

    Args:
        img_path: Path to image file
        threshold: Ratio of high-gradient pixels to trigger "hard" classification
        downsample_width: Width to downsample to for faster analysis
        grad_threshold: Grayscale difference threshold (0-255 scale)

    Returns:
        True if hard edges detected (recommend PIL mode), False otherwise
    """
    cache_key = f"{img_path}:{threshold}:{downsample_width}:{grad_threshold}"
    if cache_key in _HARDCACHE:
        return _HARDCACHE[cache_key]

    try:
        img = Image.open(img_path).convert("L")
        w, h = img.size
        if w > downsample_width:
            ratio = downsample_width / w
            img = img.resize((downsample_width, int(h * ratio)), Image.Resampling.BILINEAR)
            w, h = img.size

        edges = img.filter(ImageFilter.FIND_EDGES)
        hist = edges.histogram()
        high_grad = sum(count for value, count in enumerate(hist) if value > grad_threshold)
        total = max(sum(hist), 1)
        ratio = high_grad / total
        is_hard = ratio > threshold
        _HARDCACHE[cache_key] = is_hard
        logger.debug(
            f"[edge detect] {img_path.name}: {ratio * 100:.1f}% edges ({'hard' if is_hard else 'soft'})"
        )
        return is_hard
    except Exception as e:
        logger.warning(f"[edge detect] ERROR on {img_path.name}: {e}")
        return False  # Conservative fallback to zoompan


# ═══════════════════════════════════════════
# Motion Parameter Derivation
# ═══════════════════════════════════════════

# Shot type → default image size
# Shot type → default image size
# All sizes are from Volcengine Seedream API official recommendations:
# https://www.volcengine.com/docs/82379/1541523
# Total pixel range: [3,686,400, 16,777,216]
# Aspect ratio range: [1/16, 16]
SHOT_SIZE_MAP = {
    # ── Ultra-wide landscape shots (pan-based, need aspect >= 16:9) ──
    ShotType.WIDE_ENV: "4704x2016",  # 3K 21:9 — wide landscapes, pan_left
    ShotType.WIDE_ANGLE: "6240x2656",  # 4K 21:9 — panoramic, near max pixel limit
    ShotType.ESTABLISHING: "4704x2016",  # 3K 21:9 — establishing shots, same as wide_env
    ShotType.AERIAL: "5504x3040",  # 4K 16:9 — aerial, high-res for overhead detail
    # ── Standard cinematic shots (zoom-based, 16:9) ──
    ShotType.MEDIUM: "4096x2304",  # 3K 16:9 — standard medium shots
    ShotType.TWO_SHOT: "4096x2304",  # 3K 16:9 — two-person dialog
    ShotType.OVER_SHOULDER: "4096x2304",  # 3K 16:9 — intimate perspective
    ShotType.CLOSE_UP: "4096x2304",  # 3K 16:9 — close-up detail
    # ── Specialized framing (zoom-based, non-standard ratios) ──
    ShotType.EXTREME_CLOSE_UP: "3072x3072",  # 3K 1:1 — face centered, zoom-in crop
    ShotType.DETAIL: "3744x2496",  # 3K 3:2 — slightly wider for objects
    ShotType.INSERT: "3744x2496",  # 3K 3:2 — insert shots (letters, watches)
    ShotType.SILHOUETTE: "3520x4704",  # 4K 3:4 — vertical, full body silhouette
    ShotType.GROUP_SHOT: "4992x3328",  # 4K 3:2 — wider than 16:9, more people
    ShotType.BLACK: None,
}

# Shot type → default movement
SHOT_MOVEMENT_DEFAULT = {
    ShotType.WIDE_ENV: MovementType.PAN_LEFT,
    ShotType.WIDE_ANGLE: MovementType.PAN_RIGHT,
    ShotType.AERIAL: MovementType.PAN_UP,
    ShotType.ESTABLISHING: MovementType.PAN_LEFT,
    ShotType.MEDIUM: MovementType.ZOOM_IN,
    ShotType.TWO_SHOT: MovementType.ZOOM_IN,
    ShotType.OVER_SHOULDER: MovementType.ZOOM_SLOW,
    ShotType.CLOSE_UP: MovementType.ZOOM_IN,
    ShotType.EXTREME_CLOSE_UP: MovementType.ZOOM_SLOW,
    ShotType.DETAIL: MovementType.STILL,
    ShotType.INSERT: MovementType.ZOOM_SLOW,
    ShotType.SILHOUETTE: MovementType.ZOOM_OUT,
    ShotType.GROUP_SHOT: MovementType.ZOOM_IN,
    ShotType.BLACK: MovementType.STILL,
}

# Shot type → base zoom magnitude
SHOT_ZOOM_MAGNITUDE = {
    ShotType.WIDE_ENV: 0.12,
    ShotType.WIDE_ANGLE: 0.10,
    ShotType.AERIAL: 0.08,
    ShotType.ESTABLISHING: 0.10,
    ShotType.MEDIUM: 0.25,
    ShotType.TWO_SHOT: 0.20,
    ShotType.OVER_SHOULDER: 0.18,
    ShotType.CLOSE_UP: 0.25,
    ShotType.EXTREME_CLOSE_UP: 0.08,
    ShotType.DETAIL: 0.12,
    ShotType.INSERT: 0.10,
    ShotType.SILHOUETTE: 0.15,
    ShotType.GROUP_SHOT: 0.18,
}


def derive_size(shot_type: ShotType, manual_size: str | None) -> str | None:
    """Derive image size from shot type. Manual override takes priority."""
    if manual_size:
        return manual_size
    return SHOT_SIZE_MAP.get(shot_type, "2560x1440")


def derive_movement(
    shot_type: ShotType,
    duration: float,
    manual_movement: MovementType | None,
) -> MovementType:
    """Derive optimal Ken Burns movement from shot type and duration.

    Rules by shot type:
    - wide_env / wide_angle / aerial / establishing: always pan (need space to show)
    - medium / two_shot: zoom in for standard; still if very short
    - over_shoulder: slow zoom (intimate); still if very short
    - close_up: slow zoom for medium, still for very short
    - extreme_close_up: zoom_slow or still; never zoom_in (too intense)
    - detail / insert: still for short, slow zoom for medium; rarely zoom_in
    - silhouette: zoom_out (widening) or slow zoom; still for short
    - group_shot: zoom_in (draws attention to individual) or still for short
    - black: always still
    """
    if manual_movement:
        return manual_movement

    # ── Pan-based shots (always need horizontal/vertical movement) ──
    if shot_type in (ShotType.WIDE_ENV, ShotType.ESTABLISHING):
        if duration < 12:
            return MovementType.PAN_LEFT  # still enough motion for wide
        return MovementType.DRIFT if shot_type == ShotType.ESTABLISHING else MovementType.PAN_LEFT

    if shot_type == ShotType.WIDE_ANGLE:
        if duration < 12:
            return MovementType.PAN_RIGHT
        return MovementType.PAN_RIGHT

    if shot_type == ShotType.AERIAL:
        if duration < 15:
            return MovementType.PAN_UP
        return MovementType.TILT_UP  # aerial + long duration = dramatic tilt

    # ── Zoom-based shots ──
    if shot_type == ShotType.MEDIUM:
        if duration < 12:
            return MovementType.STILL
        elif duration < 22:
            return MovementType.ZOOM_SLOW
        return MovementType.ZOOM_IN

    if shot_type == ShotType.TWO_SHOT:
        if duration < 12:
            return MovementType.STILL
        elif duration < 22:
            return MovementType.ZOOM_SLOW
        return MovementType.ZOOM_IN

    if shot_type == ShotType.OVER_SHOULDER:
        if duration < 12:
            return MovementType.STILL
        elif duration < 25:
            return MovementType.ZOOM_SLOW
        return MovementType.ZOOM_IN

    if shot_type == ShotType.CLOSE_UP:
        if duration < 10:
            return MovementType.STILL
        elif duration < 25:
            return MovementType.ZOOM_SLOW
        return MovementType.ZOOM_IN

    if shot_type == ShotType.EXTREME_CLOSE_UP:
        if duration < 15:
            return MovementType.STILL
        return MovementType.ZOOM_IN_SLOW  # never aggressive zoom on ECU

    if shot_type == ShotType.DETAIL:
        if duration < 12:
            return MovementType.STILL
        elif duration < 30:
            return MovementType.ZOOM_SLOW
        return MovementType.ZOOM_IN

    if shot_type == ShotType.INSERT:
        if duration < 12:
            return MovementType.STILL
        elif duration < 25:
            return MovementType.ZOOM_SLOW
        return MovementType.ZOOM_IN_SLOW

    if shot_type == ShotType.SILHOUETTE:
        if duration < 15:
            return MovementType.STILL
        elif duration < 30:
            return MovementType.ZOOM_OUT_SLOW
        return MovementType.PULL_OUT  # dramatic widening for silhouette

    if shot_type == ShotType.GROUP_SHOT:
        if duration < 12:
            return MovementType.STILL
        elif duration < 25:
            return MovementType.ZOOM_SLOW
        return MovementType.PUSH_IN  # draw attention from group to individual

    return MovementType.STILL


def derive_zoom_magnitude(
    movement: MovementType,
    shot_type: ShotType,
    duration: float,
) -> float:
    """Calculate zoom magnitude based on shot type and duration.

    - Short segments (<10s): zoom magnitude halved (avoid jitter)
    - Medium segments (10-18s): zoom magnitude reduced to 75%
    - Long segments (>18s): full zoom magnitude
    - Pan/drift movements: zero zoom (use zoom=1.0)
    """
    base = SHOT_ZOOM_MAGNITUDE.get(shot_type, 0.08)

    # Pan-based movements have no zoom magnitude
    if movement in (
        MovementType.PAN_LEFT,
        MovementType.PAN_RIGHT,
        MovementType.PAN_UP,
        MovementType.PAN_DOWN,
        MovementType.TILT_UP,
        MovementType.TILT_DOWN,
        MovementType.DRIFT,
    ):
        return 0.0

    if duration < 10:
        base *= 0.5
    elif duration < 18:
        base *= 0.75

    return base


def compute_zoom_range(
    movement: MovementType,
    magnitude: float,
) -> tuple[float, float]:
    """Compute zoom start and end factors for a movement.

    Returns:
        (start_zoom, end_zoom) for use in the motion engine.
    """
    if movement == MovementType.ZOOM_SLOW:
        return 1.0, 1.0 + magnitude * 0.5
    elif movement == MovementType.ZOOM_IN_SLOW:
        return 1.0, 1.0 + magnitude * 0.3
    elif movement == MovementType.ZOOM_IN:
        return 1.0, 1.0 + magnitude
    elif movement == MovementType.ZOOM_OUT:
        return 1.0 + magnitude, 1.0
    elif movement == MovementType.ZOOM_OUT_SLOW:
        return 1.0 + magnitude * 0.5, 1.0
    elif movement == MovementType.PUSH_IN:
        return 1.0, 1.0 + magnitude * 1.2
    elif movement == MovementType.PULL_OUT:
        return 1.0 + magnitude * 1.2, 1.0
    elif movement in (
        MovementType.PAN_LEFT,
        MovementType.PAN_RIGHT,
        MovementType.PAN_UP,
        MovementType.PAN_DOWN,
        MovementType.TILT_UP,
        MovementType.TILT_DOWN,
        MovementType.DRIFT,
        MovementType.STILL,
    ):
        return 1.0, 1.0
    return 1.0, 1.0


# ═══════════════════════════════════════════
# Engine Factory
# ═══════════════════════════════════════════

_ENGINES: list[MotionEngine] = [CropEngine(), ZoomPanEngine(), PILEngine()]


def build_motion_engine(params: MotionParams) -> MotionEngine:
    """Select the best motion engine for the given parameters.

    Selection logic:
    1. For pan/tilt/drift/still movements: always CropEngine (smooth crop-based)
    2. For zoom movements: check supersample mode
       - EXTREME → always PIL
       - AUTO → detect hard edges, hard → PIL, soft → zoompan
       - NORMAL → zoompan
    """
    if params.movement in (
        MovementType.PAN_LEFT,
        MovementType.PAN_RIGHT,
        MovementType.PAN_UP,
        MovementType.PAN_DOWN,
        MovementType.TILT_UP,
        MovementType.TILT_DOWN,
        MovementType.DRIFT,
        MovementType.STILL,
    ):
        for engine in _ENGINES:
            if isinstance(engine, CropEngine) and engine.can_handle(params):
                return engine
        raise RuntimeError(f"No crop engine available for {params.movement}")

    # Zoom movement — decide based on supersample mode
    if params.supersample == SupersampleMode.EXTREME:
        for engine in _ENGINES:
            if isinstance(engine, PILEngine) and engine.can_handle(params):
                logger.info(f"[motion] EXTREME mode → PIL engine for {params.image_path.name}")
                return engine

    elif params.supersample == SupersampleMode.AUTO:
        if params.image_path.exists() and detect_hard_edges(params.image_path):
            for engine in _ENGINES:
                if isinstance(engine, PILEngine) and engine.can_handle(params):
                    logger.info("[motion] AUTO mode → hard edges detected → PIL engine")
                    return engine
        for engine in _ENGINES:
            if isinstance(engine, ZoomPanEngine) and engine.can_handle(params):
                logger.info("[motion] AUTO mode → soft edges → zoompan engine")
                return engine

    # Default: normal zoompan
    for engine in _ENGINES:
        if isinstance(engine, ZoomPanEngine) and engine.can_handle(params):
            return engine

    raise RuntimeError(f"No suitable engine for {params.movement}")
