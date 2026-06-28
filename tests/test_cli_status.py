from __future__ import annotations


def test_status_stage_names_include_film_timeline_default_path():
    from narrascape.cli import _status_stage_names

    names = _status_stage_names()

    assert "film_timeline" in names
    assert "film_assemble" in names
    assert "qa" in names
    assert "director_review" in names


def test_cli_exports_installed_entry_point():
    from narrascape.cli import main

    assert callable(main)


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
