"""Service objects used by the generated-video stage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from narrascape.artifacts import write_artifact
from narrascape.prompt_compiler import provider_negative_prompt, provider_prompt
from narrascape.prompt_quality import video_prompt_quality_assessment
from narrascape.reference_assets import is_reference_uri, resolve_reference_assets_for_shot


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class VideoGenerationPlanner:
    """Owns video generation settings and per-shot planning helpers."""

    model: str
    agnes_model: str
    resolution: str
    ratio: str
    duration: int
    frame_rate: int
    takes: int
    sleep_between: float

    def apply_config(self, config: Any, provider: str) -> None:
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

    def active_model(self, provider: str) -> str:
        return self.agnes_model if provider == "agnes" else self.model

    def takes_per_shot(self) -> int:
        return max(1, int(self.takes or 1))

    def output_names_for_segment(self, base_id: str, take_count: int) -> list[str]:
        if take_count <= 1:
            return [base_id]
        return [f"{base_id}_take_{take_index:02d}" for take_index in range(1, take_count + 1)]

    def sleep_between_for_provider(self, provider: str) -> float:
        if provider == "agnes":
            return max(self.sleep_between, 65.0)
        return self.sleep_between

    def segment_model(self, seg: dict[str, Any], provider: str) -> str:
        if provider == "agnes":
            model = str(seg.get("agnes_model", "") or "")
            return model if model.startswith("agnes-") else self.agnes_model
        return str(seg.get("seedance_model", self.model) or self.model)

    def segment_resolution(self, seg: dict[str, Any], provider: str) -> str:
        key = "agnes_resolution" if provider == "agnes" else "seedance_resolution"
        return str(seg.get(key, self.resolution) or self.resolution)


class VideoPromptBuilder:
    """Builds provider-ready video prompts from contracts or legacy design data."""

    def build_prompt(
        self,
        seg: dict[str, Any],
        contract_by_segment: dict[int, dict[str, Any]] | None = None,
        provider: str | None = None,
    ) -> str:
        segment_id = _to_int(seg.get("segment_id"))
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
        cinematic = seg.get("cinematic_format", "")
        if cinematic:
            parts.append(cinematic)

        image_prompt = seg.get("image_prompt", "")
        if image_prompt:
            parts.append(image_prompt)

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

    def build_negative_prompt(self, contract: dict[str, Any], provider: str) -> str:
        generation = contract.get("generation", {}) if isinstance(contract, dict) else {}
        if not isinstance(generation, dict):
            return ""
        return provider_negative_prompt(generation, provider)


class VideoPromptQualityReporter:
    """Writes the prompt-quality gate artifact for generated-video runs."""

    def __init__(self, prompt_builder: VideoPromptBuilder | None = None):
        self.prompt_builder = prompt_builder or VideoPromptBuilder()

    def write_report(
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
            segment_id = _to_int(segment.get("segment_id"))
            if segment_id is None:
                continue
            checked_segments.append(segment_id)
            contract = contract_by_segment.get(segment_id, {})
            if not contract:
                continue
            prompt = self.prompt_builder.build_prompt(
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
        write_artifact(
            "video_prompt_quality", config.pipeline_dir / "video_prompt_quality.yaml", report
        )
        return report


class VideoReferenceResolver:
    """Resolves storyboard/plate references and provider frame inputs."""

    def __init__(self, uploader: Any):
        self.uploader = uploader

    def reference_inputs_for_segment(
        self,
        config: Any,
        design: dict[str, Any],
        pre_production: dict[str, Any],
        seg: dict[str, Any],
        contract: dict[str, Any],
        reference_plate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = self.reference_manifest_for_segment(
            config,
            design,
            pre_production,
            seg,
            contract,
            reference_plate,
        )
        uploaded_reference_assets = self.upload_reference_assets(manifest["resolved_references"])
        uploaded_reference_images = [
            asset["url"] for asset in uploaded_reference_assets if asset.get("url")
        ]
        compact_resolved = [
            self.compact_reference_asset(asset) for asset in manifest["resolved_references"]
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

    def reference_manifest_for_segment(
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

    def upload_reference_assets(self, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

    def compact_reference_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
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

    def resolve_first_frame(self, seg: dict[str, Any], images_dir: Path, img_id: str) -> str | None:
        ref_url = seg.get("reference_image_url", "")
        if ref_url:
            return str(ref_url)

        img_path = images_dir / f"{img_id}.png"
        if img_path.exists():
            return str(self.uploader.upload(img_path))
        return None

    def resolve_last_frame(
        self,
        seg: dict[str, Any],
        images_dir: Path,
        design: dict[str, Any] | None = None,
    ) -> str | None:
        for chain in self.last_frame_chains(seg, design or {}):
            for value in self.reference_chain_values(chain):
                resolved = self.resolve_frame_reference(value, images_dir)
                if resolved:
                    return resolved
            fallback = self.generated_image_for_chain(chain, images_dir)
            if fallback:
                return fallback
        return None

    def last_frame_chains(
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
        return [chain for chain in chains if self.is_last_frame_chain(chain)]

    def is_last_frame_chain(self, chain: dict[str, Any]) -> bool:
        usage = str(chain.get("usage_mode") or "").lower()
        chain_id = str(chain.get("chain_id") or "").lower()
        if usage == "last_frame":
            return True
        return any(marker in chain_id for marker in ("last_frame", "ending", "final_frame"))

    def reference_chain_values(self, chain: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in ("generated_images", "reference_urls", "reference_local_paths"):
            value = chain.get(key)
            if isinstance(value, list):
                values.extend(str(item) for item in value if item)
            elif value:
                values.append(str(value))
        return values

    def resolve_frame_reference(self, value: str, images_dir: Path) -> str | None:
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
                return str(self.uploader.upload(candidate))
        return None

    def generated_image_for_chain(self, chain: dict[str, Any], images_dir: Path) -> str | None:
        chain_id = str(chain.get("chain_id") or "")
        match = re.search(r"(?:img|segment|seg|shot)[_-]?(\d+)", chain_id, flags=re.IGNORECASE)
        if not match:
            return None
        image_path = images_dir / f"img_{int(match.group(1)):02d}.png"
        if image_path.exists():
            return str(self.uploader.upload(image_path))
        return None
