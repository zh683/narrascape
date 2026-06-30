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
        findings = [finding for gate in gates for finding in gate["findings"]]
        status = "ready" if not findings else "blocked"
        blocking = (
            status != "ready" and getattr(config.pipeline, "video_generation", "auto") == "required"
        )
        report = {
            "schema_version": "production_readiness.v1",
            "project": {"name": config.project.name, "title": config.project.title},
            "status": status,
            "blocking": blocking,
            "video_generation_policy": getattr(config.pipeline, "video_generation", "auto"),
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

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return load_yaml_mapping(path)
