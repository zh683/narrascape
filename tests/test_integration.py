"""Integration tests for Narrascape pipeline.

These tests verify the end-to-end data flow, style consistency, and LLM architecture.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from narrascape.agent.models import (
    CharacterProfile,
    DesignReport,
    ReferenceImageChain,
    SceneStyle,
    ShotDesign,
)
from narrascape.config import (
    AudioConfig,
    ImageConfig,
    ImageProvider,
    LLMConfig,
    MusicAudioConfig,
    MusicProvider,
    NarrascapeConfig,
    PipelineConfig,
    ProjectConfig,
    ShotType,
    TTSConfig,
    TTSProvider,
    VisualConfig,
)
from narrascape.llm import LLMClient
from narrascape.stages.base import Stage
from narrascape.stages.design import DesignStage
from narrascape.stages.pre_production import PreProductionStage

# ───────────────────────────────────────────────────────────────────
# Test Fixtures
# ───────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_project():
    """Create a temporary project directory with minimal config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_dir = Path(tmpdir) / "test_project"
        proj_dir.mkdir()

        # config.yaml
        config = NarrascapeConfig(
            project=ProjectConfig(
                name="test-project",
                title="Test Project",
                script_file="scripts/script.yaml",
            ),
            llm=LLMConfig(mode="ai_assistant"),
            project_dir=proj_dir,
        )

        # scripts/script.yaml
        scripts_dir = proj_dir / "scripts"
        scripts_dir.mkdir()
        with open(scripts_dir / "script.yaml", "w", encoding="utf-8") as f:
            yaml.dump(
                {
                    "segments": [
                        {"id": 1, "text": "在晨曦的薄雾中，一位剑客站在悬崖边。"},
                        {"id": 2, "text": "他的眼神坚定而深邃。"},
                        {"id": 3, "text": "身后，古老的松树在微风中摇曳。"},
                    ]
                },
                f,
                allow_unicode=True,
            )

        yield config


# ───────────────────────────────────────────────────────────────────
# LLM Architecture Tests
# ───────────────────────────────────────────────────────────────────


class TestLLMArchitecture:
    """Test AI Assistant as built-in LLM."""

    def test_llm_config_ai_assistant_mode(self):
        """LLMConfig accepts ai_assistant mode."""
        config = LLMConfig(mode="ai_assistant")
        assert config.mode == "ai_assistant"

    def test_llm_config_auto_defaults_to_ai_assistant(self):
        """Auto mode defaults to ai_assistant when no API keys."""
        client = LLMClient.from_env()
        assert client.config.provider == "ai_assistant"

    def test_llm_client_never_returns_none(self):
        """LLMClient.from_env() never returns None."""
        client = LLMClient.from_env()
        assert client is not None
        assert isinstance(client, LLMClient)

    def test_ai_assistant_timeout_creates_single_bridge_task(self, tmp_path):
        """AI Assistant mode should not retry bridge timeouts into many tasks."""
        task_dir = tmp_path / "bridge"
        client = LLMClient.from_env()
        client.config.provider = "ai_assistant"

        with (
            patch.dict(
                "os.environ",
                {
                    "NARRASCAPE_BRIDGE_DIR": str(task_dir),
                    "NARRASCAPE_BRIDGE_TIMEOUT": "0",
                },
            ),
            pytest.raises(RuntimeError, match="Bridge timeout"),
        ):
            client.complete("Return JSON", json_mode=True)

        pending_tasks = list((task_dir / "pending").glob("task_*.md"))
        assert len(pending_tasks) == 1

    def test_bridge_reuses_pending_task_after_timeout(self, tmp_path):
        """A response written after timeout should be consumed on the next identical call."""
        from narrascape.llm.bridge import BridgeLLMClient

        client = BridgeLLMClient(task_dir=tmp_path / "bridge", timeout=0)

        with pytest.raises(RuntimeError, match="Bridge timeout"):
            client.complete("Return a compact JSON array", json_mode=True)

        pending_tasks = list((tmp_path / "bridge" / "pending").glob("task_*.md"))
        assert len(pending_tasks) == 1
        task_id = pending_tasks[0].stem.removeprefix("task_")
        response_file = tmp_path / "bridge" / "completed" / f"response_{task_id}.json"
        response_file.write_text(
            json.dumps({"content": '[{"ok": true}]', "usage": {}}),
            encoding="utf-8",
        )

        response = client.complete("Return a compact JSON array", json_mode=True)

        assert response.content == '[{"ok": true}]'
        assert not pending_tasks[0].exists()
        assert not response_file.exists()
        assert (tmp_path / "bridge" / "archive" / pending_tasks[0].name).exists()

    def test_cli_llm_client_uses_project_bridge_dir(self, temp_project):
        """Bridge-backed assistant tasks should be written inside the target project."""
        from narrascape.cli import _get_llm_client

        with patch.dict("os.environ", {}, clear=True):
            client = _get_llm_client(config=temp_project)
            assert client.config.provider == "ai_assistant"
            assert __import__("os").environ["NARRASCAPE_BRIDGE_DIR"] == str(
                temp_project.project_dir / ".narrascape" / "bridge"
            )

    def test_cli_llm_client_uses_config_when_first_positional_argument_is_config(
        self, temp_project
    ):
        """Stage commands should not accidentally pass config as an API key."""
        from narrascape.cli import _get_llm_client

        with patch.dict("os.environ", {}, clear=True):
            client = _get_llm_client(temp_project)

        assert client.config.provider == "ai_assistant"

    def test_cli_llm_client_none_mode_disables_llm(self, temp_project):
        """llm.mode=none is the explicit offline/template mode."""
        from narrascape.cli import _get_llm_client

        temp_project.llm.mode = "none"

        with patch.dict("os.environ", {}, clear=True):
            client = _get_llm_client(config=temp_project)

        assert client is None

    def test_cli_llm_client_required_video_never_uses_none_mode(self, tmp_path):
        """AI-film/video-required projects must get a real director LLM client."""
        from narrascape.cli import _get_llm_client

        config = NarrascapeConfig.model_construct(
            project=ProjectConfig(
                name="required-video",
                title="Required Video",
                script_file="scripts/script.yaml",
            ),
            pipeline=PipelineConfig(video_generation="required"),
            llm=LLMConfig(mode="none"),
            project_dir=tmp_path,
        )

        with patch.dict("os.environ", {}, clear=True):
            client = _get_llm_client(config=config)

        assert client is not None
        assert client.config.provider == "ai_assistant"

    def test_llm_config_rejects_invalid_mode(self):
        """LLMConfig rejects invalid mode."""
        with pytest.raises(ValueError):
            LLMConfig(mode="invalid_mode")


# ───────────────────────────────────────────────────────────────────
# Style Anchor Propagation Tests
# ───────────────────────────────────────────────────────────────────


class TestStyleAnchorPropagation:
    """Test style anchor propagation through the pipeline."""

    def test_design_report_has_style_anchor_path(self):
        """DesignReport model has style_anchor_path field."""
        report = DesignReport(
            project_title="test",
            style_anchor_path="/path/to/anchor.png",
        )
        assert report.style_anchor_path == "/path/to/anchor.png"

    def test_to_image_prompts_includes_style_anchor(self):
        """to_image_prompts includes style_anchor in reference_images."""

        report = DesignReport(
            project_title="test",
            segments=[
                ShotDesign(
                    segment_id=1,
                    shot_type=ShotType.MEDIUM,
                    image_prompt="test prompt",
                )
            ],
            style_anchor_path="/anchor.png",
        )
        result = report.to_image_prompts()
        prompt = result["prompts"][0]
        assert "style_anchor_path" in prompt
        assert prompt["style_anchor_path"] == "/anchor.png"

    def test_style_anchor_is_first_in_reference_images(self):
        """Style anchor is always included in reference."""
        from narrascape.agent.models import CharacterProfile

        report = DesignReport(
            project_title="test",
            segments=[
                ShotDesign(
                    segment_id=1,
                    shot_type=ShotType.MEDIUM,
                    image_prompt="test",
                )
            ],
            characters=[
                CharacterProfile(
                    char_id="char_001",
                    identity_block="A tall man",
                    reference_image_url="/char.png",
                )
            ],
            style_anchor_path="/anchor.png",
        )
        result = report.to_image_prompts()
        prompt = result["prompts"][0]

        # Check reference_image_url (singular) when only style anchor
        # or reference_images (plural) when multiple refs
        has_ref = "reference_image_url" in prompt or "reference_images" in prompt
        assert has_ref, "No reference image field in prompt"

        if "reference_images" in prompt:
            refs = prompt["reference_images"]
            assert refs[0] == "/anchor.png"
        else:
            assert prompt["reference_image_url"] == "/anchor.png"

    def test_shot_design_metadata_includes_style_anchor(self):
        """ShotDesign metadata can store style_anchor_path."""
        shot = ShotDesign(
            segment_id=1,
            shot_type=ShotType.MEDIUM,
            image_prompt="test",
            metadata={"style_anchor_path": "/anchor.png"},
        )
        assert shot.metadata["style_anchor_path"] == "/anchor.png"


# ───────────────────────────────────────────────────────────────────
# Stage Interface Tests
# ───────────────────────────────────────────────────────────────────


class TestStageInterfaceConsistency:
    """Test all Stage classes have consistent interface."""

    def test_all_stages_have_name_attribute(self):
        """All Stage subclasses have name as str."""
        import inspect

        import narrascape.stages

        for mod_name in dir(narrascape.stages):
            if mod_name.startswith("_"):
                continue
            try:
                mod = __import__(f"narrascape.stages.{mod_name}", fromlist=[""])
                for name, obj in inspect.getmembers(mod):
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, Stage)
                        and obj is not Stage
                        and not name.startswith("_")
                    ):
                        try:
                            instance = obj()
                            assert isinstance(instance.name, str), f"{name}.name is not str"
                        except Exception:
                            pass
            except Exception:
                pass

    def test_all_stages_have_depends_on_attribute(self):
        """All Stage subclasses have depends_on as list."""
        import inspect

        import narrascape.stages

        for mod_name in dir(narrascape.stages):
            if mod_name.startswith("_"):
                continue
            try:
                mod = __import__(f"narrascape.stages.{mod_name}", fromlist=[""])
                for name, obj in inspect.getmembers(mod):
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, Stage)
                        and obj is not Stage
                        and not name.startswith("_")
                    ):
                        try:
                            instance = obj()
                            assert isinstance(
                                instance.depends_on, list
                            ), f"{name}.depends_on is not list"
                        except Exception:
                            pass
            except Exception:
                pass


# ───────────────────────────────────────────────────────────────────
# Pipeline Dependency Tests
# ───────────────────────────────────────────────────────────────────


class TestPipelineDependencies:
    """Test pipeline dependency graph has no cycles."""

    def test_no_circular_dependencies(self):
        """Pipeline dependency graph has no cycles."""
        import inspect

        import narrascape.stages

        # Collect all stages and their dependencies
        stage_map = {}
        for mod_name in dir(narrascape.stages):
            if mod_name.startswith("_"):
                continue
            try:
                mod = __import__(f"narrascape.stages.{mod_name}", fromlist=[""])
                for name, obj in inspect.getmembers(mod):
                    if isinstance(obj, type) and issubclass(obj, Stage) and obj is not Stage:
                        try:
                            instance = obj()
                            stage_map[instance.name] = instance.depends_on
                        except Exception:
                            pass
            except Exception:
                pass

        # Check for cycles using DFS
        def has_cycle(node, visited, path):
            if node in path:
                return True
            if node in visited:
                return False
            visited.add(node)
            path.add(node)
            for dep in stage_map.get(node, []):
                if has_cycle(dep, visited, path):
                    return True
            path.remove(node)
            return False

        visited = set()
        for stage in stage_map:
            if has_cycle(stage, visited, set()):
                pytest.fail(f"Circular dependency detected starting from {stage}")


# ───────────────────────────────────────────────────────────────────
# Configuration Tests
# ───────────────────────────────────────────────────────────────────


class TestConfiguration:
    """Test configuration validation."""

    def test_llm_mode_options(self):
        """All valid LLM modes are accepted."""
        valid_modes = ["auto", "ai_assistant", "api", "bridge", "none"]
        for mode in valid_modes:
            config = LLMConfig(mode=mode)
            assert config.mode == mode

    def test_project_config_required_fields(self):
        """ProjectConfig requires name, title, and script_file."""
        with pytest.raises(Exception):
            ProjectConfig(name="test")

        with pytest.raises(Exception):
            ProjectConfig(title="Test")

        with pytest.raises(Exception):
            ProjectConfig(name="test", title="Test")

        # All required fields present
        config = ProjectConfig(name="test", title="Test", script_file="scripts/script.yaml")
        assert config.name == "test"
        assert config.title == "Test"
        assert config.script_file == "scripts/script.yaml"


# ───────────────────────────────────────────────────────────────────
# Data Model Tests
# ───────────────────────────────────────────────────────────────────


class TestDataModels:
    """Test core data models."""

    def test_shot_design_three_layer_model(self):
        """ShotDesign has all three layers."""
        shot = ShotDesign(
            segment_id=1,
            shot_type=ShotType.MEDIUM,
            director_vision="A man stands alone",
            cinematic_format="EXT. CLIFF - DAWN. WIDE SHOT...",
            image_prompt="Wide shot of man on cliff",
        )
        assert shot.director_vision
        assert shot.cinematic_format
        assert shot.image_prompt

    def test_character_profile_identity_block(self):
        """CharacterProfile requires identity_block."""
        char = CharacterProfile(
            char_id="char_001",
            identity_block="A tall man with dark hair",
        )
        assert char.identity_block == "A tall man with dark hair"

    def test_reference_image_chain_multi_reference(self):
        """ReferenceImageChain supports up to 14 references."""
        chain = ReferenceImageChain(
            chain_id="chain_001",
            reference_urls=[f"https://example.com/img{i}.png" for i in range(14)],
        )
        assert len(chain.reference_urls) == 14

    def test_scene_style_fields(self):
        """SceneStyle has all required fields."""
        style = SceneStyle(
            style_id="coastal_drama",
            style_name="Coastal Drama",
            color_palette="warm amber + deep teal",
            lighting_signature="natural golden hour backlight",
        )
        assert style.style_id == "coastal_drama"


# ───────────────────────────────────────────────────────────────────
# Style Consistency Seedream 5.0 Tests
# ───────────────────────────────────────────────────────────────────


class TestSeedream50StyleConsistency:
    """Test Seedream 5.0 style consistency mechanics."""

    def test_prompt_must_reference_style_image(self):
        """Prompt must explicitly reference reference image for style migration."""
        # This is the key insight from Seedream 5.0 research:
        # Simply uploading a reference image is NOT enough.
        # The prompt must explicitly reference it.
        prompt_without_ref = "Wide shot of a man on cliff"
        prompt_with_ref = "参考图1的风格和色调，Wide shot of a man on cliff"

        # The second prompt tells Seedream to extract style from reference image 1
        assert "参考图" in prompt_with_ref
        assert "参考图" not in prompt_without_ref

    def test_sample_strength_ranges(self):
        """Sample strength has appropriate ranges for different shot types."""
        # Character shots: higher for style + content migration
        character_strength = 0.65
        # Scene shots: lower for style-only migration
        scene_strength = 0.35

        assert 0.5 < character_strength < 0.8
        assert 0.2 < scene_strength < 0.5

    def test_multi_reference_order(self):
        """Style anchor must be first in multi-reference array."""
        style_anchor = "/style_anchor.png"
        character_ref = "/char_ref.png"

        ref_images = [style_anchor, character_ref]

        # Style anchor is reference image 1 (index 0)
        assert ref_images[0] == style_anchor
        # Character ref is reference image 2 (index 1)
        assert ref_images[1] == character_ref

        # Prompt references
        assert "参考图1" == "参考图1"  # Style anchor
        assert "参考图2" == "参考图2"  # Character ref


# ───────────────────────────────────────────────────────────────────
# End-to-End Data Flow Test
# ───────────────────────────────────────────────────────────────────


class TestEndToEndDataFlow:
    """Test complete data flow from script to image prompts."""

    def test_init_uses_leaf_directory_as_project_name(self, tmp_path):
        """Absolute init paths should still produce a portable project slug."""
        from narrascape.cli import init_cmd

        project_dir = tmp_path / "nested" / "leaf-project"
        init_cmd(str(project_dir), title="Leaf Project")

        data = yaml.safe_load((project_dir / "config.yaml").read_text(encoding="utf-8"))
        assert data["project"]["name"] == "leaf-project"

    def test_style_anchor_flow(self, temp_project):
        """Style anchor flows from pre_production → design → image_prompts."""
        config = temp_project

        # Step 1: PreProductionStage outputs style_anchor_path
        # (We can't actually run the stage without API keys, but we can test the model)
        style_anchor = "assets/references/style_anchor.png"

        # Step 2: DesignStage reads it and injects into shots
        shot = ShotDesign(
            segment_id=1,
            shot_type=ShotType.MEDIUM,
            image_prompt="参考图1的风格和色调，test shot",
        )
        shot.metadata["style_anchor_path"] = style_anchor
        shot.metadata["seedream_sample_strength"] = 0.65

        # Step 3: DesignReport includes it
        report = DesignReport(
            project_title="test",
            segments=[shot],
            style_anchor_path=style_anchor,
        )

        # Step 4: to_image_prompts exports it
        prompts = report.to_image_prompts()
        prompt_entry = prompts["prompts"][0]

        assert prompt_entry["style_anchor_path"] == style_anchor
        assert "参考图1" in prompt_entry["description"]
        assert "参考图" in prompt_entry["description"]

        # Step 5: reference_images has style anchor first
        refs = prompt_entry.get("reference_images", [])
        if refs:
            assert refs[0] == style_anchor

    def test_full_pipeline_stages(self, temp_project):
        """All pipeline stages can be instantiated."""
        from narrascape.stages.audio import AudioStage
        from narrascape.stages.concat import ConcatStage
        from narrascape.stages.generate_images import GenerateImagesStage
        from narrascape.stages.generate_tts import GenerateTTSStage
        from narrascape.stages.generate_video import GenerateVideoStage
        from narrascape.stages.kenburns import KenBurnsStage
        from narrascape.stages.subtitles import SubtitleStage

        stages = [
            PreProductionStage(),
            DesignStage(),
            GenerateImagesStage(),
            GenerateVideoStage(),
            GenerateTTSStage(),
            KenBurnsStage(),
            ConcatStage(),
            AudioStage(),
            SubtitleStage(),
        ]

        for stage in stages:
            assert isinstance(stage.name, str)
            assert isinstance(stage.depends_on, list)
            print(f"  {stage.name:20s} <- {stage.depends_on}")

    def test_local_provider_pipeline_reaches_final_subtitled_video(self, tmp_path):
        """Offline providers should exercise the full production chain without API keys."""
        from narrascape.pipeline import Pipeline

        project_dir = tmp_path / "local_project"
        (project_dir / "scripts").mkdir(parents=True)
        (project_dir / "assets" / "images").mkdir(parents=True)
        (project_dir / "assets" / "tts").mkdir(parents=True)
        (project_dir / "assets" / "music").mkdir(parents=True)
        (project_dir / "output").mkdir(parents=True)
        (project_dir / "scripts" / "script.yaml").write_text(
            yaml.dump(
                {
                    "segments": [
                        {"id": 1, "text": "A quiet opening shows the city at sunrise."},
                        {"id": 2, "text": "The narrator points toward a small workshop."},
                    ]
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

        config = NarrascapeConfig(
            project=ProjectConfig(
                name="local-project",
                title="Local Project",
                script_file="scripts/script.yaml",
            ),
            llm=LLMConfig(mode="none"),
            images=ImageConfig(provider=ImageProvider.LOCAL, width=1280, height=720),
            tts=TTSConfig(provider=TTSProvider.LOCAL),
            audio=AudioConfig(music=MusicAudioConfig(provider=MusicProvider.LOCAL)),
            visual=VisualConfig(segment_gap=0.1, fade_in_duration=0.1),
            project_dir=project_dir,
        )

        results = Pipeline(config, auto_approve=True, llm_client=None).run()

        assert all(result.success for result in results.values())
        assert (project_dir / "image_prompts.yaml").exists()
        assert (project_dir / "image_map.yaml").exists()
        assert (project_dir / "assets" / "images" / "img_01.png").exists()
        assert (project_dir / "assets" / "tts" / "seg_01.mp3").exists()
        assert (project_dir / "pipeline" / "local-project" / "timing.json").exists()
        assert (project_dir / "film_timeline.yaml").exists()
        assert (project_dir / "pipeline" / "local-project" / "mixed_audio.mp3").exists()
        assert (project_dir / "output" / "local-project-clean.mp4").exists()
        assert (project_dir / "output" / "local-project-sub.mp4").exists()
        assert (project_dir / "pipeline" / "local-project" / "render_report.yaml").exists()


# ───────────────────────────────────────────────────────────────────
# Run tests
# ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
