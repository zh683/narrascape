"""Generate images stage — integrate Volcengine Seedream 5.0 API.

Reads image_prompts.yaml, calls Ark API, outputs to assets/images/.
Supports reference images for character consistency and sequential batch mode.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

from narrascape.api_keys import APIKeys
from narrascape.config import NarrascapeConfig, load_image_prompts
from narrascape.providers import (
    record_provider_failure,
    record_provider_success,
    select_provider,
    selection_metadata,
)
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.uploader.image_uploader import ImageUploader
from narrascape.utils.ffmpeg import find_ffmpeg
from narrascape.utils.retry import retry_with_backoff
from narrascape.utils.safe_io import (
    atomic_write_json,
    download_to_path,
    ensure_min_free_space,
    load_json_mapping,
)

logger = logging.getLogger("narrascape.stages.generate_images")


class GenerateImagesStage(Stage):
    """Generate images from prompts using Volcengine Seedream 5.0.

    Inputs:  image_prompts.yaml
    Outputs: assets/images/img_*.png
    State:   pipeline/{name}/image_gen_state.json
    """

    name = "generate_images"
    depends_on = ["design"]
    outputs = []

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "doubao-seedream-5-0-260128",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        sequential_batch: int = 0,
        ref_image: str | None = None,
        sleep_between: float = 1.5,
        default_sample_strength: float = 0.5,
        uploader_backend: str = "base64",
    ):
        self.api_key = api_key or APIKeys.ark()
        self.model = model
        self.base_url = base_url
        self.sequential_batch = sequential_batch
        self.ref_image = ref_image
        self.sleep_between = sleep_between
        self.default_sample_strength = default_sample_strength
        self.uploader = ImageUploader(backend=uploader_backend)

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        config = context.config
        prompts_path = config.project_dir / "image_prompts.yaml"
        if not prompts_path.exists():
            return False, f"image_prompts.yaml not found: {prompts_path}"
        selection = select_provider(
            config, "image_generation", intent=self._intent_for_config(config)
        )
        if selection.tool.name == "local_image":
            return True, ""
        if not self.api_key:
            return False, (
                f"{selection.tool.name} selected but ARK_API_KEY not found. "
                "Set env var or .env file."
            )
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        project_dir = config.project_dir
        images_dir = config.images_dir
        images_dir.mkdir(parents=True, exist_ok=True)
        pipe_dir = config.pipeline_dir
        pipe_dir.mkdir(parents=True, exist_ok=True)
        selection = select_provider(
            config, "image_generation", intent=self._intent_for_config(config)
        )
        provider_meta = selection_metadata(selection)

        # Load prompts
        try:
            prompts = load_image_prompts(project_dir / "image_prompts.yaml")
        except ValidationError:
            return StageResult(self.name, False, message="No prompts in image_prompts.yaml")
        targets = prompts.prompts
        if not targets:
            return StageResult(self.name, False, message="No prompts in image_prompts.yaml")

        if selection.tool.name == "local_image":
            generated = []
            for i, prompt in enumerate(targets):
                out = images_dir / f"{prompt.id}.png"
                if not out.exists():
                    self._generate_local_placeholder(prompt, out, i, config)
                generated.append(out)
            state_path = pipe_dir / "image_gen_state.json"
            state = self._load_state(state_path)
            state["provider_selection"] = provider_meta
            state["done"] = [path.stem for path in generated]
            atomic_write_json(state_path, state)
            record_provider_success(config, selection.tool.name)
            return StageResult(
                self.name,
                True,
                outputs=generated,
                message=f"{len(generated)} local placeholder image(s)",
                metadata={
                    "mode": "local",
                    "count": len(generated),
                    "provider_selection": provider_meta,
                },
            )

        # Budget check
        from narrascape.utils.budget import BudgetTracker

        budget_tracker = BudgetTracker(config.budget, pipe_dir / "budget_state.json")
        est_cost = budget_tracker.get_cost_estimate("image", len(targets))
        can_spend, budget_msg = budget_tracker.can_spend(est_cost)
        if not can_spend:
            return StageResult(self.name, False, message=budget_msg)
        logger.info(budget_msg)

        # Asset isolation warning
        old_pngs = list(images_dir.glob("*.png"))
        if old_pngs:
            logger.warning(f"images/ has {len(old_pngs)} old PNGs. Archive before re-generating.")

        # Load state
        state_path = pipe_dir / "image_gen_state.json"
        state = self._load_state(state_path)
        state["provider_selection"] = provider_meta
        atomic_write_json(state_path, state)
        done = set(state.get("done", []))

        # Load ref image
        ref_image_b64 = None
        if self.ref_image:
            ref_image_b64 = self._load_ref_image(self.ref_image)
            logger.info(f"Reference image: {self.ref_image}")

        logger.info(f"Seedream: {len(targets)} images to generate")

        ok_count, fail_count = 0, 0

        if self.sequential_batch > 0:
            # Batch mode
            for batch_start in range(0, len(targets), self.sequential_batch):
                batch = targets[batch_start : batch_start + self.sequential_batch]
                prompts_text = [p.description.replace("\n", " ").strip() for p in batch]
                names = [p.id for p in batch]
                shot_type = batch[0].shot_type.value
                manual_size = batch[0].size
                size = self._derive_size(shot_type, manual_size)
                logger.info(
                    f"[Batch {batch_start // self.sequential_batch + 1}] {', '.join(names)} (size={size})"
                )
                results = self._generate_sequential(
                    prompts_text, names, size, ref_image_b64, images_dir
                )
                for r in results:
                    if r:
                        ok_count += 1
                        # Record actual cost per successful generation in batch
                        per_image = budget_tracker.get_cost_estimate("image", 1)
                        spend_ok, spend_msg = budget_tracker.try_spend(per_image)
                        if not spend_ok:
                            return StageResult(self.name, False, message=spend_msg)
                    else:
                        fail_count += 1
                if batch_start + self.sequential_batch < len(targets):
                    time.sleep(2)
        else:
            # Single mode - with per-prompt model and reference support
            for i, p in enumerate(targets):
                pid = p.id
                if pid in done and (images_dir / f"{pid}.png").exists():
                    logger.info(f"[{i + 1}/{len(targets)}] {pid} skip (cached)")
                    ok_count += 1
                    continue
                prompt_text = p.description.replace("\n", " ").strip()
                shot_type = p.shot_type.value
                size = self._derive_size(shot_type, p.size)

                # Extract per-prompt parameters from metadata
                negative_prompt = getattr(p, "negative_prompt", None) or ""
                seedream_model = getattr(p, "seedream_model", None) or self.model
                sample_strength = (
                    getattr(p, "seedream_sample_strength", None) or self.default_sample_strength
                )

                # Check for per-prompt reference images (multi-reference support)
                prompt_ref_image = ref_image_b64
                per_prompt_ref = getattr(p, "reference_image_url", None)
                per_prompt_refs = getattr(p, "reference_images", [])

                if per_prompt_refs:
                    # Multi-reference: upload all and pass as array
                    uploaded_refs = []
                    for ref_path in per_prompt_refs:
                        uploaded_refs.append(self._load_ref_image(ref_path))
                    prompt_ref_image = uploaded_refs
                    logger.info(f"  Per-prompt multi-reference: {len(uploaded_refs)} images")
                elif per_prompt_ref:
                    # Legacy single reference
                    prompt_ref_image = self._load_ref_image(per_prompt_ref)
                    logger.info(f"  Per-prompt reference: {per_prompt_ref}")

                logger.info(
                    f"[{i + 1}/{len(targets)}] {pid}: {prompt_text[:70]}... (size={size}, model={seedream_model})"
                )
                if self._generate_one(
                    prompt_text,
                    pid,
                    size,
                    prompt_ref_image,
                    images_dir,
                    negative_prompt=negative_prompt,
                    model=seedream_model,
                    sample_strength=sample_strength,
                ):
                    ok_count += 1
                    done.add(pid)
                    state["done"] = list(done)
                    atomic_write_json(state_path, state)
                    # Record actual cost per successful generation
                    per_image = budget_tracker.get_cost_estimate("image", 1)
                    spend_ok, spend_msg = budget_tracker.try_spend(per_image)
                    if not spend_ok:
                        return StageResult(self.name, False, message=spend_msg)
                else:
                    fail_count += 1
                if i < len(targets) - 1:
                    time.sleep(self.sleep_between)

        logger.info(f"Done: {ok_count} OK, {fail_count} failed")
        if fail_count == 0:
            record_provider_success(config, selection.tool.name)
        else:
            record_provider_failure(
                config,
                selection.tool.name,
                f"{fail_count}/{len(targets)} image generations failed",
            )
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
        return load_json_mapping(path, default={"done": [], "errors": []})

    def _intent_for_config(self, config: NarrascapeConfig) -> str:
        if config.images.provider.value == "local":
            return "offline"
        if self.ref_image:
            return "reference"
        return "creative"

    def _generate_local_placeholder(
        self, prompt: Any, out: Path, index: int, config: NarrascapeConfig
    ) -> None:
        """Generate a deterministic local image for offline pipeline verification."""
        palette = [
            ((35, 74, 101), (230, 194, 116)),
            ((88, 50, 73), (148, 191, 165)),
            ((43, 92, 76), (221, 136, 89)),
            ((99, 69, 36), (122, 171, 202)),
        ]
        bg, accent = palette[index % len(palette)]
        size = self._derive_size(prompt.shot_type.value, prompt.size)
        try:
            width, height = [int(part) for part in size.split("x")]
        except Exception:
            width, height = config.images.width, config.images.height
        width = min(width, 1920)
        height = min(height, 1080)

        image = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(image)
        for step in range(0, width, max(1, width // 18)):
            color = tuple(int(bg[c] + (accent[c] - bg[c]) * step / max(width, 1)) for c in range(3))
            draw.rectangle([step, 0, min(step + width // 18 + 1, width), height], fill=color)
        draw.rectangle(
            [width * 0.08, height * 0.12, width * 0.92, height * 0.88],
            outline=(245, 245, 235),
            width=max(2, width // 180),
        )
        font = ImageFont.load_default()
        label = f"{prompt.id} / {prompt.shot_type.value}"
        draw.text((width * 0.1, height * 0.14), label, fill=(255, 255, 255), font=font)
        desc = (prompt.description or "")[:120]
        y = int(height * 0.22)
        for line in [desc[i : i + 42] for i in range(0, len(desc), 42)][:4]:
            draw.text((width * 0.1, y), line, fill=(255, 255, 255), font=font)
            y += 18
        out.parent.mkdir(parents=True, exist_ok=True)
        ensure_min_free_space(out, min_free_mb=16.0, purpose=f"write placeholder {out.name}")
        image.save(out)

    def _derive_size(self, shot_type: str, manual_size: str | None) -> str:
        if manual_size:
            return manual_size
        # Sync with motion/factory SHOT_SIZE_MAP
        from narrascape.config import ShotType
        from narrascape.motion.factory import SHOT_SIZE_MAP

        try:
            st = ShotType(shot_type)
            return SHOT_SIZE_MAP.get(st, "2560x1440")
        except ValueError:
            return "2560x1440"

    def _load_ref_image(self, ref_path: str) -> str:
        """Upload or convert reference image for API consumption.

        Uses ImageUploader to handle different backends:
        - base64: returns data URI (default)
        - volcengine: uploads to Volcengine OSS and returns URL
        - http: uploads to generic HTTP endpoint and returns URL
        """
        return self.uploader.upload(ref_path)

    def _generate_one(
        self,
        prompt: str,
        out_name: str,
        size: str,
        ref_image: str | list[str] | None,
        images_dir: Path,
        negative_prompt: str = "",
        model: str | None = None,
        sample_strength: float | None = None,
        seed: int | None = None,
    ) -> bool:
        out_png = images_dir / f"{out_name}.png"
        if out_png.exists():
            return True

        # Use per-prompt model or default
        use_model = model or self.model

        payload = {
            "model": use_model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "url",
            "watermark": False,
        }
        if ref_image:
            # Seedream supports string (single) or array (multi, max 14)
            # Upload local paths via ImageUploader (base64/HTTP/Volcengine)
            if isinstance(ref_image, list):
                payload["image"] = [
                    self._load_ref_image(r) if r and not r.startswith(("http", "data:")) else r
                    for r in ref_image
                ]
            elif isinstance(ref_image, str) and not ref_image.startswith(("http", "data:")):
                payload["image"] = self._load_ref_image(ref_image)
            else:
                payload["image"] = ref_image
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if sample_strength is not None:
            payload["sample_strength"] = sample_strength
        if seed is not None:
            payload["seed"] = seed

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")

        try:
            r = retry_with_backoff(
                lambda: json.loads(urllib.request.urlopen(req, timeout=180).read().decode()),
                max_retries=3,
                base_delay=2.0,
                retryable_exceptions=(urllib.error.URLError, urllib.error.HTTPError),
            )
        except urllib.error.HTTPError as e:
            # Log response body for debugging
            try:
                body = e.read().decode()
                logger.error(f"HTTP {e.code} error: {body[:500]}")
            except Exception:
                logger.error(f"HTTP {e.code} error: {e}")
            return False
        except Exception as e:
            logger.error(f"HTTP/API error: {e}")
            return False

        data_field = r.get("data", [])
        img_url = None
        if isinstance(data_field, list) and data_field:
            img_url = data_field[0].get("url")
        elif isinstance(data_field, dict):
            img_url = data_field.get("url")
        else:
            img_url = r.get("url") or r.get("image_url")

        if not img_url:
            logger.error(f"No URL in response: {json.dumps(r, ensure_ascii=False)[:200]}")
            return False

        # Download and convert to PNG
        tmp = images_dir / f"_tmp_{out_name}.jpg"
        try:
            download_to_path(img_url, tmp, timeout=180, min_bytes=128, min_free_mb=32.0)
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError("download produced an empty image file")
            ensure_min_free_space(out_png, min_free_mb=32.0, purpose=f"write {out_png.name}")
            ffmpeg = find_ffmpeg()
            subprocess.run(
                [ffmpeg, "-y", "-i", str(tmp), str(out_png)], check=True, capture_output=True
            )
            if not out_png.exists() or out_png.stat().st_size == 0:
                raise RuntimeError("ffmpeg conversion produced an empty PNG")
        except Exception as e:
            logger.error(f"Download failed: {e}")
            tmp.unlink(missing_ok=True)
            out_png.unlink(missing_ok=True)
            return False
        finally:
            tmp.unlink(missing_ok=True)

        logger.info(f"OK {out_png.stat().st_size / 1024:.0f}KB")
        return True

    def _generate_sequential(
        self,
        prompts: list[str],
        names: list[str],
        size: str,
        ref_image: str | list[str] | None,
        images_dir: Path,
    ) -> list[bool]:
        results = [False] * len(names)
        to_gen_idx = [i for i, n in enumerate(names) if not (images_dir / f"{n}.png").exists()]
        if not to_gen_idx:
            return [True] * len(names)

        combined_parts = [f"Image {i + 1}: {prompts[i]}" for i in to_gen_idx]
        combined_prompt = ". ".join(combined_parts)

        payload = {
            "model": self.model,
            "prompt": combined_prompt,
            "n": len(to_gen_idx),
            "size": size,
            "response_format": "url",
            "watermark": False,
            "sequentialImageGeneration": "enabled",
        }
        if ref_image:
            payload["image"] = ref_image

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")

        try:
            r = retry_with_backoff(
                lambda: json.loads(urllib.request.urlopen(req, timeout=300).read().decode()),
                max_retries=3,
                base_delay=2.0,
                retryable_exceptions=(urllib.error.URLError, urllib.error.HTTPError),
            )
        except Exception as e:
            logger.error(f"HTTP/API error: {e}")
            return results

        data_field = r.get("data", [])
        urls = []
        if isinstance(data_field, list):
            urls = [item.get("url") for item in data_field if item.get("url")]
        elif isinstance(data_field, dict) and data_field.get("url"):
            urls = [data_field["url"]]

        ffmpeg = find_ffmpeg()
        for j, gen_idx in enumerate(to_gen_idx):
            if j >= len(urls):
                logger.error(f"{names[gen_idx]} no URL returned")
                continue
            name = names[gen_idx]
            out_png = images_dir / f"{name}.png"
            tmp = images_dir / f"_tmp_{name}.jpg"
            try:
                download_to_path(urls[j], tmp, timeout=180, min_bytes=128, min_free_mb=32.0)
                ensure_min_free_space(out_png, min_free_mb=32.0, purpose=f"write {out_png.name}")
                subprocess.run(
                    [ffmpeg, "-y", "-i", str(tmp), str(out_png)], check=True, capture_output=True
                )
                if not out_png.exists() or out_png.stat().st_size == 0:
                    raise RuntimeError("ffmpeg conversion produced an empty PNG")
            except Exception as exc:
                logger.error(f"{name} download/convert failed: {exc}")
                tmp.unlink(missing_ok=True)
                out_png.unlink(missing_ok=True)
                continue
            finally:
                tmp.unlink(missing_ok=True)
            results[gen_idx] = True
            logger.info(f"{name} OK {out_png.stat().st_size / 1024:.0f}KB")

        return results
