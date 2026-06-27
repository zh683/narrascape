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

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from narrascape.api_keys import APIKeys
from narrascape.providers import select_provider, selection_metadata
from narrascape.reference_assets import is_reference_uri, resolve_reference_assets_for_shot
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.uploader.image_uploader import ImageUploader
from narrascape.utils.retry import retry_with_backoff

logger = logging.getLogger("narrascape.stages.generate_video")


class GenerateVideoStage(Stage):
    """Generate video clips from designed shots using Seedance 2.0.

    Inputs:  design report (with ShotDesign.seedance_* fields)
             assets/images/ (generated images for first_frame)
    Outputs: assets/videos/vid_*.mp4
    State:   pipeline/{name}/video_gen_state.json
    """

    name = "generate_video"
    depends_on = ["director_contract", "generate_images"]
    outputs = []

    # 火山方舟正确的视频生成 API 端点
    BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations"

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
    ):
        self.api_key = api_key or APIKeys.ark()
        self.model = model
        self.resolution = resolution
        self.ratio = ratio
        self.duration = duration
        self.sleep_between = sleep_between
        self.poll_interval = poll_interval
        self.max_poll_time = max_poll_time
        self.uploader = ImageUploader(backend=uploader_backend)

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
        if not self.api_key:
            return False, (
                f"{selection.tool.name} selected but ARK_API_KEY not found. "
                "Set env var or .env file."
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
        pre_production = self._load_yaml(pipe_dir / "pre_production.yaml")

        # Budget check
        from narrascape.utils.budget import BudgetTracker

        budget_tracker = BudgetTracker(config.budget, pipe_dir / "budget_state.json")
        est_cost = budget_tracker.get_cost_estimate("video", len(segments))
        can_spend, budget_msg = budget_tracker.can_spend(est_cost)
        if not can_spend:
            return StageResult(self.name, False, message=budget_msg)
        logger.info(budget_msg)

        # Load state
        state_path = pipe_dir / "video_gen_state.json"
        state = self._load_state(state_path)
        state["provider_selection"] = provider_meta
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        done = set(state.get("done", []))
        # 持久化任务 ID 映射，用于断点续传
        task_map = state.get("task_map", {})

        logger.info(f"Seedance {self.model}: {len(segments)} videos to generate")

        ok_count, fail_count = 0, 0
        for i, seg in enumerate(segments):
            vid_id = f"vid_{seg['segment_id']:02d}"
            if vid_id in done and (videos_dir / f"{vid_id}.mp4").exists():
                logger.info(f"[{i + 1}/{len(segments)}] {vid_id} skip (cached)")
                ok_count += 1
                continue

            # Build video prompt from cinematic_format or image_prompt
            video_prompt = self._build_video_prompt(seg, contract_by_segment=contract_by_segment)

            # Prepare first_frame from generated image
            img_id = f"img_{seg['segment_id']:02d}"
            first_frame = self._resolve_first_frame(seg, images_dir, img_id)
            last_frame = self._resolve_last_frame(seg, images_dir)
            contract = contract_by_segment.get(int(seg["segment_id"]), {})
            reference_inputs = self._reference_inputs_for_segment(
                config,
                design,
                pre_production,
                seg,
                contract,
            )
            reference_images = reference_inputs["uploaded_reference_images"]

            # Select model per segment
            model = seg.get("seedance_model", self.model)
            resolution = seg.get("seedance_resolution", self.resolution)

            logger.info(f"[{i + 1}/{len(segments)}] {vid_id}: {video_prompt[:60]}...")
            logger.info(
                f"  model={model}, resolution={resolution}, first_frame={first_frame is not None}, "
                f"references={len(reference_images)}"
            )
            state.setdefault("reference_inputs", {})[vid_id] = reference_inputs["state"]
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

            result = self._generate_one(
                video_prompt,
                vid_id,
                model,
                resolution,
                first_frame,
                last_frame,
                videos_dir,
                reference_images,
            )
            if result:
                ok_count += 1
                done.add(vid_id)
                state["done"] = list(done)
                state_path.write_text(
                    json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                per_video = budget_tracker.get_cost_estimate("video", 1)
                budget_tracker.record(per_video)
            else:
                fail_count += 1
            if i < len(segments) - 1:
                time.sleep(self.sleep_between)

        logger.info(f"Done: {ok_count} OK, {fail_count} failed")
        return StageResult(
            self.name,
            fail_count == 0,
            message=f"{ok_count} OK, {fail_count} failed",
            metadata={
                "provider_selection": provider_meta,
                "ok_count": ok_count,
                "fail_count": fail_count,
            },
        )

    # ── Internal methods ───────────────────────────

    def _load_state(self, path: Path) -> dict:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"done": [], "errors": [], "task_map": {}}

    def _load_design_report(self, path: Path) -> dict:
        if path.exists():
            import yaml

            return yaml.safe_load(path.read_text(encoding="utf-8"))
        return {}

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]

    def _resolve_model_id(self, model: str) -> str:
        """Map internal model name to Volcengine Ark model ID."""
        return self.MODEL_MAP.get(model, model)

    def _build_video_prompt(
        self, seg: dict, contract_by_segment: dict[int, dict[str, Any]] | None = None
    ) -> str:
        """Build a video generation prompt from the shot design.

        Uses cinematic_format for camera movement, motion, and scene description.
        Falls back to image_prompt if cinematic_format is empty.
        """
        try:
            segment_id = int(seg.get("segment_id"))
        except (TypeError, ValueError):
            segment_id = None
        contract = (contract_by_segment or {}).get(segment_id) if segment_id is not None else None
        contract_prompt = (contract or {}).get("generation", {}).get("video_prompt")
        if contract_prompt:
            return str(contract_prompt)

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
        # 视频质量后缀（Seedance 2.0 对英文提示词响应更好）
        prompt += ". Cinematic motion, smooth camera movement, photorealistic, high quality."
        return prompt

    def _load_director_contract(self, path: Path) -> dict[int, dict[str, Any]]:
        if not path.exists():
            return {}
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        result: dict[int, dict[str, Any]] = {}
        for shot in data.get("shots", []) or []:
            try:
                result[int(shot.get("segment_id"))] = shot
            except (TypeError, ValueError):
                continue
        return result

    def _reference_inputs_for_segment(
        self,
        config: Any,
        design: dict[str, Any],
        pre_production: dict[str, Any],
        seg: dict[str, Any],
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        manifest = resolve_reference_assets_for_shot(
            config.project_dir,
            contract=contract,
            design_segment=seg,
            pre_production=pre_production,
            design=design,
        )
        uploaded_reference_images = self._upload_reference_assets(
            manifest["resolved_references"]
        )
        compact_resolved = [
            self._compact_reference_asset(asset) for asset in manifest["resolved_references"]
        ]
        return {
            "uploaded_reference_images": uploaded_reference_images,
            "state": {
                "segment_id": seg.get("segment_id"),
                "storyboard_reference_image_ids": manifest[
                    "storyboard_reference_image_ids"
                ],
                "expected_reference_ids": manifest["expected_reference_ids"],
                "resolved_references": compact_resolved,
                "missing_reference_ids": manifest["missing_reference_ids"],
                "uploaded_reference_count": len(uploaded_reference_images),
            },
        }

    def _upload_reference_assets(self, assets: list[dict[str, Any]]) -> list[str]:
        uploaded: list[str] = []
        for asset in assets:
            value = asset.get("url") or asset.get("path")
            if not value:
                continue
            if is_reference_uri(value):
                resolved = value
            else:
                resolved = self.uploader.upload(value)
            if resolved not in uploaded:
                uploaded.append(resolved)
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

    def _resolve_first_frame(self, seg: dict, images_dir: Path, img_id: str) -> str | None:
        """Resolve the first frame image for Seedance.

        Priority:
        1. reference_image_url from segment metadata
        2. Generated image from this segment
        3. None (text-only generation)
        """
        # Check for per-segment reference image URL
        ref_url = seg.get("reference_image_url", "")
        if ref_url:
            return ref_url

        # Use generated image as first frame
        img_path = images_dir / f"{img_id}.png"
        if img_path.exists():
            return self.uploader.upload(img_path)
        return None

    def _resolve_last_frame(self, seg: dict, images_dir: Path) -> str | None:
        """Resolve the last frame image if specified."""
        reference_chain_ids = seg.get("reference_chain_ids", [])
        if not reference_chain_ids:
            return None
        # TODO: Implement last_frame resolution from ReferenceImageChain
        # 当 reference_chain_ids 指向 next segment 的 image 时，可以提取作为尾帧
        return None

    # ── Seedance API Workflow ───────────────────────

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
        req = urllib.request.Request(create_url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")

        try:
            r = retry_with_backoff(
                lambda: json.loads(urllib.request.urlopen(req, timeout=60).read().decode()),
                max_retries=3,
                base_delay=2.0,
                retryable_exceptions=(urllib.error.URLError, urllib.error.HTTPError),
            )
        except Exception as e:
            logger.error(f"Task creation failed: {e}")
            return None

        task_id = r.get("id")
        if not task_id:
            logger.error(f"No task ID in response: {json.dumps(r, ensure_ascii=False)[:200]}")
            return None

        logger.info(f"  Task created: {task_id}")
        return task_id

    def _poll_task(self, task_id: str) -> str | None:
        """Poll task until completion. Returns video URL or None."""
        poll_url = f"{self.BASE_URL}/tasks/{task_id}"
        start_time = time.time()
        attempts = 0

        while time.time() - start_time < self.max_poll_time:
            attempts += 1
            req = urllib.request.Request(poll_url, method="GET")
            req.add_header("Authorization", f"Bearer {self.api_key}")

            try:
                r = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
            except Exception as e:
                logger.warning(f"  Poll error (attempt {attempts}): {e}")
                time.sleep(self.poll_interval)
                continue

            status = r.get("status", "unknown")
            logger.info(f"  Poll {attempts}: status={status}")

            if status == "succeeded":
                # 提取视频 URL
                content = r.get("content", {})
                if isinstance(content, dict):
                    video_url = content.get("video_url")
                    if video_url:
                        return video_url
                # 兼容其他可能的位置
                video_url = r.get("video_url") or r.get("url")
                if video_url:
                    return video_url
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
    ) -> bool:
        out_mp4 = videos_dir / f"{out_name}.mp4"
        if out_mp4.exists():
            return True

        # Step 1: Create task
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

        # Step 2: Poll until completion
        video_url = self._poll_task(task_id)
        if not video_url:
            return False

        # Step 3: Download video
        try:
            urllib.request.urlretrieve(video_url, str(out_mp4))
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False

        logger.info(f"OK {out_mp4.stat().st_size / 1024 / 1024:.1f}MB")
        return True
