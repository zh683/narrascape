from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PIL import Image

from narrascape.motion.base import MotionEngine, MotionParams, MotionResult
from narrascape.utils.ffmpeg import find_ffmpeg, validate_video

logger = logging.getLogger("narrascape.motion.pil")


class PILEngine(MotionEngine):
    """
    PIL-based affine transform for 100% sub-pixel accurate zoom.
    Bypasses ffmpeg zoompan Bug #4298 integer truncation entirely.
    Slower than zoompan (~5-10x) but pixel-perfect for hard-edge images.
    """

    @property
    def name(self) -> str:
        return "pil"

    def can_handle(self, params: MotionParams) -> bool:
        return params.movement in (
            "zoom_in", "zoom_slow", "zoom_out",
            "zoom_in_slow", "zoom_out_slow",
            "push_in", "pull_out",
        )

    def generate(self, params: MotionParams) -> MotionResult:
        try:
            img = Image.open(params.image_path).convert("RGB")
        except Exception as e:
            return MotionResult(
                output_path=params.output_path,
                success=False,
                engine_used=self.name,
                duration=params.duration,
                error=f"Cannot open image: {e}",
            )

        w, h = img.size
        total_frames = max(int(round(params.duration * params.fps)), 1)
        W, H = params.width, params.height

        # Build fade filter for ffmpeg
        fade_parts = [f"fade=t=in:st=0:d={params.fade_in}"]
        if params.duration > 3.0:
            fade_out_start = params.duration - params.fade_out
            fade_parts.append(f"fade=t=out:st={fade_out_start:.1f}:d={params.fade_out:.1f}")
        fade_vf = ",".join(fade_parts)

        ffmpeg = find_ffmpeg()
        proc = subprocess.Popen(
            [
                str(ffmpeg), "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{W}x{H}", "-r", str(params.fps),
                "-i", "-",
                "-vf", fade_vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-t", str(params.duration),
                str(params.output_path),
            ],
            stdin=subprocess.PIPE,
        )

        try:
            for i in range(total_frames):
                t = i / total_frames if total_frames > 1 else 0
                zoom = params.zoom_start + (params.zoom_end - params.zoom_start) * t

                crop_w = w / zoom
                crop_h = h / zoom
                crop_x = (w - crop_w) / 2
                crop_y = (h - crop_h) / 2

                scale_x = crop_w / W
                scale_y = crop_h / H
                transform = (scale_x, 0, crop_x, 0, scale_y, crop_y)

                frame = img.transform(
                    (W, H),
                    Image.Transform.AFFINE,
                    transform,
                    resample=Image.Resampling.BILINEAR,
                )

                data = frame.tobytes()
                CHUNK = 1_048_576
                for offset in range(0, len(data), CHUNK):
                    proc.stdin.write(data[offset:offset + CHUNK])
        finally:
            proc.stdin.close()
            proc.wait()

        if proc.returncode != 0:
            return MotionResult(
                output_path=params.output_path,
                success=False,
                engine_used=self.name,
                duration=params.duration,
                error=f"ffmpeg encoding failed (rc={proc.returncode})",
            )

        valid = validate_video(params.output_path)
        return MotionResult(
            output_path=params.output_path,
            success=valid,
            engine_used=self.name,
            duration=params.duration,
            error=None if valid else "output validation failed",
        )
