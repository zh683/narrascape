#!/usr/bin/env python3
"""Tests for agent director components."""

from __future__ import annotations

import pytest

from narrascape.agent.models import BGMZoneSuggestion, DesignReport, SegmentAnalysis, ShotDesign
from narrascape.config import MovementType, ShotType
from narrascape.llm.models import LLMResponse, Message


class FakeLLMConfig:
    def __init__(self, provider: str):
        self.provider = provider


class FakeBatchLLMClient:
    def __init__(self, provider: str, response_content: str):
        self.config = FakeLLMConfig(provider)
        self.response_content = response_content
        self.complete_calls = 0
        self.validated_calls = 0

    def complete(self, prompt: str, **kwargs):
        self.complete_calls += 1
        return LLMResponse(
            content=self.response_content,
            model="fake",
        )

    def run_template_validated(self, *args, **kwargs):
        self.validated_calls += 1
        raise AssertionError("Expected batch complete(), not per-segment template calls")


class FakeTimeoutLLMClient(FakeBatchLLMClient):
    def __init__(self, provider: str):
        super().__init__(provider=provider, response_content="")

    def complete(self, prompt: str, **kwargs):
        self.complete_calls += 1
        raise RuntimeError("Bridge timeout")


class FakePromptAwareBatchLLMClient(FakeBatchLLMClient):
    def __init__(self, provider: str):
        super().__init__(provider=provider, response_content="")
        self.prompts = []

    def complete(self, prompt: str, **kwargs):
        import re

        self.complete_calls += 1
        self.prompts.append(prompt)
        ids = [int(value) for value in re.findall(r"Segment (\d+):", prompt)]
        return LLMResponse(
            content=str(
                [
                    {
                        "segment_id": seg_id,
                        "emotion": "calm",
                        "intensity": 0.3,
                        "scene_type": "outdoor",
                        "key_entities": ["river"],
                        "visual_keywords": ["morning mist"],
                        "pacing": "slow",
                    }
                    for seg_id in ids
                ]
            ).replace("'", '"'),
            model="fake",
        )


class TestAssistantBridgeBatching:
    """AI-assistant providers must use bridge-style batch tasks."""

    def test_script_analyzer_batches_ai_assistant_segments(self):
        from narrascape.agent.analyzer import ScriptAnalyzer
        from narrascape.config import Script, ScriptSegment

        client = FakeBatchLLMClient(
            provider="ai_assistant",
            response_content="""
            [
              {
                "segment_id": 1,
                "emotion": "calm",
                "intensity": 0.3,
                "scene_type": "outdoor",
                "key_entities": ["river"],
                "visual_keywords": ["morning mist"],
                "pacing": "slow"
              },
              {
                "segment_id": 2,
                "emotion": "hopeful",
                "intensity": 0.7,
                "scene_type": "portrait",
                "key_entities": ["traveler"],
                "visual_keywords": ["warm light"],
                "pacing": "normal"
              }
            ]
            """,
        )
        script = Script(
            segments=[
                ScriptSegment(id=1, text="A river at dawn."),
                ScriptSegment(id=2, text="A traveler looks toward the sun."),
            ]
        )

        analyses = ScriptAnalyzer(llm_client=client).analyze(script)

        assert client.complete_calls == 1
        assert client.validated_calls == 0
        assert [a.segment_id for a in analyses] == [1, 2]

    def test_script_analyzer_splits_large_ai_assistant_batches(self):
        from narrascape.agent.analyzer import ScriptAnalyzer
        from narrascape.config import Script, ScriptSegment

        client = FakePromptAwareBatchLLMClient(provider="ai_assistant")
        script = Script(segments=[ScriptSegment(id=i, text=f"Text {i}") for i in range(1, 24)])

        analyses = ScriptAnalyzer(llm_client=client).analyze(script)

        assert client.complete_calls == 3
        assert [analysis.segment_id for analysis in analyses] == list(range(1, 24))
        assert all(prompt.count(": Text ") <= 10 for prompt in client.prompts)

    def test_bridge_archives_response_atomically(self, tmp_path):
        import json

        from narrascape.llm.bridge import BridgeLLMClient

        task_dir = tmp_path / "bridge"
        client = BridgeLLMClient(task_dir=task_dir, timeout=1)
        task_id = client._task_id("## User\n\nhello", False, "")
        response_file = task_dir / "completed" / f"response_{task_id}.json"
        response_file.parent.mkdir(parents=True, exist_ok=True)
        response_file.write_text(
            json.dumps({"content": "done", "usage": {"prompt_tokens": 1}}),
            encoding="utf-8",
        )

        response = client.chat([Message(role="user", content="hello")])

        assert response.content == "done"
        assert (task_dir / "archive" / f"response_{task_id}.json").exists()
        assert not (task_dir / ".bridge.lock").exists()

    def test_bridge_rejects_response_without_string_content(self, tmp_path):
        import json

        from narrascape.llm.bridge import BridgeLLMClient
        from narrascape.llm.models import Message

        task_dir = tmp_path / "bridge"
        client = BridgeLLMClient(task_dir=task_dir, timeout=1)
        task_id = client._task_id("## User\n\nhello", False, "")
        response_file = task_dir / "completed" / f"response_{task_id}.json"
        response_file.parent.mkdir(parents=True, exist_ok=True)
        response_file.write_text(json.dumps({"content": 123}), encoding="utf-8")

        with pytest.raises(RuntimeError, match="invalid"):
            client.chat([Message(role="user", content="hello")])

    def test_script_analyzer_does_not_fallback_after_ai_assistant_timeout(self):
        from narrascape.agent.analyzer import ScriptAnalyzer
        from narrascape.config import Script, ScriptSegment

        client = FakeTimeoutLLMClient(provider="ai_assistant")
        script = Script(
            segments=[
                ScriptSegment(id=1, text="A river at dawn."),
                ScriptSegment(id=2, text="A traveler looks toward the sun."),
            ]
        )

        with pytest.raises(RuntimeError, match="Bridge timeout"):
            ScriptAnalyzer(llm_client=client).analyze(script)

        assert client.complete_calls == 1
        assert client.validated_calls == 0

    def test_prompt_director_batches_ai_assistant_shots(self):
        from narrascape.agent.prompt_director import PromptDirector
        from narrascape.config import NarrascapeConfig, ProjectConfig, ScriptSegment

        client = FakeBatchLLMClient(
            provider="ai_assistant",
            response_content="""
            [
              {
                "segment_id": 1,
                "shot_type": "establishing",
                "movement": "pan_left",
                "director_vision": "A quiet river opens into pale morning mist.",
                "cinematic_format": "EXT. RIVER - DAWN. ESTABLISHING SHOT. 35mm. SLOW PAN LEFT.",
                "image_prompt": "Wide cinematic dawn river with pale mist, soft golden light, distant banks, calm water, documentary realism.",
                "negative_prompt": "blurry, low quality, distorted anatomy",
                "reasoning": "The opening needs spatial context and a calm rhythm.",
                "emotion": "calm",
                "intensity": 0.3,
                "metadata": {
                  "focal_length": "35mm",
                  "aperture": "f/5.6",
                  "camera_angle": "eye level",
                  "lighting_scheme": "soft dawn backlight",
                  "light_sources": ["sunrise"],
                  "composition": "leading lines",
                  "color_palette": "gold and blue",
                  "atmosphere": "mist",
                  "depth_of_field": "deep",
                  "style_fingerprint": "documentary_dawn"
                }
              }
            ]
            """,
        )
        config = NarrascapeConfig(
            project=ProjectConfig(name="test", title="Test", script_file="scripts/script.yaml")
        )
        segments = [ScriptSegment(id=1, text="A river at dawn.")]
        analyses = [
            SegmentAnalysis(
                segment_id=1,
                emotion="calm",
                intensity=0.3,
                scene_type="landscape",
                key_entities=["river"],
                visual_keywords=["morning mist"],
                pacing="slow",
            )
        ]

        designs = PromptDirector(llm_client=client).design_sequence(
            segments=segments,
            analysis_list=analyses,
            config=config,
        )

        assert client.complete_calls == 1
        assert client.validated_calls == 0
        assert designs[0].segment_id == 1
        assert designs[0].shot_type == ShotType.ESTABLISHING


class TestSegmentAnalysis:
    def test_basic_creation(self):
        analysis = SegmentAnalysis(
            segment_id=1,
            emotion="hopeful",
            intensity=0.8,
            scene_type="outdoor",
            key_entities=["flower", "sun"],
            visual_keywords=["golden hour", "warm"],
            pacing="slow",
        )
        assert analysis.segment_id == 1
        assert analysis.emotion == "hopeful"
        assert analysis.intensity == 0.8

    def test_intensity_bounds(self):
        with pytest.raises(ValueError):
            SegmentAnalysis(segment_id=1, emotion="calm", intensity=1.5)
        with pytest.raises(ValueError):
            SegmentAnalysis(segment_id=1, emotion="calm", intensity=-0.1)


class TestShotDesign:
    def test_basic_creation(self):
        design = ShotDesign(
            segment_id=1,
            shot_type=ShotType.WIDE_ENV,
            movement=MovementType.PAN_LEFT,
            image_prompt="A wide landscape shot of mountains at dawn.",
            reasoning="Opening scene needs establishing shot.",
            style_prefix="cinematic",
            emotion="awe",
            intensity=0.9,
        )
        assert design.segment_id == 1
        assert design.shot_type == ShotType.WIDE_ENV
        assert design.movement == MovementType.PAN_LEFT
        assert design.image_prompt.startswith("A wide landscape")

    def test_to_image_prompts(self):
        design = ShotDesign(
            segment_id=1,
            shot_type=ShotType.CLOSE_UP,
            image_prompt="Close-up of a flower petal.",
            reasoning="Detail shot for emotional impact.",
            metadata={
                "negative_prompt": "anime, illustration",
                "focal_length": "85mm",
                "lighting_scheme": "Rembrandt",
            },
        )
        report = DesignReport(
            project_title="Test",
            style_template="documentary",
            segments=[design],
        )
        prompts = report.to_image_prompts()
        assert "prompts" in prompts
        assert len(prompts["prompts"]) == 1
        entry = prompts["prompts"][0]
        assert entry["id"] == "img_01"
        assert entry["shot_type"] == "close_up"
        assert entry["negative_prompt"] == "anime, illustration"
        assert entry["focal_length"] == "85mm"

    def test_to_design_report(self):
        design = ShotDesign(
            segment_id=1,
            shot_type=ShotType.MEDIUM,
            image_prompt="Medium shot of a person walking.",
            reasoning="Follow the subject.",
            metadata={"camera_angle": "eye level"},
        )
        report = DesignReport(
            project_title="Test Project",
            style_template="documentary",
            segments=[design],
            bgm_zones=[
                BGMZoneSuggestion(
                    covers=[1, 2], label="Opening", prompt="Piano solo", emotion="calm"
                ),
            ],
        )
        design_dict = report.to_design_report()
        assert design_dict["project_title"] == "Test Project"
        assert len(design_dict["segments"]) == 1
        assert design_dict["segments"][0]["camera_angle"] == "eye level"
        assert len(design_dict["bgm_zones"]) == 1

    def test_empty_report(self):
        report = DesignReport()
        assert report.to_image_prompts()["prompts"] == []
        assert report.to_image_map()["segments"] == []
        assert report.to_design_report()["segments"] == []


class TestPromptDirectorPureLogic:
    """Tests for PromptDirector methods that do not require LLM client."""

    def test_select_template_compact_for_long_context(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        template = director._select_template(
            text="A" * 40000,  # ~10K tokens
            cinematography_knowledge="K" * 8000,  # ~2K tokens
            video_model="deepseek-v3",
        )
        # Compact template includes "(3-layer output)" in its user prompt
        assert "(3-layer output)" in template.user

    def test_select_template_full_for_short_context(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        template = director._select_template(
            text="Short text.",
            cinematography_knowledge="Brief knowledge.",
            video_model="claude-3-5-sonnet",
        )
        # Full template includes "complete image generation prompt" in its user prompt
        assert "complete image generation prompt" in template.user

    def test_parse_shot_type_valid(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        assert director._parse_shot_type("close_up") == ShotType.CLOSE_UP
        assert director._parse_shot_type("wide_env") == ShotType.WIDE_ENV
        assert director._parse_shot_type("medium") == ShotType.MEDIUM

    def test_parse_shot_type_invalid_fallback(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        assert director._parse_shot_type("nonexistent") == ShotType.MEDIUM

    def test_parse_movement_valid(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        assert director._parse_movement("zoom_in") == MovementType.ZOOM_IN
        assert director._parse_movement("still") == MovementType.STILL
        assert director._parse_movement("pan_left") == MovementType.PAN_LEFT

    def test_parse_movement_invalid_fallback(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        assert director._parse_movement("nonexistent") == MovementType.STILL

    def test_derive_size(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        size = director._derive_size("close_up")
        assert size is not None
        assert "x" in size

    def test_inject_character_identity(self):
        from narrascape.agent.models import CharacterProfile
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        director._characters = [
            CharacterProfile(
                char_id="char_01",
                identity_block="An elderly man with white hair and weathered skin",
            )
        ]
        prompt = director._inject_character_identity("A man stands on a cliff.", ["char_01"])
        assert "white hair" in prompt
        assert "weathered skin" in prompt

    def test_inject_character_identity_no_characters(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        prompt = director._inject_character_identity("A man stands on a cliff.", [])
        assert prompt == "A man stands on a cliff."

    def test_estimate_duration_chinese(self):
        from narrascape.agent.prompt_director import PromptDirector
        from narrascape.config import NarrascapeConfig, ProjectConfig, TTSConfig

        director = PromptDirector(llm_client=None)
        config = NarrascapeConfig(
            project=ProjectConfig(name="test", title="Test", script_file="scripts/script.yaml"),
            tts=TTSConfig(speed=1.0),
        )
        duration = director._estimate_duration("这是一段中文测试文本", config)
        assert duration >= 3.0

    def test_estimate_duration_english(self):
        from narrascape.agent.prompt_director import PromptDirector
        from narrascape.config import NarrascapeConfig, ProjectConfig, TTSConfig

        director = PromptDirector(llm_client=None)
        config = NarrascapeConfig(
            project=ProjectConfig(name="test", title="Test", script_file="scripts/script.yaml"),
            tts=TTSConfig(speed=1.0),
        )
        duration = director._estimate_duration("This is an English test text", config)
        assert duration >= 3.0

    def test_verify_three_layer_consistency(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        # Should not raise
        director._verify_three_layer_consistency(
            {
                "director_vision": "A man with white hair",
                "cinematic_format": "A man with white hair, 85mm, f/2.8",
                "image_prompt": "A man with white hair",
            },
            "A man with white hair",
            "A man with white hair, 85mm, f/2.8",
            seg_id=1,
        )

    def test_verify_three_layer_consistency_mismatch(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        design_data = {
            "director_vision": "A man with white hair",
            "cinematic_format": "A woman with black hair, 85mm",
            "image_prompt": "A woman with black hair",
        }
        director._verify_three_layer_consistency(
            design_data,
            "A man with white hair",
            "A woman with black hair, 85mm",
            seg_id=1,
        )
        assert "_three_layer_warnings" in design_data

    def test_select_seedream_model_single_char(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        assert director._select_seedream_model(["char_01"]) == "jimeng-4.6"

    def test_select_seedream_model_multi_char(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        assert director._select_seedream_model(["char_01", "char_02"]) == "jimeng-4.0"

    def test_select_seedream_model_no_char(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        assert director._select_seedream_model([]) == "jimeng-5.0"

    def test_select_seedance_model(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        assert director._select_seedance_model() == "jimeng-video-seedance-2.0"

    def test_format_character_profiles_empty(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        result = director._format_character_profiles_for_template()
        assert "No characters" in result

    def test_format_scene_style_empty(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        result = director._format_scene_style_for_template()
        assert "No scene style" in result

    def test_build_reference_image_chains_empty(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        designs = []
        director._build_reference_image_chains(designs)
        assert director._reference_image_chains == []

    def test_format_storyboard_for_segment(self):
        from narrascape.agent.models import StoryboardFrame
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        frames = [
            StoryboardFrame(
                frame_id="sb_001_01",
                segment_id=1,
                frame_index=0,
                description="Wide shot of protagonist standing at cliff edge",
                shot_type="wide",
                camera_angle="low-angle",
                camera_movement="static",
                character_positions=["protagonist center"],
                emotion="awe",
                duration_hint=5.0,
                notes="Golden hour lighting",
            ),
            StoryboardFrame(
                frame_id="sb_001_02",
                segment_id=1,
                frame_index=1,
                description="Close-up of protagonist's determined face",
                shot_type="close-up",
                camera_angle="eye-level",
                camera_movement="slow_push_in",
                character_positions=["protagonist center"],
                emotion="determined",
                duration_hint=3.0,
                notes="Keep cliff background blurred",
            ),
        ]
        result = director._format_storyboard_for_segment(frames)
        assert "wide shot" in result.lower()
        assert "close-up" in result.lower()
        assert "low-angle" in result.lower()
        assert "eye-level" in result.lower()
        assert "follow the storyboard" in result.lower()

    def test_format_storyboard_for_segment_empty(self):
        from narrascape.agent.prompt_director import PromptDirector

        director = PromptDirector(llm_client=None)
        result = director._format_storyboard_for_segment([])
        assert result == ""


class TestPreProductionModels:
    """Tests for pre-production models (CharacterReferenceSheet, EnvironmentReference, Storyboard, PreProductionReport)."""

    def test_character_reference_sheet_creation(self):
        from narrascape.agent.models import CharacterReferenceImage, CharacterReferenceSheet

        anchor = CharacterReferenceImage(
            image_id="char_001_anchor",
            image_type="anchor",
            local_path="/tmp/char_001_anchor.png",
            prompt="Full body front view",
            model="jimeng-4.6",
            sample_strength=0.7,
        )
        sheet = CharacterReferenceSheet(
            char_id="char_001",
            name="Protagonist",
            identity_block="A young man with dark hair",
            anchor_image=anchor,
            primary_reference_path="/tmp/char_001_anchor.png",
            seedream_model="jimeng-4.6",
            seedream_sample_strength=0.7,
        )
        assert sheet.char_id == "char_001"
        assert sheet.anchor_image.image_type == "anchor"
        assert sheet.primary_reference_path == "/tmp/char_001_anchor.png"

    def test_environment_reference_creation(self):
        from narrascape.agent.models import EnvironmentReference, EnvironmentReferenceImage

        mood = EnvironmentReferenceImage(
            image_id="scene_001_mood",
            image_type="mood",
            local_path="/tmp/scene_001_mood.png",
            prompt="Misty forest at dawn",
        )
        env = EnvironmentReference(
            scene_id="scene_001",
            scene_name="Misty Forest",
            scene_type="outdoor",
            mood_images=[mood],
            primary_reference_path="/tmp/scene_001_mood.png",
            time_of_day="dawn",
            weather="foggy",
        )
        assert env.scene_id == "scene_001"
        assert len(env.mood_images) == 1
        assert env.primary_reference_path == "/tmp/scene_001_mood.png"

    def test_storyboard_frames_for_segment(self):
        from narrascape.agent.models import Storyboard, StoryboardFrame

        frames = [
            StoryboardFrame(
                frame_id="sb_001_01", segment_id=1, frame_index=0, description="Wide shot"
            ),
            StoryboardFrame(
                frame_id="sb_001_02", segment_id=1, frame_index=1, description="Close-up"
            ),
            StoryboardFrame(
                frame_id="sb_002_01", segment_id=2, frame_index=0, description="Medium shot"
            ),
        ]
        sb = Storyboard(frames=frames, total_frames=3, total_segments=2)
        seg1_frames = sb.frames_for_segment(1)
        assert len(seg1_frames) == 2
        assert seg1_frames[0].frame_id == "sb_001_01"
        seg2_frames = sb.frames_for_segment(2)
        assert len(seg2_frames) == 1

    def test_pre_production_report_export(self):
        from narrascape.agent.models import (
            CharacterReferenceImage,
            CharacterReferenceSheet,
            EnvironmentReference,
            EnvironmentReferenceImage,
            PreProductionReport,
            Storyboard,
            StoryboardFrame,
        )

        anchor = CharacterReferenceImage(
            image_id="char_001_anchor",
            image_type="anchor",
            local_path="/tmp/char_001_anchor.png",
            prompt="test",
        )
        sheet = CharacterReferenceSheet(
            char_id="char_001",
            name="Hero",
            anchor_image=anchor,
            primary_reference_path="/tmp/char_001_anchor.png",
        )
        mood = EnvironmentReferenceImage(
            image_id="scene_001_mood",
            image_type="mood",
            local_path="/tmp/scene_001_mood.png",
            prompt="test",
        )
        env = EnvironmentReference(
            scene_id="scene_001",
            scene_name="Forest",
            mood_images=[mood],
            primary_reference_path="/tmp/scene_001_mood.png",
        )
        frame = StoryboardFrame(
            frame_id="sb_001_01",
            segment_id=1,
            frame_index=0,
            description="Wide shot",
            shot_type="wide",
        )
        sb = Storyboard(frames=[frame], total_frames=1, total_segments=1)

        report = PreProductionReport(
            project_title="Test Project",
            style_anchor_path="/tmp/style_anchor.png",
            characters=[sheet],
            environments=[env],
            storyboard=sb,
        )

        # Test dict exports
        char_refs = report.to_character_refs_dict()
        assert char_refs["char_001"] == "/tmp/char_001_anchor.png"

        scene_refs = report.to_scene_refs_dict()
        assert scene_refs["scene_001"] == "/tmp/scene_001_mood.png"

        sb_frames = report.to_storyboard_frames()
        assert len(sb_frames) == 1
        assert sb_frames[0]["frame_id"] == "sb_001_01"

        full_report = report.to_pre_production_report()
        assert full_report["project_title"] == "Test Project"
        assert full_report["style_anchor_path"] == "/tmp/style_anchor.png"
        assert len(full_report["characters"]) == 1
        assert len(full_report["environments"]) == 1
        assert full_report["storyboard"]["total_frames"] == 1

    def test_pre_production_report_empty(self):
        from narrascape.agent.models import PreProductionReport

        report = PreProductionReport()
        assert report.to_character_refs_dict() == {}
        assert report.to_scene_refs_dict() == {}
        assert report.to_storyboard_frames() == []
        assert report.to_pre_production_report()["characters"] == []


class TestLLMResponseParsing:
    def test_extract_json_handles_text_around_fenced_json(self):
        response = LLMResponse(
            content='Before\n```json\n{"ok": true, "items": [1, 2]}\n```\nAfter',
            model="fake",
        )

        assert response.extract_json() == {"ok": True, "items": [1, 2]}

    def test_extract_json_falls_back_to_embedded_object(self):
        response = LLMResponse(content='prefix {"status": "ok"} suffix', model="fake")

        assert response.extract_json() == {"status": "ok"}

    def test_extract_json_respects_braces_inside_strings(self):
        response = LLMResponse(
            content='prefix {"status": "ok", "text": "brace } inside"} suffix',
            model="fake",
        )

        assert response.extract_json() == {"status": "ok", "text": "brace } inside"}

    def test_json_repair_ignores_braces_inside_strings(self):
        from narrascape.llm.output_parser import JSONRepair

        repaired = JSONRepair.repair('{"text": "brace } inside", "items": [1, 2]')

        assert repaired == '{"text": "brace } inside", "items": [1, 2]}'

    def test_list_items_have_keys_validates_top_level_list(self):
        from narrascape.llm.output_parser import OutputValidator

        validator = OutputValidator.list_items_have_keys("id", "status")

        is_valid, error = validator([{"id": 1, "status": "ok"}])

        assert is_valid is True
        assert error == ""

    def test_list_items_have_keys_rejects_wrong_shape(self):
        from narrascape.llm.output_parser import OutputValidator

        validator = OutputValidator.list_items_have_keys("id", "status")

        is_valid, error = validator({"items": [{"id": 1, "status": "ok"}]})

        assert is_valid is False
        assert "Expected list" in error

    def test_list_items_have_keys_reports_missing_item_keys(self):
        from narrascape.llm.output_parser import OutputValidator

        validator = OutputValidator.list_items_have_keys("id", "status")

        is_valid, error = validator([{"id": 1}])

        assert is_valid is False
        assert "missing keys" in error
