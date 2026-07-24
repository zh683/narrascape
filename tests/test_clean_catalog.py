"""Catalog-driven clean: Pipeline.clean derives its deletion set from
catalog.stage_clean_targets instead of a hand-maintained list.

The anti-drift property is the point: a CORE_ARTIFACT_TEMPLATES change must
move the clean set with it, and every declared target must actually be
removed.
"""

from pathlib import Path

import pytest

from narrascape.catalog import (
    CORE_ARTIFACT_TEMPLATES,
    STAGE_CLEAN_ARTIFACTS,
    STAGE_CLEAN_EXTRAS,
    stage_clean_targets,
)
from narrascape.config import NarrascapeConfig, ProjectConfig
from narrascape.pipeline import Pipeline


def _make_config(tmp_path: Path, name: str = "clean-catalog-test") -> NarrascapeConfig:
    return NarrascapeConfig(
        project=ProjectConfig(name=name, title="Clean Catalog Test", script_file="s/script.yaml"),
        project_dir=tmp_path,
    )


def _materialize(config: NarrascapeConfig, template: str) -> list[Path]:
    """Create files/dirs matching one clean-target template; return created paths."""
    rendered = template.format(name=config.project.name)
    created: list[Path] = []
    if template.endswith("/"):
        directory = config.project_dir / rendered
        directory.mkdir(parents=True, exist_ok=True)
        inner = directory / "inner.bin"
        inner.write_bytes(b"x")
        created.extend([inner, directory])
    elif "*" in rendered:
        # e.g. assets/references/*.png -> assets/references/sample.png
        sample = config.project_dir / rendered.replace("*", "sample")
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_bytes(b"x")
        created.append(sample)
    else:
        target = config.project_dir / rendered
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
        created.append(target)
    return created


def test_clean_targets_cover_every_catalog_artifact_mapping():
    for stage_name, artifact_keys in STAGE_CLEAN_ARTIFACTS.items():
        targets = stage_clean_targets(stage_name)
        for key in artifact_keys:
            assert (
                CORE_ARTIFACT_TEMPLATES[key] in targets
            ), f"{stage_name}: template for '{key}' missing from clean targets"


def test_clean_targets_include_declared_extras():
    for stage_name, extras in STAGE_CLEAN_EXTRAS.items():
        targets = stage_clean_targets(stage_name)
        for extra in extras:
            assert extra in targets, f"{stage_name}: extra '{extra}' missing from clean targets"


def test_clean_targets_unknown_stage_is_empty():
    assert stage_clean_targets("design") == []
    assert stage_clean_targets("no_such_stage") == []


def test_clean_removes_every_declared_target(tmp_path):
    """Parity sweep: materialize every declared target, clean, all gone."""
    config = _make_config(tmp_path)
    stages = sorted(set(STAGE_CLEAN_ARTIFACTS) | set(STAGE_CLEAN_EXTRAS))
    for stage_name in stages:
        created: list[Path] = []
        for template in stage_clean_targets(stage_name):
            created.extend(_materialize(config, template))
        assert created, f"{stage_name} declares no targets?"

        Pipeline(config).clean([stage_name])

        for path in created:
            assert not path.exists(), f"clean({stage_name!r}) left {path} behind"


def test_clean_follows_core_artifact_template_changes(tmp_path, monkeypatch):
    """Anti-drift: changing CORE_ARTIFACT_TEMPLATES moves the clean set."""
    monkeypatch.setitem(
        CORE_ARTIFACT_TEMPLATES, "render_report", "pipeline/{name}/custom_render.yaml"
    )
    config = _make_config(tmp_path)
    custom = config.pipeline_dir / "custom_render.yaml"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text("artifact", encoding="utf-8")

    Pipeline(config).clean(["qa"])

    assert not custom.exists()


def test_clean_resets_status_and_clears_approvals(tmp_path):
    config = _make_config(tmp_path)
    pipeline = Pipeline(config)
    pipeline.state.set_stage_status("qa", "completed")
    pipeline.approval.approvals_dir.mkdir(parents=True, exist_ok=True)
    pending = pipeline.approval.approvals_dir / "qa.pending"
    pending.write_text("pending", encoding="utf-8")

    pipeline.clean(["qa"])

    assert pipeline.state.get_stage_status("qa") == "pending"
    assert not pending.exists()


def test_clean_stage_without_targets_only_resets_status(tmp_path):
    config = _make_config(tmp_path)
    pipeline = Pipeline(config)
    pipeline.state.set_stage_status("design", "completed")
    sentinel = config.pipeline_dir / "design_report.yaml"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("keep", encoding="utf-8")

    pipeline.clean(["design"])

    assert pipeline.state.get_stage_status("design") == "pending"
    assert sentinel.exists(), "design has no declared clean targets; artifacts must survive"


@pytest.mark.parametrize("stage_name", ["animatic", "remotion_preview", "film_assemble"])
def test_clean_removes_directory_targets_recursively(tmp_path, stage_name):
    config = _make_config(tmp_path)
    created: list[Path] = []
    for template in stage_clean_targets(stage_name):
        if template.endswith("/"):
            created.extend(_materialize(config, template))
    assert created

    Pipeline(config).clean([stage_name])

    for path in created:
        assert not path.exists()
