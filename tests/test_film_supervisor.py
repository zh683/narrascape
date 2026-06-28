from __future__ import annotations

import json
from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.pipeline import _resolve_dependencies, get_stage_map
from narrascape.stages.base import StageContext


def _config(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "supervisor_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "assets" / "images").mkdir(parents=True)
    (project_dir / "assets" / "videos").mkdir(parents=True)
    (project_dir / "source_media").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "Mira enters the observatory."},
                    {"id": 2, "text": "The lab sequence stretches too long."},
                    {"id": 3, "text": "Her face and costume drift in the memory."},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(
            {
                "project_title": "Supervisor Project",
                "segments": [
                    {
                        "segment_id": 1,
                        "image_prompt": "Mira enters the observatory in a field coat.",
                        "character_ids": ["mira"],
                        "location_id": "observatory",
                        "metadata": {"wardrobe": "field coat", "lighting_scheme": "dawn"},
                    },
                    {
                        "segment_id": 2,
                        "image_prompt": "Mira studies the machine in the lab.",
                        "character_ids": ["mira"],
                        "location_id": "lab",
                        "metadata": {
                            "wardrobe": "field coat",
                            "lighting_scheme": "green practicals",
                        },
                    },
                    {
                        "segment_id": 3,
                        "image_prompt": "Mira sees a memory in the lab, same face and field coat.",
                        "character_ids": ["mira"],
                        "location_id": "lab",
                        "metadata": {
                            "wardrobe": "field coat",
                            "lighting_scheme": "green practicals",
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
                "project": {"name": "supervisor-project", "title": "Supervisor Project"},
                "duration": 18.0,
                "coverage": {
                    "generated_video_segments": [1, 2, 3],
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
                            "duration": 4.0,
                            "character_ids": ["mira"],
                            "location_id": "observatory",
                            "wardrobe": "field coat",
                        },
                        {
                            "id": "v_002",
                            "segment_id": 2,
                            "source": "generated_video",
                            "asset_ref": "vid_02",
                            "path": "assets/videos/vid_02.mp4",
                            "duration": 12.0,
                            "character_ids": ["mira"],
                            "location_id": "lab",
                            "wardrobe": "field coat",
                        },
                        {
                            "id": "v_003",
                            "segment_id": 3,
                            "source": "generated_video",
                            "asset_ref": "vid_03",
                            "path": "assets/videos/vid_03.mp4",
                            "duration": 2.0,
                            "character_ids": ["mira"],
                            "location_id": "archive_room",
                            "wardrobe": "red dress",
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
    for index in range(1, 4):
        (project_dir / "assets" / "videos" / f"vid_{index:02d}.mp4").write_bytes(
            f"video {index}".encode()
        )
        (project_dir / "assets" / "images" / f"img_{index:02d}.png").write_bytes(
            f"image {index}".encode()
        )

    config = NarrascapeConfig(
        project=ProjectConfig(
            name="supervisor-project",
            title="Supervisor Project",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True)
    (config.pipeline_dir / "render_report.yaml").write_text(
        yaml.safe_dump(
            {
                "output": "output/supervisor-project-sub.mp4",
                "checks": {
                    "pacing_risk_segments": [2],
                    "continuity_risk_segments": [3],
                    "missing_generated_video_segments": [],
                },
                "errors": [],
                "warnings": ["narrative pacing risk", "character or location continuity risk"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config.pipeline_dir / "continuity_bible.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "continuity_bible.v1",
                "characters": {"mira": {"appearances": []}},
                "locations": {"lab": {"appearances": [2, 3]}},
                "continuity_risks": [
                    {"segment_id": 3, "risk_type": "wardrobe_jump", "severity": "high"}
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config.pipeline_dir / "editing_review.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "editing_review.v1",
                "pacing": {"risk_segments": [2]},
                "repetition": {"repeated_shot_segments": []},
                "emotion_curve": {"beats": []},
                "recommendations": [
                    {
                        "segment_id": 2,
                        "action": "recut",
                        "reason": "pacing_risk",
                        "priority": "high",
                    }
                ],
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
    (config.pipeline_dir / "rework_plan.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "rework_plan.v1",
                "status": "needs_rework",
                "actions": [
                    {
                        "segment_id": 3,
                        "action": "regenerate_video",
                        "reason": "continuity_risk",
                        "priority": "high",
                    },
                    {
                        "segment_id": 2,
                        "action": "recut",
                        "reason": "pacing_risk",
                        "priority": "medium",
                    },
                    {
                        "segment_id": 3,
                        "action": "replace_source_media",
                        "reason": "repeated_visual_asset",
                        "priority": "medium",
                    },
                ],
                "actions_by_type": {
                    "regenerate_video": [{"segment_id": 3}],
                    "recut": [{"segment_id": 2}],
                    "replace_source_media": [{"segment_id": 3}],
                },
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


def test_film_supervisor_reads_director_reports_and_decides_next_stages(tmp_path):
    from narrascape.stages.creative_review import CreativeReviewStage
    from narrascape.stages.film_supervisor import FilmSupervisorStage
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    config = _config(tmp_path)
    CreativeReviewStage().run(_context(config))
    VisualSemanticQAStage().run(_context(config))

    result = FilmSupervisorStage().run(_context(config))

    assert result.success
    report = yaml.safe_load(
        (config.pipeline_dir / "film_supervisor.yaml").read_text(encoding="utf-8")
    )
    assert report["schema_version"] == "film_supervisor.v1"
    assert report["status"] == "needs_rework"
    assert "rework_execute" in report["next_stages"]
    assert "generate_video" in report["next_stages"]
    assert "film_timeline" in report["next_stages"]
    assert report["decision"]["rework_action_count"] == 3


def test_film_supervisor_reruns_contract_chain_for_director_contract_rewrite(tmp_path):
    from narrascape.stages.creative_review import CreativeReviewStage
    from narrascape.stages.film_supervisor import FilmSupervisorStage
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    config = _config(tmp_path)
    (config.pipeline_dir / "rework_plan.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "rework_plan.v1",
                "status": "needs_rework",
                "actions": [
                    {
                        "segment_id": 2,
                        "action": "rewrite_director_contract",
                        "reason": "overloaded_camera_motion",
                        "priority": "medium",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    CreativeReviewStage().run(_context(config))
    VisualSemanticQAStage().run(_context(config))

    result = FilmSupervisorStage().run(_context(config))

    assert result.success
    report = yaml.safe_load(
        (config.pipeline_dir / "film_supervisor.yaml").read_text(encoding="utf-8")
    )
    assert report["status"] == "needs_rework"
    assert report["next_stages"][:7] == [
        "rework_execute",
        "director_contract",
        "reference_plate",
        "generate_images",
        "animatic",
        "generate_video",
        "take_select",
    ]
    assert "film_timeline" in report["next_stages"]


def test_rework_execute_executes_plan_by_quarantining_media_and_writing_queues(tmp_path):
    from narrascape.stages.rework_execute import ReworkExecuteStage

    config = _config(tmp_path)
    (config.pipeline_dir / "video_gen_state.json").write_text(
        json.dumps({"done": ["vid_01", "vid_02", "vid_03"], "errors": []}, indent=2),
        encoding="utf-8",
    )
    (config.pipeline_dir / "state.json").write_text(
        json.dumps(
            {
                "version": "2.0",
                "stages": {
                    "generate_video": "completed",
                    "film_timeline": "completed",
                    "film_assemble": "completed",
                    "qa": "completed",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = ReworkExecuteStage().run(_context(config))

    assert result.success
    assert not (config.project_dir / "assets" / "videos" / "vid_03.mp4").exists()
    assert (config.pipeline_dir / "rework_quarantine" / "videos" / "vid_03.mp4").exists()
    state = json.loads((config.pipeline_dir / "video_gen_state.json").read_text(encoding="utf-8"))
    assert state["done"] == ["vid_01", "vid_02"]
    execution = yaml.safe_load(
        (config.pipeline_dir / "rework_execution.yaml").read_text(encoding="utf-8")
    )
    assert execution["schema_version"] == "rework_execution.v1"
    assert execution["executed_actions"][0]["operation"] == "invalidate_generated_video"
    assert (config.pipeline_dir / "video_regen_queue.yaml").exists()
    assert (config.pipeline_dir / "recut_queue.yaml").exists()
    assert (config.pipeline_dir / "source_media_replacement_queue.yaml").exists()
    pipeline_state = json.loads((config.pipeline_dir / "state.json").read_text(encoding="utf-8"))
    assert pipeline_state["stages"]["generate_video"] == "pending"
    assert pipeline_state["stages"]["film_timeline"] == "pending"


def test_rework_execute_queues_director_contract_rewrite(tmp_path):
    from narrascape.stages.rework_execute import ReworkExecuteStage

    config = _config(tmp_path)
    (config.pipeline_dir / "rework_plan.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "rework_plan.v1",
                "status": "needs_rework",
                "actions": [
                    {
                        "segment_id": 2,
                        "action": "rewrite_director_contract",
                        "reason": "overloaded_camera_motion",
                        "priority": "medium",
                        "source": "video_prompt_quality",
                    }
                ],
                "actions_by_type": {"rewrite_director_contract": []},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config.pipeline_dir / "state.json").write_text(
        json.dumps(
            {
                "version": "2.0",
                "stages": {
                    "director_contract": "completed",
                    "reference_plate": "completed",
                    "generate_video": "completed",
                },
                "stage_outputs": {
                    "director_contract": ["director_contract.yaml"],
                    "generate_video": ["video_gen_state.json"],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = ReworkExecuteStage().run(_context(config))

    assert result.success
    queue = yaml.safe_load(
        (config.pipeline_dir / "director_contract_rewrite_queue.yaml").read_text(encoding="utf-8")
    )
    assert queue["actions"][0]["action"] == "rewrite_director_contract"
    execution = yaml.safe_load(
        (config.pipeline_dir / "rework_execution.yaml").read_text(encoding="utf-8")
    )
    assert execution["executed_actions"][0]["operation"] == "queue_director_contract_rewrite"
    state = json.loads((config.pipeline_dir / "state.json").read_text(encoding="utf-8"))
    assert state["stages"]["director_contract"] == "pending"
    assert state["stages"]["reference_plate"] == "pending"
    assert state["stages"]["generate_video"] == "pending"


def test_creative_review_uses_llm_when_available(tmp_path):
    from narrascape.stages.creative_review import CreativeReviewStage

    llm = _FakeLLM(
        {
            "status": "needs_rework",
            "findings": [{"segment_id": 2, "issue": "flat emotional beat", "severity": "medium"}],
            "recommendations": [
                {"segment_id": 2, "action": "recut", "reason": "flat emotional beat"}
            ],
        }
    )
    config = _config(tmp_path)

    result = CreativeReviewStage(llm_client=llm).run(_context(config))

    assert result.success
    assert llm.calls
    prompt, kwargs = llm.calls[0]
    assert "film_timeline" in prompt
    assert kwargs["json_mode"] is True
    review = yaml.safe_load(
        (config.pipeline_dir / "creative_review.yaml").read_text(encoding="utf-8")
    )
    assert review["schema_version"] == "creative_review.v1"
    assert review["review_process"]["llm_status"] == "used"
    assert review["recommendations"][0]["reason"] == "flat emotional beat"


def test_visual_semantic_qa_uses_llm_when_available(tmp_path):
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    llm = _FakeLLM(
        {
            "status": "needs_rework",
            "findings": [
                {
                    "segment_id": 3,
                    "risk_type": "character_face_drift",
                    "severity": "high",
                    "evidence": "face no longer matches Mira reference",
                }
            ],
        }
    )
    config = _config(tmp_path)

    result = VisualSemanticQAStage(llm_client=llm).run(_context(config))

    assert result.success
    assert llm.calls
    prompt, kwargs = llm.calls[0]
    assert "assets/videos/vid_03.mp4" in prompt
    assert kwargs["json_mode"] is True
    report = yaml.safe_load(
        (config.pipeline_dir / "visual_semantic_report.yaml").read_text(encoding="utf-8")
    )
    assert report["schema_version"] == "visual_semantic_report.v1"
    assert report["review_process"]["llm_status"] == "used"
    assert report["findings"][0]["risk_type"] == "character_face_drift"


def test_visual_semantic_qa_fallback_flags_timeline_design_mismatch(tmp_path):
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    config = _config(tmp_path)

    result = VisualSemanticQAStage().run(_context(config))

    assert result.success
    report = yaml.safe_load(
        (config.pipeline_dir / "visual_semantic_report.yaml").read_text(encoding="utf-8")
    )
    risks = {(item["segment_id"], item["risk_type"]) for item in report["findings"]}
    assert (3, "scene_mismatch") in risks
    assert (3, "wardrobe_mismatch") in risks


def test_supervisor_stages_are_registered_and_llm_client_is_injected(tmp_path):
    from narrascape.pipeline import Pipeline
    from narrascape.stages.creative_review import CreativeReviewStage
    from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage

    stage_map = get_stage_map()
    for name in ("creative_review", "visual_semantic_qa", "film_supervisor", "rework_execute"):
        assert name in stage_map

    order = _resolve_dependencies(["film_supervisor"], stage_map)
    assert order.index("rework_plan") < order.index("film_supervisor")
    assert order.index("creative_review") < order.index("film_supervisor")
    assert order.index("visual_semantic_qa") < order.index("film_supervisor")

    llm = object()
    pipeline = Pipeline(_config(tmp_path), llm_client=llm)
    assert pipeline._create_stage(CreativeReviewStage).llm_client is llm
    assert pipeline._create_stage(VisualSemanticQAStage).llm_client is llm
