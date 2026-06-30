from __future__ import annotations

from pathlib import Path

import tomllib
import yaml


def test_status_stage_names_include_film_timeline_default_path():
    from narrascape.cli import _status_stage_names

    names = _status_stage_names()

    assert "film_timeline" in names
    assert "remotion_preview" in names
    assert "film_assemble" in names
    assert "qa" in names
    assert "director_review" in names


def test_cli_exports_installed_entry_point():
    from narrascape.cli import main

    assert callable(main)


def test_dashboard_extra_declares_streamlit_dependency():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    optional = data["project"]["optional-dependencies"]
    assert any(dep.startswith("streamlit") for dep in optional["dashboard"])
    assert any(dep.startswith("streamlit") for dep in optional["dev"])


def test_docker_compose_default_command_exists():
    data = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    assert data["services"]["narrascape"]["command"] == ["--help"]


def test_production_profile_applies_ai_film_quality_defaults(tmp_path):
    from narrascape.cli import _apply_build_profile
    from narrascape.config import (
        ImageProvider,
        LLMConfig,
        NarrascapeConfig,
        PipelineConfig,
        ProjectConfig,
        VideoProvider,
    )

    config = NarrascapeConfig(
        project=ProjectConfig(
            name="profile-test",
            title="Profile Test",
            script_file="scripts/script.yaml",
        ),
        pipeline=PipelineConfig(video_generation="auto", max_rework_cycles=1),
        llm=LLMConfig(mode="none"),
        project_dir=tmp_path,
    )

    profiled = _apply_build_profile(config, production=True)

    assert profiled.images.provider == ImageProvider.SEEDREAM
    assert profiled.video.provider == VideoProvider.SEEDANCE
    assert profiled.video.takes >= 3
    assert profiled.pipeline.video_generation == "required"
    assert profiled.pipeline.strict_director is True
    assert profiled.pipeline.production_quality_gates is True
    assert profiled.pipeline.max_rework_cycles >= 2
    assert profiled.llm.mode == "ai_assistant"
    assert "Oil painting style" in profiled.images.style
    assert config.pipeline.video_generation == "auto"


def test_unknown_build_profile_is_rejected(tmp_path):
    import pytest

    from narrascape.cli import _apply_build_profile
    from narrascape.config import NarrascapeConfig, ProjectConfig

    config = NarrascapeConfig(
        project=ProjectConfig(
            name="profile-test",
            title="Profile Test",
            script_file="scripts/script.yaml",
        ),
        project_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="Unknown build profile"):
        _apply_build_profile(config, profile="random-profile")


def test_clean_cmd_stage_cache_removes_cache_dir(tmp_path):
    from typer.testing import CliRunner

    from narrascape.cli import app

    project_dir = tmp_path / "project"
    cache_dir = project_dir / "pipeline" / "clean-cache-test" / ".cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "index.json").write_text("{}", encoding="utf-8")
    (project_dir / "config.yaml").write_text(
        "project:\n"
        "  name: clean-cache-test\n"
        "  title: Clean Cache Test\n"
        "  script_file: scripts/script.yaml\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["clean", "--project", str(project_dir), "--stage", ".cache"])

    assert result.exit_code == 0
    assert not cache_dir.exists()


def test_status_cmd_prints_rework_loop_summary(tmp_path):
    from typer.testing import CliRunner

    from narrascape.cli import app

    project_dir = tmp_path / "project"
    pipeline_dir = project_dir / "pipeline" / "status-rework-test"
    pipeline_dir.mkdir(parents=True)
    (project_dir / "config.yaml").write_text(
        "project:\n"
        "  name: status-rework-test\n"
        "  title: Status Rework Test\n"
        "  script_file: scripts/script.yaml\n",
        encoding="utf-8",
    )
    (pipeline_dir / "film_supervisor.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "film_supervisor.v1",
                "status": "needs_rework",
                "next_stages": [
                    "rework_execute",
                    "film_timeline",
                    "remotion_preview",
                    "film_supervisor",
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "rework_plan.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "rework_plan.v1",
                "status": "needs_rework",
                "actions": [{"segment_id": 1, "action": "recut"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["status", "--project", str(project_dir)])

    assert result.exit_code == 0
    assert "Rework Loop" in result.output
    assert "needs_rework" in result.output
    assert "remotion_preview" in result.output
