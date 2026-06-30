#!/usr/bin/env python3
"""Tests for pipeline dependency resolution."""

from __future__ import annotations

import pytest
import yaml

from narrascape.cache import BuildCache
from narrascape.config import (
    EndingConfig,
    ImageConfig,
    ImageProvider,
    LLMConfig,
    NarrascapeConfig,
    PipelineConfig,
    ProjectConfig,
    Script,
)
from narrascape.llm import LLMClient
from narrascape.pipeline import Pipeline, _resolve_dependencies, get_stage_map
from narrascape.stages.animatic import AnimaticStage
from narrascape.stages.audio import AudioRemixStage, AudioStage
from narrascape.stages.base import StageContext, StageResult
from narrascape.stages.concat import ConcatStage
from narrascape.stages.design import DesignStage
from narrascape.stages.film_assemble import FilmAssembleStage
from narrascape.stages.film_timeline import FilmTimelineStage
from narrascape.stages.generate_images import GenerateImagesStage
from narrascape.stages.generate_music import GenerateMusicStage
from narrascape.stages.generate_tts import GenerateTTSStage
from narrascape.stages.humanize import HumanizeStage
from narrascape.stages.kenburns import KenBurnsStage
from narrascape.stages.pre_production import PreProductionStage
from narrascape.stages.reference_plate import ReferencePlateStage
from narrascape.stages.remotion_preview import RemotionPreviewStage
from narrascape.stages.research import ResearchStage
from narrascape.stages.subtitles import SubtitleStage
from narrascape.stages.write import WriteStage


class TestDependencyResolution:
    def test_all_stages(self):
        stages = ["kenburns", "concat", "audio", "subtitles"]
        available = {
            "pre_production": PreProductionStage,
            "design": DesignStage,
            "generate_images": GenerateImagesStage,
            "generate_tts": GenerateTTSStage,
            "film_timeline": FilmTimelineStage,
            "remotion_preview": RemotionPreviewStage,
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
            "remotion_preview",
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
            "remotion_preview": RemotionPreviewStage,
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
            "remotion_preview",
            "film_assemble",
            "generate_music",
            "remix_audio",
            "audio",
            "subtitles",
        ]

    def test_circular_dependency(self):
        class FakeStage:
            @property
            def name(self):
                return "a"

            @property
            def depends_on(self):
                return ["b"]

        class FakeStageB:
            @property
            def name(self):
                return "b"

            @property
            def depends_on(self):
                return ["a"]

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
            "remotion_preview": RemotionPreviewStage,
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
        assert order.index("film_timeline") < order.index("remotion_preview")
        assert order.index("remotion_preview") < order.index("film_assemble")
        assert order.index("generate_tts") < order.index("generate_music")
        assert order.index("generate_music") < order.index("remix_audio")
        assert order.index("remix_audio") < order.index("audio")
        assert order.index("film_assemble") < order.index("audio")
        assert order.index("audio") < order.index("subtitles")

    def test_default_pipeline_orders_media_generation_before_rendering(self):
        default_stages = [
            "pre_production",
            "design",
            "screenplay_structure",
            "director_contract",
            "reference_plate",
            "generate_images",
            "animatic",
            "generate_video",
            "take_select",
            "generate_tts",
            "film_timeline",
            "remotion_preview",
            "film_assemble",
            "generate_music",
            "remix_audio",
            "audio",
            "subtitles",
        ]
        available = {
            "pre_production": PreProductionStage,
            "design": DesignStage,
            "screenplay_structure": __import__(
                "narrascape.stages.screenplay_structure",
                fromlist=["ScriptSceneDirectorStage"],
            ).ScriptSceneDirectorStage,
            "director_contract": __import__(
                "narrascape.stages.director_contract",
                fromlist=["DirectorContractStage"],
            ).DirectorContractStage,
            "reference_plate": ReferencePlateStage,
            "generate_images": GenerateImagesStage,
            "animatic": AnimaticStage,
            "generate_video": __import__(
                "narrascape.stages.generate_video",
                fromlist=["GenerateVideoStage"],
            ).GenerateVideoStage,
            "take_select": __import__(
                "narrascape.stages.take_select",
                fromlist=["TakeSelectStage"],
            ).TakeSelectStage,
            "generate_tts": GenerateTTSStage,
            "film_timeline": FilmTimelineStage,
            "remotion_preview": RemotionPreviewStage,
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
        assert order.index("director_contract") < order.index("generate_video")
        assert order.index("reference_plate") < order.index("generate_video")
        assert order.index("reference_plate") < order.index("animatic")
        assert order.index("animatic") < order.index("generate_video")
        assert order.index("generate_video") < order.index("take_select")
        assert order.index("film_timeline") < order.index("remotion_preview")
        assert order.index("remotion_preview") < order.index("film_assemble")
        assert order.index("film_assemble") < order.index("audio")
        assert order.index("remix_audio") < order.index("audio")


class TestPipelineStageFactory:
    def test_get_stage_map_uses_class_level_stage_names_without_instantiating(self, monkeypatch):
        import narrascape.pipeline as pipeline_module

        class ExplodingStage:
            name = "explode"
            depends_on = []

            def __init__(self):
                raise AssertionError("stage should not be instantiated to read name")

        monkeypatch.setattr(pipeline_module, "ALL_STAGES", [ExplodingStage])
        monkeypatch.setattr(pipeline_module, "STAGE_MAP", None)

        assert get_stage_map() == {"explode": ExplodingStage}

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

        for stage_cls in (
            ResearchStage,
            WriteStage,
            HumanizeStage,
            PreProductionStage,
            DesignStage,
        ):
            stage = pipeline._create_stage(stage_cls)

            assert stage.llm_client is llm_client

    def test_required_video_pipeline_rejects_missing_llm_client(self, tmp_path):
        config = NarrascapeConfig.model_construct(
            project=ProjectConfig(
                name="required-video",
                title="Required Video",
                script_file="scripts/script.yaml",
            ),
            pipeline=PipelineConfig(video_generation="required"),
            llm=LLMConfig(mode="ai_assistant"),
            project_dir=tmp_path,
        )

        with pytest.raises(RuntimeError, match="video_generation=required"):
            Pipeline(config, llm_client=None)

    def test_pipeline_uses_lean_pre_production_for_agnes(self, tmp_path):
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="agnes-prepro-test",
                title="Agnes Prepro Test",
                script_file="scripts/script.yaml",
            ),
            images=ImageConfig(provider=ImageProvider.AGNES),
            project_dir=tmp_path,
        )

        stage = Pipeline(config)._create_stage(PreProductionStage)

        assert stage.generate_turns is False
        assert stage.generate_expressions is False

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

    def test_write_stage_uses_configured_ending_tone(self, tmp_path, monkeypatch):
        from narrascape.config import ScriptSegment
        from narrascape.research.engine import ResearchResult

        seen = {}

        def fake_research(self, topic, depth="standard"):
            return ResearchResult(topic=topic, findings={"Overview": "A small test story."})

        def fake_write_from_research(self, research, segment_count):
            return Script(segments=[ScriptSegment(id=1, text="Opening.")])

        def fake_write_ending(self, script, tone="hopeful"):
            seen["tone"] = tone
            return script

        monkeypatch.setattr("narrascape.stages.write.ResearchEngine.research", fake_research)
        monkeypatch.setattr(
            "narrascape.stages.write.ScriptWriter.write_from_research",
            fake_write_from_research,
        )
        monkeypatch.setattr(
            "narrascape.stages.write.ScriptWriter.write_ending",
            fake_write_ending,
        )

        config = NarrascapeConfig(
            project=ProjectConfig(
                name="write-tone-test",
                title="Write Tone Test",
                script_file="scripts/script.yaml",
            ),
            ending=EndingConfig(tone="melancholic"),
            project_dir=tmp_path,
        )

        result = WriteStage(auto_humanize=False).run(
            StageContext(
                config=config,
                script=Script.model_construct(segments=[]),
                cache=BuildCache(config.pipeline_dir / ".cache"),
            )
        )

        assert result.success is True
        assert seen["tone"] == "melancholic"

    def test_research_result_markdown_formats_nested_findings(self):
        from narrascape.research.engine import ResearchResult

        report = ResearchResult(
            topic="Nested Topic",
            findings={
                "facts": {
                    "timeline": ["first", "second"],
                    "metadata": {"source": "archive", "confidence": 0.8},
                }
            },
        )

        markdown = report.to_markdown()

        assert "{'timeline'" not in markdown
        assert "- **timeline:**" in markdown
        assert "  - first" in markdown
        assert "- **source:** archive" in markdown

    def test_default_stages_include_video_take_select_and_supervisor_loop(self, tmp_path):
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="default-stage-test",
                title="Default Stage Test",
                script_file="scripts/script.yaml",
            ),
            project_dir=tmp_path,
        )

        stages = Pipeline(config)._default_stages()

        assert "generate_video" in stages
        assert "storyboard_sheet" in stages
        assert "production_readiness" in stages
        assert "animatic" in stages
        assert "take_select" in stages
        assert stages.index("reference_plate") < stages.index("animatic")
        assert stages.index("reference_plate") < stages.index("storyboard_sheet")
        assert stages.index("storyboard_sheet") < stages.index("generate_images")
        assert stages.index("storyboard_sheet") < stages.index("production_readiness")
        assert stages.index("production_readiness") < stages.index("generate_video")
        assert stages.index("animatic") < stages.index("generate_video")
        assert stages.index("generate_video") < stages.index("take_select")
        assert stages.index("take_select") < stages.index("film_timeline")
        assert stages[-1] == "film_supervisor"

    def test_default_stages_can_disable_video_generation(self, tmp_path):
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="no-video-test",
                title="No Video Test",
                script_file="scripts/script.yaml",
            ),
            pipeline=PipelineConfig(video_generation="off"),
            project_dir=tmp_path,
        )

        stages = Pipeline(config)._default_stages()

        assert "generate_video" not in stages
        assert "take_select" not in stages
        assert "storyboard_sheet" in stages
        assert "production_readiness" in stages
        assert "animatic" in stages
        assert "film_timeline" in stages

    def test_optional_video_stage_can_be_skipped_in_auto_policy(self, tmp_path, monkeypatch):
        class FakeGenerateVideoStage:
            name = "generate_video"
            depends_on = []

            def can_run(self, context):
                return False, "seedance_video selected but ARK_API_KEY not found"

            def run(self, context):
                raise AssertionError("optional stage should not execute")

        class FakeFilmTimelineStage:
            name = "film_timeline"
            depends_on = []

            def can_run(self, context):
                return True, ""

            def run(self, context):
                return StageResult("film_timeline", True, message="timeline fallback")

        config = NarrascapeConfig(
            project=ProjectConfig(
                name="optional-video-test",
                title="Optional Video Test",
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
                "generate_video": FakeGenerateVideoStage,
                "film_timeline": FakeFilmTimelineStage,
            },
        )

        results = Pipeline(config, auto_approve=True, image_api_key=None).run(
            stages=["generate_video", "film_timeline"]
        )

        assert results["generate_video"].success is False

        results = Pipeline(config, auto_approve=True, image_api_key=None)._run_once(
            ["generate_video", "film_timeline"], allow_optional_skips=True
        )

        assert results["generate_video"].success is True
        assert results["generate_video"].metadata["optional_skipped"] is True
        assert results["film_timeline"].success is True

    def test_strict_director_mode_fails_on_not_configured_director_stage(
        self, tmp_path, monkeypatch
    ):
        class FakeDirectorContractStage:
            name = "director_contract"
            depends_on = []

            def can_run(self, context):
                return True, ""

            def run(self, context):
                output = context.config.pipeline_dir / "director_contract.yaml"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    yaml.safe_dump(
                        {
                            "schema_version": "director_contract.v1",
                            "compile_process": {
                                "mode": "deterministic_prompt_compiler",
                                "llm_status": "not_configured",
                            },
                            "shots": [],
                        },
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
                return StageResult("director_contract", True, outputs=[output])

        class FakeLaterStage:
            name = "film_timeline"
            depends_on = ["director_contract"]

            def can_run(self, context):
                return True, ""

            def run(self, context):
                raise AssertionError("strict director failure should stop downstream stages")

        config = NarrascapeConfig(
            project=ProjectConfig(
                name="strict-director-test",
                title="Strict Director Test",
                script_file="scripts/script.yaml",
            ),
            pipeline=PipelineConfig(strict_director=True),
            llm=LLMConfig(mode="ai_assistant"),
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
                "director_contract": FakeDirectorContractStage,
                "film_timeline": FakeLaterStage,
            },
        )

        results = Pipeline(config, auto_approve=True, llm_client=object()).run(
            stages=["film_timeline"]
        )

        assert results["director_contract"].success is False
        assert "Strict director mode rejected" in results["director_contract"].message
        assert "not_configured" in results["director_contract"].message
        assert "film_timeline" not in results

    def test_strict_director_mode_allows_used_director_stage(self, tmp_path, monkeypatch):
        class FakeDirectorContractStage:
            name = "director_contract"
            depends_on = []

            def can_run(self, context):
                return True, ""

            def run(self, context):
                output = context.config.pipeline_dir / "director_contract.yaml"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    yaml.safe_dump(
                        {
                            "schema_version": "director_contract.v1",
                            "compile_process": {
                                "mode": "llm_prompt_compiler",
                                "llm_status": "used",
                            },
                            "shots": [],
                        },
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
                return StageResult("director_contract", True, outputs=[output])

        config = NarrascapeConfig(
            project=ProjectConfig(
                name="strict-director-used-test",
                title="Strict Director Used Test",
                script_file="scripts/script.yaml",
            ),
            pipeline=PipelineConfig(strict_director=True),
            llm=LLMConfig(mode="ai_assistant"),
            project_dir=tmp_path,
        )
        (tmp_path / "scripts").mkdir(parents=True)
        (tmp_path / "scripts" / "script.yaml").write_text(
            "segments:\n- id: 1\n  text: Test segment.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "narrascape.pipeline.STAGE_MAP",
            {"director_contract": FakeDirectorContractStage},
        )

        results = Pipeline(config, auto_approve=True, llm_client=object()).run(
            stages=["director_contract"]
        )

        assert results["director_contract"].success is True

    def test_pipeline_auto_rework_executes_and_reruns_supervisor_next_stages(
        self, tmp_path, monkeypatch
    ):
        calls = []

        class FakeFilmSupervisorStage:
            name = "film_supervisor"
            depends_on = []

            def can_run(self, context):
                return True, ""

            def run(self, context):
                calls.append("film_supervisor")
                output = context.config.pipeline_dir / "film_supervisor.yaml"
                output.parent.mkdir(parents=True, exist_ok=True)
                status = "needs_rework" if calls.count("film_supervisor") == 1 else "approved"
                output.write_text(
                    yaml.safe_dump(
                        {
                            "schema_version": "film_supervisor.v1",
                            "status": status,
                            "decision": {},
                            "next_stages": (
                                [
                                    "rework_execute",
                                    "generate_video",
                                    "take_select",
                                    "film_timeline",
                                    "remotion_preview",
                                    "film_supervisor",
                                ]
                                if status == "needs_rework"
                                else []
                            ),
                        },
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
                return StageResult("film_supervisor", True, message=status)

        class FakeReworkExecuteStage:
            name = "rework_execute"
            depends_on = []

            def can_run(self, context):
                return True, ""

            def run(self, context):
                calls.append("rework_execute")
                return StageResult("rework_execute", True, message="executed")

        class FakeGenerateVideoStage:
            name = "generate_video"
            depends_on = []

            def can_run(self, context):
                return True, ""

            def run(self, context):
                calls.append("generate_video")
                return StageResult("generate_video", True, message="regenerated")

        class FakeTakeSelectStage:
            name = "take_select"
            depends_on = ["generate_video"]

            def can_run(self, context):
                return True, ""

            def run(self, context):
                calls.append("take_select")
                return StageResult("take_select", True, message="selected")

        class FakeFilmTimelineStage:
            name = "film_timeline"
            depends_on = ["take_select"]

            def can_run(self, context):
                return True, ""

            def run(self, context):
                calls.append("film_timeline")
                return StageResult("film_timeline", True, message="rebuilt")

        class FakeRemotionPreviewStage:
            name = "remotion_preview"
            depends_on = ["film_timeline"]

            def can_run(self, context):
                return True, ""

            def run(self, context):
                calls.append("remotion_preview")
                return StageResult("remotion_preview", True, message="preview rebuilt")

        config = NarrascapeConfig(
            project=ProjectConfig(
                name="auto-loop-test",
                title="Auto Loop Test",
                script_file="scripts/script.yaml",
            ),
            pipeline=PipelineConfig(max_rework_cycles=1),
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
                "rework_execute": FakeReworkExecuteStage,
                "generate_video": FakeGenerateVideoStage,
                "take_select": FakeTakeSelectStage,
                "film_timeline": FakeFilmTimelineStage,
                "remotion_preview": FakeRemotionPreviewStage,
                "film_supervisor": FakeFilmSupervisorStage,
            },
        )

        pipeline = Pipeline(config, auto_approve=True, image_api_key="ark")
        monkeypatch.setattr(pipeline, "_default_stages", lambda: ["film_supervisor"])

        results = pipeline.run(stages=None)

        assert calls == [
            "film_supervisor",
            "rework_execute",
            "generate_video",
            "take_select",
            "film_timeline",
            "remotion_preview",
            "film_supervisor",
        ]
        assert results["cycle_1.rework_execute"].success is True
        assert results["cycle_1.generate_video"].success is True
        assert results["cycle_1.remotion_preview"].success is True
        assert results["cycle_1.film_supervisor"].success is True
        assert results["film_supervisor"].message == "needs_rework"

    def test_pipeline_failure_marks_remaining_stages_pending_and_clears_outputs(
        self, tmp_path, monkeypatch
    ):
        class FakeFailStage:
            name = "fail_stage"
            depends_on = []

            def can_run(self, context):
                return True, ""

            def run(self, context):
                return StageResult("fail_stage", False, message="failed")

        class FakeLaterStage:
            name = "later_stage"
            depends_on = ["fail_stage"]

            def can_run(self, context):
                return True, ""

            def run(self, context):
                return StageResult("later_stage", True, message="should not run")

        config = NarrascapeConfig(
            project=ProjectConfig(
                name="failure-state-test",
                title="Failure State Test",
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
            {"fail_stage": FakeFailStage, "later_stage": FakeLaterStage},
        )

        pipeline = Pipeline(config, auto_approve=True)
        pipeline.state.set_stage_status("later_stage", "completed")
        pipeline.state.set_stage_outputs("later_stage", [str(config.pipeline_dir / "old.txt")])

        results = pipeline.run(stages=["later_stage"])

        assert results["fail_stage"].success is False
        assert "later_stage" not in results
        assert pipeline.state.get_stage_status("later_stage") == "pending"
        assert pipeline.state.get_stage_outputs("later_stage") == []

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

    def test_design_stage_can_preserve_curated_prompt_files(self, tmp_path):
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="curated-design-test",
                title="Curated Design Test",
                script_file="scripts/script.yaml",
            ),
            pipeline=PipelineConfig(design_overwrite=False),
            project_dir=tmp_path,
        )
        (tmp_path / "scripts").mkdir(parents=True)
        (tmp_path / "scripts" / "script.yaml").write_text(
            "segments:\n- id: 1\n  shot_type: close_up\n  text: Curated text.\n",
            encoding="utf-8",
        )
        prompts_text = (
            "prompts:\n"
            "- id: img_01\n"
            "  shot_type: close_up\n"
            "  movement: still\n"
            "  size: 1920x1080\n"
            "  description: Curated execution prompt.\n"
        )
        map_text = "segments:\n- id: 1\n  images: [img_01]\n"
        (tmp_path / "image_prompts.yaml").write_text(prompts_text, encoding="utf-8")
        (tmp_path / "image_map.yaml").write_text(map_text, encoding="utf-8")

        result = DesignStage().run(
            StageContext(
                config=config,
                script=Script.model_construct(segments=[]),
                cache=BuildCache(config.pipeline_dir / ".cache"),
            )
        )

        assert result.success is True
        assert result.metadata["wrote_image_prompts"] is False
        assert result.metadata["wrote_image_map"] is False
        assert (tmp_path / "image_prompts.yaml").read_text(encoding="utf-8") == prompts_text
        assert (tmp_path / "image_map.yaml").read_text(encoding="utf-8") == map_text
        assert (config.pipeline_dir / "design_report.yaml").exists()

    def test_completed_stage_reruns_when_recorded_output_is_missing(self, tmp_path, monkeypatch):
        calls = []

        class FakeStage:
            name = "fake"
            depends_on = []

            def can_run(self, context):
                return True, ""

            def run(self, context):
                calls.append("fake")
                output = context.config.pipeline_dir / "fake.txt"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("ok", encoding="utf-8")
                return StageResult("fake", True, outputs=[output], message="ok")

        config = NarrascapeConfig(
            project=ProjectConfig(
                name="missing-output-test",
                title="Missing Output Test",
                script_file="scripts/script.yaml",
            ),
            project_dir=tmp_path,
        )
        (tmp_path / "scripts").mkdir(parents=True)
        (tmp_path / "scripts" / "script.yaml").write_text(
            "segments:\n- id: 1\n  text: Test segment.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("narrascape.pipeline.STAGE_MAP", {"fake": FakeStage})

        pipeline = Pipeline(config, auto_approve=True)
        result = pipeline.run(stages=["fake"])
        assert result["fake"].success is True
        assert calls == ["fake"]

        (config.pipeline_dir / "fake.txt").unlink()
        result = Pipeline(config, auto_approve=True).run(stages=["fake"])

        assert result["fake"].success is True
        assert calls == ["fake", "fake"]

    def test_pipeline_records_nested_output_paths(self, tmp_path):
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="nested-output-test",
                title="Nested Output Test",
                script_file="scripts/script.yaml",
            ),
            project_dir=tmp_path,
        )
        pipeline = Pipeline(config, auto_approve=True)
        first = tmp_path / "pipeline" / "nested-output-test" / "a.txt"
        second = tmp_path / "pipeline" / "nested-output-test" / "b.txt"

        paths = pipeline._recordable_outputs(
            StageResult(
                "fake",
                True,
                outputs={
                    "primary": first,
                    "alternates": [second, None, ""],
                    "metadata": {"ignored": 123},
                },
            )
        )

        assert paths == [str(first), str(second)]

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

    def test_pipeline_clean_removes_rework_execute_queues(self, tmp_path):
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="clean-rework-test",
                title="Clean Rework Test",
                script_file="scripts/script.yaml",
            ),
            project_dir=tmp_path,
        )
        config.pipeline_dir.mkdir(parents=True)
        for filename in (
            "rework_execution.yaml",
            "director_contract_rewrite_queue.yaml",
            "video_regen_queue.yaml",
            "recut_queue.yaml",
            "source_media_replacement_queue.yaml",
        ):
            (config.pipeline_dir / filename).write_text("artifact", encoding="utf-8")

        Pipeline(config).clean(["rework_execute"])

        for filename in (
            "rework_execution.yaml",
            "director_contract_rewrite_queue.yaml",
            "video_regen_queue.yaml",
            "recut_queue.yaml",
            "source_media_replacement_queue.yaml",
        ):
            assert not (config.pipeline_dir / filename).exists()
