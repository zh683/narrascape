from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from narrascape.artifact_migrations import (
    TARGET_SCHEMA_VERSIONS,
    ArtifactMigrationError,
    migrate_artifact,
    migration_path,
    replay_artifact_history,
)
from narrascape.artifacts import (
    available_schemas,
    load_artifact,
    validate_artifact,
    write_artifact,
)

FIXTURES = Path(__file__).parent / "fixtures" / "history" / "v0"


def test_every_canonical_artifact_has_a_v0_to_current_migration():
    assert set(TARGET_SCHEMA_VERSIONS) == set(available_schemas())
    for name in available_schemas():
        target = TARGET_SCHEMA_VERSIONS[name]
        assert target == f"{name}.v1"
        assert migration_path(name, "v0", target) == [("v0", target)]


def test_migration_is_idempotent_and_records_provenance():
    migrated = migrate_artifact("render_report", {"output": "film.mp4", "checks": {}})

    assert migrated["schema_version"] == "render_report.v1"
    assert migrated["schema_migration"] == {
        "source_version": "v0",
        "target_version": "render_report.v1",
        "migrated_by": "narrascape",
    }
    assert migrate_artifact("render_report", migrated) == migrated


def test_unknown_future_artifact_version_is_rejected():
    with pytest.raises(ArtifactMigrationError, match="future or unsupported"):
        migrate_artifact(
            "render_report",
            {"schema_version": "render_report.v99", "output": "film.mp4", "checks": {}},
        )


def test_yaml_and_json_historical_project_snapshots_replay_all_artifacts():
    replayed = {}
    for path in (FIXTURES / "project-a.yaml", FIXTURES / "project-b.json"):
        replayed.update(replay_artifact_history(path))

    assert set(replayed) == set(available_schemas())
    for name, payload in replayed.items():
        assert payload["schema_version"] == TARGET_SCHEMA_VERSIONS[name]
        assert validate_artifact(name, payload) == payload


def test_json_artifact_load_and_canonical_write_persist_current_version(tmp_path: Path):
    source = tmp_path / "render_report.json"
    source.write_text('{"output":"film.mp4","checks":{}}', encoding="utf-8")

    loaded = load_artifact("render_report", source)
    destination = tmp_path / "render_report.yaml"
    write_artifact("render_report", destination, {"output": "film.mp4", "checks": {}})
    written = yaml.safe_load(destination.read_text(encoding="utf-8"))

    assert loaded["schema_version"] == "render_report.v1"
    assert written["schema_version"] == "render_report.v1"
