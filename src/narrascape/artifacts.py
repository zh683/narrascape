from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from narrascape.artifact_migrations import ArtifactMigrationError, migrate_artifact
from narrascape.utils.safe_io import atomic_write_yaml, load_json_mapping, load_yaml_mapping


class ArtifactValidationError(ValueError):
    """Raised when a canonical artifact does not match its typed schema."""


class ArtifactModel(BaseModel):
    """Typed core for canonical artifacts while preserving stage extensions."""

    model_config = ConfigDict(extra="allow")


class ProjectRef(ArtifactModel):
    name: str = ""
    title: str = ""


class AssetManifestArtifact(ArtifactModel):
    schema_version: Literal["asset_manifest.v1"]
    assets: list[dict[str, Any]]


class ScriptArtifact(ArtifactModel):
    schema_version: Literal["script.v1"]
    title: str = ""
    segments: list[dict[str, Any]]


class PreProductionArtifact(ArtifactModel):
    schema_version: Literal["pre_production.v1"]
    project_title: str = ""
    style_template: str = ""
    characters: list[dict[str, Any]] = Field(default_factory=list)
    environments: list[dict[str, Any]] = Field(default_factory=list)
    storyboard: dict[str, Any] = Field(default_factory=dict)
    director_process: dict[str, Any] = Field(default_factory=dict)


class DesignReportArtifact(ArtifactModel):
    schema_version: Literal["design_report.v1"]
    project_title: str
    segments: list[dict[str, Any]]


class AnimaticArtifact(ArtifactModel):
    schema_version: Literal["animatic.v1"]
    status: str
    panels: list[dict[str, Any]]
    findings: list[dict[str, Any]]


class AssistantHandoffArtifact(ArtifactModel):
    schema_version: Literal["assistant_handoff.v1"]
    project: dict[str, Any]
    status: str
    director_decision: dict[str, Any]
    assistant_contract: list[dict[str, Any]]
    required_reading: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    quality_gates: list[dict[str, Any]]
    next_actions: list[dict[str, Any]]
    commands: dict[str, Any]


class ContinuityBibleArtifact(ArtifactModel):
    schema_version: Literal["continuity_bible.v1"]
    characters: dict[str, Any]
    locations: dict[str, Any]
    continuity_risks: list[dict[str, Any]]


class ReviewArtifact(ArtifactModel):
    status: str
    findings: list[dict[str, Any]]


class CreativeReviewArtifact(ReviewArtifact):
    schema_version: Literal["creative_review.v1"]
    review_process: dict[str, Any]
    recommendations: list[dict[str, Any]]


class DirectorContractArtifact(ArtifactModel):
    schema_version: Literal["director_contract.v1"]
    compile_process: dict[str, Any]
    shots: list[dict[str, Any]]


class EditingReviewArtifact(ArtifactModel):
    schema_version: Literal["editing_review.v1"]
    pacing: dict[str, Any]
    repetition: dict[str, Any]
    emotion_curve: dict[str, Any]
    recommendations: list[dict[str, Any]]


class DirectorReviewArtifact(ArtifactModel):
    schema_version: Literal["director_review.v1"]
    status: str
    source_report: str = ""
    rework_queue: list[dict[str, Any]]
    notes: list[str] = Field(default_factory=list)


class FilmSupervisorArtifact(ArtifactModel):
    schema_version: Literal["film_supervisor.v1"]
    status: Literal["approved", "needs_rework"]
    decision: dict[str, Any]
    next_stages: list[str]


class ProductionReadinessArtifact(ArtifactModel):
    schema_version: Literal["production_readiness.v1"]
    project: dict[str, Any]
    status: str
    gates: list[dict[str, Any]]
    findings: list[dict[str, Any]]


class FilmTimelineArtifact(ArtifactModel):
    schema_version: Literal["film_timeline.v1"]
    project: dict[str, Any]
    tracks: dict[str, list[dict[str, Any]]]
    coverage: dict[str, Any]


class RenderReportArtifact(ArtifactModel):
    schema_version: Literal["render_report.v1"]
    output: str
    checks: dict[str, Any]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReferencePlatesArtifact(ArtifactModel):
    schema_version: Literal["reference_plates.v1"]
    status: str
    plates: list[dict[str, Any]]
    findings: list[dict[str, Any]]


class RemotionPreviewArtifact(ArtifactModel):
    schema_version: Literal["remotion_preview.v1"]
    status: str
    project: dict[str, Any]
    composition: dict[str, Any]
    assets: dict[str, Any]
    commands: dict[str, Any]


class ReworkExecutionArtifact(ArtifactModel):
    schema_version: Literal["rework_execution.v1"]
    status: str
    executed_actions: list[dict[str, Any]]
    queues: dict[str, Any]


class ReworkPlanArtifact(ArtifactModel):
    schema_version: Literal["rework_plan.v1"]
    status: str
    actions: list[dict[str, Any]]
    actions_by_type: dict[str, list[dict[str, Any]]]


class ScreenplayStructureArtifact(ArtifactModel):
    schema_version: Literal["screenplay_structure.v1"]
    grain_order: list[str]
    acts: list[dict[str, Any]]
    shot_index: list[dict[str, Any]] | dict[str, Any]


class StoryboardSheetArtifact(ArtifactModel):
    schema_version: Literal["storyboard_sheet.v1"]
    status: str
    project: dict[str, Any]
    shot_count: int = Field(ge=0)
    page_count: int = Field(ge=0)
    pages: list[dict[str, Any]]
    findings: list[dict[str, Any]]


class TakeSelectionArtifact(ArtifactModel):
    schema_version: Literal["take_selection.v1"]
    selection_process: dict[str, Any]
    selections: list[dict[str, Any]]


class VisualSemanticReportArtifact(ReviewArtifact):
    schema_version: Literal["visual_semantic_report.v1"]
    review_process: dict[str, Any]


class VideoPromptQualityArtifact(ArtifactModel):
    schema_version: Literal["video_prompt_quality.v1"]
    status: str
    findings: list[dict[str, Any]]


ARTIFACT_MODELS: dict[str, type[ArtifactModel]] = {
    "asset_manifest": AssetManifestArtifact,
    "animatic": AnimaticArtifact,
    "assistant_handoff": AssistantHandoffArtifact,
    "continuity_bible": ContinuityBibleArtifact,
    "creative_review": CreativeReviewArtifact,
    "design_report": DesignReportArtifact,
    "director_contract": DirectorContractArtifact,
    "director_review": DirectorReviewArtifact,
    "editing_review": EditingReviewArtifact,
    "film_supervisor": FilmSupervisorArtifact,
    "film_timeline": FilmTimelineArtifact,
    "pre_production": PreProductionArtifact,
    "production_readiness": ProductionReadinessArtifact,
    "reference_plates": ReferencePlatesArtifact,
    "remotion_preview": RemotionPreviewArtifact,
    "render_report": RenderReportArtifact,
    "rework_execution": ReworkExecutionArtifact,
    "rework_plan": ReworkPlanArtifact,
    "screenplay_structure": ScreenplayStructureArtifact,
    "script": ScriptArtifact,
    "storyboard_sheet": StoryboardSheetArtifact,
    "take_selection": TakeSelectionArtifact,
    "video_prompt_quality": VideoPromptQualityArtifact,
    "visual_semantic_report": VisualSemanticReportArtifact,
}

CANONICAL_FILENAMES: dict[str, str] = {
    "asset_manifest.yaml": "asset_manifest",
    "animatic.yaml": "animatic",
    "assistant_handoff.yaml": "assistant_handoff",
    "continuity_bible.yaml": "continuity_bible",
    "creative_review.yaml": "creative_review",
    "design_report.yaml": "design_report",
    "director_contract.yaml": "director_contract",
    "director_review.yaml": "director_review",
    "editing_review.yaml": "editing_review",
    "film_supervisor.yaml": "film_supervisor",
    "film_timeline.yaml": "film_timeline",
    "pre_production.yaml": "pre_production",
    "production_readiness.yaml": "production_readiness",
    "reference_plates.yaml": "reference_plates",
    "remotion_preview.yaml": "remotion_preview",
    "render_report.yaml": "render_report",
    "rework_execution.yaml": "rework_execution",
    "rework_plan.yaml": "rework_plan",
    "screenplay_structure.yaml": "screenplay_structure",
    "script.yaml": "script",
    "storyboard_sheet.yaml": "storyboard_sheet",
    "take_selection.yaml": "take_selection",
    "video_prompt_quality.yaml": "video_prompt_quality",
    "visual_semantic_report.yaml": "visual_semantic_report",
}


def validate_artifact(name: str, data: dict[str, Any]) -> dict[str, Any]:
    model = ARTIFACT_MODELS.get(name)
    if model is None:
        raise ArtifactValidationError(f"Unknown artifact schema: {name}")
    if not isinstance(data, dict):
        raise ArtifactValidationError(f"{name} must be a mapping")
    try:
        migrated = migrate_artifact(name, data)
        return model.model_validate(migrated).model_dump(mode="python")
    except ArtifactMigrationError as exc:
        raise ArtifactValidationError(str(exc)) from exc
    except ValidationError as exc:
        raise ArtifactValidationError(f"Invalid {name} artifact: {exc}") from exc


def load_artifact(name: str, path: Path) -> dict[str, Any]:
    """Load and validate a canonical YAML or JSON artifact."""
    target = Path(path)
    data = (
        load_json_mapping(target) if target.suffix.lower() == ".json" else load_yaml_mapping(target)
    )
    return validate_artifact(name, data)


def load_artifact_file(path: Path, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate known canonical filenames and load other YAML mappings normally."""
    target = Path(path)
    if not target.exists():
        return dict(default or {})
    artifact_name = CANONICAL_FILENAMES.get(target.name)
    if artifact_name:
        return load_artifact(artifact_name, target)
    return load_yaml_mapping(target, default=default)


def write_artifact(name: str, path: Path, data: dict[str, Any]) -> None:
    """Validate a canonical artifact before atomically replacing its YAML file."""
    normalized = validate_artifact(name, data)
    atomic_write_yaml(path, normalized)


def available_schemas() -> list[str]:
    return sorted(ARTIFACT_MODELS)
