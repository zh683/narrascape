"""Tests for the typed contract models in ``narrascape.contracts``.

Scope:

- model round-trips on writer-shaped payloads (``DirectorContract``,
  ``FilmTimeline``, ``FilmSupervisorReport``)
- defaults for optional fields, ``extra="allow"`` tolerance, readable errors
- the write-side schema gate on ``DirectorContractStage`` (fail-fast)
- read-side equivalence: ``film_timeline._semantic_fields`` typed vs raw
- ``pipeline.Pipeline._supervisor_next_stages`` typed path and raw fallback
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.contracts import (
    DirectorContract,
    DirectorShot,
    FilmSupervisorReport,
    FilmTimeline,
)
from narrascape.pipeline import Pipeline
from narrascape.stages.base import StageContext


def _shot_payload() -> dict[str, Any]:
    """Fully populated shot in the exact shape the stage writes."""
    return {
        "segment_id": 1,
        "shot_id": "shot_01",
        "story_reason": "Reveal controlled fear without exposition.",
        "emotional_target": "dread",
        "film_language": {
            "shot_type": "close_up",
            "camera_motion": "push_in",
            "lighting": "green practicals",
            "composition": "Mira isolated in negative space beside the machine",
        },
        "continuity_constraints": {
            "characters": ["mira"],
            "location": "lab",
            "wardrobe": "field coat",
            "lighting": "green practicals",
        },
        "storyboard_binding": {
            "storyboard_frame_ids": ["sb_01_01", "sb_01_02"],
            "character_positions": ["Mira center-left, looking toward the machine"],
            "scene_ref": "lab",
            "wardrobe_lock": "field coat",
            "composition_requirements": ["Mira isolated in negative space"],
            "reference_image_ids": ["char_mira_anchor", "scene_lab_mood"],
        },
        "generation": {
            "video_prompt": "Mira alone in a green-lit lab, field coat, tense expression.",
            "negative_prompt": "extra characters, red dress, cartoon style",
            "duration": 5.0,
            "motion": "push_in",
            "prompt_schema_version": "prompt_compiler.v2",
            "prompt_blueprint": {
                "schema_version": "prompt_blueprint.v1",
                "narrative_intent": "Reveal controlled fear without exposition.",
                "emotional_target": "dread",
                "subject_action": "Mira watches the machine wake",
                "camera_plan": {
                    "shot_type": "close_up",
                    "motion": "push_in",
                    "lighting": "green practicals",
                    "composition": "Mira isolated in negative space beside the machine",
                },
                "continuity_locks": {
                    "characters": ["mira"],
                    "location": "lab",
                    "wardrobe": "field coat",
                    "lighting": "green practicals",
                },
                "storyboard_locks": {
                    "storyboard_frame_ids": ["sb_01_01", "sb_01_02"],
                    "character_positions": ["Mira center-left, looking toward the machine"],
                    "scene_ref": "lab",
                    "wardrobe_lock": "field coat",
                    "composition_requirements": ["Mira isolated in negative space"],
                },
                "reference_strategy": {
                    "required_reference_image_ids": ["char_mira_anchor", "scene_lab_mood"],
                    "provider_flow": "seedance",
                    "identity_priority": "character_first",
                },
                "style_anchor": "style_anchor",
                "quality_bar": ["stable character identity"],
                "qa_assertions": {
                    "must_show": ["field coat"],
                    "must_not_show": ["extra characters"],
                    "assertions": [
                        {
                            "id": "identity_continuity:1",
                            "dimension": "identity_continuity",
                            "check": "Mira keeps the field coat and the same face throughout the clip.",
                        }
                    ],
                },
            },
            "compiled_prompts": {
                "seedance": {
                    "prompt": "Camera: push_in. Mira alone in a green-lit lab.",
                    "negative_prompt": "extra characters, red dress",
                    "prompt_style": "motion_first",
                    "parameters": {"duration": 5.0},
                },
                "agnes": {
                    "prompt": "Reference locks: field coat. Mira alone in a green-lit lab.",
                    "negative_prompt": "extra characters, red dress",
                    "prompt_style": "reference_first",
                    "parameters": {},
                },
                "generic": None,
            },
        },
        "qa": {
            "must_show": ["field coat"],
            "must_not_show": ["extra characters"],
            "assertions": [
                {
                    "id": "identity_continuity:1",
                    "dimension": "identity_continuity",
                    "check": "Mira keeps the field coat and the same face throughout the clip.",
                }
            ],
        },
    }


def _director_contract_payload() -> dict[str, Any]:
    return {
        "schema_version": "director_contract.v1",
        "project": {"name": "contract-project", "title": "Director Contract"},
        "compile_process": {
            "mode": "deterministic_prompt_compiler",
            "llm_status": "not_configured",
            "llm_error": "",
            "rework_segment_ids": [],
        },
        "shots": [_shot_payload()],
    }


def _film_timeline_payload() -> dict[str, Any]:
    return {
        "schema_version": "film_timeline.v1",
        "project": {"name": "contract-project", "title": "Director Contract"},
        "duration": 10.0,
        "strategy": {
            "visual_priority": ["generated_video", "source_media", "generated_image"],
            "fallback": "generated_image",
        },
        "coverage": {
            "generated_video_segments": [1, 2],
            "source_media_segments": [],
            "generated_image_segments": [],
            "missing_visual_segments": [],
        },
        "tracks": {
            "visual": [
                {
                    "id": "v_001",
                    "segment_id": 1,
                    "source": "generated_video",
                    "asset_ref": "vid_01",
                    "path": "assets/videos/vid_01.mp4",
                    "start": 0.0,
                    "duration": 5.0,
                    "role": "primary",
                    "transition": "cut",
                    "shot_type": "close_up",
                    "movement": "push_in",
                    "emotion": "dread",
                    "intensity": 0.8,
                    "character_ids": ["mira"],
                    "location_id": "lab",
                    "wardrobe": "field coat",
                    "lighting_scheme": "green practicals",
                    "screen_axis": "left_to_right",
                    "storyboard_frame_ids": ["sb_01_01"],
                    "character_positions": ["Mira center-left"],
                    "composition": "Mira isolated in negative space",
                }
            ],
            "narration": [
                {
                    "id": "n_001",
                    "segment_id": 1,
                    "asset_ref": "tts_01",
                    "path": "assets/audio/tts_01.mp3",
                    "start": 0.0,
                    "duration": 5.0,
                    "text": "Mira stands alone in the lab.",
                }
            ],
            "music": [
                {
                    "id": "music_zone_1",
                    "asset_ref": "zone_1",
                    "path": "assets/music/zone_1.mp3",
                    "covers": [1, 2],
                    "label": "tension",
                }
            ],
            "subtitles": [
                {"id": "subtitles_srt", "path": "pipeline/subtitles.srt", "format": "srt"}
            ],
        },
    }


def _film_supervisor_payload() -> dict[str, Any]:
    return {
        "schema_version": "film_supervisor.v1",
        "project": {"name": "contract-project", "title": "Director Contract"},
        "status": "needs_rework",
        "decision": {
            "rework_action_count": 2,
            "creative_recommendation_count": 1,
            "visual_finding_count": 3,
            "blocking_error_count": 0,
        },
        "next_stages": ["rework_plan", "qa"],
        "sources": {
            "rework_plan": "pipeline/rework_plan.yaml",
            "creative_review": "pipeline/creative_review.yaml",
            "visual_semantic_report": "pipeline/visual_semantic_report.yaml",
            "render_report": "pipeline/render_report.yaml",
        },
    }


def _assert_contains(original: Any, dumped: Any, path: str = "") -> None:
    """Every key/value in ``original`` survives validation unchanged."""
    if isinstance(original, dict):
        assert isinstance(dumped, dict), path
        for key, value in original.items():
            assert key in dumped, f"{path}.{key} missing after round-trip"
            _assert_contains(value, dumped[key], f"{path}.{key}")
    elif isinstance(original, list):
        assert isinstance(dumped, list), path
        assert len(dumped) == len(original), path
        for index, (original_item, dumped_item) in enumerate(zip(original, dumped, strict=True)):
            _assert_contains(original_item, dumped_item, f"{path}[{index}]")
    else:
        assert dumped == original, f"{path}: {dumped!r} != {original!r}"


# ─────────────────────────────────────────────
# Model round-trips
# ─────────────────────────────────────────────


def test_director_contract_round_trip_is_lossless():
    payload = _director_contract_payload()

    dumped = DirectorContract.model_validate(payload).model_dump()

    _assert_contains(payload, dumped)
    DirectorContract.model_validate(dumped)


def test_film_supervisor_round_trip_is_lossless():
    payload = _film_supervisor_payload()

    dumped = FilmSupervisorReport.model_validate(payload).model_dump()

    assert dumped == payload


def test_film_timeline_round_trip_preserves_payload():
    payload = _film_timeline_payload()

    dumped = FilmTimeline.model_validate(payload).model_dump()

    # Every original key/value survives unchanged.
    _assert_contains(payload, dumped)
    # Optional typed fields are additive for legacy payloads.
    original_clip = payload["tracks"]["visual"][0]
    dumped_clip = dumped["tracks"]["visual"][0]
    assert set(dumped_clip) - set(original_clip) == {
        "shot_id",
        "shot_order",
        "coverage_role",
        "transition_out",
        "cut_motivation",
        "source_in",
        "source_out",
    }
    assert dumped_clip["source_in"] is None
    assert dumped_clip["source_out"] is None
    # Dumped output is itself a valid contract (idempotent).
    FilmTimeline.model_validate(dumped)


# ─────────────────────────────────────────────
# Defaults for optional fields
# ─────────────────────────────────────────────


def test_director_contract_defaults_for_optional_fields():
    payload = _director_contract_payload()
    shot = payload["shots"][0]
    del shot["shot_id"]
    del shot["storyboard_binding"]
    del shot["generation"]["prompt_schema_version"]
    del shot["generation"]["prompt_blueprint"]
    del shot["generation"]["compiled_prompts"]

    contract = DirectorContract.model_validate(payload)

    parsed_shot = contract.shots[0]
    assert parsed_shot.shot_id == ""
    assert parsed_shot.film_language.shot_type == "close_up"
    assert parsed_shot.storyboard_binding.storyboard_frame_ids == []
    assert parsed_shot.generation.prompt_schema_version is None
    assert parsed_shot.generation.prompt_blueprint is None
    assert parsed_shot.generation.compiled_prompts is None


def test_director_contract_accepts_minimal_shot():
    contract = DirectorContract.model_validate(
        {
            "schema_version": "director_contract.v1",
            "compile_process": {"mode": "deterministic_prompt_compiler"},
            "shots": [{}],
        }
    )

    assert contract.project.name == ""
    assert contract.compile_process.llm_status == ""
    assert contract.shots[0].segment_id == 0
    assert contract.shots[0].generation.duration == 5.0


def test_film_supervisor_defaults_for_optional_fields():
    report = FilmSupervisorReport.model_validate(
        {
            "schema_version": "film_supervisor.v1",
            "status": "approved",
            "decision": {},
        }
    )

    assert report.next_stages == []
    assert report.sources.rework_plan == ""
    assert report.decision.rework_action_count == 0


def test_film_timeline_defaults_for_optional_fields():
    timeline = FilmTimeline.model_validate(
        {
            "schema_version": "film_timeline.v1",
            "coverage": {"generated_video_segments": [1]},
            "tracks": {"visual": [{"id": "v_001", "segment_id": 1}]},
        }
    )

    assert timeline.duration == 0.0
    assert timeline.strategy.visual_priority == []
    clip = timeline.tracks.visual[0]
    assert clip.segment_id == 1
    assert clip.source_in is None
    assert clip.character_ids == []


# ─────────────────────────────────────────────
# extra="allow" compatibility
# ─────────────────────────────────────────────


def test_unknown_fields_survive_validation_at_every_level():
    payload = _director_contract_payload()
    payload["future_top_level"] = {"experimental": True}
    payload["shots"][0]["future_shot_field"] = "kept"
    payload["shots"][0]["generation"]["future_generation_field"] = [1, 2]

    dumped = DirectorContract.model_validate(payload).model_dump()

    assert dumped["future_top_level"] == {"experimental": True}
    assert dumped["shots"][0]["future_shot_field"] == "kept"
    assert dumped["shots"][0]["generation"]["future_generation_field"] == [1, 2]


# ─────────────────────────────────────────────
# Readable validation errors
# ─────────────────────────────────────────────


def test_director_contract_rejects_empty_payload():
    with pytest.raises(ValidationError) as excinfo:
        DirectorContract.model_validate({})

    message = str(excinfo.value)
    assert "schema_version" in message
    assert "compile_process" in message
    assert "shots" in message


def test_director_contract_rejects_wrong_schema_version():
    payload = _director_contract_payload()
    payload["schema_version"] = "director_contract.v0"

    with pytest.raises(ValidationError) as excinfo:
        DirectorContract.model_validate(payload)

    assert "schema_version" in str(excinfo.value)


def test_director_contract_rejects_non_numeric_duration():
    payload = _director_contract_payload()
    payload["shots"][0]["generation"]["duration"] = "not-a-number"

    with pytest.raises(ValidationError) as excinfo:
        DirectorContract.model_validate(payload)

    assert "duration" in str(excinfo.value)


def test_film_supervisor_rejects_empty_payload():
    with pytest.raises(ValidationError) as excinfo:
        FilmSupervisorReport.model_validate({})

    message = str(excinfo.value)
    assert "status" in message
    assert "decision" in message


def test_film_timeline_rejects_missing_tracks():
    payload = _film_timeline_payload()
    del payload["tracks"]

    with pytest.raises(ValidationError) as excinfo:
        FilmTimeline.model_validate(payload)

    assert "tracks" in str(excinfo.value)


# ─────────────────────────────────────────────
# Write-side schema gate (fail-fast at the stage boundary)
# ─────────────────────────────────────────────


def _gate_config(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "gate_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump({"segments": [{"id": 1, "text": "Mira waits in the lab."}]}),
        encoding="utf-8",
    )
    (project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(
            {"project_title": "Gate", "segments": [{"segment_id": 1}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="gate-project",
            title="Gate",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True, exist_ok=True)
    return config


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(config=config, script=load_script(config.script_path))


def test_director_contract_write_gate_fails_fast_on_drifted_shots(tmp_path, monkeypatch):
    from narrascape.stages.director_contract import DirectorContractStage

    config = _gate_config(tmp_path)
    stage = DirectorContractStage()
    drifted_shots = [
        {
            "segment_id": 1,
            "story_reason": "drifted shot from a misbehaving producer",
            "generation": {"video_prompt": "prompt", "duration": "not-a-number"},
        }
    ]
    monkeypatch.setattr(stage, "_compile_locally", lambda *args, **kwargs: drifted_shots)

    with pytest.raises(ValidationError) as excinfo:
        stage.run(_context(config))

    assert "duration" in str(excinfo.value)
    # Fail-fast: nothing was written.
    assert not (config.pipeline_dir / "director_contract.yaml").exists()


# ─────────────────────────────────────────────
# Read-side: _semantic_fields typed/raw equivalence
# ─────────────────────────────────────────────


def test_semantic_fields_match_for_typed_and_raw_contract_items():
    from narrascape.stages.film_timeline import FilmTimelineStage

    stage = FilmTimelineStage()
    design_item = {
        "segment_id": 1,
        "character_ids": ["mira"],
        "location_id": "lab",
        "metadata": {"wardrobe": "field coat", "lighting_scheme": "green practicals"},
    }
    shot = _shot_payload()

    typed_result = stage._semantic_fields(design_item, DirectorShot.model_validate(shot))
    raw_result = stage._semantic_fields(design_item, shot)

    assert typed_result == raw_result
    assert typed_result["character_ids"] == ["mira"]
    assert typed_result["location_id"] == "lab"
    assert typed_result["wardrobe"] == "field coat"
    assert typed_result["storyboard_frame_ids"] == ["sb_01_01", "sb_01_02"]


def test_semantic_fields_match_when_contract_lacks_optional_blocks():
    from narrascape.stages.film_timeline import FilmTimelineStage

    stage = FilmTimelineStage()
    design_item = {"segment_id": 2}
    sparse_shot = {"segment_id": 2, "story_reason": "no continuity blocks present"}

    typed_result = stage._semantic_fields(design_item, DirectorShot.model_validate(sparse_shot))
    raw_result = stage._semantic_fields(design_item, sparse_shot)

    assert typed_result == raw_result
    assert typed_result["character_ids"] == []
    assert typed_result["location_id"] is None
    assert typed_result["storyboard_frame_ids"] == []


# ─────────────────────────────────────────────
# Read-side: pipeline._supervisor_next_stages
# ─────────────────────────────────────────────


def _supervisor_config(tmp_path: Path) -> NarrascapeConfig:
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="supervisor-project",
            title="Supervisor",
            script_file="scripts/script.yaml",
        ),
        project_dir=tmp_path,
    )
    config.pipeline_dir.mkdir(parents=True, exist_ok=True)
    return config


def _write_supervisor_report(config: NarrascapeConfig, report: dict[str, Any]) -> None:
    (config.pipeline_dir / "film_supervisor.yaml").write_text(
        yaml.safe_dump(report, sort_keys=False),
        encoding="utf-8",
    )


def test_supervisor_next_stages_typed_path(tmp_path):
    config = _supervisor_config(tmp_path)
    _write_supervisor_report(config, _film_supervisor_payload())

    assert Pipeline(config)._supervisor_next_stages() == ["rework_plan", "qa"]


def test_supervisor_next_stages_returns_empty_when_approved(tmp_path):
    config = _supervisor_config(tmp_path)
    report = _film_supervisor_payload()
    report["status"] = "approved"
    _write_supervisor_report(config, report)

    assert Pipeline(config)._supervisor_next_stages() == []


def test_supervisor_next_stages_falls_back_for_legacy_schema(tmp_path, caplog):
    config = _supervisor_config(tmp_path)
    report = _film_supervisor_payload()
    report["schema_version"] = "film_supervisor.v0"  # fails the Literal anchor
    report["next_stages"] = ["qa"]
    _write_supervisor_report(config, report)

    with caplog.at_level(logging.WARNING):
        next_stages = Pipeline(config)._supervisor_next_stages()

    assert next_stages == ["qa"]
    assert "failed typed validation" in caplog.text


def test_supervisor_next_stages_returns_empty_without_report(tmp_path):
    config = _supervisor_config(tmp_path)

    assert Pipeline(config)._supervisor_next_stages() == []
