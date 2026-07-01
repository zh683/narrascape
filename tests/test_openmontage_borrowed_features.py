from __future__ import annotations

from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, ProjectConfig, Script
from narrascape.pipeline import _resolve_dependencies, get_stage_map
from narrascape.stages.base import StageContext


def _config(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.dump({"segments": [{"id": 1, "text": "A city at dawn."}]}),
        encoding="utf-8",
    )
    return NarrascapeConfig(
        project=ProjectConfig(
            name="project",
            title="Project",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )


def test_provider_registry_reports_available_local_providers(tmp_path):
    from narrascape.providers.registry import ProviderRegistry, build_default_registry

    config = _config(tmp_path)
    registry = build_default_registry(config)

    assert isinstance(registry, ProviderRegistry)
    envelope = registry.support_envelope()
    assert "local_image" in envelope
    assert envelope["local_image"]["capability"] == "image_generation"
    assert envelope["local_image"]["status"] == "available"


def test_provider_selector_prefers_available_provider_with_task_fit(tmp_path):
    from narrascape.providers.registry import ProviderCapability, ProviderTool
    from narrascape.providers.selector import ProviderSelector

    selector = ProviderSelector()
    selected = selector.select(
        capability="image_generation",
        candidates=[
            ProviderTool(
                name="offline",
                capability=ProviderCapability.IMAGE_GENERATION,
                provider="local",
                status="available",
                quality=0.2,
                cost_efficiency=1.0,
                task_fit={"offline": 1.0},
            ),
            ProviderTool(
                name="premium",
                capability=ProviderCapability.IMAGE_GENERATION,
                provider="seedream",
                status="unavailable",
                quality=1.0,
                cost_efficiency=0.4,
                task_fit={"offline": 0.1},
            ),
        ],
        task_context={"intent": "offline"},
    )

    assert selected.tool.name == "offline"
    assert selected.score > 0
    assert "offline" in selected.reason


def test_qa_stage_is_registered_after_subtitles():
    stage_map = get_stage_map()
    assert "qa" in stage_map

    order = _resolve_dependencies(["qa"], stage_map)

    assert order[-2:] == ["subtitles", "qa"]


def test_source_media_stage_builds_asset_manifest_from_local_library(tmp_path):
    from narrascape.stages.source_media import SourceMediaStage

    config = _config(tmp_path)
    media_dir = config.project_dir / "source_media"
    media_dir.mkdir()
    clip = media_dir / "clip.mp4"
    clip.write_bytes(b"not a real video but enough for manifest discovery")

    context = StageContext(
        config=config,
        script=Script.model_construct(segments=[]),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )

    result = SourceMediaStage().run(context)

    assert result.success
    manifest_path = config.project_dir / "asset_manifest.yaml"
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert data["assets"][0]["path"].endswith("clip.mp4")
    assert data["assets"][0]["provider"] == "local"


def test_artifact_schema_validator_rejects_missing_required_fields():
    from narrascape.artifacts import ArtifactValidationError, validate_artifact

    validate_artifact("asset_manifest", {"assets": []})
    validate_artifact(
        "film_supervisor",
        {
            "schema_version": "film_supervisor.v1",
            "status": "approved",
            "decision": {},
            "next_stages": [],
        },
    )

    try:
        validate_artifact("asset_manifest", {"items": []})
    except ArtifactValidationError as exc:
        assert "assets" in str(exc)
    else:
        raise AssertionError("expected validation error")

    try:
        validate_artifact(
            "film_supervisor",
            {
                "schema_version": "film_supervisor.v0",
                "status": "approved",
                "decision": {},
                "next_stages": [],
            },
        )
    except ArtifactValidationError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("expected schema_version validation error")


def test_agent_stage_director_docs_exist_for_core_stages():
    docs_dir = Path("docs/agent-stages")
    for stage in ("design", "generate_images", "qa"):
        path = docs_dir / f"{stage}.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "Inputs" in text
        assert "Outputs" in text
        assert "Do Not" in text


def test_stage_catalog_doc_paths_exist_and_expose_assistant_handoff():
    from narrascape.catalog import STAGE_DOC_PATHS, core_artifact_templates, stage_intent

    assert "assistant_handoff" in STAGE_DOC_PATHS
    for path in STAGE_DOC_PATHS.values():
        assert Path(path).exists(), path
    assert core_artifact_templates()["assistant_handoff"].endswith("assistant_handoff.yaml")
    assert "video" in stage_intent("generate_video")


def test_composition_runtime_selects_ffmpeg_by_default(tmp_path):
    from narrascape.compose import CompositionPlan, CompositionRuntimeRegistry

    registry = CompositionRuntimeRegistry.default()
    plan = CompositionPlan(
        project="project", runtime="auto", inputs=[], output=tmp_path / "out.mp4"
    )

    runtime = registry.select(plan)

    assert runtime.name == "ffmpeg"
    assert "ffmpeg" in registry.support_envelope()
