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
import json
import logging
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from narrascape.api_keys import APIKeys
from narrascape.catalog import design_report_candidates
from narrascape.contracts import DirectorContract
from narrascape.prompt_safety import sanitize_prompt_for_provider, write_sanitize_audit
from narrascape.providers import (
    record_provider_failure,
    record_provider_success,
    select_provider,
    selection_metadata,
)
from narrascape.providers.health import health_store_for_project
from narrascape.providers.http_client import ProviderHttpClient, retry_after_hint
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.stages.generate_video_services import (
    VideoGenerationPlanner,
    VideoPromptBuilder,
    VideoPromptQualityReporter,
    VideoReferenceResolver,
    VideoTaskLedger,
    video_task_prompt_hash,
)
from narrascape.uploader.image_uploader import ImageUploader
from narrascape.utils.budget import BudgetTracker
from narrascape.utils.ffmpeg import validate_video
from narrascape.utils.fingerprint import hash_reference, request_fingerprint
from narrascape.utils.retry import is_retryable_provider_error
from narrascape.utils.safe_io import (
    atomic_write_json,
    download_to_path,
    load_json_mapping,
    load_yaml_mapping,
)

logger = logging.getLogger("narrascape.stages.generate_video")


def _is_explicit_rate_limit(exc: Exception) -> bool:
    return isinstance(exc, urllib.error.HTTPError) and exc.code == 429


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
        self._task_ledger: VideoTaskLedger | None = None
        self._per_task_cost_estimate: float | None = None
        self._budget_tracker: BudgetTracker | None = None
        self._http = ProviderHttpClient("video_generation")
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

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        config = context.config
        selection = select_provider(config, "video_generation", intent="creative")
        design_path = self._first_existing(*design_report_candidates(config))
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
        rpm = config.video.requests_per_minute
        self._http.configure(
            rate_per_second=rpm / 60.0 if rpm > 0 else 0.0,
            health_store=health_store_for_project(config.project_dir),
            health_key=selection.tool.name,
        )

        # Load design report
        design_path = self._first_existing(*design_report_candidates(config))
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
        contract_path = pipe_dir / "director_contract.yaml"
        contract_by_segment = self._load_director_contract(contract_path)
        contract_shots = self._load_director_contract_shots(contract_path)
        reference_plate_path = pipe_dir / "reference_plates.yaml"
        reference_plates = self._load_reference_plates(reference_plate_path)
        reference_plates_by_shot = self._load_reference_plates_by_shot(reference_plate_path)
        pre_production = self._load_yaml(pipe_dir / "pre_production.yaml")
        segments = self._generation_units(
            segments,
            contract_shots,
            reference_plates_by_shot,
            coverage_mode=str(config.video.coverage_mode),
            project_style=str(config.images.style or ""),
        )
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
        budget_tracker = BudgetTracker(config.budget, pipe_dir / "budget_state.json")
        self._budget_tracker = budget_tracker
        take_count = self._takes_per_shot()
        total_jobs = len(segments) * take_count
        est_cost = budget_tracker.get_cost_estimate("video", total_jobs)
        can_spend, budget_msg = budget_tracker.can_spend(est_cost)
        if not can_spend:
            return StageResult(self.name, False, message=budget_msg)
        logger.info(budget_msg)
        self._per_task_cost_estimate = budget_tracker.get_cost_estimate("video", 1)

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
        # 付费任务台账：任务创建即落盘，崩溃/超时后重跑可断点续轮询
        self._task_ledger = VideoTaskLedger(pipe_dir / "video_tasks.json")

        logger.info(
            f"{selection.tool.name} {self._active_model(provider_name)}: "
            f"{total_jobs} video job(s) to generate"
        )

        max_concurrency = max(1, min(8, int(getattr(config.video, "max_concurrency", 1))))
        if max_concurrency > 1:
            return self._run_pipelined(
                config=config,
                state=state,
                state_path=state_path,
                done=done,
                segments=segments,
                design=design,
                images_dir=images_dir,
                videos_dir=videos_dir,
                provider_name=provider_name,
                selection=selection,
                provider_meta=provider_meta,
                budget_tracker=budget_tracker,
                take_count=take_count,
                total_jobs=total_jobs,
                rework_segment_ids=rework_segment_ids,
                max_concurrency=max_concurrency,
                contract_by_segment=contract_by_segment,
                reference_plates=reference_plates,
                pre_production=pre_production,
            )

        ok_count, fail_count = 0, 0
        job_index = 0
        for i, seg in enumerate(segments):
            vid_id = self._video_id_for_unit(seg)
            out_names = self._output_names_for_segment(vid_id, take_count)
            state.setdefault("generated_takes", {})[vid_id] = list(out_names)

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
            contract = self._contract_for_unit(seg, contract_by_segment)
            negative_prompt = self._build_video_negative_prompt(contract, provider_name)
            reference_inputs = self._reference_inputs_for_segment(
                config,
                design,
                pre_production,
                seg,
                contract,
                self._reference_plate_for_unit(seg, reference_plates),
            )
            uploaded_reference_images = reference_inputs.get("uploaded_reference_images", [])
            reference_images = (
                reference_inputs.get("uploaded_reference_assets", uploaded_reference_images)
                if provider_name == "agnes"
                else uploaded_reference_images
            )
            if config.video.storyboard_conditioning == "auto":
                first_frame, reference_images = self._storyboard_conditioned_inputs(
                    config, contract, first_frame, reference_inputs, provider_name
                )

            # Select model per segment
            model = self._segment_model(seg, provider_name)
            resolution = self._segment_resolution(seg, provider_name)

            # 请求级指纹：文件存在且台账指纹匹配才允许跳过付费生成
            segment_fingerprint = self._video_request_fingerprint(
                provider=provider_name,
                model=model,
                resolution=resolution,
                prompt=video_prompt,
                negative_prompt=negative_prompt,
                first_frame=first_frame,
                last_frame=last_frame,
                reference_images=reference_images,
            )

            cached_names = [
                out_name
                for out_name in out_names
                if out_name in done
                and (videos_dir / f"{out_name}.mp4").exists()
                and self._ledger_fingerprint_matches(out_name, segment_fingerprint)
            ]
            if len(cached_names) == len(out_names):
                logger.info(f"[{i + 1}/{len(segments)}] {vid_id} skip (cached, fingerprint match)")
                ok_count += len(out_names)
                job_index += len(out_names)
                continue

            logger.info(f"[{i + 1}/{len(segments)}] {vid_id}: {video_prompt[:60]}...")
            logger.info(
                f"  model={model}, resolution={resolution}, first_frame={first_frame is not None}, "
                f"references={len(reference_images)}, takes={take_count}"
            )

            for take_number, out_name in enumerate(out_names, start=1):
                job_index += 1
                state.setdefault("reference_inputs", {})[out_name] = reference_inputs["state"]
                atomic_write_json(state_path, state)

                if (
                    out_name in done
                    and (videos_dir / f"{out_name}.mp4").exists()
                    and self._ledger_fingerprint_matches(out_name, segment_fingerprint)
                ):
                    logger.info(f"  [{job_index}/{total_jobs}] {out_name} skip (cached)")
                    ok_count += 1
                    continue

                if take_count > 1:
                    logger.info(
                        f"  [{job_index}/{total_jobs}] {out_name} take {take_number}/{take_count}"
                    )

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
                    per_video = budget_tracker.get_cost_estimate("video", 1)
                    spend_ok, spend_msg = budget_tracker.try_spend(
                        per_video,
                        kind="video",
                        stage="generate_video",
                        provider=provider_name,
                        detail=out_name,
                    )
                    if not spend_ok:
                        return StageResult(self.name, False, message=spend_msg)
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
        write_sanitize_audit(config.pipeline_dir, self.name)
        return StageResult(
            self.name,
            fail_count == 0,
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
        return load_json_mapping(path, default={"done": [], "errors": []})

    def _load_design_report(self, path: Path) -> dict[str, Any]:
        return load_yaml_mapping(path)

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
        return load_yaml_mapping(path)

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

    def _apply_video_config(self, config: Any, provider: str) -> None:
        self._current_video_planner().apply_config(config, provider)
        self._sync_video_settings_from_planner()
        video_cfg = getattr(config, "video", None)
        configured_poll_time = getattr(video_cfg, "max_poll_time", None) if video_cfg else None
        if configured_poll_time:
            self.max_poll_time = float(configured_poll_time)

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
        data = load_yaml_mapping(path)
        self._warn_on_contract_drift(data)
        result: dict[int, dict[str, Any]] = {}
        for shot in data.get("shots", []) or []:
            if not isinstance(shot, dict):
                continue
            segment_id = self._to_int(shot.get("segment_id"))
            if segment_id is None:
                continue
            current = result.get(segment_id)
            if current is None or int(shot.get("shot_order") or 1) < int(
                current.get("shot_order") or 1
            ):
                result[segment_id] = shot
        return result

    def _load_director_contract_shots(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        data = load_yaml_mapping(path)
        shots = [dict(shot) for shot in data.get("shots", []) or [] if isinstance(shot, dict)]
        shots.sort(
            key=lambda shot: (
                self._to_int(shot.get("segment_id")) or 0,
                self._to_int(shot.get("shot_order")) or 1,
            )
        )
        return shots

    def _warn_on_contract_drift(self, data: dict[str, Any]) -> None:
        """Detect contract schema drift at read time without changing behavior.

        Downstream reference resolution is deep dict plumbing; the typed model
        is used here as a drift detector (warning only) rather than re-typing
        the whole consumption chain.
        """
        if not data:
            return
        try:
            DirectorContract.model_validate(data)
        except ValidationError as exc:
            logger.warning(
                f"director_contract.yaml schema drift detected "
                f"(read continues with legacy access): {exc}"
            )

    def _load_reference_plates(self, path: Path) -> dict[int, dict[str, Any]]:
        if not path.exists():
            return {}
        data = load_yaml_mapping(path)
        result: dict[int, dict[str, Any]] = {}
        for plate in data.get("plates", []) or []:
            if not isinstance(plate, dict):
                continue
            segment_id = self._to_int(plate.get("segment_id"))
            if segment_id is None:
                continue
            current = result.get(segment_id)
            if current is None or int(plate.get("shot_order") or 1) < int(
                current.get("shot_order") or 1
            ):
                result[segment_id] = plate
        return result

    def _load_reference_plates_by_shot(self, path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        data = load_yaml_mapping(path)
        return {
            str(plate["shot_id"]): plate
            for plate in data.get("plates", []) or []
            if isinstance(plate, dict) and plate.get("shot_id")
        }

    def _generation_units(
        self,
        segments: list[dict[str, Any]],
        contract_shots: list[dict[str, Any]],
        reference_plates_by_shot: dict[str, dict[str, Any]],
        *,
        coverage_mode: str,
        project_style: str,
    ) -> list[dict[str, Any]]:
        shots_by_segment: dict[int, list[dict[str, Any]]] = {}
        for shot in contract_shots:
            segment_id = self._to_int(shot.get("segment_id"))
            if segment_id is not None:
                shots_by_segment.setdefault(segment_id, []).append(shot)

        units: list[dict[str, Any]] = []
        for segment in segments:
            segment_id = self._to_int(segment.get("segment_id"))
            if segment_id is None:
                continue
            shots = shots_by_segment.get(segment_id, [])
            selected_shots = shots if coverage_mode == "director" else shots[:1]
            if not selected_shots:
                selected_shots = [{}]
            for shot in selected_shots:
                unit = dict(segment)
                unit["_project_style"] = project_style
                unit["_coverage_expanded"] = coverage_mode == "director"
                if shot:
                    unit["_director_contract"] = shot
                    unit["shot_id"] = str(shot.get("shot_id") or "")
                    unit["shot_order"] = int(shot.get("shot_order") or 1)
                    unit["coverage_role"] = str(shot.get("coverage_role") or "primary")
                    plate = reference_plates_by_shot.get(unit["shot_id"])
                    if plate:
                        unit["_reference_plate"] = plate
                units.append(unit)
        return units

    def _video_id_for_unit(self, unit: dict[str, Any]) -> str:
        segment_id = int(unit["segment_id"])
        if unit.get("_coverage_expanded"):
            return f"vid_{segment_id:02d}_shot_{int(unit.get('shot_order') or 1):02d}"
        return f"vid_{segment_id:02d}"

    def _contract_for_unit(
        self,
        unit: dict[str, Any],
        contract_by_segment: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        contract = unit.get("_director_contract")
        if isinstance(contract, dict):
            return contract
        return contract_by_segment.get(int(unit["segment_id"]), {})

    def _reference_plate_for_unit(
        self,
        unit: dict[str, Any],
        reference_plates: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        plate = unit.get("_reference_plate")
        if isinstance(plate, dict):
            return plate
        return reference_plates.get(int(unit["segment_id"]), {})

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

    def _storyboard_conditioned_inputs(
        self,
        config: Any,
        contract: dict[str, Any],
        first_frame: str | None,
        reference_inputs: dict[str, Any],
        provider_name: str,
    ) -> tuple[str | None, list[Any]]:
        """Apply opt-in storyboard conditioning (video.storyboard_conditioning == "auto").

        Priority decision: a physical storyboard panel — an explicit,
        human-reviewable narrative keyframe bound by the director contract —
        outranks the derived generated still as ``first_frame``; storyboard-bound
        reference images lead the reference list ahead of the auto-derived
        style/character/scene refs. Missing panels or unresolvable ids fall
        back to the pre-existing inputs and never block generation.
        """
        resolver = self._current_reference_resolver()
        assets = [
            dict(asset) for asset in reference_inputs.get("uploaded_reference_assets", []) or []
        ]
        uploaded_reference_images = list(
            reference_inputs.get("uploaded_reference_images", []) or []
        )

        conditioned_first = first_frame
        panel_path = resolver.find_storyboard_panel(config.project_dir, contract)
        if panel_path is not None:
            conditioned_first = str(resolver.uploader.upload(panel_path))
            logger.info(f"  storyboard panel -> first_frame: {panel_path.name}")

        assets = resolver.prioritize_storyboard_references(assets, contract)

        binding = contract.get("storyboard_binding", {}) if isinstance(contract, dict) else {}
        state = reference_inputs.get("state")
        if isinstance(state, dict):
            state["storyboard_conditioning"] = {
                "panel": panel_path.name if panel_path else None,
                "panel_applied": panel_path is not None,
                "storyboard_reference_ids": [
                    str(value) for value in binding.get("reference_image_ids", []) or []
                ],
            }

        if provider_name == "agnes":
            return conditioned_first, assets or uploaded_reference_images
        urls = [str(asset["url"]) for asset in assets if asset.get("url")]
        return conditioned_first, urls or uploaded_reference_images

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

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        create_url = f"{self.BASE_URL}/tasks"
        api_key = self._api_key_for_provider("seedance")
        if not api_key:
            logger.error("Seedance video provider selected but API key is not configured")
            return None
        req = urllib.request.Request(create_url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")

        try:
            r = self._http.execute_request(
                req,
                timeout=60,
                max_retries=3,
                base_delay=2.0,
                retryable_if=_is_explicit_rate_limit,
            )
        except Exception as e:
            logger.error(f"Task creation failed: {e}")
            return None

        task_id = r.get("id")
        if not task_id:
            logger.error(f"No task ID in response: {json.dumps(r, ensure_ascii=False)[:200]}")
            return None

        logger.info(f"  Task created: {task_id}")
        return str(task_id)

    def _poll_task(self, task_id: str) -> str | None:
        """Poll task until completion. Returns video URL or None."""
        poll_url = f"{self.BASE_URL}/tasks/{task_id}"
        start_time = time.time()
        attempts = 0
        consecutive_errors = 0

        while time.time() - start_time < self.max_poll_time:
            attempts += 1
            api_key = self._api_key_for_provider("seedance")
            if not api_key:
                logger.error("Seedance video provider selected but API key is not configured")
                return None
            req = urllib.request.Request(poll_url, method="GET")
            req.add_header("Authorization", f"Bearer {api_key}")

            try:
                r = self._http.get_json(
                    poll_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30
                )
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    # Rate limits use the total polling deadline, not the error budget.
                    hint = retry_after_hint(e)
                    wait = max(self.poll_interval, hint) if hint is not None else self.poll_interval
                    logger.warning(
                        f"  Poll rate-limited (429, attempt {attempts}); "
                        f"waiting {wait:.1f}s (not counted as error)"
                    )
                    time.sleep(wait)
                    continue
                if not is_retryable_provider_error(e):
                    logger.error(f"  Polling aborted after permanent HTTP error {e.code}")
                    return None
                consecutive_errors += 1
                logger.warning(f"  Poll error (attempt {attempts}): {e}")
                if consecutive_errors >= self.max_poll_errors:
                    logger.error(f"  Polling aborted after {consecutive_errors} consecutive errors")
                    return None
                time.sleep(self.poll_interval)
                continue
            except Exception as e:
                consecutive_errors += 1
                logger.warning(f"  Poll error (attempt {attempts}): {e}")
                if consecutive_errors >= self.max_poll_errors:
                    logger.error(f"  Polling aborted after {consecutive_errors} consecutive errors")
                    return None
                time.sleep(self.poll_interval)
                continue
            consecutive_errors = 0

            status = r.get("status", "unknown")
            logger.info(f"  Poll {attempts}: status={status}")

            if status == "succeeded":
                # 提取视频 URL
                content = r.get("content", {})
                if isinstance(content, dict):
                    video_url = content.get("video_url")
                    if video_url:
                        return str(video_url)
                # 兼容其他可能的位置
                video_url = r.get("video_url") or r.get("url")
                if video_url:
                    return str(video_url)
                logger.error(
                    f"  No video_url in succeeded response: {json.dumps(r, ensure_ascii=False)[:200]}"
                )
                return None

            elif status in ("failed", "expired"):
                error = r.get("error", "unknown error")
                logger.error(f"  Task {status}: {error}")
                return None

            elif status in ("queued", "running"):
                time.sleep(self.poll_interval)
                continue

            else:
                logger.warning(f"  Unknown status: {status}")
                time.sleep(self.poll_interval)

        logger.error(f"  Polling timeout after {self.max_poll_time}s")
        return None

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
        api_key = self._api_key_for_provider("agnes")
        if not api_key:
            logger.error("Agnes video provider selected but API key is not configured")
            return None, None

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.AGNES_CREATE_URL, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")

        try:
            response = self._http.execute_request(
                req,
                timeout=self.AGNES_CREATE_TIMEOUT,
                max_retries=4,
                base_delay=65.0,
                max_delay=75.0,
                retryable_if=_is_explicit_rate_limit,
                on_retry=self._log_agnes_retry,
            )
        except Exception as exc:
            logger.error(f"Agnes task creation failed: {exc}")
            return None, None

        task_id = response.get("task_id") or response.get("id")
        video_id = response.get("video_id")
        if not task_id and not video_id:
            logger.error(
                f"No Agnes task_id/video_id in response: {json.dumps(response, ensure_ascii=False)[:200]}"
            )
            return None, None
        logger.info(f"  Agnes task created: task_id={task_id}, video_id={video_id}")
        return task_id, video_id

    def _log_agnes_retry(self, exc: Exception, attempt: int, delay: float) -> None:
        retry_delay = delay
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
            retry_delay = max(delay, self._retry_after_from_http_error(exc))
        logger.warning(f"Agnes retry {attempt} after {retry_delay:.1f}s: {exc}")

    def _retry_after_from_http_error(self, exc: urllib.error.HTTPError) -> float:
        hint = retry_after_hint(exc, default_for_429=65.0)
        return hint if hint is not None else 65.0

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
        api_key = self._api_key_for_provider("agnes")
        if not api_key:
            logger.error("Agnes video provider selected but API key is not configured")
            return None
        start_time = time.time()
        attempts = 0
        consecutive_errors = 0
        while time.time() - start_time < self.max_poll_time:
            attempts += 1
            if video_id:
                query = urllib.parse.urlencode(
                    {"video_id": video_id, "model_name": self.agnes_model}
                )
                poll_url = f"{self.AGNES_RESULT_URL}?{query}"
            elif task_id:
                poll_url = f"{self.AGNES_CREATE_URL}/{task_id}"
            else:
                return None

            try:
                response = self._http.get_json(
                    poll_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30
                )
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    # Rate limits use the total polling deadline, not the error budget.
                    wait = max(self.poll_interval, self._retry_after_from_http_error(exc))
                    logger.warning(
                        f"  Agnes poll rate-limited (429, attempt {attempts}); "
                        f"waiting {wait:.1f}s (not counted as error)"
                    )
                    time.sleep(wait)
                    continue
                consecutive_errors += 1
                logger.warning(f"  Agnes poll error (attempt {attempts}): {exc}")
                if consecutive_errors >= self.max_poll_errors:
                    logger.error(
                        f"  Agnes polling aborted after {consecutive_errors} consecutive errors"
                    )
                    return None
                time.sleep(self.poll_interval)
                continue
            except Exception as exc:
                consecutive_errors += 1
                logger.warning(f"  Agnes poll error (attempt {attempts}): {exc}")
                if consecutive_errors >= self.max_poll_errors:
                    logger.error(
                        f"  Agnes polling aborted after {consecutive_errors} consecutive errors"
                    )
                    return None
                time.sleep(self.poll_interval)
                continue
            consecutive_errors = 0

            status = str(response.get("status", "unknown")).lower()
            logger.info(f"  Agnes poll {attempts}: status={status}")
            if status in {"completed", "succeeded", "success"}:
                video_url = self._extract_agnes_video_url(response)
                if video_url:
                    return video_url
                logger.error(
                    f"  No Agnes video URL in completed response: {json.dumps(response, ensure_ascii=False)[:200]}"
                )
                return None
            if status in {"failed", "error", "expired"}:
                logger.error(f"  Agnes task {status}: {response.get('error', 'unknown error')}")
                return None
            time.sleep(self.poll_interval)

        logger.error(f"  Agnes polling timeout after {self.max_poll_time}s")
        return None

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

    def _query_task_status_detailed(self, task_id: str) -> tuple[str, str | None, float | None]:
        """Single-shot Seedance status query for the unified poll loop.

        Returns ``(status, video_url, retry_after_hint)``. Status is one of:
        queued, running, succeeded, failed, expired, not_found (HTTP 404),
        rate_limited (HTTP 429 — hint attached, never an error), unknown,
        or error (request failed).
        """
        api_key = self._api_key_for_provider("seedance")
        if not api_key:
            return "error", None, None
        req = urllib.request.Request(f"{self.BASE_URL}/tasks/{task_id}", method="GET")
        req.add_header("Authorization", f"Bearer {api_key}")
        try:
            r = self._json_object(
                json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
            )
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "not_found", None, None
            if e.code == 429:
                return "rate_limited", None, retry_after_hint(e)
            return "error", None, None
        except Exception:
            return "error", None, None
        status = str(r.get("status", "unknown")).lower()
        if status != "succeeded":
            return status, None, None
        content = r.get("content", {})
        video_url = content.get("video_url") if isinstance(content, dict) else None
        if not video_url:
            video_url = r.get("video_url") or r.get("url")
        return "succeeded", str(video_url) if video_url else None, None

    def _query_task_status(self, task_id: str) -> str:
        """Single-shot Seedance status query.

        Returns one of: queued, running, succeeded, failed, expired,
        not_found (HTTP 404), unknown, or error (request failed).
        """
        status, _, _ = self._query_task_status_detailed(task_id)
        # 旧接口把 429 折叠为 error：续跑对账语义不变（保持台账可续跑）
        return "error" if status == "rate_limited" else status

    def _query_agnes_task_status_detailed(
        self, task_id: str | None = None, video_id: str | None = None
    ) -> tuple[str, str | None, float | None]:
        """Single-shot Agnes status query for the unified poll loop.

        Returns ``(status, video_url, retry_after_hint)`` with status
        normalized to Seedance-like values (plus rate_limited / error).
        """
        api_key = self._api_key_for_provider("agnes")
        if not api_key:
            return "error", None, None
        if video_id:
            query = urllib.parse.urlencode({"video_id": video_id, "model_name": self.agnes_model})
            poll_url = f"{self.AGNES_RESULT_URL}?{query}"
        elif task_id:
            poll_url = f"{self.AGNES_CREATE_URL}/{task_id}"
        else:
            return "error", None, None
        req = urllib.request.Request(poll_url, method="GET")
        req.add_header("Authorization", f"Bearer {api_key}")
        try:
            response = self._json_object(
                json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
            )
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "not_found", None, None
            if e.code == 429:
                return "rate_limited", None, self._retry_after_from_http_error(e)
            return "error", None, None
        except Exception:
            return "error", None, None
        status = str(response.get("status", "unknown")).lower()
        mapping = {
            "completed": "succeeded",
            "succeeded": "succeeded",
            "success": "succeeded",
            "failed": "failed",
            "error": "failed",
            "expired": "expired",
        }
        normalized = mapping.get(status, "running")
        if normalized != "succeeded":
            return normalized, None, None
        video_url = self._extract_agnes_video_url(response)
        return "succeeded", video_url, None

    def _query_agnes_task_status(
        self, task_id: str | None = None, video_id: str | None = None
    ) -> str:
        """Single-shot Agnes status query, normalized to Seedance-like values."""
        status, _, _ = self._query_agnes_task_status_detailed(task_id, video_id)
        return "error" if status == "rate_limited" else status

    def _query_provider_task_status(
        self, provider: str, task_id: str | None, video_id: str | None
    ) -> str:
        if provider == "agnes":
            return self._query_agnes_task_status(task_id=task_id, video_id=video_id)
        return self._query_task_status(str(task_id)) if task_id else "error"

    def _query_provider_task_status_detailed(
        self, provider: str, task_id: str | None, video_id: str | None
    ) -> tuple[str, str | None, float | None]:
        if provider == "agnes":
            return self._query_agnes_task_status_detailed(task_id=task_id, video_id=video_id)
        if not task_id:
            return "error", None, None
        return self._query_task_status_detailed(str(task_id))

    def _record_failed_video_cost(self, out_name: str, provider: str) -> None:
        """Account a provider-billed failed video task (failed/expired/gone).

        The task was created and reached a terminal failure server-side, so
        the estimated cost is real spend. Paired with the success path in
        run() — each created task ends in exactly one of the two, so there is
        no double counting.
        """
        tracker = self._budget_tracker
        if tracker is None:
            return
        cost = self._per_task_cost_estimate
        if cost is None:
            cost = tracker.get_cost_estimate("video", 1)
        tracker.record_actual(
            cost,
            kind="video",
            status="failed",
            stage="generate_video",
            provider=provider,
            detail=out_name,
        )

    def _record_poll_outcome(
        self,
        ledger: VideoTaskLedger,
        out_name: str,
        provider: str,
        task_id: str | None,
        video_id: str | None,
    ) -> None:
        """Reconcile the ledger after polling returned no video URL.

        A poll timeout does NOT mean the paid task is gone: when the provider
        still reports the task as running, the record stays resumable so the
        next run continues polling instead of paying for a new task.
        """
        status = self._query_provider_task_status(provider, task_id, video_id)
        if status in ("failed", "expired"):
            ledger.update_status(out_name, status)
            self._record_failed_video_cost(out_name, provider)
        elif status == "not_found":
            ledger.update_status(out_name, "failed", error="task not found (HTTP 404)")
            self._record_failed_video_cost(out_name, provider)
        else:
            # queued/running/unknown/error: keep the record resumable.
            ledger.update_status(out_name, "polling")

    def _download_video(self, video_url: str, out_mp4: Path) -> bool:
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
            return False

        logger.info(f"OK {out_mp4.stat().st_size / 1024 / 1024:.1f}MB")
        return True

    def _video_request_fingerprint(
        self,
        *,
        provider: str,
        model: str,
        resolution: str,
        prompt: str,
        negative_prompt: str,
        first_frame: str | None,
        last_frame: str | None,
        reference_images: list[str] | None,
    ) -> str:
        """Full-fidelity fingerprint of one paid video generation request.

        Distinct from ``video_task_prompt_hash``: the prompt hash is the
        stable task-equivalence key for resuming in-flight paid tasks and
        must never change value for existing ledger records; this fingerprint
        additionally covers negative prompt, ratio, duration, and reference
        content, and gates cache skips / free re-downloads.
        """
        references = [first_frame, *(reference_images or []), last_frame]
        return request_fingerprint(
            provider=provider,
            model=model,
            prompt=prompt,
            negative_prompt=negative_prompt,
            params={
                "resolution": resolution,
                "ratio": self.ratio,
                "duration": self.duration,
            },
            reference_hashes=[hash_reference(value) for value in references if value],
        )

    def _ledger_fingerprint_matches(self, out_name: str, fingerprint: str) -> bool:
        """Cache gate: without a ledger there is no fingerprint store, so the
        legacy "file exists" behavior is kept; with a ledger, only an exact
        fingerprint match on a succeeded record allows skipping."""
        ledger = self._task_ledger
        if ledger is None:
            return True
        return ledger.fingerprint_matches(out_name, fingerprint)

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
    ) -> bool:
        out_mp4 = videos_dir / f"{out_name}.mp4"

        ledger = self._task_ledger
        prompt_hash = video_task_prompt_hash(
            provider=provider, model=model, resolution=resolution, prompt=prompt
        )
        fingerprint = self._video_request_fingerprint(
            provider=provider,
            model=model,
            resolution=resolution,
            prompt=prompt,
            negative_prompt=negative_prompt,
            first_frame=first_frame,
            last_frame=last_frame,
            reference_images=reference_images,
        )

        if out_mp4.exists():
            if self._ledger_fingerprint_matches(out_name, fingerprint):
                return True
            logger.info(f"  {out_name}: request fingerprint changed, regenerating")

        if ledger is not None:
            # 已成功但下载失败的旧任务：直接复用 video_url 重新下载，不再付费。
            reusable = ledger.find_reusable_download(out_name, prompt_hash, fingerprint)
            if reusable is not None:
                logger.info(f"  {out_name}: re-downloading from completed task (no new task)")
                return self._download_video(str(reusable["video_url"]), out_mp4)

            # 断点续轮询：恢复未完成的已付费任务，绝不重复创建。
            record = ledger.find_resumable(out_name, prompt_hash, fingerprint)
            if record is not None:
                task_id = record.get("task_id")
                video_id = record.get("video_id")
                logger.info(
                    f"  {out_name}: resuming paid task "
                    f"task_id={task_id} video_id={video_id} (no new task created)"
                )
                ledger.update_status(out_name, "polling")
                if provider == "agnes":
                    video_url = self._poll_agnes_task(task_id=task_id, video_id=video_id)
                else:
                    video_url = self._poll_task(str(task_id))
                if video_url:
                    ledger.update_status(out_name, "succeeded", video_url=video_url)
                    return self._download_video(video_url, out_mp4)
                status = self._query_provider_task_status(provider, task_id, video_id)
                if status in ("failed", "expired"):
                    ledger.update_status(out_name, status)
                    self._record_failed_video_cost(out_name, provider)
                    # 任务已终结：清理后按正常流程创建新任务
                elif status == "not_found":
                    ledger.update_status(out_name, "failed", error="task not found (HTTP 404)")
                    self._record_failed_video_cost(out_name, provider)
                else:
                    # 远端仍在运行（或状态未知）：保留台账，下次运行继续续轮询
                    ledger.update_status(out_name, "polling")
                    return False

            ambiguous = ledger.find_ambiguous_submission(out_name, prompt_hash, fingerprint)
            if ambiguous is not None:
                logger.error(
                    f"  {out_name}: previous task submission has an ambiguous outcome; "
                    "refusing to create a duplicate paid task"
                )
                return False
            ledger.record_submitting(
                out_name,
                provider=provider,
                prompt_hash=prompt_hash,
                model=model,
                resolution=resolution,
                output_path=out_mp4.as_posix(),
                cost_estimate=self._per_task_cost_estimate,
                request_fingerprint=fingerprint,
            )

        if provider == "agnes":
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
            if ledger is not None:
                ledger.record_created(
                    out_name,
                    task_id=str(task_id) if task_id else None,
                    video_id=str(video_id) if video_id else None,
                    provider=provider,
                    prompt_hash=prompt_hash,
                    model=model,
                    resolution=resolution,
                    output_path=out_mp4.as_posix(),
                    cost_estimate=self._per_task_cost_estimate,
                    request_fingerprint=fingerprint,
                )
            video_url = self._poll_agnes_task(task_id=task_id, video_id=video_id)
        else:
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
            video_id = None
            if ledger is not None:
                ledger.record_created(
                    out_name,
                    task_id=str(task_id),
                    provider=provider,
                    prompt_hash=prompt_hash,
                    model=model,
                    resolution=resolution,
                    output_path=out_mp4.as_posix(),
                    cost_estimate=self._per_task_cost_estimate,
                    request_fingerprint=fingerprint,
                )
            video_url = self._poll_task(task_id)
        if not video_url:
            if ledger is not None:
                self._record_poll_outcome(ledger, out_name, provider, task_id, video_id)
            return False

        if ledger is not None:
            ledger.update_status(out_name, "succeeded", video_url=video_url)
        return self._download_video(video_url, out_mp4)

    # ── Submit-all → poll-all pipeline (opt-in: video.max_concurrency > 1) ──

    def _pipelined_mark_success(
        self,
        out_name: str,
        state: dict[str, Any],
        state_path: Path,
        done: set[str],
        budget_tracker: BudgetTracker,
        provider_name: str,
    ) -> tuple[bool, str]:
        """Mirror the serial run() post-success block: state done + try_spend."""
        done.add(out_name)
        state["done"] = sorted(done)
        atomic_write_json(state_path, state)
        per_video = budget_tracker.get_cost_estimate("video", 1)
        return budget_tracker.try_spend(
            per_video,
            kind="video",
            stage="generate_video",
            provider=provider_name,
            detail=out_name,
        )

    def _run_pipelined(
        self,
        *,
        config: Any,
        state: dict[str, Any],
        state_path: Path,
        done: set[str],
        segments: list[dict[str, Any]],
        design: dict[str, Any],
        images_dir: Path,
        videos_dir: Path,
        provider_name: str,
        selection: Any,
        provider_meta: dict[str, Any],
        budget_tracker: BudgetTracker,
        take_count: int,
        total_jobs: int,
        rework_segment_ids: set[int],
        max_concurrency: int,
        contract_by_segment: dict[int, dict[str, Any]],
        reference_plates: dict[int, dict[str, Any]],
        pre_production: dict[str, Any],
    ) -> StageResult:
        """Submit-all → poll-all pipeline used when ``video.max_concurrency > 1``.

        Thread model:

        - Phase A (main thread, serial): prompt/reference building, request
          fingerprints, and all cache decisions (skip / free re-download /
          resume / create) — identical judgment order to ``_generate_one``.
        - Phase B (bounded thread pool): task creation only. Creations are
          recorded in the paid task ledger the moment a task id exists. Agnes
          keeps its >=65s creation cadence by submitting serially with the
          provider sleep between creates. A failed creation fails only its
          own take and is never billed (network failure, task not created).
        - Phase C (main thread unified poll loop + download pool): every
          in-flight task (new + resumed) is queried once per round; HTTP 429
          backs off per Retry-After and is exempt from error counting;
          succeeded tasks are ledger-marked and handed to the download pool;
          failed/expired/not_found tasks are accounted exactly once via
          ``_record_failed_video_cost``. The total poll budget is
          ``max_poll_time`` measured across the slowest task, not per task.
          Tasks still running at timeout keep their ledger record resumable
          (anti-orphan semantics unchanged).

        Deliberate differences from the serial path (opt-in only):

        - A resumed task that terminates failed/expired is accounted and fails
          this run; it is NOT re-created in the same run (the next run's
          Phase A picks it up as a fresh creation).
        - Budget-cap exhaustion lets in-flight work finish before the stage
          fails (serial aborts immediately).
        """
        ledger = self._task_ledger
        ok_count = 0
        fail_count = 0
        budget_failure: list[str] = []
        redownloads: list[dict[str, Any]] = []
        creates: list[dict[str, Any]] = []
        in_flight: list[dict[str, Any]] = []

        # ── Phase A：主线程串行判定（与 _generate_one 同一判定序）──
        for i, seg in enumerate(segments):
            vid_id = self._video_id_for_unit(seg)
            out_names = self._output_names_for_segment(vid_id, take_count)
            state.setdefault("generated_takes", {})[vid_id] = list(out_names)

            video_prompt = self._build_video_prompt(
                seg,
                contract_by_segment=contract_by_segment,
                provider=provider_name,
            )
            img_id = f"img_{seg['segment_id']:02d}"
            first_frame = self._resolve_first_frame(seg, images_dir, img_id)
            last_frame = self._resolve_last_frame(seg, images_dir, design)
            contract = self._contract_for_unit(seg, contract_by_segment)
            negative_prompt = self._build_video_negative_prompt(contract, provider_name)
            reference_inputs = self._reference_inputs_for_segment(
                config,
                design,
                pre_production,
                seg,
                contract,
                self._reference_plate_for_unit(seg, reference_plates),
            )
            uploaded_reference_images = reference_inputs.get("uploaded_reference_images", [])
            reference_images = (
                reference_inputs.get("uploaded_reference_assets", uploaded_reference_images)
                if provider_name == "agnes"
                else uploaded_reference_images
            )
            if config.video.storyboard_conditioning == "auto":
                first_frame, reference_images = self._storyboard_conditioned_inputs(
                    config, contract, first_frame, reference_inputs, provider_name
                )
            model = self._segment_model(seg, provider_name)
            resolution = self._segment_resolution(seg, provider_name)
            segment_fingerprint = self._video_request_fingerprint(
                provider=provider_name,
                model=model,
                resolution=resolution,
                prompt=video_prompt,
                negative_prompt=negative_prompt,
                first_frame=first_frame,
                last_frame=last_frame,
                reference_images=reference_images,
            )

            cached_names = [
                out_name
                for out_name in out_names
                if out_name in done
                and (videos_dir / f"{out_name}.mp4").exists()
                and self._ledger_fingerprint_matches(out_name, segment_fingerprint)
            ]
            if len(cached_names) == len(out_names):
                logger.info(f"[{i + 1}/{len(segments)}] {vid_id} skip (cached, fingerprint match)")
                ok_count += len(out_names)
                continue

            logger.info(f"[{i + 1}/{len(segments)}] {vid_id}: {video_prompt[:60]}...")
            logger.info(
                f"  model={model}, resolution={resolution}, first_frame={first_frame is not None}, "
                f"references={len(reference_images)}, takes={take_count}"
            )
            prompt_hash = video_task_prompt_hash(
                provider=provider_name, model=model, resolution=resolution, prompt=video_prompt
            )

            for take_number, out_name in enumerate(out_names, start=1):
                state.setdefault("reference_inputs", {})[out_name] = reference_inputs["state"]
                atomic_write_json(state_path, state)

                if (
                    out_name in done
                    and (videos_dir / f"{out_name}.mp4").exists()
                    and self._ledger_fingerprint_matches(out_name, segment_fingerprint)
                ):
                    logger.info(f"  {out_name} skip (cached)")
                    ok_count += 1
                    continue

                out_mp4 = videos_dir / f"{out_name}.mp4"
                if take_count > 1:
                    logger.info(f"  {out_name} take {take_number}/{take_count}")

                # 与 _generate_one 相同：文件+指纹 → 免费重下载 → 续跑 → 创建
                if out_mp4.exists() and self._ledger_fingerprint_matches(
                    out_name, segment_fingerprint
                ):
                    ok_count += 1
                    spend_ok, spend_msg = self._pipelined_mark_success(
                        out_name, state, state_path, done, budget_tracker, provider_name
                    )
                    if not spend_ok:
                        budget_failure.append(spend_msg)
                    continue

                if ledger is not None:
                    reusable = ledger.find_reusable_download(
                        out_name, prompt_hash, segment_fingerprint
                    )
                    if reusable is not None:
                        logger.info(
                            f"  {out_name}: re-downloading from completed task (no new task)"
                        )
                        redownloads.append(
                            {
                                "out_name": out_name,
                                "video_url": str(reusable["video_url"]),
                                "out_mp4": out_mp4,
                            }
                        )
                        continue
                    record = ledger.find_resumable(out_name, prompt_hash, segment_fingerprint)
                    if record is not None:
                        logger.info(
                            f"  {out_name}: resuming paid task "
                            f"task_id={record.get('task_id')} video_id={record.get('video_id')} "
                            "(no new task created)"
                        )
                        ledger.update_status(out_name, "polling")
                        in_flight.append(
                            {
                                "out_name": out_name,
                                "task_id": record.get("task_id"),
                                "video_id": record.get("video_id"),
                                "out_mp4": out_mp4,
                                "consecutive_errors": 0,
                                "next_poll_at": 0.0,
                            }
                        )
                        continue
                    ambiguous = ledger.find_ambiguous_submission(
                        out_name, prompt_hash, segment_fingerprint
                    )
                    if ambiguous is not None:
                        logger.error(
                            f"  {out_name}: previous task submission has an ambiguous outcome; "
                            "refusing to create a duplicate paid task"
                        )
                        fail_count += 1
                        continue

                creates.append(
                    {
                        "out_name": out_name,
                        "prompt": video_prompt,
                        "model": model,
                        "resolution": resolution,
                        "first_frame": first_frame,
                        "last_frame": last_frame,
                        "reference_images": reference_images,
                        "negative_prompt": negative_prompt,
                        "out_mp4": out_mp4,
                        "prompt_hash": prompt_hash,
                        "fingerprint": segment_fingerprint,
                    }
                )

        logger.info(
            f"Pipelined plan (max_concurrency={max_concurrency}): "
            f"{len(creates)} to create, {len(in_flight)} to resume, "
            f"{len(redownloads)} to re-download, {ok_count} cached"
        )

        # ── Phase B：受限并发提交（创建即落台账）──
        def _submit(item: dict[str, Any]) -> dict[str, Any]:
            # 预算 cap 复查：超预算不创建新付费任务（不超发）
            if self._per_task_cost_estimate is not None:
                can, msg = budget_tracker.can_spend(self._per_task_cost_estimate)
                if not can:
                    return {"item": item, "task_id": None, "video_id": None, "budget_error": msg}
            if ledger is not None:
                ledger.record_submitting(
                    item["out_name"],
                    provider=provider_name,
                    prompt_hash=item["prompt_hash"],
                    model=item["model"],
                    resolution=item["resolution"],
                    output_path=item["out_mp4"].as_posix(),
                    cost_estimate=self._per_task_cost_estimate,
                    request_fingerprint=item["fingerprint"],
                )
            if provider_name == "agnes":
                task_id, video_id = self._create_agnes_task(
                    item["prompt"],
                    item["model"],
                    item["resolution"],
                    item["first_frame"],
                    item["last_frame"],
                    reference_images=item["reference_images"],
                    negative_prompt=item["negative_prompt"],
                )
            else:
                task_id = self._create_task(
                    item["prompt"],
                    item["model"],
                    item["resolution"],
                    item["first_frame"],
                    item["last_frame"],
                    reference_images=item["reference_images"],
                )
                video_id = None
            if not task_id and not video_id:
                # 创建失败（任务不存在，未计费）：该 take 记失败，不阻断其他 take
                return {"item": item, "task_id": None, "video_id": None, "budget_error": None}
            if ledger is not None:
                ledger.record_created(
                    item["out_name"],
                    task_id=str(task_id) if task_id else None,
                    video_id=str(video_id) if video_id else None,
                    provider=provider_name,
                    prompt_hash=item["prompt_hash"],
                    model=item["model"],
                    resolution=item["resolution"],
                    output_path=item["out_mp4"].as_posix(),
                    cost_estimate=self._per_task_cost_estimate,
                    request_fingerprint=item["fingerprint"],
                )
            return {"item": item, "task_id": task_id, "video_id": video_id, "budget_error": None}

        def _collect_submission(outcome: dict[str, Any]) -> None:
            nonlocal fail_count
            item = outcome["item"]
            if outcome["budget_error"] is not None:
                logger.error(f"  {item['out_name']}: {outcome['budget_error']}")
                budget_failure.append(str(outcome["budget_error"]))
                fail_count += 1
                return
            if not outcome["task_id"] and not outcome["video_id"]:
                fail_count += 1
                return
            in_flight.append(
                {
                    "out_name": item["out_name"],
                    "task_id": outcome["task_id"],
                    "video_id": outcome["video_id"],
                    "out_mp4": item["out_mp4"],
                    "consecutive_errors": 0,
                    "next_poll_at": 0.0,
                }
            )

        if creates:
            if provider_name == "agnes":
                # Agnes 创建节奏（≥65s/次）保留：串行提交 + 创建间隔 sleep
                for index, item in enumerate(creates):
                    _collect_submission(_submit(item))
                    if index < len(creates) - 1:
                        time.sleep(self._sleep_between_for_provider(provider_name))
            else:
                with ThreadPoolExecutor(
                    max_workers=max_concurrency,
                    thread_name_prefix="narrascape-video-submit",
                ) as pool:
                    futures = [pool.submit(_submit, item) for item in creates]
                    for future in as_completed(futures):
                        _collect_submission(future.result())

        # ── Phase C：统一轮询 + 并发下载 ──
        download_futures: dict[Future[bool], str] = {}
        with ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="narrascape-video-dl",
        ) as download_pool:
            for item in redownloads:
                dl_future = download_pool.submit(
                    self._download_video, item["video_url"], item["out_mp4"]
                )
                download_futures[dl_future] = item["out_name"]

            poll_start = time.monotonic()
            while in_flight and (time.monotonic() - poll_start) < self.max_poll_time:
                now = time.monotonic()
                for task in list(in_flight):
                    if task["next_poll_at"] > now:
                        continue
                    status, video_url, retry_hint = self._query_provider_task_status_detailed(
                        provider_name, task["task_id"], task["video_id"]
                    )
                    if status == "succeeded" and video_url:
                        if ledger is not None:
                            ledger.update_status(task["out_name"], "succeeded", video_url=video_url)
                        dl_future = download_pool.submit(
                            self._download_video, video_url, task["out_mp4"]
                        )
                        download_futures[dl_future] = task["out_name"]
                        in_flight.remove(task)
                    elif status == "succeeded":
                        logger.error(
                            f"  {task['out_name']}: succeeded but no video URL; "
                            "ledger kept resumable"
                        )
                        in_flight.remove(task)
                        fail_count += 1
                    elif status in ("failed", "expired"):
                        if ledger is not None:
                            ledger.update_status(task["out_name"], status)
                        self._record_failed_video_cost(task["out_name"], provider_name)
                        in_flight.remove(task)
                        fail_count += 1
                    elif status == "not_found":
                        if ledger is not None:
                            ledger.update_status(
                                task["out_name"], "failed", error="task not found (HTTP 404)"
                            )
                        self._record_failed_video_cost(task["out_name"], provider_name)
                        in_flight.remove(task)
                        fail_count += 1
                    elif status == "rate_limited":
                        # 限流不是故障：按 Retry-After 退避，不计入连续错误
                        wait = max(self.poll_interval, retry_hint or 0.0)
                        logger.warning(
                            f"  {task['out_name']}: poll rate-limited (429); "
                            f"backing off {wait:.1f}s (not counted as error)"
                        )
                        task["next_poll_at"] = time.monotonic() + wait
                    elif status == "error":
                        task["consecutive_errors"] += 1
                        if task["consecutive_errors"] >= self.max_poll_errors:
                            logger.error(
                                f"  {task['out_name']}: polling aborted after "
                                f"{task['consecutive_errors']} consecutive errors; "
                                "ledger kept resumable"
                            )
                            if ledger is not None:
                                ledger.update_status(task["out_name"], "polling")
                            in_flight.remove(task)
                            fail_count += 1
                        else:
                            task["next_poll_at"] = time.monotonic() + self.poll_interval
                    else:
                        # queued / running / unknown：继续等
                        task["next_poll_at"] = time.monotonic() + self.poll_interval
                if in_flight:
                    wait = min(t["next_poll_at"] for t in in_flight) - time.monotonic()
                    if wait > 0:
                        time.sleep(min(wait, 1.0))

            # 超时未终结：台账保持 polling 可续（反孤儿语义不动），本轮记失败
            for task in in_flight:
                logger.error(
                    f"  {task['out_name']}: polling timeout after {self.max_poll_time}s; "
                    "paid task stays resumable in the ledger"
                )
                if ledger is not None:
                    ledger.update_status(task["out_name"], "polling")
                fail_count += 1

            # 汇总下载结果（主线程，按提交顺序无关）
            for dl_future, out_name in download_futures.items():
                try:
                    download_ok = bool(dl_future.result())
                except Exception as exc:  # pragma: no cover - defensive guard
                    logger.error(f"  {out_name}: download raised: {exc}")
                    download_ok = False
                if download_ok:
                    ok_count += 1
                    spend_ok, spend_msg = self._pipelined_mark_success(
                        out_name, state, state_path, done, budget_tracker, provider_name
                    )
                    if not spend_ok:
                        budget_failure.append(spend_msg)
                else:
                    fail_count += 1

        if budget_failure:
            return StageResult(self.name, False, message=budget_failure[0])

        logger.info(f"Done: {ok_count} OK, {fail_count} failed")
        if fail_count == 0:
            record_provider_success(config, selection.tool.name)
        else:
            record_provider_failure(
                config,
                selection.tool.name,
                f"{fail_count}/{len(segments)} video generations failed",
            )
        write_sanitize_audit(config.pipeline_dir, self.name)
        return StageResult(
            self.name,
            fail_count == 0,
            message=f"{ok_count} OK, {fail_count} failed",
            metadata={
                "provider_selection": provider_meta,
                "ok_count": ok_count,
                "fail_count": fail_count,
                "takes_per_shot": take_count,
                "take_count": total_jobs,
                "rework_segment_ids": sorted(rework_segment_ids),
                "pipelined": True,
                "max_concurrency": max_concurrency,
            },
        )
