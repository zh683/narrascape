#!/usr/bin/env python3
"""Tests for opt-in storyboard-as-generation-condition (video.storyboard_conditioning).

Covers: default-off zero behavior change, storyboard panel promotion to
first_frame, storyboard-bound reference prioritization, graceful fallback
when panels/ids are missing, fingerprint invalidation on panel switches,
and per-segment state recording — all at the mock layer (no real provider
calls).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from PIL import Image

from narrascape.config import (
    AudioConfig,
    ImageConfig,
    ImageProvider,
    MusicAudioConfig,
    MusicProvider,
    NarrascapeConfig,
    ProjectConfig,
    TTSConfig,
    TTSProvider,
    VideoConfig,
    load_script,
)
from narrascape.stages.base import StageContext
from narrascape.stages.generate_video import GenerateVideoStage


def _png(path: Path, color: str = "red") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _contract(*, with_binding: bool = True) -> dict:
    binding = (
        {
            "storyboard_frame_ids": ["sb_01_01"],
            "character_positions": [],
            "scene_ref": "",
            "wardrobe_lock": "",
            "composition_requirements": [],
            "reference_image_ids": ["sb_ref_1"],
        }
        if with_binding
        else {}
    )
    return {"segment_id": 1, "storyboard_binding": binding}


class TestStoryboardConditionedInputs:
    def _stage(self) -> GenerateVideoStage:
        return GenerateVideoStage(api_key="fake")

    def test_panel_promoted_to_first_frame_and_storyboard_refs_lead(self, tmp_path):
        stage = self._stage()
        panel = tmp_path / "assets" / "storyboard" / "sb_01_01.png"
        _png(panel, "blue")
        reference_inputs = {
            "uploaded_reference_assets": [
                {"url": "data:style", "requested_id": "style_anchor"},
                {"url": "data:char", "requested_id": "sb_ref_1"},
            ],
            "uploaded_reference_images": ["data:style", "data:char"],
            "state": {"segment_id": 1},
        }

        first_frame, reference_images = stage._storyboard_conditioned_inputs(
            SimpleNamespace(project_dir=tmp_path),
            _contract(),
            "data:generated-still",
            reference_inputs,
            "seedance",
        )

        assert first_frame == _data_uri(panel)
        # 分镜绑定参考（叙事意图）领先自动派生参考
        assert reference_images == ["data:char", "data:style"]
        annotation = reference_inputs["state"]["storyboard_conditioning"]
        assert annotation["panel"] == "sb_01_01.png"
        assert annotation["panel_applied"] is True
        assert annotation["storyboard_reference_ids"] == ["sb_ref_1"]

    def test_missing_panel_falls_back_but_still_prioritizes_storyboard_refs(self, tmp_path):
        stage = self._stage()
        reference_inputs = {
            "uploaded_reference_assets": [
                {"url": "data:style", "requested_id": "style_anchor"},
                {"url": "data:char", "requested_id": "sb_ref_1"},
            ],
            "uploaded_reference_images": ["data:style", "data:char"],
            "state": {},
        }

        first_frame, reference_images = stage._storyboard_conditioned_inputs(
            SimpleNamespace(project_dir=tmp_path),
            _contract(),
            "data:generated-still",
            reference_inputs,
            "seedance",
        )

        assert first_frame == "data:generated-still"
        assert reference_images == ["data:char", "data:style"]
        assert reference_inputs["state"]["storyboard_conditioning"]["panel_applied"] is False

    def test_no_binding_leaves_inputs_untouched(self, tmp_path):
        stage = self._stage()
        reference_inputs = {
            "uploaded_reference_assets": [{"url": "data:style", "requested_id": "style_anchor"}],
            "uploaded_reference_images": ["data:style"],
            "state": {},
        }

        first_frame, reference_images = stage._storyboard_conditioned_inputs(
            SimpleNamespace(project_dir=tmp_path),
            _contract(with_binding=False),
            "data:generated-still",
            reference_inputs,
            "seedance",
        )

        assert first_frame == "data:generated-still"
        assert reference_images == ["data:style"]
        assert reference_inputs["state"]["storyboard_conditioning"] == {
            "panel": None,
            "panel_applied": False,
            "storyboard_reference_ids": [],
        }

    def test_agnes_branch_returns_asset_dicts(self, tmp_path):
        stage = self._stage()
        reference_inputs = {
            "uploaded_reference_assets": [
                {"url": "data:style", "requested_id": "style_anchor"},
                {"url": "data:char", "requested_id": "sb_ref_1"},
            ],
            "uploaded_reference_images": ["data:style", "data:char"],
            "state": {},
        }

        _first, reference_images = stage._storyboard_conditioned_inputs(
            SimpleNamespace(project_dir=tmp_path),
            _contract(),
            None,
            reference_inputs,
            "agnes",
        )

        assert [asset["requested_id"] for asset in reference_images] == ["sb_ref_1", "style_anchor"]


class TestStoryboardConditioningFingerprint:
    def test_panel_switch_changes_request_fingerprint(self, tmp_path):
        stage = GenerateVideoStage(api_key="fake")
        panel_a = tmp_path / "assets" / "storyboard" / "sb_01_01.png"
        panel_b = tmp_path / "assets" / "storyboard" / "sb_02_01.png"
        _png(panel_a, "blue")
        _png(panel_b, "green")

        base = {
            "provider": "seedance",
            "model": "m",
            "resolution": "720p",
            "prompt": "p",
            "negative_prompt": "",
            "last_frame": None,
            "reference_images": [],
        }
        fp_a = stage._video_request_fingerprint(first_frame=stage.uploader.upload(panel_a), **base)
        fp_b = stage._video_request_fingerprint(first_frame=stage.uploader.upload(panel_b), **base)
        fp_still = stage._video_request_fingerprint(first_frame="data:generated-still", **base)

        assert fp_a != fp_b
        assert fp_a != fp_still

    def test_panel_content_change_changes_request_fingerprint(self, tmp_path):
        stage = GenerateVideoStage(api_key="fake")
        panel = tmp_path / "assets" / "storyboard" / "sb_01_01.png"
        _png(panel, "blue")
        base = {
            "provider": "seedance",
            "model": "m",
            "resolution": "720p",
            "prompt": "p",
            "negative_prompt": "",
            "last_frame": None,
            "reference_images": [],
        }
        fp_before = stage._video_request_fingerprint(
            first_frame=stage.uploader.upload(panel), **base
        )
        _png(panel, "yellow")  # same path, new content
        fp_after = stage._video_request_fingerprint(
            first_frame=stage.uploader.upload(panel), **base
        )

        assert fp_before != fp_after


# ── Integration: full stage run at the mock layer ──


def _write_project(project_dir: Path) -> None:
    (project_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump({"segments": [{"id": 1, "text": "One."}, {"id": 2, "text": "Two."}]}),
        encoding="utf-8",
    )
    (project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(
            {
                "project_title": "Storyboard Conditioning",
                "segments": [
                    {"segment_id": 1, "shot_type": "medium", "image_prompt": "First shot."},
                    {"segment_id": 2, "shot_type": "medium", "image_prompt": "Second shot."},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_director_contract(pipeline_dir: Path) -> None:
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "director_contract.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "director_contract.v1",
                "compile_process": {
                    "mode": "deterministic_prompt_compiler",
                    "llm_status": "not_configured",
                },
                "shots": [
                    {
                        "segment_id": 1,
                        "shot_id": "shot_001",
                        "story_reason": "Mira adjusts the telescope before dawn.",
                        "emotional_target": "quiet resolve",
                        "film_language": {
                            "shot_type": "wide",
                            "camera_motion": "push_in",
                            "lighting": "warm window light",
                            "composition": "Mira at the frame edge beside the telescope",
                        },
                        "continuity_constraints": {
                            "characters": ["mira"],
                            "location": "observatory",
                            "wardrobe": "field coat",
                            "lighting": "warm window light",
                        },
                        "storyboard_binding": {
                            "storyboard_frame_ids": ["sb_01_01"],
                            "character_positions": ["Mira beside the telescope"],
                            "scene_ref": "observatory",
                            "wardrobe_lock": "field coat",
                            "composition_requirements": [
                                "Mira at the frame edge beside the telescope"
                            ],
                            "reference_image_ids": ["sb_ref_1"],
                        },
                        "generation": {
                            "video_prompt": (
                                "Mira in a field coat walks through the observatory and "
                                "adjusts the brass telescope; slow push-in, wide shot, warm "
                                "window light and soft shadow palette, oil painting style "
                                "with visible brush texture."
                            ),
                            "negative_prompt": "",
                            "duration": 5.0,
                            "motion": "push_in",
                        },
                        "qa": {"must_show": ["mira"], "must_not_show": []},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _fake_download(url, dest, **kwargs):
    dest.write_bytes(b"\x00\x00\x00\x18ftypmp42")


def _make_stage(tmp_path, monkeypatch, *, conditioning: str):
    project_dir = tmp_path / "project"
    _write_project(project_dir)
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="project",
            title="Storyboard Conditioning",
            script_file="scripts/script.yaml",
        ),
        images=ImageConfig(provider=ImageProvider.LOCAL, width=640, height=480),
        tts=TTSConfig(provider=TTSProvider.LOCAL),
        audio=AudioConfig(music=MusicAudioConfig(provider=MusicProvider.LOCAL)),
        video=VideoConfig(storyboard_conditioning=conditioning),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True, exist_ok=True)
    config.images_dir.mkdir(parents=True, exist_ok=True)
    _write_director_contract(config.pipeline_dir)
    _png(project_dir / "assets" / "storyboard" / "sb_01_01.png", "blue")
    _png(project_dir / "assets" / "references" / "sb_ref_1.png", "green")
    _png(project_dir / "assets" / "references" / "style_anchor.png", "gray")

    stage = GenerateVideoStage(api_key="fake", poll_interval=0, sleep_between=0)
    captured: list[dict] = []

    def fake_create(prompt, model, resolution, first_frame, last_frame, reference_images=None):
        captured.append(
            {
                "prompt": prompt,
                "first_frame": first_frame,
                "reference_images": list(reference_images or []),
            }
        )
        return f"task-{len(captured)}"

    monkeypatch.setattr(stage, "_create_task", fake_create)
    monkeypatch.setattr(stage, "_poll_task", lambda task_id: f"https://v/{task_id}.mp4")
    monkeypatch.setattr("narrascape.stages.generate_video.download_to_path", _fake_download)
    monkeypatch.setattr("narrascape.stages.generate_video.validate_video", lambda path: True)
    context = StageContext(config=config, script=load_script(config.script_path))
    return config, stage, context, captured


class TestStoryboardConditioningEndToEnd:
    def test_auto_mode_promotes_panel_and_prioritizes_storyboard_refs(self, tmp_path, monkeypatch):
        config, _stage, context, captured = _make_stage(tmp_path, monkeypatch, conditioning="auto")

        result = _stage_run(_stage, context)

        assert result.success is True
        assert len(captured) == 2
        panel_uri = _data_uri(config.project_dir / "assets" / "storyboard" / "sb_01_01.png")
        sb_ref_uri = _data_uri(config.project_dir / "assets" / "references" / "sb_ref_1.png")
        style_uri = _data_uri(config.project_dir / "assets" / "references" / "style_anchor.png")
        # Segment 1 (bound): panel is the first_frame, storyboard ref leads.
        assert captured[0]["first_frame"] == panel_uri
        assert captured[0]["reference_images"][0] == sb_ref_uri
        assert style_uri in captured[0]["reference_images"]
        # Segment 2 (no binding): untouched.
        assert captured[1]["first_frame"] is None

        state = json.loads(
            (config.pipeline_dir / "video_gen_state.json").read_text(encoding="utf-8")
        )
        annotation = state["reference_inputs"]["vid_01"]["storyboard_conditioning"]
        assert annotation["panel"] == "sb_01_01.png"
        assert annotation["panel_applied"] is True

    def test_default_off_keeps_legacy_inputs(self, tmp_path, monkeypatch):
        config, _stage, context, captured = _make_stage(tmp_path, monkeypatch, conditioning="off")

        result = _stage_run(_stage, context)

        assert result.success is True
        assert len(captured) == 2
        style_uri = _data_uri(config.project_dir / "assets" / "references" / "style_anchor.png")
        sb_ref_uri = _data_uri(config.project_dir / "assets" / "references" / "sb_ref_1.png")
        # 面板存在也不提升；参考顺序保持自动派生（style_anchor 领先）
        assert captured[0]["first_frame"] is None
        assert captured[0]["reference_images"][:2] == [style_uri, sb_ref_uri]
        state = json.loads(
            (config.pipeline_dir / "video_gen_state.json").read_text(encoding="utf-8")
        )
        assert "storyboard_conditioning" not in state["reference_inputs"]["vid_01"]


def _stage_run(stage, context):
    return stage.run(context)
