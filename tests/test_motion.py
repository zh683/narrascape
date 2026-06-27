#!/usr/bin/env python3
"""Tests for motion engines and factory functions."""
from __future__ import annotations

import pytest
from pathlib import Path

from narrascape.config import MovementType, ShotType, SupersampleMode
from narrascape.motion import (
    MotionParams,
    build_motion_engine,
    compute_zoom_range,
    derive_movement,
    derive_size,
    derive_zoom_magnitude,
    detect_hard_edges,
)
from narrascape.motion.crop import CropEngine
from narrascape.motion.pil import PILEngine
from narrascape.motion.zoompan import ZoomPanEngine


class TestDeriveFunctions:
    def test_derive_size(self):
        assert derive_size(ShotType.WIDE_ENV, None) == "4704x2016"
        assert derive_size(ShotType.CLOSE_UP, None) == "4096x2304"
        assert derive_size(ShotType.WIDE_ENV, "custom") == "custom"

    def test_derive_movement(self):
        assert derive_movement(ShotType.WIDE_ENV, 20, None) == MovementType.PAN_LEFT
        assert derive_movement(ShotType.CLOSE_UP, 5, None) == MovementType.STILL
        assert derive_movement(ShotType.CLOSE_UP, 15, None) == MovementType.ZOOM_SLOW
        assert derive_movement(ShotType.CLOSE_UP, 30, None) == MovementType.ZOOM_IN
        assert derive_movement(ShotType.CLOSE_UP, 30, MovementType.ZOOM_OUT) == MovementType.ZOOM_OUT

    def test_derive_zoom_magnitude(self):
        assert derive_zoom_magnitude(MovementType.ZOOM_IN, ShotType.WIDE_ENV, 30) == 0.12
        assert derive_zoom_magnitude(MovementType.ZOOM_IN, ShotType.WIDE_ENV, 5) == 0.06  # < 10s, halved
        assert derive_zoom_magnitude(MovementType.ZOOM_IN, ShotType.WIDE_ENV, 12) == 0.09  # < 18s, 75%

    def test_compute_zoom_range(self):
        assert compute_zoom_range(MovementType.ZOOM_IN, 0.15) == (1.0, 1.15)
        assert compute_zoom_range(MovementType.ZOOM_OUT, 0.15) == (1.15, 1.0)
        assert compute_zoom_range(MovementType.ZOOM_SLOW, 0.15) == (1.0, 1.075)
        assert compute_zoom_range(MovementType.STILL, 0.15) == (1.0, 1.0)


class TestEngineSelection:
    def test_pan_uses_crop(self):
        params = MotionParams(
            image_path=Path("/tmp/test.png"),
            output_path=Path("/tmp/out.mp4"),
            duration=10.0, fps=25, width=1920, height=1080,
            movement=MovementType.PAN_LEFT,
            shot_type=ShotType.WIDE_ENV,
            fade_in=1.0, fade_out=1.0,
        )
        engine = build_motion_engine(params)
        assert isinstance(engine, CropEngine)

    def test_zoom_normal_uses_zoompan(self):
        params = MotionParams(
            image_path=Path("/tmp/test.png"),
            output_path=Path("/tmp/out.mp4"),
            duration=10.0, fps=25, width=1920, height=1080,
            movement=MovementType.ZOOM_IN,
            shot_type=ShotType.MEDIUM,
            fade_in=1.0, fade_out=1.0,
            supersample=SupersampleMode.NORMAL,
        )
        engine = build_motion_engine(params)
        assert isinstance(engine, ZoomPanEngine)

    def test_zoom_extreme_uses_pil(self):
        params = MotionParams(
            image_path=Path("/tmp/test.png"),
            output_path=Path("/tmp/out.mp4"),
            duration=10.0, fps=25, width=1920, height=1080,
            movement=MovementType.ZOOM_IN,
            shot_type=ShotType.MEDIUM,
            fade_in=1.0, fade_out=1.0,
            supersample=SupersampleMode.EXTREME,
        )
        engine = build_motion_engine(params)
        assert isinstance(engine, PILEngine)
