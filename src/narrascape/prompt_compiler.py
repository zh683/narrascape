from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "prompt_compiler.v2"


def compile_video_prompts(shot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Compile a director shot contract into provider-specific video prompts."""
    base = _base_fields(shot)
    seedance_prompt = _join_sections(
        [
            f"Camera: {base['shot_type']} shot, {base['camera_motion']} movement.",
            f"Subject action: {base['story_reason']} {base['emotional_target']}.",
            f"Scene: {base['location']}. Lighting: {base['lighting']}.",
            f"Composition: {base['composition']}.",
            f"Motion beat: {base['motion_instruction']}.",
            f"Continuity locks: {base['character_lock']} {base['wardrobe_lock']}",
            f"Storyboard: {base['storyboard_lock']}",
            "Photorealistic cinematic motion, stable identity, clean frame.",
        ]
    )
    agnes_prompt = _join_sections(
        [
            f"{base['story_reason']} {base['emotional_target']}.",
            f"{base['shot_type']} shot with {base['camera_motion']} camera movement.",
            f"Reference locks: {base['character_lock']} {base['scene_lock']} {base['wardrobe_lock']}",
            f"Composition requirements: {base['composition']}. {base['storyboard_lock']}",
            f"Lighting and atmosphere: {base['lighting']}.",
            "Keep the referenced character face, age, body, and outfit consistent across the whole clip.",
            "Cinematic, coherent, physically plausible motion.",
        ]
    )
    generic_prompt = _join_sections(
        [
            f"{base['shot_type']} shot, {base['camera_motion']} movement.",
            base["story_reason"],
            f"Show {base['character_lock']} in {base['location']}, wearing {base['wardrobe']}.",
            f"Lighting: {base['lighting']}. Composition: {base['composition']}.",
        ]
    )
    negative = _negative_prompt(base["negative_prompt"])
    return {
        "seedance": {
            "prompt": seedance_prompt,
            "negative_prompt": negative,
            "prompt_style": "motion_first",
            "parameters": {
                "reference_strategy": "first_frame_plus_references",
                "motion": base["motion"],
            },
        },
        "agnes": {
            "prompt": agnes_prompt,
            "negative_prompt": negative,
            "prompt_style": "reference_lock_first",
            "parameters": {
                "reference_strategy": "first_frame_character_scene",
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
    return {
        "story_reason": str(shot.get("story_reason") or "Execute the story beat."),
        "emotional_target": f"Emotional target: {shot.get('emotional_target') or 'focused'}",
        "shot_type": str(film_language.get("shot_type") or "medium"),
        "camera_motion": camera_motion,
        "lighting": str(film_language.get("lighting") or continuity.get("lighting") or ""),
        "composition": str(
            film_language.get("composition")
            or ", ".join(binding.get("composition_requirements") or [])
            or "story-driven composition"
        ),
        "location": location,
        "wardrobe": wardrobe,
        "character_lock": f"characters: {character_lock}.",
        "scene_lock": f"scene: {location}.",
        "wardrobe_lock": f"wardrobe: {wardrobe}.",
        "storyboard_lock": "; ".join(storyboard_parts) or "follow the storyboard beat.",
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
