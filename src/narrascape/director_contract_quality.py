from __future__ import annotations

from collections import Counter
from typing import Any

from narrascape.contracts.qa_taxonomy import QA_DIMENSIONS, normalize_assertions

GENERIC_VALUES = {
    "",
    "focused",
    "the named character",
    "the specified scene",
    "the locked wardrobe",
    "story location",
    "consistent wardrobe",
    "composition serves the story beat",
    "serve the story beat",
}


def shot_semantic_errors(
    shot: dict[str, Any],
    *,
    require_advanced: bool,
    require_compiled: bool,
) -> list[str]:
    """Return actionable semantic errors for one director-contract shot."""
    errors: list[str] = []
    shot_id = str(shot.get("shot_id") or "<missing-shot-id>")

    def require_text(container: dict[str, Any], key: str, label: str) -> str:
        value = str(container.get(key) or "").strip()
        if not value or value.casefold() in GENERIC_VALUES:
            errors.append(f"{shot_id}: {label} must be concrete")
        return value

    story_reason = require_text(shot, "story_reason", "story_reason")
    subject_action = require_text(shot, "subject_action", "subject_action")
    if story_reason and subject_action and story_reason.casefold() == subject_action.casefold():
        errors.append(f"{shot_id}: subject_action must be distinct from story_reason")

    raw_film = shot.get("film_language")
    film: dict[str, Any] = raw_film if isinstance(raw_film, dict) else {}
    for key in ("shot_type", "camera_motion", "lighting", "composition"):
        require_text(film, key, f"film_language.{key}")
    if require_advanced:
        for key in ("focal_length", "camera_angle", "depth_of_field"):
            require_text(film, key, f"film_language.{key}")
        if not list(film.get("blocking") or []):
            errors.append(f"{shot_id}: film_language.blocking must describe subject placement")

    raw_temporal = shot.get("temporal_plan")
    temporal: dict[str, Any] = raw_temporal if isinstance(raw_temporal, dict) else {}
    if require_advanced:
        require_text(temporal, "start_state", "temporal_plan.start_state")
        require_text(temporal, "end_state", "temporal_plan.end_state")
        raw_beats = temporal.get("beats")
        beats: list[Any] = raw_beats if isinstance(raw_beats, list) else []
        if not beats:
            errors.append(f"{shot_id}: temporal_plan.beats must contain at least one timed beat")
        for index, beat in enumerate(beats):
            if not isinstance(beat, dict):
                errors.append(f"{shot_id}: temporal_plan.beats[{index}] must be an object")
                continue
            try:
                at = float(str(beat.get("at")))
            except (TypeError, ValueError):
                errors.append(f"{shot_id}: temporal_plan.beats[{index}].at must be numeric")
            else:
                if not 0.0 <= at <= 1.0:
                    errors.append(f"{shot_id}: temporal_plan.beats[{index}].at must be 0..1")
            require_text(beat, "subject_action", f"temporal_plan.beats[{index}].subject_action")

    raw_editorial = shot.get("editorial_intent")
    editorial: dict[str, Any] = raw_editorial if isinstance(raw_editorial, dict) else {}
    if require_advanced:
        require_text(editorial, "coverage_role", "editorial_intent.coverage_role")
        require_text(editorial, "cut_motivation", "editorial_intent.cut_motivation")

    raw_generation = shot.get("generation")
    generation: dict[str, Any] = raw_generation if isinstance(raw_generation, dict) else {}
    require_text(generation, "video_prompt", "generation.video_prompt")
    try:
        duration = float(str(generation.get("duration")))
    except (TypeError, ValueError):
        errors.append(f"{shot_id}: generation.duration must be numeric")
    else:
        if duration <= 0:
            errors.append(f"{shot_id}: generation.duration must be positive")
    if require_compiled:
        compiled = generation.get("compiled_prompts")
        if not isinstance(compiled, dict) or not any(
            isinstance(value, dict) and str(value.get("prompt") or "").strip()
            for value in compiled.values()
        ):
            errors.append(f"{shot_id}: generation.compiled_prompts has no executable prompt")
        blueprint = generation.get("prompt_blueprint")
        if not isinstance(blueprint, dict) or not str(blueprint.get("style_anchor") or "").strip():
            errors.append(f"{shot_id}: generation.prompt_blueprint.style_anchor is missing")

    raw_qa = shot.get("qa")
    qa: dict[str, Any] = raw_qa if isinstance(raw_qa, dict) else {}
    if not list(qa.get("must_show") or []):
        errors.append(f"{shot_id}: qa.must_show must contain observable acceptance criteria")
    assertions = normalize_assertions(qa.get("assertions"))
    if require_advanced:
        dimensions = {str(item.get("dimension") or "") for item in assertions}
        required_dimensions = {"camera_language", "motion_plausibility", "technical_quality"}
        missing = sorted(required_dimensions - dimensions)
        if missing:
            errors.append(f"{shot_id}: qa.assertions missing dimensions: {', '.join(missing)}")
        unknown = sorted(dimension for dimension in dimensions if dimension not in QA_DIMENSIONS)
        if unknown:
            errors.append(f"{shot_id}: qa.assertions has unknown dimensions: {', '.join(unknown)}")
    return errors


def contract_semantic_errors(
    shots: list[dict[str, Any]],
    *,
    expected_segment_ids: list[int],
    max_shots_per_segment: int,
    require_advanced: bool,
    require_compiled: bool,
) -> list[str]:
    errors: list[str] = []
    ids: list[int] = []
    shot_ids: list[str] = []
    orders_by_segment: dict[int, list[int]] = {}
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            errors.append(f"shots[{index}] must be an object")
            continue
        try:
            segment_id = int(str(shot.get("segment_id")))
        except (TypeError, ValueError):
            errors.append(f"shots[{index}].segment_id must be an integer")
            continue
        ids.append(segment_id)
        shot_id = str(shot.get("shot_id") or "").strip()
        if not shot_id:
            errors.append(f"segment {segment_id}: shot_id is required")
        else:
            shot_ids.append(shot_id)
        try:
            order = int(shot.get("shot_order") or 1)
        except (TypeError, ValueError):
            errors.append(f"{shot_id or segment_id}: shot_order must be an integer")
        else:
            orders_by_segment.setdefault(segment_id, []).append(order)
        errors.extend(
            shot_semantic_errors(
                shot,
                require_advanced=require_advanced,
                require_compiled=require_compiled,
            )
        )

    expected = set(expected_segment_ids)
    actual = set(ids)
    if actual != expected:
        errors.append(f"shots must cover segment_ids {sorted(expected)}; got {sorted(actual)}")
    duplicates = sorted(shot_id for shot_id, count in Counter(shot_ids).items() if count > 1)
    if duplicates:
        errors.append(f"shot_id values must be unique: {', '.join(duplicates)}")
    for segment_id, count in Counter(ids).items():
        if count > max_shots_per_segment:
            errors.append(
                f"segment {segment_id} has {count} shots; maximum is {max_shots_per_segment}"
            )
    for segment_id, orders in orders_by_segment.items():
        if sorted(orders) != list(range(1, len(orders) + 1)):
            errors.append(
                f"segment {segment_id} shot_order values must be contiguous from 1; got {orders}"
            )
    return errors
