"""Generate video stage — integrate Volcengine Seedance 2.0 API.

Reads design report and generated images, calls Seedance API via async task workflow,
outputs video clips to assets/videos/.

Correct API workflow (火山方舟):
1. Create task: POST /api/v3/contents/generations/tasks
   - Body: {model, content[], resolution, ratio, duration, watermark, ...}
   - Returns: {id} (task ID)
2. Poll task: GET /api/v3/contents/generations/tasks/{id}
   - Returns: {status, error, content: {video_url, last_frame_url}}

Native workflow: Seedream image -> Seedance video (zero-loss character consistency)
"""

from __future__ import annotations

import base64
import binascii
import logging
import math
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from narrascape.api_keys import APIKeys
from narrascape.prompt_safety import sanitize_prompt_for_provider
from narrascape.providers import (
    record_provider_failure,
    record_provider_success,
    select_provider,
    selection_metadata,
)
from narrascape.providers.runtime import (
    BudgetReservationCoordinator,
    BudgetReservationError,
    ProviderTaskRepository,
)
from narrascape.providers.video_adapters import AgnesVideoAdapter, SeedanceVideoAdapter
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.stages.generate_video_services import (
    VideoGenerationPlanner,
    VideoPromptBuilder,
    VideoPromptQualityReporter,
    VideoReferenceResolver,
)
from narrascape.uploader.image_uploader import ImageUploader
from narrascape.utils.ffmpeg import validate_video
from narrascape.utils.safe_io import (
    atomic_write_json,
    download_to_path,
    load_json_mapping,
    load_yaml_mapping,
)

logger = logging.getLogger("narrascape.stages.generate_video")


class GenerateVideoStage(Stage):
    """Generate video clips from designed shots using Seedance 2.0.

    Inputs:  design report (with ShotDesign.seedance_* fields)
             assets/images/ (generated images for first_frame)
    Outputs: assets/videos/vid_*.mp4
    State:   pipeline/{name}/video_gen_state.json
    """

    name = "generate_video"
    depends_on = ["production_readiness", "animatic", "generate_images"]
    outputs = []

    # 火山方舟正确的视频生成 API 端点
    BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations"
    AGNES_CREATE_URL = "https://apihub.agnes-ai.com/v1/videos"
    AGNES_RESULT_URL = "https://apihub.agnes-ai.com/agnesapi"
    AGNES_CREATE_TIMEOUT = 120
    AGNES_REFERENCE_MAX_EDGE = 768
    AGNES_REFERENCE_JPEG_QUALITY = 82

    # 模型 ID 映射（技术报告中使用的名称 -> 方舟实际模型 ID）
    MODEL_MAP = {
        "jimeng-video-seedance-2.0": "doubao-seedance-2-0-260128",
        "jimeng-video-seedance-2.0-fast": "doubao-seedance-2-0-fast-260128",
        "jimeng-video-seedance-1.5-pro": "doubao-seedance-1-5-pro-260128",
        "jimeng-video-seedance-1.0-pro": "doubao-seedance-1-0-pro-260128",
        "jimeng-video-seedance-1.0-pro-fast": "doubao-seedance-1-0-pro-fast-260128",
    }

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "jimeng-video-seedance-2.0",
        resolution: str = "720p",
        ratio: str = "16:9",
        duration: int = 5,
        sleep_between: float = 3.0,
        poll_interval: float = 5.0,
        max_poll_time: float = 300.0,
        uploader_backend: str = "base64",
        max_poll_errors: int = 3,
        agnes_model: str = "agnes-video-v2.0",
        seedance_adapter: SeedanceVideoAdapter | None = None,
        agnes_adapter: AgnesVideoAdapter | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.agnes_model = agnes_model
        self.resolution = resolution
        self.ratio = ratio
        self.duration = duration
        self.frame_rate = 24
        self.takes = 1
        self.sleep_between = sleep_between
        self.poll_interval = poll_interval
        self.max_poll_time = max_poll_time
        self.max_poll_errors = max(1, max_poll_errors)
        self.uploader = ImageUploader(backend=uploader_backend)
        self._selected_provider = "seedance"
        self.video_planner = VideoGenerationPlanner(
            model=self.model,
            agnes_model=self.agnes_model,
            resolution=self.resolution,
            ratio=self.ratio,
            duration=self.duration,
            frame_rate=self.frame_rate,
            takes=self.takes,
            sleep_between=self.sleep_between,
        )
        self.prompt_builder = VideoPromptBuilder()
        self.prompt_quality_reporter = VideoPromptQualityReporter(self.prompt_builder)
        self.reference_resolver = VideoReferenceResolver(self.uploader)
        self._task_map: dict[str, Any] = {}
        self._persist_task_map: Callable[[], None] | None = None
        self.seedance_adapter = seedance_adapter
        self.agnes_adapter = agnes_adapter

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        config = context.config
        selection = select_provider(config, "video_generation", intent="creative")
        design_path = self._first_existing(
            config.project_dir / "design_report.yaml",
            config.pipeline_dir / "design_report.yaml",
        )
        images_dir = config.images_dir
        if not design_path.exists():
            return False, f"design_report.yaml not found: {design_path}"
        if not images_dir.exists() or not list(images_dir.glob("*.png")):
            return False, f"No images found in {images_dir}. Run generate_images first."
        api_key = self._api_key_for_provider(selection.tool.provider)
        if not api_key:
            required = selection.tool.requires[0] if selection.tool.requires else "API key"
            return False, (
                f"{selection.tool.name} selected but {required} not found. "
                "Set env var or .env file."
            )
        plate_path = config.pipeline_dir / "reference_plates.yaml"
        if not plate_path.exists():
            return False, f"reference_plates.yaml not found: {plate_path}"
        readiness_path = config.pipeline_dir / "production_readiness.yaml"
        if not readiness_path.exists():
            return False, f"production_readiness.yaml not found: {readiness_path}"
        readiness = self._load_yaml(readiness_path)
        if readiness.get("status") != "ready":
            return False, (
                "production_readiness.yaml is not ready: " f"{readiness.get('status', 'missing')}"
            )
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        project_dir = config.project_dir
        videos_dir = project_dir / "assets" / "videos"
        videos_dir.mkdir(parents=True, exist_ok=True)
        pipe_dir = config.pipeline_dir
        pipe_dir.mkdir(parents=True, exist_ok=True)
        images_dir = config.images_dir
        selection = select_provider(config, "video_generation", intent="creative")
        provider_meta = selection_metadata(selection)
        provider_name = selection.tool.provider
        self._selected_provider = provider_name
        self._apply_video_config(config, provider_name)

        # Load design report
        design_path = self._first_existing(
            project_dir / "design_report.yaml",
            pipe_dir / "design_report.yaml",
        )
        design = self._load_design_report(design_path)
        segments = design.get("segments", [])
        if not segments:
            return StageResult(self.name, False, message="No segments in design_report.yaml")
        rework_segment_ids = self._segment_ids_from_queue(pipe_dir / "video_regen_queue.yaml")
        if rework_segment_ids:
            segments = [
                segment
                for segment in segments
                if self._to_int(segment.get("segment_id")) in rework_segment_ids
            ]
            if not segments:
                return StageResult(
                    self.name,
                    False,
                    message="video_regen_queue.yaml has no matching design segments",
                )
        contract_by_segment = self._load_director_contract(pipe_dir / "director_contract.yaml")
        reference_plates = self._load_reference_plates(pipe_dir / "reference_plates.yaml")
        pre_production = self._load_yaml(pipe_dir / "pre_production.yaml")
        quality_report = self._write_prompt_quality_report(
            config,
            segments,
            contract_by_segment,
            provider_name,
        )
        if quality_report["status"] == "blocked":
            quality_path = pipe_dir / "video_prompt_quality.yaml"
            return StageResult(
                self.name,
                False,
                outputs=[quality_path],
                message="video prompt quality gate blocked generation",
                metadata={
                    "status": "blocked",
                    "finding_count": len(quality_report["findings"]),
                    "quality_report": quality_path.as_posix(),
                },
            )

        # Budget check
        from narrascape.utils.budget import BudgetTracker

        budget_tracker = BudgetTracker(config.budget, pipe_dir / "budget_state.json")
        budget_reservations = BudgetReservationCoordinator(budget_tracker)
        take_count = self._takes_per_shot()
        total_jobs = len(segments) * take_count
        est_cost = budget_tracker.get_cost_estimate("video", total_jobs)
        can_spend, budget_msg = budget_tracker.can_spend(est_cost)
        if not can_spend:
            return StageResult(self.name, False, message=budget_msg)
        logger.info(budget_msg)

        # Load state
        state_path = pipe_dir / "video_gen_state.json"
        state = self._load_state(state_path)
        state["provider_selection"] = provider_meta
        state["take_policy"] = {
            "takes_per_shot": take_count,
            "naming": "base_clip" if take_count == 1 else "multi_take",
        }
        atomic_write_json(state_path, state)
        done = set(state.get("done", []))
        # 持久化任务 ID 映射，用于断点续传
        task_map = state.get("task_map", {})
        if not isinstance(task_map, dict):
            task_map = {}
            state["task_map"] = task_map

        def persist_task_map() -> None:
            state["task_map"] = task_map
            atomic_write_json(state_path, state)

        self._task_map = task_map
        self._persist_task_map = persist_task_map

        logger.info(
            f"{selection.tool.name} {self._active_model(provider_name)}: "
            f"{total_jobs} video job(s) to generate"
        )

        ok_count, fail_count = 0, 0
        job_index = 0
        for i, seg in enumerate(segments):
            vid_id = f"vid_{seg['segment_id']:02d}"
            out_names = self._output_names_for_segment(vid_id, take_count)
            state.setdefault("generated_takes", {})[vid_id] = list(out_names)
            cached_names = [
                out_name
                for out_name in out_names
                if out_name in done and (videos_dir / f"{out_name}.mp4").exists()
            ]
            if len(cached_names) == len(out_names):
                logger.info(f"[{i + 1}/{len(segments)}] {vid_id} skip (cached)")
                ok_count += len(out_names)
                job_index += len(out_names)
                continue

            # Build video prompt from cinematic_format or image_prompt
            video_prompt = self._build_video_prompt(
                seg,
                contract_by_segment=contract_by_segment,
                provider=provider_name,
            )

            # Prepare first_frame from generated image
            img_id = f"img_{seg['segment_id']:02d}"
            first_frame = self._resolve_first_frame(seg, images_dir, img_id)
            last_frame = self._resolve_last_frame(seg, images_dir, design)
            contract = contract_by_segment.get(int(seg["segment_id"]), {})
            negative_prompt = self._build_video_negative_prompt(contract, provider_name)
            reference_inputs = self._reference_inputs_for_segment(
                config,
                design,
                pre_production,
                seg,
                contract,
                reference_plates.get(int(seg["segment_id"]), {}),
            )
            uploaded_reference_images = reference_inputs.get("uploaded_reference_images", [])
            reference_images = (
                reference_inputs.get("uploaded_reference_assets", uploaded_reference_images)
                if provider_name == "agnes"
                else uploaded_reference_images
            )

            # Select model per segment
            model = self._segment_model(seg, provider_name)
            resolution = self._segment_resolution(seg, provider_name)

            logger.info(f"[{i + 1}/{len(segments)}] {vid_id}: {video_prompt[:60]}...")
            logger.info(
                f"  model={model}, resolution={resolution}, first_frame={first_frame is not None}, "
                f"references={len(reference_images)}, takes={take_count}"
            )

            for take_number, out_name in enumerate(out_names, start=1):
                job_index += 1
                state.setdefault("reference_inputs", {})[out_name] = reference_inputs["state"]
                atomic_write_json(state_path, state)

                if out_name in done and (videos_dir / f"{out_name}.mp4").exists():
                    logger.info(f"  [{job_index}/{total_jobs}] {out_name} skip (cached)")
                    ok_count += 1
                    continue

                if take_count > 1:
                    logger.info(
                        f"  [{job_index}/{total_jobs}] {out_name} take {take_number}/{take_count}"
                    )

                per_video = budget_tracker.get_cost_estimate("video", 1)
                reservation_id = f"generate_video:{provider_name}:{out_name}"
                existing_task = task_map.get(out_name, {})
                try:
                    budget_reservations.reserve(
                        reservation_id,
                        per_video,
                        task=existing_task if isinstance(existing_task, dict) else {},
                    )
                except BudgetReservationError as exc:
                    return StageResult(self.name, False, message=str(exc))

                result = self._generate_one(
                    video_prompt,
                    out_name,
                    model,
                    resolution,
                    first_frame,
                    last_frame,
                    videos_dir,
                    reference_images,
                    provider=provider_name,
                    negative_prompt=negative_prompt,
                )
                if result:
                    ok_count += 1
                    done.add(out_name)
                    state["done"] = sorted(done)
                    atomic_write_json(state_path, state)
                    try:
                        budget_reservations.commit(reservation_id)
                    except BudgetReservationError as exc:
                        return StageResult(self.name, False, message=str(exc))
                else:
                    fail_count += 1
                if job_index < total_jobs:
                    time.sleep(self._sleep_between_for_provider(provider_name))

        logger.info(f"Done: {ok_count} OK, {fail_count} failed")
        if fail_count == 0:
            record_provider_success(config, selection.tool.name)
        else:
            record_provider_failure(
                config,
                selection.tool.name,
                f"{fail_count}/{len(segments)} video generations failed",
            )
        generated_outputs = [
            videos_dir / f"{out_name}.mp4"
            for seg in segments
            for out_name in self._output_names_for_segment(
                f"vid_{seg['segment_id']:02d}", take_count
            )
            if (videos_dir / f"{out_name}.mp4").exists()
        ]
        return StageResult(
            self.name,
            fail_count == 0,
            outputs=generated_outputs,
            message=f"{ok_count} OK, {fail_count} failed",
            metadata={
                "provider_selection": provider_meta,
                "ok_count": ok_count,
                "fail_count": fail_count,
                "takes_per_shot": take_count,
                "take_count": total_jobs,
                "rework_segment_ids": sorted(rework_segment_ids),
            },
        )

    # ── Internal methods ───────────────────────────

    def _load_state(self, path: Path) -> dict[str, Any]:
        return load_json_mapping(path, default={"done": [], "errors": [], "task_map": {}})

    def _load_design_report(self, path: Path) -> dict[str, Any]:
        return self._load_yaml(path)

    def _json_object(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _to_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return super()._load_yaml(path)

    def _segment_ids_from_queue(self, path: Path) -> set[int]:
        if not path.exists():
            return set()
        try:
            data = load_yaml_mapping(path)
        except Exception:
            return set()
        ids: set[int] = set()
        for action in data.get("actions", []) or []:
            if not isinstance(action, dict):
                continue
            segment_id = self._to_int(action.get("segment_id"))
            if segment_id is not None:
                ids.add(segment_id)
        return ids

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]

    def _resolve_model_id(self, model: str) -> str:
        """Map internal model name to Volcengine Ark model ID."""
        return self.MODEL_MAP.get(model, model)

    def _current_video_planner(self) -> VideoGenerationPlanner:
        self.video_planner.model = self.model
        self.video_planner.agnes_model = self.agnes_model
        self.video_planner.resolution = self.resolution
        self.video_planner.ratio = self.ratio
        self.video_planner.duration = self.duration
        self.video_planner.frame_rate = self.frame_rate
        self.video_planner.takes = self.takes
        self.video_planner.sleep_between = self.sleep_between
        return self.video_planner

    def _sync_video_settings_from_planner(self) -> None:
        self.model = self.video_planner.model
        self.agnes_model = self.video_planner.agnes_model
        self.resolution = self.video_planner.resolution
        self.ratio = self.video_planner.ratio
        self.duration = self.video_planner.duration
        self.frame_rate = self.video_planner.frame_rate
        self.takes = self.video_planner.takes
        self.sleep_between = self.video_planner.sleep_between

    def _current_reference_resolver(self) -> VideoReferenceResolver:
        self.reference_resolver.uploader = self.uploader
        return self.reference_resolver

    def _write_prompt_quality_report(
        self,
        config: Any,
        segments: list[dict[str, Any]],
        contract_by_segment: dict[int, dict[str, Any]],
        provider: str,
    ) -> dict[str, Any]:
        return self.prompt_quality_reporter.write_report(
            config,
            segments,
            contract_by_segment,
            provider,
        )

    def _api_key_for_provider(self, provider: str) -> str | None:
        if self.api_key:
            return self.api_key
        active_provider = provider or self._selected_provider
        if active_provider == "agnes":
            return APIKeys.agnes()
        return APIKeys.ark()

    def _current_seedance_adapter(self) -> SeedanceVideoAdapter:
        if self.seedance_adapter is None:
            self.seedance_adapter = SeedanceVideoAdapter(
                api_key=lambda: self._api_key_for_provider("seedance"),
                base_url=self.BASE_URL,
                poll_interval=self.poll_interval,
                max_poll_time=self.max_poll_time,
                max_poll_errors=self.max_poll_errors,
            )
        return self.seedance_adapter

    def _current_agnes_adapter(self) -> AgnesVideoAdapter:
        if self.agnes_adapter is None:
            self.agnes_adapter = AgnesVideoAdapter(
                api_key=lambda: self._api_key_for_provider("agnes"),
                model=lambda: self.agnes_model,
                create_url=self.AGNES_CREATE_URL,
                result_url=self.AGNES_RESULT_URL,
                create_timeout=self.AGNES_CREATE_TIMEOUT,
                poll_interval=self.poll_interval,
                max_poll_time=self.max_poll_time,
                max_poll_errors=self.max_poll_errors,
            )
        return self.agnes_adapter

    def _apply_video_config(self, config: Any, provider: str) -> None:
        self._current_video_planner().apply_config(config, provider)
        self._sync_video_settings_from_planner()

    def _active_model(self, provider: str) -> str:
        return self._current_video_planner().active_model(provider)

    def _takes_per_shot(self) -> int:
        return self._current_video_planner().takes_per_shot()

    def _output_names_for_segment(self, base_id: str, take_count: int) -> list[str]:
        return self._current_video_planner().output_names_for_segment(base_id, take_count)

    def _sleep_between_for_provider(self, provider: str) -> float:
        return self._current_video_planner().sleep_between_for_provider(provider)

    def _segment_model(self, seg: dict[str, Any], provider: str) -> str:
        return self._current_video_planner().segment_model(seg, provider)

    def _segment_resolution(self, seg: dict[str, Any], provider: str) -> str:
        return self._current_video_planner().segment_resolution(seg, provider)

    def _build_video_prompt(
        self,
        seg: dict[str, Any],
        contract_by_segment: dict[int, dict[str, Any]] | None = None,
        provider: str | None = None,
    ) -> str:
        """Build a video generation prompt from the shot design.

        Uses cinematic_format for camera movement, motion, and scene description.
        Falls back to image_prompt if cinematic_format is empty.
        """
        return self.prompt_builder.build_prompt(
            seg,
            contract_by_segment=contract_by_segment,
            provider=provider,
        )

    def _build_video_negative_prompt(self, contract: dict[str, Any], provider: str) -> str:
        return self.prompt_builder.build_negative_prompt(contract, provider)

    def _load_director_contract(self, path: Path) -> dict[int, dict[str, Any]]:
        if not path.exists():
            return {}
        data = self._load_yaml(path)
        result: dict[int, dict[str, Any]] = {}
        for shot in data.get("shots", []) or []:
            if not isinstance(shot, dict):
                continue
            segment_id = self._to_int(shot.get("segment_id"))
            if segment_id is None:
                continue
            result[segment_id] = shot
        return result

    def _load_reference_plates(self, path: Path) -> dict[int, dict[str, Any]]:
        if not path.exists():
            return {}
        data = self._load_yaml(path)
        result: dict[int, dict[str, Any]] = {}
        for plate in data.get("plates", []) or []:
            if not isinstance(plate, dict):
                continue
            segment_id = self._to_int(plate.get("segment_id"))
            if segment_id is None:
                continue
            result[segment_id] = plate
        return result

    def _reference_inputs_for_segment(
        self,
        config: Any,
        design: dict[str, Any],
        pre_production: dict[str, Any],
        seg: dict[str, Any],
        contract: dict[str, Any],
        reference_plate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._current_reference_resolver().reference_inputs_for_segment(
            config,
            design,
            pre_production,
            seg,
            contract,
            reference_plate,
        )

    def _reference_manifest_for_segment(
        self,
        config: Any,
        design: dict[str, Any],
        pre_production: dict[str, Any],
        seg: dict[str, Any],
        contract: dict[str, Any],
        reference_plate: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._current_reference_resolver().reference_manifest_for_segment(
            config,
            design,
            pre_production,
            seg,
            contract,
            reference_plate,
        )

    def _upload_reference_assets(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._current_reference_resolver().upload_reference_assets(assets)

    def _compact_reference_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return self._current_reference_resolver().compact_reference_asset(asset)

    def _resolve_first_frame(
        self, seg: dict[str, Any], images_dir: Path, img_id: str
    ) -> str | None:
        """Resolve the first frame image for Seedance.

        Priority:
        1. reference_image_url from segment metadata
        2. Generated image from this segment
        3. None (text-only generation)
        """
        return self._current_reference_resolver().resolve_first_frame(seg, images_dir, img_id)

    def _resolve_last_frame(
        self,
        seg: dict[str, Any],
        images_dir: Path,
        design: dict[str, Any] | None = None,
    ) -> str | None:
        """Resolve an explicit ending frame for bookended video generation."""
        return self._current_reference_resolver().resolve_last_frame(seg, images_dir, design)

    # ── Seedance API Workflow ───────────────────────

    def _last_frame_chains(
        self,
        seg: dict[str, Any],
        design: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self._current_reference_resolver().last_frame_chains(seg, design)

    def _is_last_frame_chain(self, chain: dict[str, Any]) -> bool:
        return self._current_reference_resolver().is_last_frame_chain(chain)

    def _reference_chain_values(self, chain: dict[str, Any]) -> list[str]:
        return self._current_reference_resolver().reference_chain_values(chain)

    def _resolve_frame_reference(self, value: str, images_dir: Path) -> str | None:
        return self._current_reference_resolver().resolve_frame_reference(value, images_dir)

    def _generated_image_for_chain(self, chain: dict[str, Any], images_dir: Path) -> str | None:
        return self._current_reference_resolver().generated_image_for_chain(chain, images_dir)

    def _create_task(
        self,
        prompt: str,
        model: str,
        resolution: str,
        first_frame: str | None,
        last_frame: str | None,
        reference_images: list[str] | None = None,
    ) -> str | None:
        """Create a video generation task. Returns task ID or None on failure.

        Three mutually exclusive modes (per official docs):
        1. first_frame only: 1 image, role=first_frame or omitted
        2. first_frame + last_frame: 2 images, roles required
        3. multi-modal reference: 1-9 images, role=reference_image each
        """
        content: list[dict[str, Any]] = []
        reference_images = reference_images or []

        # Determine mode - modes are mutually exclusive per official docs
        # Priority: bookend > multi-modal > first_frame > text-only
        has_first = bool(first_frame)
        has_last = bool(last_frame)
        has_refs = len(reference_images) > 0

        if has_first and has_last:
            # Mode 2: First + last frame (bookend mode) - takes priority
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": first_frame},
                    "role": "first_frame",
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": last_frame},
                    "role": "last_frame",
                }
            )
        elif has_refs:
            # Mode 3: Multi-modal reference (1-9 images)
            for ref_url in reference_images[:9]:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": ref_url},
                        "role": "reference_image",
                    }
                )
            # If first_frame is also provided and not already in refs, add it
            if has_first and first_frame not in reference_images:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": first_frame},
                        "role": "reference_image",
                    }
                )
        elif has_first:
            # Mode 1: First frame only
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": first_frame},
                    "role": "first_frame",
                }
            )
        else:
            # Text-only generation (no reference images)
            pass

        # Text prompt (required, must be present)
        content.append(
            {
                "type": "text",
                "text": prompt,
            }
        )

        model_id = self._resolve_model_id(model)

        payload = {
            "model": model_id,
            "content": content,
            "resolution": resolution,
            "ratio": self.ratio,
            "duration": self.duration,
            "watermark": False,
        }

        # Seedance 2.0 支持 return_last_frame，可以获取最后一帧用于后续衔接
        if last_frame:
            payload["return_last_frame"] = True

        return self._current_seedance_adapter().create_task(payload)

    def _poll_task(self, task_id: str) -> str | None:
        """Poll task until completion. Returns video URL or None."""
        return self._current_seedance_adapter().poll(task_id)

    def _create_agnes_task(
        self,
        prompt: str,
        model: str,
        resolution: str,
        first_frame: str | None,
        last_frame: str | None,
        reference_images: list[str] | None = None,
        negative_prompt: str = "",
    ) -> tuple[str | None, str | None]:
        payload = self._build_agnes_payload(
            prompt=prompt,
            model=model,
            resolution=resolution,
            first_frame=first_frame,
            last_frame=last_frame,
            reference_images=reference_images or [],
            negative_prompt=negative_prompt,
        )
        return self._current_agnes_adapter().create_task(payload)

    def _build_agnes_payload(
        self,
        *,
        prompt: str,
        model: str,
        resolution: str,
        first_frame: str | None,
        last_frame: str | None,
        reference_images: list[Any],
        negative_prompt: str = "",
    ) -> dict[str, Any]:
        width, height = self._agnes_dimensions(resolution)
        safe_prompt = sanitize_prompt_for_provider("agnes", prompt)
        payload: dict[str, Any] = {
            "model": model if model.startswith("agnes-") else self.agnes_model,
            "prompt": safe_prompt,
            "height": height,
            "width": width,
            "num_frames": self._agnes_num_frames(self.duration, self.frame_rate),
            "frame_rate": self.frame_rate,
        }
        safe_negative_prompt = sanitize_prompt_for_provider(
            "agnes",
            negative_prompt or self._extract_negative_prompt(prompt),
            append_safety_suffix=False,
        )
        if safe_negative_prompt:
            payload["negative_prompt"] = safe_negative_prompt

        refs = [
            self._agnes_image_value(ref)
            for ref in self._ordered_reference_images(
                first_frame,
                last_frame,
                reference_images,
                provider="agnes",
            )
        ]
        if last_frame and len(refs) >= 2:
            payload["extra_body"] = {"image": refs, "mode": "keyframes"}
        elif len(refs) == 1:
            payload["image"] = refs[0]
        elif len(refs) > 1:
            payload["extra_body"] = {"image": refs}
        return payload

    def _agnes_image_value(self, value: str) -> str:
        if value.startswith("data:") and "," in value:
            return self._compact_agnes_data_uri(value)
        return value

    def _compact_agnes_data_uri(self, value: str) -> str:
        raw_b64 = value.split(",", 1)[1]
        try:
            raw = base64.b64decode(raw_b64, validate=True)
            with Image.open(BytesIO(raw)) as image:
                image = image.convert("RGB")
                image.thumbnail(
                    (self.AGNES_REFERENCE_MAX_EDGE, self.AGNES_REFERENCE_MAX_EDGE),
                    Image.Resampling.LANCZOS,
                )
                output = BytesIO()
                image.save(
                    output,
                    format="JPEG",
                    quality=self.AGNES_REFERENCE_JPEG_QUALITY,
                    optimize=True,
                )
        except (binascii.Error, OSError, UnidentifiedImageError, ValueError):
            return raw_b64
        compact_b64 = base64.b64encode(output.getvalue()).decode("ascii")
        return compact_b64 if len(compact_b64) < len(raw_b64) else raw_b64

    def _ordered_reference_images(
        self,
        first_frame: str | None,
        last_frame: str | None,
        reference_images: list[Any],
        provider: str = "seedance",
    ) -> list[str]:
        if provider == "agnes":
            refs = self._ordered_agnes_reference_images(first_frame, reference_images)
            if last_frame:
                return self._dedupe_refs([first_frame, last_frame])
            return refs
        values = [
            self._reference_url(item) for item in [first_frame, *reference_images[:8], last_frame]
        ]
        return self._dedupe_refs(values)[:9]

    def _ordered_agnes_reference_images(
        self,
        first_frame: str | None,
        reference_images: list[Any],
    ) -> list[str]:
        character_refs = []
        scene_refs = []
        general_refs = []
        for item in reference_images:
            url = self._reference_url(item)
            if not url:
                continue
            role = self._reference_role(item)
            if role == "character":
                character_refs.append(url)
            elif role == "scene":
                scene_refs.append(url)
            elif role != "style":
                general_refs.append(url)
        return self._dedupe_refs(
            [first_frame, *character_refs[:1], *scene_refs[:1], *general_refs[:1]]
        )[:3]

    def _reference_url(self, item: Any) -> str | None:
        if isinstance(item, dict):
            value = item.get("url") or item.get("path")
        else:
            value = item
        return str(value) if value else None

    def _reference_role(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("role") or "reference")
        return "reference"

    def _dedupe_refs(self, values: list[str | None]) -> list[str]:
        refs: list[str] = []
        for value in values:
            if value and value not in refs:
                refs.append(value)
        return refs

    def _agnes_dimensions(self, resolution: str) -> tuple[int, int]:
        if "x" in resolution:
            try:
                width, height = [int(part) for part in resolution.lower().split("x", 1)]
                return width, height
            except ValueError:
                pass
        landscape = self.ratio != "9:16"
        table = {
            "480p": (854, 480) if landscape else (480, 854),
            "720p": (1280, 720) if landscape else (720, 1280),
            "1080p": (1920, 1080) if landscape else (1080, 1920),
        }
        return table.get(resolution.lower(), (1152, 768))

    def _agnes_num_frames(self, duration: int | float, frame_rate: int | float) -> int:
        raw = max(1, int(math.ceil(float(duration) * float(frame_rate))))
        frames = min(raw, 441)
        n = max(10, math.ceil((frames - 1) / 8))
        return min(441, n * 8 + 1)

    def _extract_negative_prompt(self, prompt: str) -> str:
        return ""

    def _poll_agnes_task(
        self, task_id: str | None = None, video_id: str | None = None
    ) -> str | None:
        return self._current_agnes_adapter().poll(task_id=task_id, video_id=video_id)

    def _extract_agnes_video_url(self, response: dict[str, Any]) -> str | None:
        video_url = (
            response.get("remixed_from_video_id")
            or response.get("video_url")
            or response.get("url")
        )
        if video_url:
            return str(video_url)
        data = response.get("data")
        if isinstance(data, dict):
            return data.get("video_url") or data.get("url")
        return None

    def _generate_one(
        self,
        prompt: str,
        out_name: str,
        model: str,
        resolution: str,
        first_frame: str | None,
        last_frame: str | None,
        videos_dir: Path,
        reference_images: list[str] | None = None,
        provider: str = "seedance",
        negative_prompt: str = "",
        task_map: dict[str, Any] | None = None,
        persist_task_map: Callable[[], None] | None = None,
    ) -> bool:
        out_mp4 = videos_dir / f"{out_name}.mp4"
        if out_mp4.exists():
            return True

        task_map = task_map if task_map is not None else self._task_map
        persist_task_map = (
            persist_task_map if persist_task_map is not None else self._persist_task_map
        )
        task_repository = ProviderTaskRepository(task_map, persist_task_map)
        task_entry = task_repository.get(out_name, provider=provider)
        if (
            task_entry.get("status") == "submitting"
            and not task_entry.get("task_id")
            and not task_entry.get("video_id")
        ):
            logger.error(
                f"Provider submission for {out_name} has an unknown outcome; "
                "inspect the provider and video_gen_state.json before retrying"
            )
            return False

        if provider == "agnes":
            task_id = task_entry.get("task_id")
            video_id = task_entry.get("video_id")
            if not task_id and not video_id:
                task_repository.mark_submitting(out_name, provider)
                task_id, video_id = self._create_agnes_task(
                    prompt,
                    model,
                    resolution,
                    first_frame,
                    last_frame,
                    reference_images=reference_images,
                    negative_prompt=negative_prompt,
                )
            if not task_id and not video_id:
                return False
            task_repository.mark_submitted(out_name, provider, task_id=task_id, video_id=video_id)
            video_url = self._poll_agnes_task(task_id=task_id, video_id=video_id)
        else:
            task_id = task_entry.get("task_id")
            if not task_id:
                task_repository.mark_submitting(out_name, provider)
                task_id = self._create_task(
                    prompt,
                    model,
                    resolution,
                    first_frame,
                    last_frame,
                    reference_images=reference_images,
                )
            if not task_id:
                return False
            task_repository.mark_submitted(out_name, provider, task_id=task_id)
            video_url = self._poll_task(task_id)
        if not video_url:
            task_repository.mark_status(out_name, "polling_failed")
            return False

        try:
            download_to_path(
                video_url,
                out_mp4,
                timeout=300,
                min_bytes=1024,
                min_free_mb=128.0,
                expected_content_prefixes=("video/", "application/octet-stream"),
            )
            if not validate_video(out_mp4):
                out_mp4.unlink(missing_ok=True)
                raise RuntimeError("downloaded video failed ffprobe validation")
        except Exception as e:
            logger.error(f"Download failed: {e}")
            task_repository.mark_status(out_name, "download_failed")
            return False

        task_repository.mark_status(out_name, "completed", output=out_mp4.as_posix())
        logger.info(f"OK {out_mp4.stat().st_size / 1024 / 1024:.1f}MB")
        return True
