#!/usr/bin/env python3
"""Tests for pipeline dependency resolution."""
from __future__ import annotations

import pytest

from narrascape.pipeline import _resolve_dependencies
from narrascape.pipeline import Pipeline
from narrascape.config import LLMConfig, NarrascapeConfig, ProjectConfig, Script
from narrascape.llm import LLMClient
from narrascape.stages.base import StageResult
from narrascape.stages.kenburns import KenBurnsStage
from narrascape.stages.concat import ConcatStage
from narrascape.stages.audio import AudioStage
from narrascape.stages.subtitles import SubtitleStage
from narrascape.stages.design import DesignStage
from narrascape.stages.film_assemble import FilmAssembleStage
from narrascape.stages.generate_images import GenerateImagesStage
from narrascape.stages.generate_music import GenerateMusicStage
from narrascape.stages.generate_tts import GenerateTTSStage
from narrascape.stages.film_timeline import FilmTimelineStage
from narrascape.stages.humanize import HumanizeStage
from narrascape.stages.pre_production import PreProductionStage
from narrascape.stages.research import ResearchStage
from narrascape.stages.write import WriteStage
from narrascape.stages.audio import AudioRemixStage


class TestDependencyResolution:
    def test_all_stages(self):
        stages = ["kenburns", "concat", "audio", "subtitles"]
        available = {
            "pre_production": PreProductionStage,
            "design": DesignStage,
            "generate_images": GenerateImagesStage,
            "generate_tts": GenerateTTSStage,
            "film_timeline": FilmTimelineStage,
            "film_assemble": FilmAssembleStage,
            "generate_music": GenerateMusicStage,
            "remix_audio": AudioRemixStage,
            "kenburns": KenBurnsStage,
            "concat": ConcatStage,
            "audio": AudioStage,
            "subtitles": SubtitleStage,
        }
        order = _resolve_dependencies(stages, available)
        assert order == [
            "pre_production",
            "design",
            "generate_images",
            "generate_tts",
            "film_timeline",
            "film_assemble",
            "generate_music",
            "remix_audio",
            "kenburns",
            "concat",
            "audio",
            "subtitles",
        ]

    def test_partial_with_deps(self):
        # Asking for subtitles should pull the film timeline assembly chain.
        stages = ["subtitles"]
        available = {
            "pre_production": PreProductionStage,
            "design": DesignStage,
            "generate_images": GenerateImagesStage,
            "generate_tts": GenerateTTSStage,
            "film_timeline": FilmTimelineStage,
            "film_assemble": FilmAssembleStage,
            "generate_music": GenerateMusicStage,
            "remix_audio": AudioRemixStage,
            "kenburns": KenBurnsStage,
            "concat": ConcatStage,
            "audio": AudioStage,
            "subtitles": SubtitleStage,
        }
        order = _resolve_dependencies(stages, available)
        assert order == [
            "pre_production",
            "design",
            "generate_images",
            "generate_tts",
            "film_timeline",
            "film_assemble",
            "generate_music",
            "remix_audio",
            "audio",
            "subtitles",
        ]

    def test_circular_dependency(self):
        class FakeStage:
            @property
            def name(self): return "a"
            @property
            def depends_on(self): return ["b"]
        class FakeStageB:
            @property
            def name(self): return "b"
            @property
            def depends_on(self): return ["a"]

        available = {"a": FakeStage, "b": FakeStageB}
        with pytest.raises(RuntimeError, match="Circular"):
            _resolve_dependencies(["a"], available)

    def test_subtitles_resolves_complete_production_chain(self):
        stages = ["subtitles"]
        available = {
            "pre_production": PreProductionStage,
            "design": DesignStage,
            "generate_images": GenerateImagesStage,
            "generate_tts": GenerateTTSStage,
            "film_timeline": FilmTimelineStage,
            "film_assemble": FilmAssembleStage,
            "generate_music": GenerateMusicStage,
            "remix_audio": AudioRemixStage,
            "kenburns": KenBurnsStage,
            "concat": ConcatStage,
            "audio": AudioStage,
            "subtitles": SubtitleStage,
        }

        order = _resolve_dependencies(stages, available)

        assert order.index("pre_production") < order.index("design")
        assert order.index("design") < order.index("generate_images")
        assert order.index("design") < order.index("film_timeline")
        assert order.index("generate_tts") < order.index("film_timeline")
        assert order.index("film_timeline") < order.index("film_assemble")
        assert order.index("generate_tts") < order.index("generate_music")
        assert order.index("generate_music") < order.index("remix_audio")
        assert order.index("remix_audio") < order.index("audio")
        assert order.index("film_assemble") < order.index("audio")
        assert order.index("audio") < order.index("subtitles")

    def test_default_pipeline_orders_media_generation_before_rendering(self):
        default_stages = [
            "pre_production",
            "design",
            "generate_images",
            "generate_tts",
            "film_timeline",
            "film_assemble",
            "generate_music",
            "remix_audio",
            "audio",
            "subtitles",
        ]
        available = {
            "pre_production": PreProductionStage,
            "design": DesignStage,
            "generate_images": GenerateImagesStage,
            "generate_tts": GenerateTTSStage,
            "film_timeline": FilmTimelineStage,
            "film_assemble": FilmAssembleStage,
            "generate_music": GenerateMusicStage,
            "remix_audio": AudioRemixStage,
            "kenburns": KenBurnsStage,
            "concat": ConcatStage,
            "audio": AudioStage,
            "subtitles": SubtitleStage,
        }

        order = _resolve_dependencies(default_stages, available)

        assert order.index("generate_tts") < order.index("film_timeline")
        assert order.index("film_timeline") < order.index("film_assemble")
        assert order.index("film_assemble") < order.index("audio")
        assert order.index("remix_audio") < order.index("audio")


class TestPipelineStageFactory:
    def test_pipeline_passes_llm_client_to_all_llm_stages(self, tmp_path):
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="factory-test",
                title="Factory Test",
                script_file="scripts/script.yaml",
            ),
            llm=LLMConfig(mode="ai_assistant"),
            project_dir=tmp_path,
        )
        llm_client = LLMClient.from_env()
        pipeline = Pipeline(config, llm_client=llm_client)

        for stage_cls in (ResearchStage, WriteStage, HumanizeStage, PreProductionStage, DesignStage):
            stage = pipeline._create_stage(stage_cls)

            assert stage.llm_client is llm_client

    def test_pipeline_allows_missing_script_until_writer_creates_it(self, tmp_path):
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="missing-script-test",
                title="Missing Script Test",
                script_file="scripts/script.yaml",
            ),
            project_dir=tmp_path,
        )

        pipeline = Pipeline(config)

        assert isinstance(pipeline.script, Script)
        assert pipeline.script.segments == []

    def test_pipeline_runs_director_review_after_failed_qa(self, tmp_path, monkeypatch):
        class FakeQAStage:
            name = "qa"
            depends_on = []
            continue_on_failure = True

            def can_run(self, context):
                return True, ""

            def run(self, context):
                context.config.pipeline_dir.mkdir(parents=True, exist_ok=True)
                (context.config.pipeline_dir / "render_report.yaml").write_text(
                    "errors:\n- shot coverage incomplete\nchecks:\n  missing_visual_segments: [2]\n",
                    encoding="utf-8",
                )
                return StageResult("qa", False, message="shot coverage incomplete")

        class FakeDirectorReviewStage:
            name = "director_review"
            depends_on = ["qa"]

            def can_run(self, context):
                if not (context.config.pipeline_dir / "render_report.yaml").exists():
                    return False, "render_report.yaml not found"
                return True, ""

            def run(self, context):
                output = context.config.pipeline_dir / "director_review.yaml"
                output.write_text("status: needs_rework\n", encoding="utf-8")
                return StageResult("director_review", True, outputs=[output])

        config = NarrascapeConfig(
            project=ProjectConfig(
                name="qa-review-test",
                title="QA Review Test",
                script_file="scripts/script.yaml",
            ),
            project_dir=tmp_path,
        )
        (tmp_path / "scripts").mkdir(parents=True)
        (tmp_path / "scripts" / "script.yaml").write_text(
            "segments:\n- id: 1\n  text: Test segment.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "narrascape.pipeline.STAGE_MAP",
            {
                "qa": FakeQAStage,
                "director_review": FakeDirectorReviewStage,
            },
        )

        results = Pipeline(config, auto_approve=True).run(stages=["director_review"])

        assert results["qa"].success is False
        assert results["director_review"].success is True
        assert (config.pipeline_dir / "director_review.yaml").exists()

    def test_pipeline_clean_removes_film_assembly_and_director_review_artifacts(self, tmp_path):
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="clean-film-test",
                title="Clean Film Test",
                script_file="scripts/script.yaml",
            ),
            project_dir=tmp_path,
        )
        timeline_segments = config.pipeline_dir / "timeline_segments"
        timeline_segments.mkdir(parents=True)
        (timeline_segments / "v_001.mp4").write_bytes(b"segment")
        for filename in (
            "film_assemble.txt",
            "film_assembled.mp4",
            "render_report.yaml",
            "director_review.yaml",
        ):
            (config.pipeline_dir / filename).write_text("artifact", encoding="utf-8")

        Pipeline(config).clean(["film_assemble", "qa", "director_review"])

        assert not timeline_segments.exists()
        assert not (config.pipeline_dir / "film_assemble.txt").exists()
        assert not (config.pipeline_dir / "film_assembled.mp4").exists()
        assert not (config.pipeline_dir / "render_report.yaml").exists()
        assert not (config.pipeline_dir / "director_review.yaml").exists()
