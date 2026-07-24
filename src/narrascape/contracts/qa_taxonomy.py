"""QA assertion dimension taxonomy (Stable-cinemetrics-inspired).

Stable cinemetrics (Chatterjee et al., NeurIPS 2025) argues professional AI
video evaluation needs a structured checklist — not one vibe score — covering
dimensions such as "the right character says the right line", camera-language
accuracy, subject consistency, and action plausibility. This module maps that
taxonomy onto the dimensions Narrascape can actually execute:

* ``director_contract`` tags every QA assertion with one of these dimensions
  (LLM path is instructed to; the deterministic fallback generates a default
  checklist covering all dimensions per shot).
* ``visual_semantic_qa`` reviews per dimension and attributes every finding
  to one, so the report answers "which dimension failed" at a glance.

Compatibility: the taxonomy is additive. Legacy contracts carry no dimension
tags; readers treat them as ``uncategorized`` and never crash.
"""

from __future__ import annotations

from typing import Any

# Dimension id -> human-readable review intent (kept in prompts verbatim).
QA_DIMENSIONS: dict[str, str] = {
    "identity_continuity": (
        "Correct character identity: face, age, body, and wardrobe stay locked "
        "to the character references across the whole clip."
    ),
    "dialogue_attribution": (
        "The right character says the right line: the on-screen subject matches "
        "the narration beat (who speaks/acts is correctly attributed)."
    ),
    "camera_language": (
        "Shot type, camera motion, lighting, and composition execute the "
        "film-language plan for the shot."
    ),
    "motion_plausibility": (
        "Subject action and camera movement are physically plausible — no "
        "warping, ghosting, frozen frames, or impossible motion."
    ),
    "scene_consistency": (
        "Location, scene geography, props, and time-of-day stay coherent with "
        "the continuity locks and storyboard binding."
    ),
    "technical_quality": (
        "No readable text, watermark, flicker, compression artifacts, or " "low-quality frames."
    ),
}

UNCATEGORIZED_DIMENSION = "uncategorized"

# Finding risk_type -> dimension, for deterministic findings and for
# normalizing LLM findings that omit (or invent) a dimension label.
RISK_TYPE_DIMENSIONS: dict[str, str] = {
    "scene_mismatch": "scene_consistency",
    "wardrobe_mismatch": "identity_continuity",
    "storyboard_scene_mismatch": "scene_consistency",
    "storyboard_wardrobe_mismatch": "identity_continuity",
    "storyboard_character_position_mismatch": "camera_language",
    "storyboard_composition_mismatch": "camera_language",
    "reference_asset_missing": "identity_continuity",
    "reference_images_not_executed": "identity_continuity",
    "reference_execution_mismatch": "identity_continuity",
    "visual_frame_extract_failed": "technical_quality",
    "missing_character_lock": "identity_continuity",
    "missing_wardrobe_lock": "identity_continuity",
    "missing_scene_lock": "scene_consistency",
    "under_specified_video_prompt": "camera_language",
    "under_specified_director_contract": "camera_language",
}


def is_known_dimension(value: Any) -> bool:
    return isinstance(value, str) and value in QA_DIMENSIONS


def dimension_for_risk_type(risk_type: Any) -> str:
    return RISK_TYPE_DIMENSIONS.get(str(risk_type or ""), UNCATEGORIZED_DIMENSION)


def normalize_assertions(value: Any) -> list[dict[str, str]]:
    """Tolerantly normalize a raw ``qa.assertions`` list.

    Keeps dicts with a non-empty ``check``; unknown/missing dimensions become
    ``uncategorized``; malformed entries are dropped. Legacy contracts (no
    ``assertions`` key) simply yield an empty list.
    """
    assertions: list[dict[str, str]] = []
    if not isinstance(value, list):
        return assertions
    for item in value:
        if not isinstance(item, dict):
            continue
        check = str(item.get("check") or "").strip()
        if not check:
            continue
        dimension = str(item.get("dimension") or "").strip()
        if dimension not in QA_DIMENSIONS:
            dimension = UNCATEGORIZED_DIMENSION
        assertion_id = str(item.get("id") or "").strip()
        assertions.append(
            {
                "id": assertion_id or f"{dimension}:{len(assertions) + 1}",
                "dimension": dimension,
                "check": check,
            }
        )
    return assertions


def assertion_dimension_for_value(value: str, contract_shot: dict[str, Any]) -> str:
    """Attribute a must_show/must_not_show value to a dimension.

    Order: (1) the shot's tagged assertions whose check text mentions the
    value; (2) continuity constraints — characters/wardrobe are identity,
    location is scene; (3) uncategorized.
    """
    text = str(value or "").strip().lower()
    if not text:
        return UNCATEGORIZED_DIMENSION
    qa = contract_shot.get("qa", {}) if isinstance(contract_shot.get("qa"), dict) else {}
    for assertion in normalize_assertions(qa.get("assertions")):
        if text in assertion["check"].lower():
            return assertion["dimension"]
    continuity = (
        contract_shot.get("continuity_constraints", {})
        if isinstance(contract_shot.get("continuity_constraints"), dict)
        else {}
    )
    characters = [str(item).lower() for item in continuity.get("characters") or []]
    wardrobe = str(continuity.get("wardrobe") or "").lower()
    if (
        text in characters
        or (wardrobe and text in wardrobe)
        or any(text in character for character in characters)
    ):
        return "identity_continuity"
    location = str(continuity.get("location") or "").lower()
    if location and text in location:
        return "scene_consistency"
    return UNCATEGORIZED_DIMENSION


def dimension_summary(
    shots: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Per-dimension 通过/未过/未评估 counts for the visual_semantic report.

    * ``assertions`` — tagged checklist size for that dimension (all shots).
    * ``failed`` — findings attributed to the dimension.
    * ``passed`` — assertions minus failed (floored at 0): a finding means at
      least one assertion in that dimension did not pass.
    * ``unevaluated`` — shots whose checklist has no assertion in that
      dimension (legacy contracts mark every dimension unevaluated).
    """
    summary: dict[str, dict[str, int]] = {
        dimension: {"assertions": 0, "passed": 0, "failed": 0, "unevaluated": 0}
        for dimension in QA_DIMENSIONS
    }
    summary[UNCATEGORIZED_DIMENSION] = {
        "assertions": 0,
        "passed": 0,
        "failed": 0,
        "unevaluated": 0,
    }
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        qa = shot.get("qa", {}) if isinstance(shot.get("qa"), dict) else {}
        shot_assertions = normalize_assertions(qa.get("assertions"))
        covered = {assertion["dimension"] for assertion in shot_assertions}
        for dimension in summary:
            if dimension in covered:
                summary[dimension]["assertions"] += sum(
                    1 for assertion in shot_assertions if assertion["dimension"] == dimension
                )
            else:
                summary[dimension]["unevaluated"] += 1
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        dimension = str(finding.get("dimension") or UNCATEGORIZED_DIMENSION)
        if dimension not in summary:
            dimension = UNCATEGORIZED_DIMENSION
        summary[dimension]["failed"] += 1
    for counts in summary.values():
        counts["passed"] = max(counts["assertions"] - counts["failed"], 0)
    return summary
