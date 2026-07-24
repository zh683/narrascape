from __future__ import annotations

from types import SimpleNamespace

from narrascape.agent.prompt_director_parsing import (
    parse_batch_shot_designs,
    parse_movement,
    parse_shot_type,
)
from narrascape.config import MovementType, ShotType


def test_prompt_director_parsing_handles_aliases_and_batch_models():
    assert parse_shot_type("close-up") == ShotType.CLOSE_UP
    assert parse_shot_type("not-real") == ShotType.MEDIUM
    assert parse_movement("dolly_in") == MovementType.PUSH_IN
    assert parse_movement("still") is None

    designs = parse_batch_shot_designs(
        [{"segment_id": 4, "shot_type": "wide", "movement": "pan", "intensity": 0.7}],
        [SimpleNamespace(id=4)],
        style_template="oil",
    )

    assert designs[0].segment_id == 4
    assert designs[0].shot_type == ShotType.WIDE_ENV
    assert designs[0].movement == MovementType.PAN_LEFT
    assert designs[0].style_prefix == "oil"
