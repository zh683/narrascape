from __future__ import annotations

from typing import Any

ACTION_CUES: tuple[str, ...] = (
    "stands",
    "walks",
    "turns",
    "looks",
    "reaches",
    "holds",
    "opens",
    "closes",
    "pauses",
    "pulls",
    "pushes",
    "runs",
    "sits",
    "leans",
    "drifts",
    "reveals",
    "watches",
    "listens",
    "gestures",
    "breathes",
    "moves",
    "types",
    "enters",
    "exits",
    "crosses",
)

CAMERA_CUES: tuple[str, ...] = (
    "camera",
    "shot",
    "close-up",
    "close_up",
    "wide",
    "medium",
    "tracking",
    "push",
    "pull",
    "pan",
    "tilt",
    "zoom",
    "dolly",
    "orbit",
    "handheld",
    "locked-off",
    "static",
    "drift",
)

CAMERA_MOTION_CUES: dict[str, tuple[str, ...]] = {
    "push": ("push in", "push-in", "push_in", "pushes", "push"),
    "pull": ("pull out", "pull-out", "pull_out", "pulls", "pull"),
    "pan": ("pan left", "pan right", "panning", "pan"),
    "tilt": ("tilt up", "tilt down", "tilting", "tilt"),
    "zoom": ("zoom in", "zoom out", "zooming", "zoom"),
    "dolly": ("dolly", "tracking", "track in", "track out"),
    "orbit": ("orbit", "arc around", "circle around"),
    "handheld": ("handheld", "hand-held"),
    "drift": ("drift", "drifting"),
    "static": ("static", "locked-off", "locked off", "still camera"),
}

LIGHTING_CUES: tuple[str, ...] = (
    "light",
    "lighting",
    "lit",
    "glow",
    "shadow",
    "moonlight",
    "sunlight",
    "practical",
    "rim",
    "palette",
    "color",
    "golden hour",
    "green-lit",
    "blue",
    "amber",
)

STYLE_CUES: tuple[str, ...] = (
    "cinematic",
    "photorealistic",
    "realistic",
    "documentary",
    "film",
    "35mm",
    "high quality",
    "coherent",
    "physically plausible",
)

COMPOSITION_CUES: tuple[str, ...] = (
    "composition",
    "frame",
    "framed",
    "center",
    "centre",
    "foreground",
    "background",
    "negative space",
    "silhouette",
    "profile",
    "low angle",
    "high angle",
    "eye-level",
)

GENERIC_PROMPT_PHRASES: tuple[str, ...] = (
    "the subject",
    "story location",
    "consistent wardrobe",
    "clear medium documentary frame",
    "clear establishing documentary frame",
    "clear close_up documentary frame",
    "clear wide_env documentary frame",
    "clear detail documentary frame",
)


def video_prompt_quality_findings(
    shot: dict[str, Any],
    *,
    provider: str,
    prompt: str,
) -> list[dict[str, Any]]:
    """Return blocking prompt/contract findings before paid video generation."""
    return list(video_prompt_quality_assessment(shot, provider=provider, prompt=prompt)["findings"])


def video_prompt_quality_assessment(
    shot: dict[str, Any],
    *,
    provider: str,
    prompt: str,
) -> dict[str, Any]:
    """Return a structured prompt ingredient audit plus blocking findings."""
    segment_id = _segment_id(shot)
    continuity = shot.get("continuity_constraints", {}) or {}
    binding = shot.get("storyboard_binding", {}) or {}
    ingredients = _video_prompt_ingredients(shot, prompt)
    findings: list[dict[str, Any]] = []
    prompt_text = str(prompt or "")
    camera_motion_cues = _camera_motion_cues(prompt_text)
    characters = list(continuity.get("characters") or [])
    has_scene_lock = str(continuity.get("location") or "").lower() not in {"", "story location"}
    has_wardrobe_lock = str(continuity.get("wardrobe") or "").lower() not in {
        "",
        "consistent wardrobe",
    }
    has_character_lock = bool(characters)
    present_generic = [
        phrase for phrase in GENERIC_PROMPT_PHRASES if phrase.lower() in prompt_text.lower()
    ]
    if present_generic and not (has_character_lock and has_scene_lock and has_wardrobe_lock):
        findings.append(
            _finding(
                segment_id,
                "under_specified_video_prompt",
                "high",
                "compiled video prompt still contains generic placeholders without complete continuity locks: "
                + ", ".join(present_generic),
                provider,
            )
        )
    if len(prompt_text.split()) < 12 and not (has_character_lock and has_scene_lock):
        findings.append(
            _finding(
                segment_id,
                "video_prompt_too_short",
                "medium",
                "compiled video prompt is too short to carry director intent",
                provider,
            )
        )
    if not _ingredient_present(ingredients, "action_beat"):
        findings.append(
            _finding(
                segment_id,
                "missing_action_beat",
                "medium",
                "prompt does not describe a concrete subject action or timed beat",
                provider,
            )
        )
    if not _ingredient_present(ingredients, "camera_language"):
        findings.append(
            _finding(
                segment_id,
                "missing_camera_language",
                "medium",
                "prompt does not include shot type, camera movement, or framing language",
                provider,
            )
        )
    if not _ingredient_present(ingredients, "lighting_palette"):
        findings.append(
            _finding(
                segment_id,
                "missing_lighting_palette",
                "medium",
                "prompt does not lock lighting, color, or palette cues for cross-shot continuity",
                provider,
            )
        )
    if not _ingredient_present(ingredients, "style_quality"):
        findings.append(
            _finding(
                segment_id,
                "missing_style_quality_anchor",
                "low",
                "prompt does not include a coherent visual style or quality anchor",
                provider,
            )
        )
    if len(camera_motion_cues) > 2:
        findings.append(
            _finding(
                segment_id,
                "overloaded_camera_motion",
                "medium",
                "prompt asks for too many camera movements in one short generated-video shot: "
                + ", ".join(camera_motion_cues),
                provider,
            )
        )
    if binding.get("reference_image_ids") and not characters:
        findings.append(
            _finding(
                segment_id,
                "missing_character_lock",
                "high",
                "storyboard has reference images but continuity characters are empty",
                provider,
            )
        )
    if not has_scene_lock:
        findings.append(
            _finding(
                segment_id,
                "missing_scene_lock",
                "high",
                "director contract did not lock a concrete scene",
                provider,
            )
        )
    if not has_wardrobe_lock:
        findings.append(
            _finding(
                segment_id,
                "missing_wardrobe_lock",
                "high",
                "director contract did not lock concrete wardrobe",
                provider,
            )
        )
    if binding.get("storyboard_frame_ids") and not binding.get("composition_requirements"):
        findings.append(
            _finding(
                segment_id,
                "missing_composition_requirements",
                "medium",
                "storyboard frames are bound but composition requirements are empty",
                provider,
            )
        )
    present_count = sum(1 for item in ingredients if item["present"])
    return {
        "segment_id": segment_id,
        "provider": provider,
        "prompt_word_count": len(prompt_text.split()),
        "score": present_count,
        "max_score": len(ingredients),
        "camera_motion_cues": camera_motion_cues,
        "missing_components": [
            str(item["component"]) for item in ingredients if not item["present"]
        ],
        "ingredients": ingredients,
        "findings": findings,
    }


def _video_prompt_ingredients(
    shot: dict[str, Any],
    prompt: str,
) -> list[dict[str, Any]]:
    continuity = shot.get("continuity_constraints", {}) or {}
    film_language = shot.get("film_language", {}) or {}
    binding = shot.get("storyboard_binding", {}) or {}
    generation = shot.get("generation", {}) or {}
    prompt_text = str(prompt or "")
    characters = [str(item) for item in continuity.get("characters", []) or [] if item]
    location = str(continuity.get("location") or binding.get("scene_ref") or "")
    wardrobe = str(continuity.get("wardrobe") or binding.get("wardrobe_lock") or "")
    lighting = str(film_language.get("lighting") or continuity.get("lighting") or "")
    composition_values = [
        str(film_language.get("composition") or ""),
        *[str(item) for item in binding.get("composition_requirements", []) or []],
    ]
    camera_values = [
        str(film_language.get("shot_type") or ""),
        str(film_language.get("camera_motion") or generation.get("motion") or ""),
    ]
    return [
        _ingredient(
            "subject_identity",
            bool(characters) and _mentions_any(prompt_text, characters),
            "named character lock appears in prompt",
            f"characters={', '.join(characters) or 'missing'}",
        ),
        _ingredient(
            "action_beat",
            _has_any_cue(prompt_text, ACTION_CUES)
            or _has_text_overlap(prompt_text, [shot.get("story_reason", "")]),
            "subject action or story beat appears in prompt",
            "add one concrete action or timed beat",
        ),
        _ingredient(
            "scene_lock",
            _is_concrete(location, {"story location", "the specified scene"})
            and _has_text_overlap(prompt_text, [location]),
            "scene/location lock appears in prompt",
            f"location={location or 'missing'}",
        ),
        _ingredient(
            "wardrobe_lock",
            _is_concrete(wardrobe, {"consistent wardrobe", "the locked wardrobe"})
            and _has_text_overlap(prompt_text, [wardrobe]),
            "wardrobe lock appears in prompt",
            f"wardrobe={wardrobe or 'missing'}",
        ),
        _ingredient(
            "camera_language",
            _has_any_cue(prompt_text, CAMERA_CUES) or _has_text_overlap(prompt_text, camera_values),
            "shot type or camera movement appears in prompt",
            "add shot size and one camera movement",
        ),
        _ingredient(
            "composition",
            _has_any_cue(prompt_text, COMPOSITION_CUES)
            or _has_text_overlap(prompt_text, composition_values),
            "composition/framing language appears in prompt",
            "add framing or storyboard composition requirement",
        ),
        _ingredient(
            "lighting_palette",
            _has_any_cue(prompt_text, LIGHTING_CUES) or _has_text_overlap(prompt_text, [lighting]),
            "lighting or color palette appears in prompt",
            "add lighting quality and palette anchors",
        ),
        _ingredient(
            "style_quality",
            _has_any_cue(prompt_text, STYLE_CUES),
            "style/quality anchor appears in prompt",
            "add cinematic, documentary, photorealistic, or other style anchor",
        ),
        _ingredient(
            "reference_binding",
            not binding.get("reference_image_ids")
            or bool(characters and _is_concrete(location, {"story location"}) and wardrobe),
            "reference images are paired with continuity locks",
            "bind reference images to character, scene, and wardrobe locks",
        ),
    ]


def _ingredient(
    component: str,
    present: bool,
    evidence: str,
    missing_hint: str,
) -> dict[str, Any]:
    return {
        "component": component,
        "present": bool(present),
        "evidence": evidence if present else missing_hint,
    }


def _ingredient_present(ingredients: list[dict[str, Any]], component: str) -> bool:
    return any(item["component"] == component and item["present"] for item in ingredients)


def _mentions_any(text: str, values: list[str]) -> bool:
    lowered = text.casefold()
    return any(value.casefold() in lowered for value in values if value)


def _has_any_cue(text: str, cues: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(cue.casefold() in lowered for cue in cues)


def _camera_motion_cues(text: str) -> list[str]:
    lowered = text.casefold().replace("_", " ").replace("-", " ")
    found: list[str] = []
    for canonical, variants in CAMERA_MOTION_CUES.items():
        if any(variant.replace("_", " ").replace("-", " ") in lowered for variant in variants):
            found.append(canonical)
    return found


def _has_text_overlap(text: str, values: list[Any]) -> bool:
    prompt_tokens = _semantic_tokens(text)
    if not prompt_tokens:
        return False
    for value in values:
        tokens = _semantic_tokens(str(value or ""))
        if tokens and len(tokens & prompt_tokens) >= min(2, len(tokens)):
            return True
    return False


def _semantic_tokens(text: str) -> set[str]:
    import re

    stopwords = {
        "the",
        "and",
        "with",
        "into",
        "from",
        "that",
        "this",
        "shot",
        "camera",
        "scene",
        "show",
        "wearing",
    }
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_-]+", text.casefold())
        if len(token) > 2 and token not in stopwords
    }


def _is_concrete(value: str, generic_values: set[str]) -> bool:
    text = str(value or "").strip().casefold()
    return bool(text) and text not in {item.casefold() for item in generic_values}


def _segment_id(shot: dict[str, Any]) -> int | None:
    try:
        return int(shot.get("segment_id"))
    except (TypeError, ValueError):
        return None


def _finding(
    segment_id: int | None,
    risk_type: str,
    severity: str,
    evidence: str,
    provider: str,
) -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "risk_type": risk_type,
        "severity": severity,
        "provider": provider,
        "evidence": evidence,
    }
