from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError, as_completed
from pathlib import Path

from narrascape.config import (
    ImagePrompts,
    NarrascapeConfig,
    ShotType,
    SupersampleMode,
)
from narrascape.motion import (
    MotionParams,
    MotionResult,
    build_motion_engine,
    compute_zoom_range,
    derive_movement,
    derive_zoom_magnitude,
)
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import run_ffmpeg
from narrascape.utils.safe_io import atomic_write_text, load_json_mapping

logger = logging.getLogger("narrascape.stages.kenburns")


def _render_segment(
    seg_id: int,
    img_ids: list[str],
    timing: list[float] | None,
    durations: dict[str, float],
    prompts: ImagePrompts,
    config: NarrascapeConfig,
    supersample: SupersampleMode,
) -> MotionResult:
    """Worker function for parallel segment rendering."""
    seg_dir = config.pipeline_dir / "video_segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    dur = durations.get(str(seg_id), 30.0)
    seg_video = seg_dir / f"seg_{seg_id:02d}.mp4"

    # Black segment (no images)
    if not img_ids:
        ok = run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={config.encode.width}x{config.encode.height}:d={dur}:r={config.encode.fps}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                str(seg_video),
            ],
            desc=f"black seg {seg_id}",
            validate_output=True,
        )
        return MotionResult(
            output_path=seg_video,
            success=ok,
            engine_used="black",
            duration=dur,
            error=None if ok else "black segment failed",
        )

    # Single image segment
    if len(img_ids) == 1:
        return _render_single_image(
            seg_id, img_ids[0], dur, prompts, config, supersample, seg_video
        )

    # Multi-image segment: render each part, then concat
    return _render_multi_image(seg_id, img_ids, timing, dur, prompts, config, supersample, seg_dir)


def _render_single_image(
    seg_id: int,
    img_id: str,
    dur: float,
    prompts: ImagePrompts,
    config: NarrascapeConfig,
    supersample: SupersampleMode,
    output_path: Path,
) -> MotionResult:
    img_path = config.images_dir / f"{img_id}.png"
    if not img_path.exists():
        return MotionResult(
            output_path=output_path,
            success=False,
            engine_used="none",
            duration=dur,
            error=f"Missing image: {img_id}",
        )

    prompt = prompts.get_prompt(img_id)
    shot_type = prompt.shot_type if prompt else ShotType.MEDIUM
    movement = derive_movement(shot_type, dur, prompt.movement if prompt else None)
    magnitude = derive_zoom_magnitude(movement, shot_type, dur)
    zoom_start, zoom_end = compute_zoom_range(movement, magnitude)
    fade_out = min(2.0, dur * 0.4)

    params = MotionParams(
        image_path=img_path,
        output_path=output_path,
        duration=dur,
        fps=config.encode.fps,
        width=config.encode.width,
        height=config.encode.height,
        movement=movement,
        shot_type=shot_type,
        fade_in=config.visual.fade_in_duration,
        fade_out=fade_out,
        zoom_start=zoom_start,
        zoom_end=zoom_end,
        supersample=supersample,
    )

    engine = build_motion_engine(params)
    return engine.generate(params)


def _render_multi_image(
    seg_id: int,
    img_ids: list[str],
    timing: list[float] | None,
    dur: float,
    prompts: ImagePrompts,
    config: NarrascapeConfig,
    supersample: SupersampleMode,
    seg_dir: Path,
) -> MotionResult:
    seg_video = seg_dir / f"seg_{seg_id:02d}.mp4"

    # Calculate sub-durations
    if timing and len(timing) == len(img_ids):
        sub_durs = [dur * r for r in timing]
    else:
        sub_durs = [dur / len(img_ids)] * len(img_ids)

    parts = []
    for idx, iid in enumerate(img_ids):
        img_path = config.images_dir / f"{iid}.png"
        if not img_path.exists():
            logger.warning(f"[{seg_id}] Missing image: {iid}")
            continue

        part_video = seg_dir / f"seg_{seg_id:02d}_part{idx}.mp4"
        sub_dur = sub_durs[idx]
        prompt = prompts.get_prompt(iid)
        shot_type = prompt.shot_type if prompt else ShotType.MEDIUM
        movement = derive_movement(shot_type, sub_dur, prompt.movement if prompt else None)
        magnitude = derive_zoom_magnitude(movement, shot_type, sub_dur)
        zoom_start, zoom_end = compute_zoom_range(movement, magnitude)
        fade_out = min(1.0, sub_dur * 0.3)
        fade_in = min(config.visual.fade_in_duration, sub_dur * 0.3)

        params = MotionParams(
            image_path=img_path,
            output_path=part_video,
            duration=sub_dur,
            fps=config.encode.fps,
            width=config.encode.width,
            height=config.encode.height,
            movement=movement,
            shot_type=shot_type,
            fade_in=fade_in,
            fade_out=fade_out,
            zoom_start=zoom_start,
            zoom_end=zoom_end,
            supersample=supersample,
        )

        engine = build_motion_engine(params)
        result = engine.generate(params)
        if result.success:
            parts.append(part_video)
        else:
            logger.error(f"[{seg_id}] Part {idx} failed: {result.error}")

    if not parts:
        return MotionResult(
            output_path=seg_video,
            success=False,
            engine_used="none",
            duration=dur,
            error="No parts built successfully",
        )

    # Concat parts with stream copy
    concat_file = seg_dir / f"seg_{seg_id:02d}_concat.txt"
    lines = [f"file '{p.as_posix()}'" for p in parts]
    atomic_write_text(concat_file, "\n".join(lines))

    ok = run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(seg_video)],
        desc=f"concat seg {seg_id}",
        validate_output=True,
    )

    # Cleanup temp parts
    for p in parts:
        p.unlink(missing_ok=True)
    concat_file.unlink(missing_ok=True)

    return MotionResult(
        output_path=seg_video,
        success=ok,
        engine_used="concat",
        duration=dur,
        error=None if ok else "concat failed",
    )


class KenBurnsStage(Stage):
    """Generate Ken Burns motion segments for all script segments."""

    name = "kenburns"
    depends_on = ["generate_images", "generate_tts"]
    outputs = []

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        # Check prerequisites
        if not context.config.script_path.exists():
            return False, f"Script not found: {context.config.script_path}"
        if not context.config.images_dir.exists():
            return False, f"Images directory not found: {context.config.images_dir}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        script = context.script
        visual = config.visual
        supersample = visual.supersample

        # Load image map and prompts
        image_map_path = config.project_dir / "image_map.yaml"
        image_prompts_path = config.project_dir / "image_prompts.yaml"
        timing_path = config.pipeline_dir / "timing.json"

        if not image_map_path.exists():
            return StageResult(self.name, False, message="image_map.yaml not found")
        if not image_prompts_path.exists():
            return StageResult(self.name, False, message="image_prompts.yaml not found")

        from narrascape.config import load_image_map, load_image_prompts

        image_map = load_image_map(image_map_path)
        prompts = load_image_prompts(image_prompts_path)

        # Load durations
        durations: dict[str, float] = {}
        if timing_path.exists():
            durations = {str(k): float(v) for k, v in load_json_mapping(timing_path).items()}
        else:
            logger.warning("timing.json not found, using default 30s per segment")
            for seg in script.segments:
                durations[str(seg.id)] = 30.0

        # Prepare work items
        work_items = []
        for seg in script.segments:
            seg_id = seg.id
            images = image_map.get_images(seg_id)
            timing = image_map.get_timing(seg_id)
            work_items.append((seg_id, images, timing))

        seg_dir = config.pipeline_dir / "video_segments"
        seg_dir.mkdir(parents=True, exist_ok=True)

        if context.dry_run:
            logger.info(f"[dry-run] Would render {len(work_items)} segments")
            for seg_id, images, timing in work_items:
                logger.info(f"  seg {seg_id}: {len(images)} image(s)")
            return StageResult(self.name, True, message=f"dry-run: {len(work_items)} segments")

        # Parallel rendering
        start = time.monotonic()
        results = []
        failed = []

        max_workers = self._max_workers(len(work_items))
        worker_timeout = self._worker_timeout(durations)
        logger.info(f"[kenburns] Rendering with {max_workers} worker(s), timeout={worker_timeout}s")

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _render_segment, seg_id, images, timing, durations, prompts, config, supersample
                ): seg_id
                for seg_id, images, timing in work_items
            }

            try:
                completed = as_completed(futures, timeout=max(worker_timeout * len(futures), 1))
                for future in completed:
                    seg_id = futures[future]
                    try:
                        result = future.result(timeout=worker_timeout)
                        results.append(result)
                        if not result.success:
                            failed.append(seg_id)
                            logger.error(f"[{seg_id}] FAILED: {result.error}")
                        else:
                            logger.info(f"[{seg_id}] OK ({result.engine_used})")
                    except TimeoutError:
                        logger.error(f"[{seg_id}] Timed out after {worker_timeout}s")
                        future.cancel()
                        failed.append(seg_id)
                    except Exception as e:
                        logger.exception(f"[{seg_id}] Exception: {e}")
                        failed.append(seg_id)
            except TimeoutError:
                pending = [seg_id for future, seg_id in futures.items() if not future.done()]
                failed.extend(pending)
                for future in futures:
                    if not future.done():
                        future.cancel()
                logger.error(f"[kenburns] Timed out waiting for segments: {pending}")

        elapsed = time.monotonic() - start
        outputs = [r.output_path for r in results if r.success]

        if failed:
            return StageResult(
                self.name,
                False,
                outputs=outputs,
                message=f"{len(failed)}/{len(work_items)} segments failed: {failed}",
                duration_seconds=elapsed,
            )

        return StageResult(
            self.name,
            True,
            outputs=outputs,
            message=f"All {len(work_items)} segments rendered in {elapsed:.1f}s",
            duration_seconds=elapsed,
        )

    def _max_workers(self, work_item_count: int) -> int:
        raw = os.environ.get("NARRASCAPE_KENBURNS_WORKERS")
        if raw:
            try:
                return max(1, min(int(raw), work_item_count))
            except ValueError:
                logger.warning(f"Invalid NARRASCAPE_KENBURNS_WORKERS={raw!r}, using default")
        return max(1, min(2, work_item_count))

    def _worker_timeout(self, durations: dict[str, float]) -> float:
        raw = os.environ.get("NARRASCAPE_KENBURNS_TIMEOUT")
        if raw:
            try:
                return max(30.0, float(raw))
            except ValueError:
                logger.warning(f"Invalid NARRASCAPE_KENBURNS_TIMEOUT={raw!r}, using default")
        longest = max([float(value) for value in durations.values()] or [30.0])
        return max(120.0, longest * 20.0)
