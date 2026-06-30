from __future__ import annotations

from pathlib import Path
from typing import Any

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import atomic_write_yaml, load_yaml_mapping


class ProductionReadinessStage(Stage):
    """Gate generated-video execution on the readiness of prep artifacts."""

    name = "production_readiness"
    depends_on = ["reference_plate", "storyboard_sheet", "animatic"]
    outputs = ["pipeline/{name}/production_readiness.yaml"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "production_readiness.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)

        reference_plates = self._load_yaml(config.pipeline_dir / "reference_plates.yaml")
        storyboard_sheet = self._load_yaml(config.pipeline_dir / "storyboard_sheet.yaml")
        animatic = self._load_yaml(config.pipeline_dir / "animatic.yaml")
        pre_production = self._load_yaml(config.pipeline_dir / "pre_production.yaml")
        director_contract = self._load_yaml(config.pipeline_dir / "director_contract.yaml")

        gates = [
            self._gate(
                "reference_plates",
                config.pipeline_dir / "reference_plates.yaml",
                reference_plates,
                required_status="ready",
            ),
            self._gate(
                "storyboard_sheet",
                config.pipeline_dir / "storyboard_sheet.yaml",
                storyboard_sheet,
                required_status="ready",
            ),
            self._gate(
                "animatic",
                config.pipeline_dir / "animatic.yaml",
                animatic,
                required_status="ready",
            ),
        ]
        if self._strict_prep_enabled(config):
            gates.extend(
                [
                    self._script_gate(context),
                    self._pre_production_gate(
                        config.pipeline_dir / "pre_production.yaml",
                        pre_production,
                        context,
                    ),
                    self._director_contract_gate(
                        config.pipeline_dir / "director_contract.yaml",
                        director_contract,
                        context,
                    ),
                ]
            )
        findings = [finding for gate in gates for finding in gate["findings"]]
        status = "ready" if not findings else "blocked"
        blocking = status != "ready" and (
            getattr(config.pipeline, "video_generation", "auto") == "required"
            or self._strict_prep_enabled(config)
        )
        report = {
            "schema_version": "production_readiness.v1",
            "project": {"name": config.project.name, "title": config.project.title},
            "status": status,
            "blocking": blocking,
            "video_generation_policy": getattr(config.pipeline, "video_generation", "auto"),
            "production_quality_gates": self._strict_prep_enabled(config),
            "gates": gates,
            "findings": findings,
        }
        validate_artifact("production_readiness", report)
        atomic_write_yaml(output, report)
        return StageResult(
            self.name,
            not blocking,
            outputs=[output],
            message=(
                "prep gates ready"
                if status == "ready"
                else f"{len(findings)} production readiness issue(s); generated video gated"
            ),
            metadata={
                "status": status,
                "blocking": blocking,
                "finding_count": len(findings),
            },
        )

    def _gate(
        self,
        stage_name: str,
        path: Path,
        artifact: dict[str, Any],
        *,
        required_status: str,
    ) -> dict[str, Any]:
        actual_status = str(artifact.get("status") or "missing")
        findings = list(artifact.get("findings", []) or [])
        gate_findings: list[dict[str, Any]] = []
        if not path.exists():
            gate_findings.append(
                {
                    "stage": stage_name,
                    "risk_type": f"{stage_name}_missing",
                    "severity": "high",
                    "evidence": f"missing prep artifact: {path.as_posix()}",
                }
            )
        elif actual_status != required_status:
            gate_findings.append(
                {
                    "stage": stage_name,
                    "risk_type": f"{stage_name}_not_ready",
                    "severity": "high",
                    "evidence": f"{stage_name} status is {actual_status!r}, expected {required_status!r}",
                }
            )
        if findings and actual_status != required_status:
            gate_findings.append(
                {
                    "stage": stage_name,
                    "risk_type": f"{stage_name}_has_findings",
                    "severity": "high",
                    "evidence": f"{stage_name} has {len(findings)} finding(s)",
                }
            )
        return {
            "stage": stage_name,
            "path": path.as_posix(),
            "required_status": required_status,
            "status": actual_status,
            "finding_count": len(findings),
            "findings": gate_findings,
        }

    def _strict_prep_enabled(self, config: Any) -> bool:
        return bool(getattr(config.pipeline, "production_quality_gates", False))

    def _script_gate(self, context: StageContext) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        segments = list(getattr(context.script, "segments", []) or [])
        if not segments:
            findings.append(
                {
                    "stage": "script",
                    "risk_type": "script_missing_segments",
                    "severity": "high",
                    "evidence": "script has no segments",
                }
            )
        short_segments = [
            int(segment.id)
            for segment in segments
            if len(str(getattr(segment, "text", "") or "").split()) < 6
        ]
        if short_segments:
            findings.append(
                {
                    "stage": "script",
                    "risk_type": "script_segment_underwritten",
                    "severity": "medium",
                    "evidence": "segment(s) too short for production direction: "
                    + ", ".join(str(item) for item in short_segments),
                }
            )
        return {
            "stage": "script",
            "path": context.config.script_path.as_posix(),
            "required_status": "production_ready",
            "status": "ready" if not findings else "blocked",
            "segment_count": len(segments),
            "finding_count": len(findings),
            "findings": findings,
        }

    def _pre_production_gate(
        self,
        path: Path,
        artifact: dict[str, Any],
        context: StageContext,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        frames = self._storyboard_frames(artifact)
        characters = artifact.get("characters", []) or []
        environments = artifact.get("environments", []) or []
        if not path.exists():
            findings.append(self._finding("pre_production", "pre_production_missing", path))
        if not characters:
            findings.append(
                {
                    "stage": "pre_production",
                    "risk_type": "character_bible_missing",
                    "severity": "high",
                    "evidence": "pre_production.yaml has no character references",
                }
            )
        if not environments:
            findings.append(
                {
                    "stage": "pre_production",
                    "risk_type": "scene_bible_missing",
                    "severity": "high",
                    "evidence": "pre_production.yaml has no scene/environment references",
                }
            )
        segment_ids = {int(segment.id) for segment in context.script.segments}
        storyboard_segment_ids = {
            segment_id
            for segment_id in (self._to_int(frame.get("segment_id")) for frame in frames)
            if segment_id is not None
        }
        missing_storyboards = sorted(segment_ids - storyboard_segment_ids)
        if missing_storyboards:
            findings.append(
                {
                    "stage": "pre_production",
                    "risk_type": "storyboard_segment_missing",
                    "severity": "high",
                    "evidence": "missing storyboard frame(s) for segment(s): "
                    + ", ".join(str(item) for item in missing_storyboards),
                }
            )
        unbound_frames = [
            str(frame.get("frame_id") or frame.get("segment_id") or "unknown")
            for frame in frames
            if not frame.get("reference_image_ids")
            or not frame.get("scene_ref")
            or not frame.get("character_positions")
        ]
        if unbound_frames:
            findings.append(
                {
                    "stage": "pre_production",
                    "risk_type": "storyboard_binding_incomplete",
                    "severity": "medium",
                    "evidence": "storyboard frame(s) lack references, scene, or positions: "
                    + ", ".join(unbound_frames[:8]),
                }
            )
        return {
            "stage": "pre_production",
            "path": path.as_posix(),
            "required_status": "complete_storyboard_bible",
            "status": "ready" if not findings else "blocked",
            "character_count": len(characters),
            "scene_count": len(environments),
            "storyboard_frame_count": len(frames),
            "finding_count": len(findings),
            "findings": findings,
        }

    def _director_contract_gate(
        self,
        path: Path,
        artifact: dict[str, Any],
        context: StageContext,
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if not path.exists():
            findings.append(self._finding("director_contract", "director_contract_missing", path))
        shots = artifact.get("shots", []) or []
        segment_ids = {int(segment.id) for segment in context.script.segments}
        shot_segment_ids = {
            segment_id
            for segment_id in (self._to_int(shot.get("segment_id")) for shot in shots)
            if segment_id is not None
        }
        missing_shots = sorted(segment_ids - shot_segment_ids)
        if missing_shots:
            findings.append(
                {
                    "stage": "director_contract",
                    "risk_type": "director_contract_shot_missing",
                    "severity": "high",
                    "evidence": "missing director contract shot(s) for segment(s): "
                    + ", ".join(str(item) for item in missing_shots),
                }
            )
        for shot in shots:
            segment_id = self._to_int(shot.get("segment_id"))
            binding = shot.get("storyboard_binding", {}) if isinstance(shot, dict) else {}
            generation = shot.get("generation", {}) if isinstance(shot, dict) else {}
            qa = shot.get("qa", {}) if isinstance(shot, dict) else {}
            continuity = shot.get("continuity_constraints", {}) if isinstance(shot, dict) else {}
            missing_components = []
            if not binding.get("storyboard_frame_ids"):
                missing_components.append("storyboard_frame_ids")
            if not binding.get("reference_image_ids"):
                missing_components.append("reference_image_ids")
            if not binding.get("wardrobe_lock"):
                missing_components.append("wardrobe_lock")
            if not continuity.get("characters"):
                missing_components.append("characters")
            if not continuity.get("location"):
                missing_components.append("location")
            if not generation.get("compiled_prompts"):
                missing_components.append("compiled_prompts")
            if not generation.get("prompt_blueprint"):
                missing_components.append("prompt_blueprint")
            if not qa.get("must_show"):
                missing_components.append("qa.must_show")
            if missing_components:
                findings.append(
                    {
                        "stage": "director_contract",
                        "segment_id": segment_id,
                        "risk_type": "shot_contract_incomplete",
                        "severity": "high",
                        "evidence": "shot contract missing: " + ", ".join(missing_components),
                    }
                )
        return {
            "stage": "director_contract",
            "path": path.as_posix(),
            "required_status": "complete_executable_contract",
            "status": "ready" if not findings else "blocked",
            "shot_count": len(shots),
            "finding_count": len(findings),
            "findings": findings,
        }

    def _storyboard_frames(self, artifact: dict[str, Any]) -> list[dict[str, Any]]:
        frames = artifact.get("storyboard", {}).get("frames", []) or []
        return [frame for frame in frames if isinstance(frame, dict)]

    def _finding(self, stage: str, risk_type: str, path: Path) -> dict[str, Any]:
        return {
            "stage": stage,
            "risk_type": risk_type,
            "severity": "high",
            "evidence": f"missing prep artifact: {path.as_posix()}",
        }

    def _to_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return load_yaml_mapping(path)
