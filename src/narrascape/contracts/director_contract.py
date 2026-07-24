"""Typed model for `director_contract.yaml` (schema_version: director_contract.v1).

Field set traced from the writers in `stages/director_contract.py`
(`_compile_locally`, `_normalize_shot`, `_with_compiled_prompts`,
`_prompt_blueprint`) and `prompt_compiler.compile_video_prompts`, verified
against production artifacts under `examples/` and `.narrascape/`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from narrascape.contracts.common import ContractModel, ProjectRef


class FilmLanguage(ContractModel):
    shot_type: str = "medium"
    camera_motion: str = "still"
    lighting: str = ""
    composition: str = ""


class ContinuityConstraints(ContractModel):
    characters: list[str] = Field(default_factory=list)
    location: str = ""
    wardrobe: str = ""
    lighting: str = ""


class StoryboardBinding(ContractModel):
    storyboard_frame_ids: list[str] = Field(default_factory=list)
    character_positions: list[str] = Field(default_factory=list)
    scene_ref: str = ""
    wardrobe_lock: str = ""
    composition_requirements: list[str] = Field(default_factory=list)
    reference_image_ids: list[str] = Field(default_factory=list)


class CameraPlan(ContractModel):
    shot_type: str = "medium"
    motion: str = "still"
    lighting: str = ""
    composition: str = ""


class BlueprintContinuityLocks(ContractModel):
    characters: list[str] = Field(default_factory=list)
    location: str = ""
    wardrobe: str = ""
    lighting: str = ""


class BlueprintStoryboardLocks(ContractModel):
    storyboard_frame_ids: list[str] = Field(default_factory=list)
    character_positions: list[str] = Field(default_factory=list)
    scene_ref: str = ""
    wardrobe_lock: str = ""
    composition_requirements: list[str] = Field(default_factory=list)


class ReferenceStrategy(ContractModel):
    required_reference_image_ids: list[str] = Field(default_factory=list)
    provider_flow: str = ""
    identity_priority: str = ""


class ShotQaAssertion(ContractModel):
    """A single QA assertion tagged with a stable cinemetrics dimension.

    ``dimension`` is one of the ids in
    :data:`narrascape.contracts.qa_taxonomy.QA_DIMENSIONS`; unknown values are
    tolerated and bucketed as ``uncategorized`` by the taxonomy helpers.
    """

    id: str = ""
    dimension: str = ""
    check: str = ""


class QaAssertions(ContractModel):
    must_show: list[str] = Field(default_factory=list)
    must_not_show: list[str] = Field(default_factory=list)
    assertions: list[ShotQaAssertion] = Field(default_factory=list)


class PromptBlueprint(ContractModel):
    schema_version: str = "prompt_blueprint.v1"
    narrative_intent: str = ""
    emotional_target: str = ""
    subject_action: str = ""
    camera_plan: CameraPlan = Field(default_factory=CameraPlan)
    continuity_locks: BlueprintContinuityLocks = Field(default_factory=BlueprintContinuityLocks)
    storyboard_locks: BlueprintStoryboardLocks = Field(default_factory=BlueprintStoryboardLocks)
    reference_strategy: ReferenceStrategy = Field(default_factory=ReferenceStrategy)
    style_anchor: str = ""
    quality_bar: list[str] = Field(default_factory=list)
    qa_assertions: QaAssertions = Field(default_factory=QaAssertions)


class CompiledProviderPrompt(ContractModel):
    prompt: str = ""
    negative_prompt: str = ""
    prompt_style: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class CompiledPrompts(ContractModel):
    seedance: CompiledProviderPrompt | None = None
    agnes: CompiledProviderPrompt | None = None
    generic: CompiledProviderPrompt | None = None


class GenerationContract(ContractModel):
    video_prompt: str = ""
    negative_prompt: str = ""
    duration: float = 5.0
    motion: str = ""
    # Present on all shots written since prompt_compiler.v2; optional so
    # contracts produced by older pipeline versions keep loading.
    prompt_schema_version: str | None = None
    prompt_blueprint: PromptBlueprint | None = None
    compiled_prompts: CompiledPrompts | None = None


class ShotQa(ContractModel):
    """Acceptance hints for downstream QA stages.

    ``assertions`` is an additive structured checklist alongside the flat
    ``must_show`` / ``must_not_show`` token lists; both planes stay populated
    so older consumers keep working unchanged.
    """

    must_show: list[str] = Field(default_factory=list)
    must_not_show: list[str] = Field(default_factory=list)
    assertions: list[ShotQaAssertion] = Field(default_factory=list)


class DirectorShot(ContractModel):
    segment_id: int = 0
    shot_id: str = ""
    story_reason: str = ""
    emotional_target: str = ""
    film_language: FilmLanguage = Field(default_factory=FilmLanguage)
    continuity_constraints: ContinuityConstraints = Field(default_factory=ContinuityConstraints)
    storyboard_binding: StoryboardBinding = Field(default_factory=StoryboardBinding)
    generation: GenerationContract = Field(default_factory=GenerationContract)
    qa: ShotQa = Field(default_factory=ShotQa)


class CompileProcess(ContractModel):
    mode: str = ""
    llm_status: str = ""
    llm_error: str = ""
    rework_segment_ids: list[int] = Field(default_factory=list)


class DirectorContract(ContractModel):
    """Top-level director_contract.yaml model (write-side gate + typed reads)."""

    schema_version: Literal["director_contract.v1"]
    project: ProjectRef = Field(default_factory=ProjectRef)
    compile_process: CompileProcess
    shots: list[DirectorShot]
