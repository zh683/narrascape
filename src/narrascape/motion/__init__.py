"""Narrascape motion engines — Ken Burns rendering backends."""
from narrascape.motion.base import MotionEngine, MotionParams, MotionResult
from narrascape.motion.zoompan import ZoomPanEngine
from narrascape.motion.crop import CropEngine
from narrascape.motion.pil import PILEngine
from narrascape.motion.factory import (
    build_motion_engine,
    detect_hard_edges,
    compute_zoom_range,
    derive_movement,
    derive_size,
    derive_zoom_magnitude,
)

__all__ = [
    "MotionEngine",
    "MotionParams",
    "MotionResult",
    "ZoomPanEngine",
    "CropEngine",
    "PILEngine",
    "build_motion_engine",
    "detect_hard_edges",
    "compute_zoom_range",
    "derive_movement",
    "derive_size",
    "derive_zoom_magnitude",
]
