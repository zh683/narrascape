from __future__ import annotations

import json
from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.pipeline import _resolve_dependencies, get_stage_map
from narrascape.stages.base import StageContext


def _config(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "contract_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "assets" / "images").mkdir(parents=True)
    (project_dir / "assets" / "videos").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "Mira stands alone in the lab before the machine wakes."},
                    {"id": 2, "text": "The machine reveals the lost city beyond the glass."},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(
            {
                "project_title": "Director Contract",
                "segments": [
                    {
                        "segment_id": 1,
                        "shot_type": "close_up",
                        "movement": "push_in",
                        "director_vision": "Reveal controlled fear without exposition.",
                        "cinematic_format": "INT. LAB - NIGHT. Slow push-in on Mira.",
                        "image_prompt": "Mira alone in a green-lit lab, field coat, tense expression.",
                        "emotion": "dread",
                        "intensity": 0.8,
                        "character_ids": ["mira"],
                        "location_id": "lab",
                        "metadata": {
                            "wardrobe": "field coat",
                            "lighting_scheme": "green practicals",
                            "negative_prompt": "extra characters, red dress, cartoon style",
                        },
                    },
                    {
                        "segment_id": 2,
                        "shot_type": "wide_env",
                        "movement": "pull_out",
                        "director_vision": "Open the scale of the mystery.",
                        "cinematic_format": "INT. LAB WINDOW - NIGHT. Pull out to reveal city.",
                        "image_prompt": "Lost city visible beyond glass, Mira in foreground.",
                        "emotion": "awe",
                        "intensity": 0.6,
                        "character_ids": ["mira"],
                        "location_id": "lab_window",
                        "metadata": {
                            "wardrobe": "field coat",
                            "lighting_scheme": "blue moonlight",
                            "negative_prompt": "daylight, empty frame, text",
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "film_timeline.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "film_timeline.v1",
                "project": {"name": "contract-project", "title": "Director Contract"},
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
                            "duration": 5.0,
                            "character_ids": ["mira"],
                            "location_id": "lab",
                            "wardrobe": "field coat",
                            "lighting_scheme": "green practicals",
                            "storyboard_frame_ids": ["sb_01_01", "sb_01_02"],
                            "character_positions": [
                                "Mira center-left, looking toward the waking machine"
                            ],
                            "composition": "Mira isolated in negative space beside the machine",
                        },
                        {
                            "id": "v_002",
                            "segment_id": 2,
                            "source": "generated_video",
                            "asset_ref": "vid_02",
                            "path": "assets/videos/vid_02.mp4",
                            "duration": 5.0,
                            "character_ids": ["mira"],
                            "location_id": "lab_window",
                            "wardrobe": "field coat",
                            "lighting_scheme": "blue moonlight",
                            "storyboard_frame_ids": ["sb_02_01"],
                            "character_positions": [
                                "Mira foreground silhouette against the window"
                            ],
                            "composition": "Wide reveal with Mira small against the lost city",
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
    for index in range(1, 3):
        (project_dir / "assets" / "images" / f"img_{index:02d}.png").write_bytes(b"image")
        (project_dir / "assets" / "videos" / f"vid_{index:02d}.mp4").write_bytes(b"video")
    refs_dir = project_dir / "assets" / "references"
    refs_dir.mkdir(parents=True)
    for ref_id in (
        "style_anchor",
        "char_mira_anchor",
        "scene_lab_mood",
        "scene_lab_window_mood",
    ):
        (refs_dir / f"{ref_id}.png").write_bytes(f"{ref_id} image".encode())
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="contract-project",
            title="Director Contract",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True)
    (config.pipeline_dir / "pre_production.yaml").write_text(
        yaml.safe_dump(
            {
                "project_title": "Director Contract",
                "storyboard": {
                    "total_frames": 3,
                    "total_segments": 2,
                    "frames": [
                        {
                            "frame_id": "sb_01_01",
                            "segment_id": 1,
                            "frame_index": 0,
                            "description": "Mira isolated in negative space beside the machine.",
                            "shot_type": "close_up",
                            "camera_movement": "push_in",
                            "camera_angle": "eye-level",
                            "character_positions": [
                                "Mira center-left, looking toward the waking machine"
                            ],
                            "emotion": "dread",
                            "duration_hint": 3.0,
                            "character_refs": ["mira"],
                            "scene_ref": "lab",
                            "reference_image_ids": ["char_mira_anchor", "scene_lab_mood"],
                            "notes": "Keep the field coat visible as the wardrobe lock.",
                        },
                        {
                            "frame_id": "sb_01_02",
                            "segment_id": 1,
                            "frame_index": 1,
                            "description": "The machine glow cuts across Mira's field coat.",
                            "shot_type": "insert",
                            "camera_movement": "static",
                            "camera_angle": "low-angle",
                            "character_positions": ["Mira hands near the machine controls"],
                            "emotion": "dread",
                            "duration_hint": 2.0,
                            "character_refs": ["mira"],
                            "scene_ref": "lab",
                            "reference_image_ids": ["scene_lab_mood"],
                            "notes": "Composition must preserve the green practical light.",
                        },
                        {
                            "frame_id": "sb_02_01",
                            "segment_id": 2,
                            "frame_index": 0,
                            "description": "Wide reveal with Mira small against the lost city.",
                            "shot_type": "wide_env",
                            "camera_movement": "pull_out",
                            "camera_angle": "eye-level",
                            "character_positions": [
                                "Mira foreground silhouette against the window"
                            ],
                            "emotion": "awe",
                            "duration_hint": 5.0,
                            "character_refs": ["mira"],
                            "scene_ref": "lab_window",
                            "reference_image_ids": ["scene_lab_window_mood"],
                            "notes": "Hold the scale of the city.",
                        },
                    ],
                },
                "style_anchor_path": "assets/references/style_anchor.png",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config.pipeline_dir / "render_report.yaml").write_text(
        yaml.safe_dump(
            {
                "output": "output/contract-project-sub.mp4",
                "checks": {},
                "errors": [],
                "warnings": [],
            }
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


class _Response:
    def __init__(self, data):
        self.data = data
        self.content = json.dumps(data)

    def extract_json_safe(self, default=None):
        return self.data


class _FakeLLM:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return _Response(self.data)


def test_director_contract_compiles_story_language_prompt_and_qa(tmp_path):
    from narrascape.stages.director_contract import DirectorContractStage

    config = _config(tmp_path)

    result = DirectorContractStage().run(_context(config))

    assert result.success
    contract = yaml.safe_load(
        (config.pipeline_dir / "director_contract.yaml").read_text(encoding="utf-8")
    )
    assert contract["schema_version"] == "director_contract.v1"
    first = contract["shots"][0]
    assert first["story_reason"] == "Reveal controlled fear without exposition."
    assert first["film_language"]["camera_motion"] == "push_in"
    assert "controlled fear" in first["generation"]["video_prompt"]
    assert "green practicals" in first["generation"]["video_prompt"]
    assert "extra characters" in first["generation"]["negative_prompt"]
    assert "field coat" in first["qa"]["must_show"]
    assert "extra characters" in first["qa"]["must_not_show"]


def test_director_contract_binds_storyboard_frames_to_execution_contract(tmp_path):
    from narrascape.stages.director_contract import DirectorContractStage

    config = _config(tmp_path)

    result = DirectorContractStage().run(_context(config))

    assert result.success
    contract = yaml.safe_load(
        (config.pipeline_dir / "director_contract.yaml").read_text(encoding="utf-8")
    )
    first = contract["shots"][0]
    binding = first["storyboard_binding"]
    assert binding["storyboard_frame_ids"] == ["sb_01_01", "sb_01_02"]
    assert "Mira center-left, looking toward the waking machine" in binding["character_positions"]
    assert binding["scene_ref"] == "lab"
    assert binding["wardrobe_lock"] == "field coat"
    assert any("negative space" in item for item in binding["composition_requirements"])
    assert "sb_01_01" in first["generation"]["video_prompt"]
    assert "center-left" in first["generation"]["video_prompt"]
    assert "negative space" in first["generation"]["video_prompt"]


def test_director_contract_uses_llm_when_available(tmp_path):
    from narrascape.stages.director_contract import DirectorContractStage

    llm = _FakeLLM(
        {
            "shots": [
                {
                    "segment_id": 1,
                    "story_reason": "LLM chooses a withheld panic beat.",
                    "emotional_target": "withheld panic",
                    "film_language": {
                        "shot_type": "close_up",
                        "camera_motion": "slow push_in",
                        "lighting": "green practicals",
                        "composition": "Mira isolated in negative space",
                    },
                    "continuity_constraints": {
                        "characters": ["mira"],
                        "location": "lab",
                        "wardrobe": "field coat",
                        "lighting": "green practicals",
                    },
                    "generation": {
                        "video_prompt": "LLM prompt: slow push-in on Mira alone in green lab.",
                        "negative_prompt": "extra characters, red dress",
                        "duration": 5,
                        "motion": "slow push_in",
                    },
                    "qa": {
                        "must_show": ["mira", "field coat", "lab"],
                        "must_not_show": ["extra characters", "red dress"],
                    },
                }
            ]
        }
    )
    config = _config(tmp_path)

    result = DirectorContractStage(llm_client=llm).run(_context(config))

    assert result.success
    assert llm.calls
    prompt, kwargs = llm.calls[0]
    assert "top-tier film director" in prompt
    assert kwargs["json_mode"] is True
    contract = yaml.safe_load(
        (config.pipeline_dir / "director_contract.yaml").read_text(encoding="utf-8")
    )
    assert contract["compile_process"]["llm_status"] == "used"
    assert contract["shots"][0]["story_reason"] == "LLM chooses a withheld panic beat."


def test_generate_video_prefers_director_contract_prompt(tmp_path):
    from narrascape.stages.director_contract import DirectorContractStage
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))
    design = yaml.safe_load((config.project_dir / "design_report.yaml").read_text(encoding="utf-8"))
    contract = yaml.safe_load(
        (config.pipeline_dir / "director_contract.yaml").read_text(encoding="utf-8")
    )
    stage = GenerateVideoStage(api_key="fake")
    segment = design["segments"][0]

    prompt = stage._build_video_prompt(segment, contract_by_segment={1: contract["shots"][0]})

    assert prompt == contract["shots"][0]["generation"]["video_prompt"]


def test_generate_video_resolves_contract_reference_images_for_seedance(tmp_path, monkeypatch):
    from narrascape.stages.director_contract import DirectorContractStage
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))
    design = yaml.safe_load((config.project_dir / "design_report.yaml").read_text(encoding="utf-8"))
    contract = yaml.safe_load(
        (config.pipeline_dir / "director_contract.yaml").read_text(encoding="utf-8")
    )
    pre_production = yaml.safe_load(
        (config.pipeline_dir / "pre_production.yaml").read_text(encoding="utf-8")
    )
    stage = GenerateVideoStage(api_key="fake")
    monkeypatch.setattr(stage.uploader, "upload", lambda value: f"uploaded://{Path(value).stem}")

    refs = stage._reference_inputs_for_segment(
        config,
        design,
        pre_production,
        design["segments"][0],
        contract["shots"][0],
    )

    state = refs["state"]
    assert state["storyboard_reference_image_ids"] == ["char_mira_anchor", "scene_lab_mood"]
    assert "style_anchor" in state["expected_reference_ids"]
    assert "char_mira_anchor" in state["expected_reference_ids"]
    assert "scene_lab_mood" in state["expected_reference_ids"]
    assert not state["missing_reference_ids"]
    uploaded = refs["uploaded_reference_images"]
    assert "uploaded://style_anchor" in uploaded
    assert "uploaded://char_mira_anchor" in uploaded
    assert "uploaded://scene_lab_mood" in uploaded


def test_generate_video_passes_contract_references_to_task(tmp_path, monkeypatch):
    from narrascape.stages.director_contract import DirectorContractStage
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))
    created = []

    stage = GenerateVideoStage(api_key="fake", sleep_between=0)
    monkeypatch.setattr(stage.uploader, "upload", lambda value: f"uploaded://{Path(value).stem}")

    def fake_generate_one(
        prompt,
        out_name,
        model,
        resolution,
        first_frame,
        last_frame,
        videos_dir,
        reference_images=None,
    ):
        created.append(
            {
                "out_name": out_name,
                "reference_images": reference_images or [],
                "first_frame": first_frame,
            }
        )
        (videos_dir / f"{out_name}.mp4").write_bytes(b"video")
        return True

    monkeypatch.setattr(stage, "_generate_one", fake_generate_one)

    result = stage.run(_context(config))

    assert result.success
    assert created
    first_refs = created[0]["reference_images"]
    assert "uploaded://style_anchor" in first_refs
    assert "uploaded://char_mira_anchor" in first_refs
    assert "uploaded://scene_lab_mood" in first_refs
    state = json.loads((config.pipeline_dir / "video_gen_state.json").read_text(encoding="utf-8"))
    assert state["reference_inputs"]["vid_01"]["uploaded_reference_count"] >= 3


def test_visual_semantic_qa_sends_director_contract_to_llm(tmp_path):
    from narrascape.stages.director_contract import DirectorContractStage
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    llm = _FakeLLM({"status": "approved", "findings": []})
    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))

    result = VisualSemanticQAStage(llm_client=llm).run(_context(config))

    assert result.success
    prompt, kwargs = llm.calls[0]
    assert "director_contract" in prompt
    assert "must_show" in prompt
    assert "reference image paths" in prompt
    assert kwargs["json_mode"] is True


def test_visual_semantic_qa_fallback_checks_contract_assertions(tmp_path):
    from narrascape.stages.director_contract import DirectorContractStage
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))
    timeline_path = config.project_dir / "film_timeline.yaml"
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    timeline["tracks"]["visual"][0]["wardrobe"] = "red dress"
    timeline_path.write_text(yaml.safe_dump(timeline, sort_keys=False), encoding="utf-8")

    result = VisualSemanticQAStage().run(_context(config))

    assert result.success
    report = yaml.safe_load(
        (config.pipeline_dir / "visual_semantic_report.yaml").read_text(encoding="utf-8")
    )
    risks = {(item["segment_id"], item["risk_type"]) for item in report["findings"]}
    assert (1, "contract_must_show_missing") in risks
    assert (1, "contract_must_not_show_present") in risks


def test_visual_semantic_qa_fallback_checks_storyboard_contract_fields(tmp_path):
    from narrascape.stages.director_contract import DirectorContractStage
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))
    timeline_path = config.project_dir / "film_timeline.yaml"
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    timeline["tracks"]["visual"][0]["location_id"] = "cafeteria"
    timeline["tracks"]["visual"][0]["wardrobe"] = "red dress"
    timeline["tracks"]["visual"][0]["character_positions"] = ["Mira right edge, looking away"]
    timeline["tracks"]["visual"][0]["composition"] = "flat centered passport photo"
    timeline_path.write_text(yaml.safe_dump(timeline, sort_keys=False), encoding="utf-8")

    result = VisualSemanticQAStage().run(_context(config))

    assert result.success
    report = yaml.safe_load(
        (config.pipeline_dir / "visual_semantic_report.yaml").read_text(encoding="utf-8")
    )
    risks = {(item["segment_id"], item["risk_type"]) for item in report["findings"]}
    assert (1, "storyboard_scene_mismatch") in risks
    assert (1, "storyboard_wardrobe_mismatch") in risks
    assert (1, "storyboard_character_position_mismatch") in risks
    assert (1, "storyboard_composition_mismatch") in risks


def test_visual_semantic_qa_records_reference_assets_and_extracted_frames(tmp_path, monkeypatch):
    from narrascape.stages.director_contract import DirectorContractStage
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))
    (config.pipeline_dir / "video_gen_state.json").write_text(
        json.dumps(
            {
                "done": ["vid_01", "vid_02"],
                "reference_inputs": {
                    "vid_01": {
                        "expected_reference_ids": [
                            "style_anchor",
                            "char_mira_anchor",
                            "scene_lab_mood",
                        ],
                        "uploaded_reference_count": 3,
                    },
                    "vid_02": {
                        "expected_reference_ids": [
                            "style_anchor",
                            "scene_lab_window_mood",
                        ],
                        "uploaded_reference_count": 2,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    stage = VisualSemanticQAStage()
    monkeypatch.setattr(
        stage,
        "_extract_clip_frames",
        lambda clip, path, context: [
            (context.config.pipeline_dir / f"frame_{clip['segment_id']}.jpg").as_posix()
        ],
    )

    result = stage.run(_context(config))

    assert result.success
    report = yaml.safe_load(
        (config.pipeline_dir / "visual_semantic_report.yaml").read_text(encoding="utf-8")
    )
    first = report["reference_checks"][0]
    assert first["extracted_frames"]
    assert "char_mira_anchor" in first["expected_reference_ids"]
    assert any(item["requested_id"] == "char_mira_anchor" for item in first["reference_assets"])
    risks = {(item["segment_id"], item["risk_type"]) for item in report["findings"]}
    assert (1, "reference_images_not_executed") not in risks


def test_visual_semantic_qa_flags_reference_images_not_executed(tmp_path, monkeypatch):
    from narrascape.stages.director_contract import DirectorContractStage
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))
    stage = VisualSemanticQAStage()
    monkeypatch.setattr(stage, "_extract_clip_frames", lambda clip, path, context: [])

    result = stage.run(_context(config))

    assert result.success
    report = yaml.safe_load(
        (config.pipeline_dir / "visual_semantic_report.yaml").read_text(encoding="utf-8")
    )
    risks = {(item["segment_id"], item["risk_type"]) for item in report["findings"]}
    assert (1, "reference_images_not_executed") in risks
    assert (1, "visual_frame_extract_failed") in risks


def test_director_contract_stage_is_registered_before_generate_video():
    stage_map = get_stage_map()

    assert "director_contract" in stage_map
    order = _resolve_dependencies(["generate_video"], stage_map)

    assert order.index("director_contract") < order.index("generate_video")
