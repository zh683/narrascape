from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "prompt_compiler.v2"


def compile_video_prompts(shot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Compile a director shot contract into provider-specific video prompts."""
    base = _base_fields(shot)
    seedance_prompt = _join_sections(
        [
            f"Camera: {base['shot_type']} shot, {base['camera_motion']} movement.",
            f"Subject action: {base['subject_action']} {base['emotional_target']}.",
            f"Story purpose: {base['story_reason']}.",
            f"Temporal action: {base['temporal_plan']}.",
            f"Scene: {base['location']}. Lighting: {base['lighting']}.",
            f"Lens and camera: {base['lens_plan']}.",
            f"Composition and blocking: {base['composition']}; {base['blocking']}.",
            f"Color and depth: {base['color_palette']}; {base['depth_of_field']}.",
            f"Motion beat: {base['motion_instruction']}.",
            f"Continuity locks: {base['character_lock']} {base['wardrobe_lock']}",
            f"Storyboard: {base['storyboard_lock']}",
            f"Visual style: {base['style_anchor']}.",
            f"Editorial intent: {base['editorial_intent']}.",
            "Stable identity, physically plausible motion, clean frame.",
        ]
    )
    agnes_prompt = _join_sections(
        [
            f"{base['subject_action']} {base['emotional_target']}.",
            f"Story purpose: {base['story_reason']}.",
            f"Temporal action: {base['temporal_plan']}.",
            f"{base['shot_type']} shot with {base['camera_motion']} camera movement.",
            f"Lens and camera: {base['lens_plan']}.",
            f"Reference locks: {base['character_lock']} {base['scene_lock']} {base['wardrobe_lock']}",
            f"Composition requirements: {base['composition']}; {base['blocking']}. {base['storyboard_lock']}",
            f"Lighting and atmosphere: {base['lighting']}.",
            f"Color, depth, and style: {base['color_palette']}; {base['depth_of_field']}; {base['style_anchor']}.",
            "Keep the referenced character face, age, body, and outfit consistent across the whole clip.",
            "Cinematic, coherent, physically plausible motion.",
        ]
    )
    generic_prompt = _join_sections(
        [
            f"{base['shot_type']} shot, {base['camera_motion']} movement.",
            base["subject_action"],
            f"Story purpose: {base['story_reason']}.",
            f"Temporal action: {base['temporal_plan']}.",
            f"Show {base['character_lock']} in {base['location']}, wearing {base['wardrobe']}.",
            f"Lens: {base['lens_plan']}. Lighting: {base['lighting']}. Composition: {base['composition']}.",
            f"Visual style: {base['style_anchor']}.",
        ]
    )
    negative = _negative_prompt(base["negative_prompt"])
    return {
        "seedance": {
            "prompt": seedance_prompt,
            "negative_prompt": negative,
            "prompt_style": "motion_first",
            "parameters": {
                "reference_strategy": base["provider_flow"],
                "motion": base["motion"],
            },
        },
        "agnes": {
            "prompt": agnes_prompt,
            "negative_prompt": negative,
            "prompt_style": "reference_lock_first",
            "parameters": {
                "reference_strategy": base["provider_flow"],
                "motion": base["motion"],
            },
        },
        "generic": {
            "prompt": generic_prompt,
            "negative_prompt": negative,
            "prompt_style": "portable",
            "parameters": {"motion": base["motion"]},
        },
    }


def provider_prompt(
    generation: dict[str, Any],
    provider: str,
    fallback_prompt: str = "",
) -> str:
    compiled = generation.get("compiled_prompts", {})
    if isinstance(compiled, dict):
        provider_item = compiled.get(provider)
        if isinstance(provider_item, dict) and provider_item.get("prompt"):
            return str(provider_item["prompt"])
        generic_item = compiled.get("generic")
        if isinstance(generic_item, dict) and generic_item.get("prompt"):
            return str(generic_item["prompt"])
    return str(generation.get("video_prompt") or fallback_prompt)


def provider_negative_prompt(generation: dict[str, Any], provider: str) -> str:
    compiled = generation.get("compiled_prompts", {})
    if isinstance(compiled, dict):
        provider_item = compiled.get(provider)
        if isinstance(provider_item, dict) and provider_item.get("negative_prompt"):
            return str(provider_item["negative_prompt"])
    return str(generation.get("negative_prompt") or "")


def _base_fields(shot: dict[str, Any]) -> dict[str, str]:
    film_language = shot.get("film_language", {}) or {}
    continuity = shot.get("continuity_constraints", {}) or {}
    binding = shot.get("storyboard_binding", {}) or {}
    generation = shot.get("generation", {}) or {}
    blueprint = generation.get("prompt_blueprint", {}) or {}
    temporal = shot.get("temporal_plan", {}) or {}
    editorial = shot.get("editorial_intent", {}) or {}
    characters = [str(item) for item in continuity.get("characters", []) or [] if item]
    character_lock = ", ".join(characters) if characters else "the named character"
    location = str(continuity.get("location") or binding.get("scene_ref") or "the locked scene")
    wardrobe = str(
        continuity.get("wardrobe") or binding.get("wardrobe_lock") or "the locked wardrobe"
    )
    camera_motion = str(
        film_language.get("camera_motion") or generation.get("motion") or "controlled stillness"
    )
    motion = str(generation.get("motion") or camera_motion)
    storyboard_parts = []
    if binding.get("storyboard_frame_ids"):
        storyboard_parts.append("frames " + ", ".join(binding["storyboard_frame_ids"]))
    if binding.get("character_positions"):
        storyboard_parts.append("positions " + ", ".join(binding["character_positions"]))
    if binding.get("reference_image_ids"):
        storyboard_parts.append("references " + ", ".join(binding["reference_image_ids"]))
    beats = []
    for beat in temporal.get("beats", []) or []:
        if not isinstance(beat, dict):
            continue
        try:
            beat_at = float(beat.get("at") or 0.5)
        except (TypeError, ValueError):
            beat_at = 0.5
        beats.append(
            f"{min(1.0, max(0.0, beat_at)):.2f}: "
            f"{beat.get('subject_action') or ''} {beat.get('camera_action') or ''}".strip()
        )
    temporal_plan = "; ".join(
        part
        for part in (
            f"start {temporal.get('start_state')}" if temporal.get("start_state") else "",
            *beats,
            f"end {temporal.get('end_state')}" if temporal.get("end_state") else "",
        )
        if part
    )
    lens_plan = ", ".join(
        part
        for part in (
            str(film_language.get("focal_length") or ""),
            str(film_language.get("aperture") or ""),
            str(film_language.get("camera_angle") or ""),
            str(film_language.get("camera_height") or ""),
        )
        if part
    )
    return {
        "story_reason": str(shot.get("story_reason") or "Execute the story beat."),
        "subject_action": str(
            shot.get("subject_action")
            or temporal.get("subject_action")
            or "The subject performs the scripted action."
        ),
        "emotional_target": f"Emotional target: {shot.get('emotional_target') or 'focused'}",
        "shot_type": str(film_language.get("shot_type") or "medium"),
        "camera_motion": camera_motion,
        "lighting": str(film_language.get("lighting") or continuity.get("lighting") or ""),
        "composition": str(
            film_language.get("composition")
            or ", ".join(binding.get("composition_requirements") or [])
            or "story-driven composition"
        ),
        "blocking": "; ".join(str(item) for item in film_language.get("blocking", []) or [])
        or "preserve clear subject placement and coherent eyelines",
        "lens_plan": lens_plan or "natural perspective at eye level",
        "depth_of_field": str(film_language.get("depth_of_field") or "controlled depth of field"),
        "color_palette": str(film_language.get("color_palette") or "coherent scene palette"),
        "location": location,
        "wardrobe": wardrobe,
        "character_lock": f"characters: {character_lock}.",
        "scene_lock": f"scene: {location}.",
        "wardrobe_lock": f"wardrobe: {wardrobe}.",
        "storyboard_lock": "; ".join(storyboard_parts) or "follow the storyboard beat.",
        "temporal_plan": temporal_plan or "one readable action with a clear start and end state",
        "editorial_intent": str(
            editorial.get("cut_motivation")
            or f"serve the {shot.get('coverage_role') or 'primary'} coverage role"
        ),
        "style_anchor": str(
            blueprint.get("style_anchor") or "cinematic, coherent with the project style bible"
        ),
        "provider_flow": str(
            (blueprint.get("reference_strategy") or {}).get("provider_flow")
            or "first_frame_plus_references"
        ),
        "motion_instruction": _motion_instruction(motion),
        "motion": motion,
        "negative_prompt": str(generation.get("negative_prompt") or ""),
    }


def _motion_instruction(motion: str) -> str:
    motion_map = {
        "push_in": "slowly push toward the subject while preserving stable identity",
        "pull_out": "slowly pull back to reveal scale and geography",
        "pan_left": "pan left with stable horizon and coherent subject placement",
        "pan_right": "pan right with stable horizon and coherent subject placement",
        "still": "hold a restrained locked-off frame with subtle natural movement",
    }
    return motion_map.get(motion, motion.replace("_", " "))


def _negative_prompt(value: str) -> str:
    standard = ["readable text", "watermark", "low quality"]
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    lower_parts = {part.lower() for part in parts}
    for item in standard:
        if item.lower() not in lower_parts:
            parts.append(item)
    return ", ".join(parts)


def _join_sections(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if str(part).strip())
