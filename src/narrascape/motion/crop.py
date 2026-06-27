from __future__ import annotations

import logging

from narrascape.motion.base import MotionEngine, MotionParams, MotionResult
from narrascape.utils.ffmpeg import run_ffmpeg

logger = logging.getLogger("narrascape.motion.crop")


class CropEngine(MotionEngine):
    """
    Ken Burns pan via ffmpeg crop filter.
    crop uses floating-point 't' interpolation — always smooth, no jitter.
    Supports horizontal, vertical, and tilt movements.
    """

    @property
    def name(self) -> str:
        return "crop"

    def can_handle(self, params: MotionParams) -> bool:
        return params.movement in (
            "pan_left",
            "pan_right",
            "pan_up",
            "pan_down",
            "tilt_up",
            "tilt_down",
            "drift",
            "still",
        )

    def generate(self, params: MotionParams) -> MotionResult:
        pre_scale = f"scale=-1:{params.height},"

        w, h = params.width, params.height

        if params.movement == "pan_left":
            crop_expr = (
                f"crop={w}:{h}:" f"x='(in_w-{w})*t/{params.duration:.3f}':" f"y='(in_h-{h})/2'"
            )
        elif params.movement == "pan_right":
            crop_expr = (
                f"crop={w}:{h}:" f"x='(in_w-{w})*(1-t/{params.duration:.3f})':" f"y='(in_h-{h})/2'"
            )
        elif params.movement == "pan_up":
            crop_expr = (
                f"crop={w}:{h}:" f"x='(in_w-{w})/2':" f"y='(in_h-{h})*(1-t/{params.duration:.3f})'"
            )
        elif params.movement == "pan_down":
            crop_expr = (
                f"crop={w}:{h}:" f"x='(in_w-{w})/2':" f"y='(in_h-{h})*t/{params.duration:.3f}'"
            )
        elif params.movement == "tilt_up":
            # Tilt-up: more dramatic vertical pan + slight zoom (start lower, end higher)
            crop_expr = (
                f"crop={w}:{h}:"
                f"x='(in_w-{w})/2':"
                f"y='(in_h-{h})*0.7*(1-t/{params.duration:.3f})'"
            )
        elif params.movement == "tilt_down":
            # Tilt-down: start high, end low
            crop_expr = (
                f"crop={w}:{h}:"
                f"x='(in_w-{w})/2':"
                f"y='(in_h-{h})*0.7*(t/{params.duration:.3f})'"
            )
        elif params.movement == "drift":
            # Drift: subtle diagonal movement (very gentle)
            crop_expr = (
                f"crop={w}:{h}:"
                f"x='(in_w-{w})*(0.2*t/{params.duration:.3f})':"
                f"y='(in_h-{h})*(0.15*(1-t/{params.duration:.3f}))'"
            )
        else:  # still
            crop_expr = f"crop={w}:{h}:" f"x='(in_w-{w})/2':y='(in_h-{h})/2'"

        vf = f"{pre_scale}{crop_expr},{self._build_fade_vf(params)}"

        ok = run_ffmpeg(
            [
                "-loop",
                "1",
                "-i",
                str(params.image_path),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-t",
                str(params.duration),
                str(params.output_path),
            ],
            desc=f"crop {params.movement.value}",
            validate_output=True,
        )

        return MotionResult(
            output_path=params.output_path,
            success=ok,
            engine_used=self.name,
            duration=params.duration,
            error=None if ok else "crop ffmpeg failed",
        )
