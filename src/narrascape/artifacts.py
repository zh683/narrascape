from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ArtifactValidationError(ValueError):
    """Raised when a canonical artifact does not match its schema."""


@dataclass(frozen=True)
class ArtifactSchema:
    name: str
    required: tuple[str, ...]
    schema_version: str | None = None

    def validate(self, data: dict[str, Any]) -> None:
        missing = [field for field in self.required if field not in data]
        if missing:
            raise ArtifactValidationError(
                f"{self.name} missing required field(s): {', '.join(missing)}"
            )
        if self.schema_version is not None:
            actual = data.get("schema_version")
            if actual != self.schema_version:
                raise ArtifactValidationError(
                    f"{self.name} schema_version must be {self.schema_version}, got {actual!r}"
                )


SCHEMAS = {
    "asset_manifest": ArtifactSchema("asset_manifest", ("assets",)),
    "continuity_bible": ArtifactSchema(
        "continuity_bible",
        ("schema_version", "characters", "locations", "continuity_risks"),
        "continuity_bible.v1",
    ),
    "creative_review": ArtifactSchema(
        "creative_review",
        ("schema_version", "status", "review_process", "findings", "recommendations"),
        "creative_review.v1",
    ),
    "design_report": ArtifactSchema("design_report", ("project_title", "segments")),
    "director_contract": ArtifactSchema(
        "director_contract",
        ("schema_version", "compile_process", "shots"),
        "director_contract.v1",
    ),
    "editing_review": ArtifactSchema(
        "editing_review",
        ("schema_version", "pacing", "repetition", "emotion_curve", "recommendations"),
        "editing_review.v1",
    ),
    "film_supervisor": ArtifactSchema(
        "film_supervisor",
        ("schema_version", "status", "decision", "next_stages"),
        "film_supervisor.v1",
    ),
    "film_timeline": ArtifactSchema(
        "film_timeline",
        ("schema_version", "project", "tracks", "coverage"),
        "film_timeline.v1",
    ),
    "render_report": ArtifactSchema("render_report", ("output", "checks")),
    "rework_execution": ArtifactSchema(
        "rework_execution",
        ("schema_version", "status", "executed_actions", "queues"),
        "rework_execution.v1",
    ),
    "rework_plan": ArtifactSchema(
        "rework_plan",
        ("schema_version", "status", "actions", "actions_by_type"),
        "rework_plan.v1",
    ),
    "screenplay_structure": ArtifactSchema(
        "screenplay_structure",
        ("schema_version", "grain_order", "acts", "shot_index"),
        "screenplay_structure.v1",
    ),
    "take_selection": ArtifactSchema(
        "take_selection",
        ("schema_version", "selection_process", "selections"),
        "take_selection.v1",
    ),
    "visual_semantic_report": ArtifactSchema(
        "visual_semantic_report",
        ("schema_version", "status", "review_process", "findings"),
        "visual_semantic_report.v1",
    ),
}


def validate_artifact(name: str, data: dict[str, Any]) -> None:
    schema = SCHEMAS.get(name)
    if schema is None:
        raise ArtifactValidationError(f"Unknown artifact schema: {name}")
    if not isinstance(data, dict):
        raise ArtifactValidationError(f"{name} must be a mapping")
    schema.validate(data)


def available_schemas() -> list[str]:
    return sorted(SCHEMAS)
