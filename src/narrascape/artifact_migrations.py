from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from narrascape.utils.safe_io import load_json_mapping, load_yaml_mapping


class ArtifactMigrationError(ValueError):
    """Raised when an artifact cannot be upgraded to its canonical schema."""


_CANONICAL_ARTIFACTS = (
    "asset_manifest",
    "animatic",
    "assistant_handoff",
    "continuity_bible",
    "creative_review",
    "design_report",
    "director_contract",
    "director_review",
    "editing_review",
    "film_supervisor",
    "film_timeline",
    "pre_production",
    "production_readiness",
    "reference_plates",
    "remotion_preview",
    "render_report",
    "rework_execution",
    "rework_plan",
    "screenplay_structure",
    "script",
    "storyboard_sheet",
    "take_selection",
    "video_prompt_quality",
    "visual_semantic_report",
)

TARGET_SCHEMA_VERSIONS = {name: f"{name}.v1" for name in _CANONICAL_ARTIFACTS}
Migration = Callable[[dict[str, Any]], dict[str, Any]]


def _legacy_to_v1(name: str, data: dict[str, Any]) -> dict[str, Any]:
    migrated = copy.deepcopy(data)
    target = TARGET_SCHEMA_VERSIONS[name]
    migrated["schema_version"] = target
    migrated["schema_migration"] = {
        "source_version": "v0",
        "target_version": target,
        "migrated_by": "narrascape",
    }
    return migrated


def _migration_for(name: str) -> Migration:
    def migrate(data: dict[str, Any]) -> dict[str, Any]:
        return _legacy_to_v1(name, data)

    return migrate


MIGRATIONS: dict[tuple[str, str, str], Migration] = {
    (name, "v0", target): _migration_for(name) for name, target in TARGET_SCHEMA_VERSIONS.items()
}


def migration_path(name: str, source: str, target: str) -> list[tuple[str, str]]:
    """Return the ordered migration path supported for a canonical artifact."""
    _target_version(name)
    if source == target:
        return []
    if (name, source, target) in MIGRATIONS:
        return [(source, target)]
    raise ArtifactMigrationError(f"No artifact migration path for {name}: {source} -> {target}")


def migrate_artifact(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a legacy or current artifact without mutating the caller's mapping."""
    target = _target_version(name)
    if not isinstance(data, dict):
        raise ArtifactMigrationError(f"{name} must be a mapping")
    source_value = data.get("schema_version")
    source = "v0" if source_value in (None, "") else str(source_value)
    if source == target:
        return copy.deepcopy(data)
    if source != "v0":
        raise ArtifactMigrationError(
            f"Artifact {name} uses future or unsupported schema_version {source!r}; "
            f"current version is {target!r}"
        )
    path = migration_path(name, source, target)
    migrated = copy.deepcopy(data)
    for step_source, step_target in path:
        migrated = MIGRATIONS[(name, step_source, step_target)](migrated)
    return migrated


def replay_artifact_history(path: Path) -> dict[str, dict[str, Any]]:
    """Load and migrate every artifact in a historical YAML or JSON project snapshot."""
    from narrascape.artifacts import validate_artifact

    target = Path(path)
    payload = (
        load_json_mapping(target) if target.suffix.lower() == ".json" else load_yaml_mapping(target)
    )
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ArtifactMigrationError(f"Historical snapshot {target} has no artifacts mapping")
    replayed: dict[str, dict[str, Any]] = {}
    for name, artifact in artifacts.items():
        if not isinstance(name, str) or not isinstance(artifact, dict):
            raise ArtifactMigrationError(f"Historical snapshot {target} contains invalid artifact")
        replayed[name] = validate_artifact(name, artifact)
    return replayed


def _target_version(name: str) -> str:
    try:
        return TARGET_SCHEMA_VERSIONS[name]
    except KeyError as exc:
        raise ArtifactMigrationError(f"Unknown artifact schema: {name}") from exc
