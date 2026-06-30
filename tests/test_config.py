#!/usr/bin/env python3
"""Tests for narrascape configuration models."""

from __future__ import annotations

from pathlib import Path

import pytest

from narrascape.config import (
    BudgetConfig,
    EndingConfig,
    ImageConfig,
    ImageMap,
    ImageMapEntry,
    ImagePrompt,
    ImageProvider,
    LLMConfig,
    NarrascapeConfig,
    PipelineConfig,
    ProjectConfig,
    Script,
    ScriptSegment,
    ShotType,
    SupersampleMode,
    VideoConfig,
    VideoProvider,
    VisualConfig,
    load_config,
)


class TestProjectConfig:
    def test_basic(self):
        cfg = ProjectConfig(name="test", title="Test Project", script_file="scripts/test.yaml")
        assert cfg.name == "test"
        assert cfg.title == "Test Project"


class TestVisualConfig:
    def test_defaults(self):
        cfg = VisualConfig()
        assert cfg.supersample == SupersampleMode.AUTO
        assert cfg.segment_gap == 1.5
        assert cfg.fade_in_duration == 3.0

    def test_gap_map_validation(self):
        with pytest.raises(ValueError):
            VisualConfig(gap_map={1: -1.0})
        with pytest.raises(ValueError):
            VisualConfig(gap_map={1: 15.0})

    def test_valid_gap_map(self):
        cfg = VisualConfig(gap_map={1: 2.5, 2: 1.0})
        assert cfg.gap_map[1] == 2.5


class TestNarrascapeConfig:
    def test_derived_paths(self):
        cfg = NarrascapeConfig(
            project=ProjectConfig(name="test-proj", title="Test", script_file="scripts/test.yaml"),
            project_dir=Path("/tmp/test"),
        )
        assert cfg.pipeline_dir == Path("/tmp/test/pipeline/test-proj")
        assert cfg.output_dir == Path("/tmp/test/output")
        assert cfg.resolution == (1920, 1080)

    def test_pipeline_defaults_enable_productized_film_loop(self):
        cfg = PipelineConfig()

        assert cfg.video_generation == "auto"
        assert cfg.design_overwrite is True
        assert cfg.strict_director is False
        assert cfg.production_quality_gates is False
        assert cfg.auto_rework is True
        assert cfg.max_rework_cycles == 1

    def test_pipeline_can_enable_strict_director_mode(self):
        cfg = PipelineConfig(strict_director=True)

        assert cfg.strict_director is True

    def test_pipeline_can_preserve_curated_design_files(self):
        cfg = PipelineConfig(design_overwrite=False)

        assert cfg.design_overwrite is False

    def test_pipeline_rejects_invalid_video_generation_policy(self):
        with pytest.raises(ValueError):
            PipelineConfig(video_generation="sometimes")

    def test_video_required_rejects_offline_llm_mode(self):
        with pytest.raises(ValueError, match="video_generation=required"):
            NarrascapeConfig(
                project=ProjectConfig(
                    name="required-video",
                    title="Required Video",
                    script_file="scripts/script.yaml",
                ),
                pipeline=PipelineConfig(video_generation="required"),
                llm=LLMConfig(mode="none"),
            )

    def test_crime_and_punishment_production_example_uses_seedream_seedance(self):
        config_path = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "crime-and-punishment"
            / "config.production.yaml"
        )

        cfg = load_config(config_path)

        assert cfg.pipeline.video_generation == "required"
        assert cfg.llm.mode == "ai_assistant"
        assert cfg.images.provider == ImageProvider.SEEDREAM
        assert cfg.video.provider == VideoProvider.SEEDANCE
        assert "Oil painting style" in cfg.images.style
        assert "photorealistic photography" in cfg.images.style

    def test_project_dir_is_not_serialized(self):
        cfg = NarrascapeConfig(
            project=ProjectConfig(name="test-proj", title="Test", script_file="scripts/test.yaml"),
            project_dir=Path("/tmp/test"),
        )

        dumped = cfg.model_dump()

        assert "project_dir" not in dumped

    def test_budget_video_estimate_is_configurable(self):
        cfg = BudgetConfig(video_estimated=0.0)

        assert cfg.video_estimated == 0.0


class TestEndingConfig:
    def test_ending_tone_is_configurable(self):
        cfg = EndingConfig(tone="melancholic")

        assert cfg.tone == "melancholic"


class TestScript:
    def test_basic(self):
        script = Script(
            segments=[
                ScriptSegment(id=1, text="Hello world."),
                ScriptSegment(id=2, text="Second segment."),
            ]
        )
        assert script.segment_count == 2
        assert script.get_text(1) == "Hello world."
        assert script.get_text(99) == ""


class TestImagePrompts:
    def test_shot_type_auto_derive(self):
        prompt = ImagePrompt(id="img_01", shot_type=ShotType.WIDE_ENV, description="Test")
        assert prompt.shot_type == ShotType.WIDE_ENV

    def test_size_validation(self):
        # Invalid format should raise ValueError
        with pytest.raises(ValueError):
            ImagePrompt(id="img_01", description="Test", size="not-valid")
        # Non-integer dimensions should raise ValueError
        with pytest.raises(ValueError):
            ImagePrompt(id="img_01", description="Test", size="abcxdef")
        # Too small dimensions should raise ValueError
        with pytest.raises(ValueError):
            ImagePrompt(id="img_01", description="Test", size="50x50")

        # Valid size should pass
        ImagePrompt(id="img_01", description="Test", size="100x100")

    def test_agnes_image_provider_is_valid(self):
        cfg = ImageConfig(provider=ImageProvider.AGNES, model="agnes-image-2.1-flash")

        assert cfg.provider == ImageProvider.AGNES


class TestVideoConfig:
    def test_agnes_video_provider_is_valid(self):
        cfg = VideoConfig(provider=VideoProvider.AGNES, model="agnes-video-v2.0")

        assert cfg.provider == VideoProvider.AGNES
        assert cfg.frame_rate == 24
        assert cfg.takes == 1

    def test_video_take_count_is_configurable(self):
        cfg = VideoConfig(takes=3)

        assert cfg.takes == 3

        with pytest.raises(ValueError):
            VideoConfig(takes=0)


class TestImageMap:
    def test_timing_validation(self):
        with pytest.raises(ValueError):
            ImageMapEntry(id=1, images=["img_01", "img_02"], timing=[0.6])
        with pytest.raises(ValueError):
            ImageMapEntry(id=1, images=["img_01"], timing=[0.5])

        entry = ImageMapEntry(id=1, images=["img_01", "img_02"], timing=[0.6, 0.4])
        assert entry.timing == [0.6, 0.4]

    def test_lookup(self):
        imap = ImageMap(
            segments=[
                ImageMapEntry(id=1, images=["img_01"]),
                ImageMapEntry(id=2, images=["img_02", "img_03"], timing=[0.5, 0.5]),
            ]
        )
        assert imap.get_images(1) == ["img_01"]
        assert imap.get_images(99) == []
