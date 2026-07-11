from __future__ import annotations

from typing import Any

from narrascape.artifacts import write_artifact
from narrascape.reference_assets import resolve_reference_assets_for_shot
from narrascape.stages.base import Stage, StageContext, StageResult


class ReferencePlateStage(Stage):
    """Build per-shot reference plates for video generation and semantic QA."""

    name = "reference_plate"
    depends_on = ["director_contract"]
    outputs = ["pipeline/{name}/reference_plates.yaml"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        path = context.config.pipeline_dir / "director_contract.yaml"
        if not path.exists():
            return False, f"director_contract.yaml not found: {path}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        design = self._load_design(config)
        pre_production = self._load_yaml(config.pipeline_dir / "pre_production.yaml")
        director_contract = self._load_yaml(config.pipeline_dir / "director_contract.yaml")
        design_by_segment = self._design_by_segment(design)

        plates: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        for shot in director_contract.get("shots", []) or []:
            segment_id = self._segment_id(shot)
            design_segment = design_by_segment.get(segment_id or -1, {})
            manifest = resolve_reference_assets_for_shot(
                config.project_dir,
                contract=shot,
                design_segment=design_segment,
                pre_production=pre_production,
                design=design,
            )
            plate = self._plate_for_shot(shot, manifest)
            plates.append(plate)
            for missing_id in plate["missing_reference_ids"]:
                findings.append(
                    {
                        "segment_id": segment_id,
                        "shot_id": plate["shot_id"],
                        "risk_type": "reference_asset_missing",
                        "severity": "high",
                        "evidence": f"reference id could not be resolved: {missing_id}",
                    }
                )

        status = "blocked" if findings else "ready"
        blocking = status == "blocked" and config.pipeline.video_generation == "required"
        report = {
            "schema_version": "reference_plates.v1",
            "status": status,
            "blocking": blocking,
            "plate_count": len(plates),
            "plates": plates,
            "findings": findings,
        }
        out_path = config.pipeline_dir / "reference_plates.yaml"
        write_artifact("reference_plates", out_path, report)
        return StageResult(
            self.name,
            not blocking,
            outputs=[out_path],
            message=f"{len(plates)} reference plates, {len(findings)} finding(s)",
            metadata={
                "status": status,
                "blocking": blocking,
                "plate_count": len(plates),
                "findings": len(findings),
            },
        )

    def _load_design(self, config: Any) -> dict[str, Any]:
        for path in (
            config.pipeline_dir / "design_report.yaml",
            config.project_dir / "design_report.yaml",
        ):
            if path.exists():
                return self._load_yaml(path)
        return {}

    def _design_by_segment(self, design: dict[str, Any]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for item in design.get("segments", []) or []:
            try:
                result[int(item.get("segment_id"))] = item
            except (TypeError, ValueError):
                continue
        return result

    def _plate_for_shot(self, shot: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
        binding = shot.get("storyboard_binding", {}) if isinstance(shot, dict) else {}
        generation = shot.get("generation", {}) if isinstance(shot, dict) else {}
        return {
            "segment_id": self._segment_id(shot),
            "shot_id": str(shot.get("shot_id") or ""),
            "story_reason": str(shot.get("story_reason") or ""),
            "storyboard_frame_ids": list(binding.get("storyboard_frame_ids") or []),
            "character_positions": list(binding.get("character_positions") or []),
            "scene_ref": str(binding.get("scene_ref") or ""),
            "wardrobe_lock": str(binding.get("wardrobe_lock") or ""),
            "composition_requirements": list(binding.get("composition_requirements") or []),
            "storyboard_reference_image_ids": manifest["storyboard_reference_image_ids"],
            "expected_reference_ids": manifest["expected_reference_ids"],
            "missing_reference_ids": manifest["missing_reference_ids"],
            "reference_assets": [
                self._compact_reference_asset(asset) for asset in manifest["resolved_references"]
            ],
            "compiled_prompts": generation.get("compiled_prompts", {}),
            "prompt_blueprint": generation.get("prompt_blueprint", {}),
            "provider_negative_prompts": self._provider_negative_prompts(generation),
            "qa_requirements": shot.get("qa", {}),
        }

    def _provider_negative_prompts(self, generation: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        compiled = generation.get("compiled_prompts", {})
        if isinstance(compiled, dict):
            for provider, item in compiled.items():
                if isinstance(item, dict) and item.get("negative_prompt"):
                    result[str(provider)] = str(item["negative_prompt"])
        if generation.get("negative_prompt"):
            result.setdefault("generic", str(generation["negative_prompt"]))
        return result

    def _compact_reference_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        return {
            "requested_id": asset.get("requested_id"),
            "asset_id": asset.get("asset_id"),
            "role": asset.get("role"),
            "source": asset.get("source"),
            "path": asset.get("path"),
            "url": asset.get("url"),
            "exists": asset.get("exists"),
        }

    def _segment_id(self, shot: dict[str, Any]) -> int | None:
        value = shot.get("segment_id")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
