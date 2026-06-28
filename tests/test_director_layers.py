from __future__ import annotations

import json
from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.pipeline import _resolve_dependencies, get_stage_map
from narrascape.stages.base import StageContext


def _config(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "director_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "assets" / "images").mkdir(parents=True)
    (project_dir / "assets" / "tts").mkdir(parents=True)
    (project_dir / "assets" / "videos").mkdir(parents=True)
    (project_dir / "output").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "Mira discovers the abandoned observatory at dawn."},
                    {"id": 2, "text": "Inside the lab, she finds the machine still awake."},
                    {"id": 3, "text": "The machine repeats the same memory from another angle."},
                    {"id": 4, "text": "Mira leaves with proof as the city lights return."},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    design = {
        "project_title": "Director Layers",
        "segments": [
            {
                "segment_id": 1,
                "shot_type": "establishing",
                "movement": "push_in",
                "image_prompt": "Dawn observatory exterior with Mira in a field coat.",
                "emotion": "curious",
                "intensity": 0.3,
                "character_ids": ["mira"],
                "location_id": "observatory_exterior",
                "metadata": {
                    "wardrobe": "field coat",
                    "lighting_scheme": "cool dawn",
                    "screen_axis": "left_to_right",
                },
            },
            {
                "segment_id": 2,
                "shot_type": "medium",
                "movement": "pan_left",
                "image_prompt": "Mira inside a laboratory, coat unchanged.",
                "emotion": "tense",
                "intensity": 0.7,
                "character_ids": ["mira"],
                "location_id": "lab",
                "metadata": {
                    "wardrobe": "field coat",
                    "lighting_scheme": "green practicals",
                    "screen_axis": "left_to_right",
                },
            },
            {
                "segment_id": 3,
                "shot_type": "medium",
                "movement": "pan_left",
                "image_prompt": "The same laboratory memory repeats with mismatched costume.",
                "emotion": "tense",
                "intensity": 0.8,
                "character_ids": ["mira"],
                "location_id": "lab",
                "metadata": {
                    "wardrobe": "red dress",
                    "lighting_scheme": "green practicals",
                    "screen_axis": "right_to_left",
                },
            },
            {
                "segment_id": 4,
                "shot_type": "wide_env",
                "movement": "pull_out",
                "image_prompt": "Mira exits into the returning city lights.",
                "emotion": "relief",
                "intensity": 0.5,
                "character_ids": ["mira"],
                "location_id": "city_rooftop",
                "metadata": {
                    "wardrobe": "field coat",
                    "lighting_scheme": "warm city lights",
                    "screen_axis": "left_to_right",
                },
            },
        ],
    }
    (project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(design, sort_keys=False),
        encoding="utf-8",
    )
    (project_dir / "image_map.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "images": ["img_01"]},
                    {"id": 2, "images": ["img_02"]},
                    {"id": 3, "images": ["img_03"]},
                    {"id": 4, "images": ["img_04"]},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    for index in range(1, 5):
        (project_dir / "assets" / "images" / f"img_{index:02d}.png").write_bytes(b"image")
        (project_dir / "assets" / "tts" / f"seg_{index:02d}.mp3").write_bytes(b"tts")
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="director-project",
            title="Director Layers",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True)
    (config.pipeline_dir / "timing.json").write_text(
        json.dumps({"1": 4.0, "2": 12.0, "3": 4.0, "4": 5.0}, indent=2),
        encoding="utf-8",
    )
    (project_dir / "film_timeline.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "film_timeline.v1",
                "project": {"name": "director-project", "title": "Director Layers"},
                "duration": 25.0,
                "coverage": {
                    "generated_video_segments": [1, 2, 3],
                    "source_media_segments": [],
                    "generated_image_segments": [4],
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
                            "duration": 4.0,
                            "shot_type": "establishing",
                            "movement": "push_in",
                            "emotion": "curious",
                            "intensity": 0.3,
                            "character_ids": ["mira"],
                            "location_id": "observatory_exterior",
                            "wardrobe": "field coat",
                            "lighting_scheme": "cool dawn",
                            "screen_axis": "left_to_right",
                        },
                        {
                            "id": "v_002",
                            "segment_id": 2,
                            "source": "generated_video",
                            "asset_ref": "vid_02",
                            "path": "assets/videos/vid_02.mp4",
                            "start": 4.0,
                            "duration": 12.0,
                            "shot_type": "medium",
                            "movement": "pan_left",
                            "emotion": "tense",
                            "intensity": 0.7,
                            "character_ids": ["mira"],
                            "location_id": "lab",
                            "wardrobe": "field coat",
                            "lighting_scheme": "green practicals",
                            "screen_axis": "left_to_right",
                        },
                        {
                            "id": "v_003",
                            "segment_id": 3,
                            "source": "generated_video",
                            "asset_ref": "vid_02",
                            "path": "assets/videos/vid_02.mp4",
                            "start": 16.0,
                            "duration": 4.0,
                            "shot_type": "medium",
                            "movement": "pan_left",
                            "emotion": "tense",
                            "intensity": 0.8,
                            "character_ids": ["mira"],
                            "location_id": "lab",
                            "wardrobe": "red dress",
                            "lighting_scheme": "green practicals",
                            "screen_axis": "right_to_left",
                        },
                        {
                            "id": "v_004",
                            "segment_id": 4,
                            "source": "generated_image",
                            "asset_ref": "img_04",
                            "path": "assets/images/img_04.png",
                            "start": 20.0,
                            "duration": 5.0,
                            "shot_type": "wide_env",
                            "movement": "pull_out",
                            "emotion": "relief",
                            "intensity": 0.5,
                            "character_ids": ["mira"],
                            "location_id": "city_rooftop",
                            "wardrobe": "field coat",
                            "lighting_scheme": "warm city lights",
                            "screen_axis": "left_to_right",
                        },
                    ],
                    "narration": [],
                    "music": [],
                    "subtitles": [],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config.pipeline_dir / "render_report.yaml").write_text(
        yaml.safe_dump(
            {
                "output": "output/director-project-sub.mp4",
                "checks": {
                    "pacing_risk_segments": [2],
                    "continuity_risk_segments": [3],
                    "missing_generated_video_segments": [4],
                    "repeated_shot_risk": True,
                },
                "errors": [],
                "warnings": ["narrative pacing risk"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config.pipeline_dir / "director_review.yaml").write_text(
        yaml.safe_dump(
            {
                "status": "needs_rework",
                "rework_queue": [
                    {"segment_id": 3, "action": "regenerate_video", "reason": "continuity_risk"},
                    {"segment_id": 2, "action": "recut", "reason": "pacing_risk"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )


def test_script_scene_director_builds_act_scene_sequence_shot_hierarchy(tmp_path):
    from narrascape.stages.screenplay_structure import ScriptSceneDirectorStage

    config = _config(tmp_path)

    result = ScriptSceneDirectorStage().run(_context(config))

    assert result.success
    structure = yaml.safe_load(
        (config.pipeline_dir / "screenplay_structure.yaml").read_text(encoding="utf-8")
    )
    assert structure["schema_version"] == "screenplay_structure.v1"
    assert structure["grain_order"] == ["act", "scene", "sequence", "shot"]
    assert len(structure["acts"]) >= 3
    shot_segments = [
        shot["segment_id"]
        for act in structure["acts"]
        for scene in act["scenes"]
        for sequence in scene["sequences"]
        for shot in sequence["shots"]
    ]
    assert shot_segments == [1, 2, 3, 4]
    assert structure["shot_index"]["1"]["act_id"].startswith("act_")
    assert structure["shot_index"]["3"]["sequence_id"].startswith("seq_")


def test_continuity_director_writes_bible_and_flags_wardrobe_axis_risks(tmp_path):
    from narrascape.stages.continuity_bible import ContinuityBibleStage
    from narrascape.stages.screenplay_structure import ScriptSceneDirectorStage

    config = _config(tmp_path)
    ScriptSceneDirectorStage().run(_context(config))

    result = ContinuityBibleStage().run(_context(config))

    assert result.success
    bible = yaml.safe_load(
        (config.pipeline_dir / "continuity_bible.yaml").read_text(encoding="utf-8")
    )
    assert bible["schema_version"] == "continuity_bible.v1"
    assert bible["characters"]["mira"]["appearances"][0]["wardrobe"] == "field coat"
    assert "lab" in bible["locations"]
    risk_types = {risk["risk_type"] for risk in bible["continuity_risks"]}
    assert "wardrobe_jump" in risk_types
    assert "screen_axis_flip" in risk_types


def test_editing_director_reviews_pacing_repetition_and_emotion_curve(tmp_path):
    from narrascape.stages.editing_review import EditingReviewStage

    config = _config(tmp_path)

    result = EditingReviewStage().run(_context(config))

    assert result.success
    review = yaml.safe_load(
        (config.pipeline_dir / "editing_review.yaml").read_text(encoding="utf-8")
    )
    assert review["schema_version"] == "editing_review.v1"
    assert 2 in review["pacing"]["risk_segments"]
    assert 3 in review["repetition"]["repeated_shot_segments"]
    assert [beat["emotion"] for beat in review["emotion_curve"]["beats"]] == [
        "curious",
        "tense",
        "tense",
        "relief",
    ]
    assert any(
        item["action"] == "recut" and item["segment_id"] == 2 for item in review["recommendations"]
    )


def test_rework_director_merges_review_editing_and_continuity_into_action_plan(tmp_path):
    from narrascape.stages.continuity_bible import ContinuityBibleStage
    from narrascape.stages.editing_review import EditingReviewStage
    from narrascape.stages.rework_plan import ReworkPlanStage
    from narrascape.stages.screenplay_structure import ScriptSceneDirectorStage

    config = _config(tmp_path)
    ScriptSceneDirectorStage().run(_context(config))
    ContinuityBibleStage().run(_context(config))
    EditingReviewStage().run(_context(config))

    result = ReworkPlanStage().run(_context(config))

    assert result.success
    plan = yaml.safe_load((config.pipeline_dir / "rework_plan.yaml").read_text(encoding="utf-8"))
    assert plan["schema_version"] == "rework_plan.v1"
    assert plan["status"] == "needs_rework"
    actions = {(item["segment_id"], item["action"], item["reason"]) for item in plan["actions"]}
    assert (3, "regenerate_video", "continuity_risk") in actions
    assert (2, "recut", "pacing_risk") in actions
    assert (3, "replace_source_media", "repeated_visual_asset") in actions
    assert plan["actions_by_type"]["regenerate_video"]
    assert plan["actions_by_type"]["recut"]
    assert plan["actions_by_type"]["replace_source_media"]


def test_rework_director_includes_video_prompt_quality_actions(tmp_path):
    from narrascape.stages.rework_plan import ReworkPlanStage

    config = _config(tmp_path)
    (config.pipeline_dir / "video_prompt_quality.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "video_prompt_quality.v1",
                "status": "blocked",
                "findings": [
                    {
                        "segment_id": 2,
                        "risk_type": "overloaded_camera_motion",
                        "severity": "medium",
                        "provider": "seedance",
                        "evidence": "push, pan, tilt, zoom",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = ReworkPlanStage().run(_context(config))

    assert result.success
    plan = yaml.safe_load((config.pipeline_dir / "rework_plan.yaml").read_text(encoding="utf-8"))
    actions = {(item["segment_id"], item["action"], item["reason"]) for item in plan["actions"]}
    assert (2, "rewrite_director_contract", "overloaded_camera_motion") in actions
    assert (2, "regenerate_video", "overloaded_camera_motion") in actions
    assert plan["actions_by_type"]["rewrite_director_contract"]


def test_multi_take_director_selects_best_take_and_timeline_uses_it(tmp_path):
    from narrascape.stages.film_timeline import FilmTimelineStage
    from narrascape.stages.take_select import TakeSelectStage

    config = _config(tmp_path)
    videos_dir = config.project_dir / "assets" / "videos"
    (videos_dir / "vid_01_take_01.mp4").write_bytes(b"short")
    (videos_dir / "vid_01_take_02.mp4").write_bytes(b"larger and therefore better candidate")
    (config.pipeline_dir / "video_gen_state.json").write_text(
        json.dumps({"done": ["vid_01_take_01", "vid_01_take_02"]}, indent=2),
        encoding="utf-8",
    )

    result = TakeSelectStage().run(_context(config))

    assert result.success
    selection = yaml.safe_load(
        (config.pipeline_dir / "take_selection.yaml").read_text(encoding="utf-8")
    )
    assert selection["schema_version"] == "take_selection.v1"
    assert selection["selections"][0]["selected_take"] == "vid_01_take_02"
    assert "qa" in selection["selection_process"]["judges"]

    FilmTimelineStage().run(_context(config))
    timeline = yaml.safe_load(
        (config.project_dir / "film_timeline.yaml").read_text(encoding="utf-8")
    )
    first_clip = timeline["tracks"]["visual"][0]
    assert first_clip["asset_ref"] == "vid_01_take_02"
    assert first_clip["path"] == "assets/videos/vid_01_take_02.mp4"


def test_multi_take_director_uses_llm_judge_when_available(tmp_path):
    from narrascape.stages.take_select import TakeSelectStage

    class Response:
        content = '{"selected_take": "vid_01_take_01", "reason": "stronger emotional continuity"}'

        def extract_json_safe(self, default=None):
            return {"selected_take": "vid_01_take_01", "reason": "stronger emotional continuity"}

    class FakeLLM:
        def __init__(self):
            self.calls = []

        def complete(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            return Response()

    config = _config(tmp_path)
    videos_dir = config.project_dir / "assets" / "videos"
    (videos_dir / "vid_01_take_01.mp4").write_bytes(b"short")
    (videos_dir / "vid_01_take_02.mp4").write_bytes(b"larger and therefore better candidate")
    (config.pipeline_dir / "video_gen_state.json").write_text(
        json.dumps({"done": ["vid_01_take_01", "vid_01_take_02"]}, indent=2),
        encoding="utf-8",
    )
    llm = FakeLLM()

    result = TakeSelectStage(llm_client=llm).run(_context(config))

    assert result.success
    assert llm.calls
    prompt, kwargs = llm.calls[0]
    assert "vid_01_take_01" in prompt
    assert kwargs["json_mode"] is True
    selection = yaml.safe_load(
        (config.pipeline_dir / "take_selection.yaml").read_text(encoding="utf-8")
    )
    assert selection["selection_process"]["mode"] == "qa_plus_llm"
    assert selection["selection_process"]["llm_status"] == "used"
    assert selection["selections"][0]["selected_take"] == "vid_01_take_01"
    assert selection["selections"][0]["reason"] == "stronger emotional continuity"


def test_pipeline_passes_llm_client_to_take_select_stage(tmp_path):
    from narrascape.pipeline import Pipeline
    from narrascape.stages.take_select import TakeSelectStage

    config = _config(tmp_path)
    llm = object()

    stage = Pipeline(config, llm_client=llm)._create_stage(TakeSelectStage)

    assert stage.llm_client is llm


def test_director_layer_stages_are_registered_in_rework_dependency_chain():
    stage_map = get_stage_map()
    for name in (
        "screenplay_structure",
        "continuity_bible",
        "editing_review",
        "rework_plan",
        "take_select",
    ):
        assert name in stage_map

    order = _resolve_dependencies(["rework_plan"], stage_map)

    assert order.index("screenplay_structure") < order.index("continuity_bible")
    assert order.index("qa") < order.index("editing_review")
    assert order.index("director_review") < order.index("rework_plan")
    assert order.index("editing_review") < order.index("rework_plan")
    assert order.index("continuity_bible") < order.index("rework_plan")
