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
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from narrascape.api_keys import APIKeys
from narrascape.artifacts import validate_artifact
from narrascape.prompt_compiler import provider_negative_prompt, provider_prompt
from narrascape.prompt_quality import video_prompt_quality_assessment
from narrascape.prompt_safety import sanitize_prompt_for_provider
from narrascape.providers import (
    record_provider_failure,
    record_provider_success,
    select_provider,
    selection_metadata,
)
from narrascape.reference_assets import is_reference_uri, resolve_reference_assets_for_shot
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.uploader.image_uploader import ImageUploader
from narrascape.utils.ffmpeg import validate_video
from narrascape.utils.retry import retry_with_backoff
from narrascape.utils.safe_io import (
    atomic_write_json,
    atomic_write_yaml,
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
                    spend_ok, spend_msg = budget_tracker.try_spend(per_video)
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
            },
        )

    # ── Internal methods ───────────────────────────

    def _load_state(self, path: Path) -> dict[str, Any]:
        return load_json_mapping(path, default={"done": [], "errors": [], "task_map": {}})

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

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]

    def _resolve_model_id(self, model: str) -> str:
        """Map internal model name to Volcengine Ark model ID."""
        return self.MODEL_MAP.get(model, model)

    def _write_prompt_quality_report(
        self,
        config: Any,
        segments: list[dict[str, Any]],
        contract_by_segment: dict[int, dict[str, Any]],
        provider: str,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        assessments: list[dict[str, Any]] = []
        checked_segments: list[int] = []
        for segment in segments:
            segment_id = self._to_int(segment.get("segment_id"))
            if segment_id is None:
                continue
            checked_segments.append(segment_id)
            contract = contract_by_segment.get(segment_id, {})
            if not contract:
                continue
            prompt = self._build_video_prompt(
                segment,
                contract_by_segment=contract_by_segment,
                provider=provider,
            )
            assessment = video_prompt_quality_assessment(
                contract,
                provider=provider,
                prompt=prompt,
            )
            assessments.append(assessment)
            findings.extend(assessment["findings"])
        report = {
            "schema_version": "video_prompt_quality.v1",
            "status": "blocked" if findings else "passed",
            "provider": provider,
            "checked_segments": checked_segments,
            "assessments": assessments,
            "findings": findings,
        }
        validate_artifact("video_prompt_quality", report)
        atomic_write_yaml(config.pipeline_dir / "video_prompt_quality.yaml", report)
        return report

    def _api_key_for_provider(self, provider: str) -> str | None:
        if self.api_key:
            return self.api_key
        active_provider = provider or self._selected_provider
        if active_provider == "agnes":
            return APIKeys.agnes()
        return APIKeys.ark()

    def _apply_video_config(self, config: Any, provider: str) -> None:
        video_cfg = getattr(config, "video", None)
        if not video_cfg:
            return
        self.ratio = str(getattr(video_cfg, "ratio", self.ratio) or self.ratio)
        self.duration = int(getattr(video_cfg, "duration", self.duration) or self.duration)
        self.frame_rate = int(getattr(video_cfg, "frame_rate", self.frame_rate) or self.frame_rate)
        self.takes = int(getattr(video_cfg, "takes", self.takes) or self.takes)
        self.resolution = str(getattr(video_cfg, "resolution", self.resolution) or self.resolution)
        configured_model = str(getattr(video_cfg, "model", "") or "")
        if provider == "agnes":
            if configured_model.startswith("agnes-"):
                self.agnes_model = configured_model
        elif configured_model and not configured_model.startswith("agnes-"):
            self.model = configured_model

    def _active_model(self, provider: str) -> str:
        return self.agnes_model if provider == "agnes" else self.model

    def _takes_per_shot(self) -> int:
        return max(1, int(self.takes or 1))

    def _output_names_for_segment(self, base_id: str, take_count: int) -> list[str]:
        if take_count <= 1:
            return [base_id]
        return [f"{base_id}_take_{take_index:02d}" for take_index in range(1, take_count + 1)]

    def _sleep_between_for_provider(self, provider: str) -> float:
        if provider == "agnes":
            return max(self.sleep_between, 65.0)
        return self.sleep_between

    def _segment_model(self, seg: dict[str, Any], provider: str) -> str:
        if provider == "agnes":
            model = str(seg.get("agnes_model", "") or "")
            return model if model.startswith("agnes-") else self.agnes_model
        return str(seg.get("seedance_model", self.model) or self.model)

    def _segment_resolution(self, seg: dict[str, Any], provider: str) -> str:
        key = "agnes_resolution" if provider == "agnes" else "seedance_resolution"
        return str(seg.get(key, self.resolution) or self.resolution)

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
        segment_id = self._to_int(seg.get("segment_id"))
        contract = (contract_by_segment or {}).get(segment_id) if segment_id is not None else None
        generation = (contract or {}).get("generation", {})
        if isinstance(generation, dict):
            if provider:
                contract_prompt = provider_prompt(generation, provider)
                if contract_prompt:
                    return contract_prompt
            elif generation.get("video_prompt"):
                return str(generation["video_prompt"])

        parts = []

        # Prefer cinematic_format for motion details
        cinematic = seg.get("cinematic_format", "")
        if cinematic:
            parts.append(cinematic)

        image_prompt = seg.get("image_prompt", "")
        if image_prompt:
            parts.append(image_prompt)

        # Add movement from metadata if available
        movement = seg.get("movement", "")
        if movement and movement != "still":
            movement_map = {
                "zoom_in": "camera slowly zooms in",
                "zoom_out": "camera slowly zooms out",
                "pan_left": "camera pans to the left",
                "pan_right": "camera pans to the right",
                "pan_up": "camera tilts up",
                "pan_down": "camera tilts down",
                "tracking": "camera tracks alongside the subject",
                "drift": "camera drifts slowly",
                "push_in": "camera pushes in toward the subject",
                "pull_out": "camera pulls back from the subject",
                "dolly_in": "dolly in smoothly",
                "dolly_out": "dolly out smoothly",
                "crane_up": "crane shot moving up",
                "crane_down": "crane shot moving down",
                "handheld": "subtle handheld camera movement",
            }
            motion_desc = movement_map.get(movement, f"camera {movement}")
            parts.append(f"{motion_desc}, smooth and cinematic")

        prompt = ". ".join(parts)
        prompt += (
            ". Cinematic motion, smooth camera movement, oil painting style, "
            "visible brush texture, cohesive painterly color palette, high quality."
        )
        return prompt

    def _build_video_negative_prompt(self, contract: dict[str, Any], provider: str) -> str:
        generation = contract.get("generation", {}) if isinstance(contract, dict) else {}
        if not isinstance(generation, dict):
            return ""
        return provider_negative_prompt(generation, provider)

    def _load_director_contract(self, path: Path) -> dict[int, dict[str, Any]]:
        if not path.exists():
            return {}
        data = load_yaml_mapping(path)
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
        data = load_yaml_mapping(path)
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
        manifest = self._reference_manifest_for_segment(
            config,
            design,
            pre_production,
            seg,
            contract,
            reference_plate,
        )
        uploaded_reference_assets = self._upload_reference_assets(manifest["resolved_references"])
        uploaded_reference_images = [
            asset["url"] for asset in uploaded_reference_assets if asset.get("url")
        ]
        compact_resolved = [
            self._compact_reference_asset(asset) for asset in manifest["resolved_references"]
        ]
        return {
            "uploaded_reference_images": uploaded_reference_images,
            "uploaded_reference_assets": uploaded_reference_assets,
            "state": {
                "segment_id": seg.get("segment_id"),
                "storyboard_reference_image_ids": manifest["storyboard_reference_image_ids"],
                "expected_reference_ids": manifest["expected_reference_ids"],
                "resolved_references": compact_resolved,
                "missing_reference_ids": manifest["missing_reference_ids"],
                "uploaded_reference_count": len(uploaded_reference_images),
            },
        }

    def _reference_manifest_for_segment(
        self,
        config: Any,
        design: dict[str, Any],
        pre_production: dict[str, Any],
        seg: dict[str, Any],
        contract: dict[str, Any],
        reference_plate: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if reference_plate:
            return {
                "storyboard_reference_image_ids": list(
                    reference_plate.get("storyboard_reference_image_ids") or []
                ),
                "expected_reference_ids": list(reference_plate.get("expected_reference_ids") or []),
                "resolved_references": list(reference_plate.get("reference_assets") or []),
                "missing_reference_ids": list(reference_plate.get("missing_reference_ids") or []),
            }
        return resolve_reference_assets_for_shot(
            config.project_dir,
            contract=contract,
            design_segment=seg,
            pre_production=pre_production,
            design=design,
        )

    def _upload_reference_assets(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        uploaded: list[dict[str, Any]] = []
        seen: set[str] = set()
        for asset in assets:
            value = asset.get("url") or asset.get("path")
            if not value:
                continue
            if is_reference_uri(value):
                resolved = value
            else:
                resolved = self.uploader.upload(value)
            if resolved not in seen:
                uploaded.append(
                    {
                        "url": resolved,
                        "role": asset.get("role") or "reference",
                        "requested_id": asset.get("requested_id"),
                        "asset_id": asset.get("asset_id"),
                    }
                )
                seen.add(resolved)
        return uploaded[:9]

    def _compact_reference_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        item = {
            "requested_id": asset.get("requested_id"),
            "asset_id": asset.get("asset_id"),
            "role": asset.get("role"),
            "source": asset.get("source"),
            "path": asset.get("path"),
            "exists": asset.get("exists"),
        }
        url = str(asset.get("url") or "")
        if url.startswith("data:"):
            item["url"] = "data-uri"
        elif url:
            item["url"] = url
        return item

    def _resolve_first_frame(
        self, seg: dict[str, Any], images_dir: Path, img_id: str
    ) -> str | None:
        """Resolve the first frame image for Seedance.

        Priority:
        1. reference_image_url from segment metadata
        2. Generated image from this segment
        3. None (text-only generation)
        """
        # Check for per-segment reference image URL
        ref_url = seg.get("reference_image_url", "")
        if ref_url:
            return str(ref_url)

        # Use generated image as first frame
        img_path = images_dir / f"{img_id}.png"
        if img_path.exists():
            return self.uploader.upload(img_path)
        return None

    def _resolve_last_frame(
        self,
        seg: dict[str, Any],
        images_dir: Path,
        design: dict[str, Any] | None = None,
    ) -> str | None:
        """Resolve an explicit ending frame for bookended video generation."""
        for chain in self._last_frame_chains(seg, design or {}):
            for value in self._reference_chain_values(chain):
                resolved = self._resolve_frame_reference(value, images_dir)
                if resolved:
                    return resolved
            fallback = self._generated_image_for_chain(chain, images_dir)
            if fallback:
                return fallback
        # 当 reference_chain_ids 指向 next segment 的 image 时，可以提取作为尾帧
        return None

    # ── Seedance API Workflow ───────────────────────

    def _last_frame_chains(
        self,
        seg: dict[str, Any],
        design: dict[str, Any],
    ) -> list[dict[str, Any]]:
        reference_chain_ids = [str(item) for item in seg.get("reference_chain_ids", []) or []]
        if not reference_chain_ids:
            return []
        chains = [
            chain
            for chain in design.get("reference_image_chains", []) or []
            if str(chain.get("chain_id")) in reference_chain_ids
        ]
        return [chain for chain in chains if self._is_last_frame_chain(chain)]

    def _is_last_frame_chain(self, chain: dict[str, Any]) -> bool:
        usage = str(chain.get("usage_mode") or "").lower()
        chain_id = str(chain.get("chain_id") or "").lower()
        if usage == "last_frame":
            return True
        return any(marker in chain_id for marker in ("last_frame", "ending", "final_frame"))

    def _reference_chain_values(self, chain: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in ("generated_images", "reference_urls", "reference_local_paths"):
            value = chain.get(key)
            if isinstance(value, list):
                values.extend(str(item) for item in value if item)
            elif value:
                values.append(str(value))
        return values

    def _resolve_frame_reference(self, value: str, images_dir: Path) -> str | None:
        if not value:
            return None
        if is_reference_uri(value):
            return value
        path = Path(value)
        candidates = (
            [path] if path.is_absolute() else [images_dir / value, images_dir.parent / value]
        )
        for candidate in candidates:
            if candidate.exists():
                return self.uploader.upload(candidate)
        return None

    def _generated_image_for_chain(self, chain: dict[str, Any], images_dir: Path) -> str | None:
        chain_id = str(chain.get("chain_id") or "")
        match = re.search(r"(?:img|segment|seg|shot)[_-]?(\d+)", chain_id, flags=re.IGNORECASE)
        if not match:
            return None
        image_path = images_dir / f"img_{int(match.group(1)):02d}.png"
        if image_path.exists():
            return self.uploader.upload(image_path)
        return None

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
            r = self._json_object(
                retry_with_backoff(
                    lambda: json.loads(urllib.request.urlopen(req, timeout=60).read().decode()),
                    max_retries=3,
                    base_delay=2.0,
                    retryable_exceptions=(urllib.error.URLError, urllib.error.HTTPError),
                )
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
                r = self._json_object(
                    json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
                )
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
            response = retry_with_backoff(
                lambda: json.loads(
                    urllib.request.urlopen(req, timeout=self.AGNES_CREATE_TIMEOUT).read().decode()
                ),
                max_retries=4,
                base_delay=65.0,
                max_delay=75.0,
                retryable_exceptions=(
                    TimeoutError,
                    urllib.error.URLError,
                    urllib.error.HTTPError,
                ),
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
        header = exc.headers.get("Retry-After") if exc.headers else None
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        try:
            body = exc.read().decode(errors="ignore")
        except Exception:
            body = ""
        minute_match = re.search(r"(\d+)\s+minute", body, flags=re.IGNORECASE)
        if minute_match:
            return max(65.0, float(minute_match.group(1)) * 65.0)
        return 65.0

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

            req = urllib.request.Request(poll_url, method="GET")
            req.add_header("Authorization", f"Bearer {api_key}")
            try:
                response = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
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
        if out_mp4.exists():
            return True

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
            video_url = self._poll_task(task_id)
        if not video_url:
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
            return False

        logger.info(f"OK {out_mp4.stat().st_size / 1024 / 1024:.1f}MB")
        return True
