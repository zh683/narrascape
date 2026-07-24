from __future__ import annotations

import logging
from typing import Any

from narrascape.agent.models import ShotDesign
from narrascape.config import MovementType, ShotType

logger = logging.getLogger("narrascape.agent.prompt_director.parsing")

SHOT_TYPE_ALIASES = {
    "medium_shot": "MEDIUM",
    "medium": "MEDIUM",
    "long_shot": "WIDE_ENV",
    "wide": "WIDE_ENV",
    "wide_shot": "WIDE_ENV",
    "close_up": "CLOSE_UP",
    "close-up": "CLOSE_UP",
    "closeup": "CLOSE_UP",
    "extreme_close_up": "EXTREME_CLOSE_UP",
    "extreme_closeup": "EXTREME_CLOSE_UP",
    "extreme_close-up": "EXTREME_CLOSE_UP",
    "ecu": "EXTREME_CLOSE_UP",
    "insert": "INSERT",
    "detail": "DETAIL",
    "establishing": "ESTABLISHING",
    "establishing_shot": "ESTABLISHING",
    "two_shot": "TWO_SHOT",
    "two-shot": "TWO_SHOT",
    "over_shoulder": "OVER_SHOULDER",
    "over-shoulder": "OVER_SHOULDER",
    "shoulder": "OVER_SHOULDER",
    "silhouette": "SILHOUETTE",
    "group_shot": "GROUP_SHOT",
    "group": "GROUP_SHOT",
    "aerial": "AERIAL",
    "drone": "AERIAL",
    "black": "BLACK",
    "wide_angle": "WIDE_ANGLE",
    "wide-angle": "WIDE_ANGLE",
}

MOVEMENT_ALIASES = {
    "zoom_in": "ZOOM_IN",
    "zoom_in_slow": "ZOOM_IN_SLOW",
    "zoom_slow": "ZOOM_SLOW",
    "zoom_out": "ZOOM_OUT",
    "zoom_out_slow": "ZOOM_OUT_SLOW",
    "push_in": "PUSH_IN",
    "push-in": "PUSH_IN",
    "pull_out": "PULL_OUT",
    "pull-out": "PULL_OUT",
    "pan_left": "PAN_LEFT",
    "pan-left": "PAN_LEFT",
    "pan_left_slow": "PAN_LEFT",
    "pan_right": "PAN_RIGHT",
    "pan-right": "PAN_RIGHT",
    "pan_right_slow": "PAN_RIGHT",
    "pan": "PAN_LEFT",
    "dolly": "PUSH_IN",
    "dolly_in": "PUSH_IN",
    "dolly_out": "PULL_OUT",
    "tracking": "PAN_LEFT",
    "truck_left": "PAN_LEFT",
    "truck_right": "PAN_RIGHT",
    "crane_up": "ZOOM_OUT",
    "crane_down": "ZOOM_IN",
    "handheld": "ZOOM_SLOW",
}


def parse_shot_type(value: str) -> ShotType:
    key = value.lower().strip()
    enum_name = SHOT_TYPE_ALIASES.get(key, key.upper().replace("-", "_"))
    try:
        return ShotType[enum_name]
    except KeyError:
        logger.warning(f"Unknown shot type {value!r}, defaulting to MEDIUM")
        return ShotType.MEDIUM


def parse_movement(value: str) -> MovementType | None:
    if not value or value.lower() in {"none", "", "null", "still"}:
        return None
    key = value.lower().strip()
    enum_name = MOVEMENT_ALIASES.get(key, key.upper().replace("-", "_"))
    try:
        return MovementType[enum_name]
    except KeyError:
        logger.warning(f"Unknown movement type {value!r}, defaulting to None")
        return None


def parse_batch_shot_designs(
    data: list[Any], segments: list[Any], *, style_template: str
) -> list[ShotDesign]:
    designs: list[ShotDesign] = []
    for index, raw in enumerate(data):
        item = raw if isinstance(raw, dict) else {}
        segment_id = item.get("segment_id", segments[index].id if index < len(segments) else 0)
        metadata = item.get("metadata", {})
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        if item.get("negative_prompt"):
            metadata["negative_prompt"] = item["negative_prompt"]
        designs.append(
            ShotDesign(
                segment_id=segment_id,
                shot_type=parse_shot_type(str(item.get("shot_type") or "medium")),
                movement=parse_movement(str(item.get("movement") or "none")),
                director_vision=str(item.get("director_vision") or ""),
                cinematic_format=str(item.get("cinematic_format") or ""),
                image_prompt=str(item.get("image_prompt") or ""),
                reasoning=str(item.get("reasoning") or ""),
                emotion=str(item.get("emotion") or ""),
                intensity=float(item.get("intensity", 0.5)),
                metadata=metadata,
                style_prefix=style_template,
            )
        )
    return designs
