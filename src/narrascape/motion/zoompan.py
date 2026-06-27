from __future__ import annotations

import logging

from narrascape.motion.base import MotionEngine, MotionParams, MotionResult
from narrascape.utils.ffmpeg import run_ffmpeg

logger = logging.getLogger("narrascape.motion.zoompan")


class ZoomPanEngine(MotionEngine):
    """
    Ken Burns zoom via ffmpeg zoompan filter.
    V4 fix: d=1 + in variable + 2x pre-scale eliminates cumulative jitter (Bug #4298).
    """

    @property
    def name(self) -> str:
        return "zoompan"

    def can_handle(self, params: MotionParams) -> bool:
        return params.movement in (
            "zoom_in",
            "zoom_slow",
            "zoom_out",
            "zoom_in_slow",
            "zoom_out_slow",
            "push_in",
            "pull_out",
        )

    def generate(self, params: MotionParams) -> MotionResult:
        total_frames = max(int(round(params.duration * params.fps)), 1)
        zoom_delta = params.zoom_end - params.zoom_start

        # V4: 2x pre-scale + d=1 + in/total_frames eliminates cumulative error
        # zoompan's z operates on the 2x pre-scaled image, so we double the zoom values
        zoom_2x_start = 2 * params.zoom_start
        zoom_2x_end = 2 * params.zoom_end
        zoom_step = zoom_2x_end - zoom_2x_start

        vf = (
            f"scale=iw*2:ih*2:flags=lanczos,"
            f"zoompan=z='{zoom_2x_start}+{zoom_step}*in/{total_frames}':"
            f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s={params.width}x{params.height},"
            f"{self._build_fade_vf(params)}"
        )

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
            desc=f"zoompan {params.movement.value}",
            validate_output=True,
        )

        return MotionResult(
            output_path=params.output_path,
            success=ok,
            engine_used=self.name,
            duration=params.duration,
            error=None if ok else "zoompan ffmpeg failed",
        )
