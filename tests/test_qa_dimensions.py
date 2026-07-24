from __future__ import annotations

import json
from pathlib import Path

import yaml

from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.contracts.qa_taxonomy import (
    QA_DIMENSIONS,
    RISK_TYPE_DIMENSIONS,
    UNCATEGORIZED_DIMENSION,
    assertion_dimension_for_value,
    dimension_for_risk_type,
    dimension_summary,
    is_known_dimension,
    normalize_assertions,
)
from narrascape.stages.base import StageContext
from narrascape.stages.director_contract import DirectorContractStage
from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage


def _config(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "qa_dimension_project"
    (project_dir / "scripts").mkdir(parents=True)
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
                "project_title": "QA Dimensions",
                "segments": [
                    {
                        "segment_id": 1,
                        "shot_type": "close_up",
                        "movement": "push_in",
                        "director_vision": "Reveal controlled fear without exposition.",
                        "emotion": "dread",
                        "character_ids": ["mira"],
                        "location_id": "lab",
                        "metadata": {
                            "wardrobe": "field coat",
                            "lighting_scheme": "green practicals",
                            "negative_prompt": "extra characters, red dress",
                        },
                    },
                    {
                        "segment_id": 2,
                        "shot_type": "wide_env",
                        "movement": "pull_out",
                        "director_vision": "Open the scale of the mystery.",
                        "emotion": "awe",
                        "character_ids": ["mira"],
                        "location_id": "lab_window",
                        "metadata": {
                            "wardrobe": "field coat",
                            "lighting_scheme": "blue moonlight",
                            "negative_prompt": "daylight, empty frame",
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
                "project": {"name": "qa-dimension-project", "title": "QA Dimensions"},
                "tracks": {
                    "visual": [
                        {
                            "id": "v_001",
                            "segment_id": 1,
                            "source": "generated_video",
                            "path": "assets/videos/vid_01.mp4",
                            "duration": 5.0,
                            "character_ids": ["mira"],
                            "location_id": "lab",
                            "wardrobe": "field coat",
                        },
                        {
                            "id": "v_002",
                            "segment_id": 2,
                            "source": "generated_video",
                            "path": "assets/videos/vid_02.mp4",
                            "duration": 5.0,
                            "character_ids": ["mira"],
                            "location_id": "lab_window",
                            "wardrobe": "field coat",
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
        (project_dir / "assets" / "videos" / f"vid_{index:02d}.mp4").write_bytes(b"video")
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="qa-dimension-project",
            title="QA Dimensions",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True)
    (config.pipeline_dir / "render_report.yaml").write_text(
        yaml.safe_dump({"output": "output/qa-dimensions.mp4", "checks": {}, "errors": []}),
        encoding="utf-8",
    )
    return config


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(config=config, script=load_script(config.script_path))


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


def _load_report(config: NarrascapeConfig) -> dict:
    return yaml.safe_load(
        (config.pipeline_dir / "visual_semantic_report.yaml").read_text(encoding="utf-8")
    )


def _load_contract(config: NarrascapeConfig) -> dict:
    return yaml.safe_load(
        (config.pipeline_dir / "director_contract.yaml").read_text(encoding="utf-8")
    )


# ─────────────────────────────────────────────
# Taxonomy helpers
# ─────────────────────────────────────────────


def test_taxonomy_has_six_stable_dimensions():
    assert set(QA_DIMENSIONS) == {
        "identity_continuity",
        "dialogue_attribution",
        "camera_language",
        "motion_plausibility",
        "scene_consistency",
        "technical_quality",
    }
    assert all(intent.strip() for intent in QA_DIMENSIONS.values())
    assert UNCATEGORIZED_DIMENSION not in QA_DIMENSIONS
    for risk_type, dimension in RISK_TYPE_DIMENSIONS.items():
        assert is_known_dimension(dimension), risk_type
    assert dimension_for_risk_type("scene_mismatch") == "scene_consistency"
    assert dimension_for_risk_type("totally_unknown") == UNCATEGORIZED_DIMENSION
    assert not is_known_dimension("uncategorized")
    assert not is_known_dimension(None)


def test_normalize_assertions_tolerates_malformed_entries():
    raw = [
        {"dimension": "camera_language", "check": "push-in executes"},
        {"dimension": "bogus_dimension", "check": "still a real check"},
        {"dimension": "identity_continuity", "check": ""},
        "not a dict",
        {"id": "custom-7", "dimension": "motion_plausibility", "check": "no warping"},
    ]

    normalized = normalize_assertions(raw)

    assert [item["dimension"] for item in normalized] == [
        "camera_language",
        UNCATEGORIZED_DIMENSION,
        "motion_plausibility",
    ]
    assert normalized[0]["id"] == "camera_language:1"
    assert normalized[1]["id"] == f"{UNCATEGORIZED_DIMENSION}:2"
    assert normalized[2]["id"] == "custom-7"
    assert normalize_assertions(None) == []
    assert normalize_assertions({"not": "a list"}) == []


def test_assertion_dimension_for_value_uses_check_text_then_continuity():
    shot = {
        "qa": {
            "assertions": [
                {"dimension": "identity_continuity", "check": "field coat stays locked"},
            ]
        },
        "continuity_constraints": {
            "characters": ["mira"],
            "location": "lab",
            "wardrobe": "field coat",
        },
    }

    assert assertion_dimension_for_value("field coat", shot) == "identity_continuity"
    legacy_shot = {"qa": {}, "continuity_constraints": shot["continuity_constraints"]}
    assert assertion_dimension_for_value("mira", legacy_shot) == "identity_continuity"
    assert assertion_dimension_for_value("field coat", legacy_shot) == "identity_continuity"
    assert assertion_dimension_for_value("lab", legacy_shot) == "scene_consistency"
    assert assertion_dimension_for_value("unrelated token", legacy_shot) == UNCATEGORIZED_DIMENSION


def test_dimension_summary_counts_pass_fail_unevaluated():
    shots = [
        {"qa": {}},  # legacy shot: nothing evaluated
        {
            "qa": {
                "assertions": [
                    {"dimension": dimension, "check": f"check {dimension}"}
                    for dimension in QA_DIMENSIONS
                ]
            }
        },
    ]
    findings = [
        {"dimension": "camera_language"},
        {"dimension": "camera_language"},
        {"dimension": "bogus", "risk_type": "ignored"},
    ]

    summary = dimension_summary(shots, findings)

    assert summary["identity_continuity"] == {
        "assertions": 1,
        "passed": 1,
        "failed": 0,
        "unevaluated": 1,
    }
    assert summary["camera_language"] == {
        "assertions": 1,
        "passed": 0,  # floored: 1 assertion - 2 findings
        "failed": 2,
        "unevaluated": 1,
    }
    assert summary[UNCATEGORIZED_DIMENSION]["failed"] == 1
    assert summary[UNCATEGORIZED_DIMENSION]["unevaluated"] == 2


# ─────────────────────────────────────────────
# Contract model
# ─────────────────────────────────────────────


def test_shot_qa_model_accepts_legacy_and_tagged_payloads():
    from narrascape.contracts.director_contract import ShotQa

    legacy = ShotQa.model_validate({"must_show": ["mira"], "must_not_show": ["text"]})
    assert legacy.assertions == []
    assert legacy.must_show == ["mira"]

    tagged = ShotQa.model_validate(
        {
            "must_show": ["mira"],
            "assertions": [
                {
                    "id": "identity_continuity:1",
                    "dimension": "identity_continuity",
                    "check": "same face throughout",
                }
            ],
        }
    )
    assert tagged.assertions[0].dimension == "identity_continuity"
    assert tagged.assertions[0].check == "same face throughout"


# ─────────────────────────────────────────────
# director_contract stage (producer side)
# ─────────────────────────────────────────────


def test_local_compile_tags_every_dimension_per_shot(tmp_path):
    config = _config(tmp_path)

    result = DirectorContractStage().run(_context(config))

    assert result.success
    contract = _load_contract(config)
    for shot in contract["shots"]:
        assertions = shot["qa"]["assertions"]
        dimensions = {item["dimension"] for item in assertions}
        assert dimensions == set(QA_DIMENSIONS)
        ids = [item["id"] for item in assertions]
        assert len(ids) == len(set(ids))
        assert all(item["check"].strip() for item in assertions)
        # The flat token planes stay populated for older consumers.
        assert "field coat" in shot["qa"]["must_show"]
        blueprint_qa = shot["generation"]["prompt_blueprint"]["qa_assertions"]
        assert {item["dimension"] for item in blueprint_qa["assertions"]} == set(QA_DIMENSIONS)
    first = contract["shots"][0]
    assert "mira" in first["qa"]["must_show"]
    assert "lab" in first["qa"]["must_show"]
    dialogue = next(
        item for item in first["qa"]["assertions"] if item["dimension"] == "dialogue_attribution"
    )
    assert "Mira stands alone in the lab" in dialogue["check"]


def test_llm_path_prompt_carries_taxonomy_and_normalizes(tmp_path):
    llm = _FakeLLM(
        {
            "shots": [
                {
                    "segment_id": 1,
                    "story_reason": "LLM withheld panic beat.",
                    "generation": {
                        "video_prompt": "LLM prompt: slow push-in on Mira.",
                        "negative_prompt": "extra characters",
                        "duration": 5,
                        "motion": "push_in",
                    },
                    "qa": {
                        "must_show": ["mira", "field coat"],
                        "must_not_show": ["extra characters"],
                        "assertions": [
                            {
                                "dimension": "identity_continuity",
                                "check": "Mira keeps her face lock",
                            },
                            {"dimension": "bogus", "check": "unknown dimension survives"},
                            {"dimension": "camera_language"},
                            "junk entry",
                        ],
                    },
                }
            ]
        }
    )
    config = _config(tmp_path)

    result = DirectorContractStage(llm_client=llm).run(_context(config))

    assert result.success
    prompt, kwargs = llm.calls[0]
    assert kwargs["json_mode"] is True
    for dimension in QA_DIMENSIONS:
        assert dimension in prompt
    assert "qa.assertions" in prompt
    assert "must_show" in prompt  # legacy plane stays in the contract format

    shot = _load_contract(config)["shots"][0]
    assert shot["qa"]["must_show"] == ["mira", "field coat"]
    assertions = shot["qa"]["assertions"]
    assert [item["dimension"] for item in assertions] == [
        "identity_continuity",
        UNCATEGORIZED_DIMENSION,
    ]
    assert assertions[0]["id"] == "identity_continuity:1"
    assert assertions[1]["id"] == f"{UNCATEGORIZED_DIMENSION}:2"


# ─────────────────────────────────────────────
# visual_semantic_qa stage (consumer side)
# ─────────────────────────────────────────────


def test_visual_qa_llm_prompt_includes_assertion_checklist(tmp_path):
    llm = _FakeLLM({"status": "approved", "findings": []})
    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))

    result = VisualSemanticQAStage(llm_client=llm).run(_context(config))

    assert result.success
    prompt, _ = llm.calls[0]
    assert "assertion_checklist" in prompt
    assert "identity_continuity" in prompt
    assert '"dimension"' in prompt
    report = _load_report(config)
    assert report["findings"] == []
    summary = report["dimension_summary"]
    for dimension in QA_DIMENSIONS:
        # 2 shots x 1 assertion per dimension from the deterministic checklist.
        assert summary[dimension] == {
            "assertions": 2,
            "passed": 2,
            "failed": 0,
            "unevaluated": 0,
        }
    assert summary[UNCATEGORIZED_DIMENSION]["assertions"] == 0
    assert summary[UNCATEGORIZED_DIMENSION]["unevaluated"] == 2


def test_visual_qa_llm_findings_get_dimension_attribution(tmp_path):
    llm = _FakeLLM(
        {
            "status": "needs_rework",
            "findings": [
                {
                    "segment_id": 1,
                    "risk_type": "identity_drift",
                    "dimension": "identity_continuity",
                    "severity": "high",
                    "evidence": "face drifts in frame 3",
                },
                {
                    "segment_id": 2,
                    "risk_type": "scene_mismatch",
                    "severity": "high",
                    "evidence": "window reads as daylight",
                },
                {
                    "segment_id": 1,
                    "risk_type": "something_new",
                    "dimension": "nonsense",
                    "severity": "low",
                    "evidence": "invented labels fall back safely",
                },
            ],
        }
    )
    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))

    result = VisualSemanticQAStage(llm_client=llm).run(_context(config))

    assert result.success
    report = _load_report(config)
    dimensions = [item["dimension"] for item in report["findings"]]
    assert dimensions == [
        "identity_continuity",  # valid LLM label kept
        "scene_consistency",  # risk_type mapping
        UNCATEGORIZED_DIMENSION,  # invented label discarded
    ]
    summary = report["dimension_summary"]
    assert summary["identity_continuity"]["failed"] == 1
    assert summary["scene_consistency"]["failed"] == 1
    assert summary[UNCATEGORIZED_DIMENSION]["failed"] == 1


def test_visual_qa_fallback_maps_risk_types_to_dimensions(tmp_path):
    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))
    timeline_path = config.project_dir / "film_timeline.yaml"
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    timeline["tracks"]["visual"][0]["wardrobe"] = "red dress"
    timeline_path.write_text(yaml.safe_dump(timeline, sort_keys=False), encoding="utf-8")

    result = VisualSemanticQAStage().run(_context(config))

    assert result.success
    report = _load_report(config)
    by_risk = {}
    for item in report["findings"]:
        assert item["dimension"] in set(QA_DIMENSIONS) | {UNCATEGORIZED_DIMENSION}
        by_risk.setdefault(item["risk_type"], item["dimension"])
    assert by_risk["wardrobe_mismatch"] == "identity_continuity"
    # The deterministic checklist mentions "field coat" in its identity check.
    assert by_risk["contract_must_show_missing"] == "identity_continuity"
    assert report["dimension_summary"]["identity_continuity"]["failed"] >= 2


def test_legacy_contract_without_assertions_reads_as_unevaluated(tmp_path):
    config = _config(tmp_path)
    DirectorContractStage().run(_context(config))
    contract_path = config.pipeline_dir / "director_contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    for shot in contract["shots"]:
        shot["qa"].pop("assertions", None)
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    timeline_path = config.project_dir / "film_timeline.yaml"
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    timeline["tracks"]["visual"][0]["wardrobe"] = "red dress"
    timeline_path.write_text(yaml.safe_dump(timeline, sort_keys=False), encoding="utf-8")

    result = VisualSemanticQAStage().run(_context(config))

    assert result.success
    report = _load_report(config)
    summary = report["dimension_summary"]
    for dimension in QA_DIMENSIONS:
        assert summary[dimension]["assertions"] == 0
        assert summary[dimension]["unevaluated"] == 2
    by_risk = {item["risk_type"]: item["dimension"] for item in report["findings"]}
    # Legacy contracts still attribute via continuity constraints.
    assert by_risk["contract_must_show_missing"] == "identity_continuity"
    assert by_risk["wardrobe_mismatch"] == "identity_continuity"
    assert summary["identity_continuity"]["failed"] >= 1
