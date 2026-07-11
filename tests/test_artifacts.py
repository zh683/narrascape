from __future__ import annotations

import pytest

from narrascape.artifacts import (
    ArtifactValidationError,
    available_schemas,
    load_artifact,
    validate_artifact,
    write_artifact,
)
from narrascape.catalog import core_artifact_templates
from narrascape.stages.base import Stage, StageContext, StageResult


def test_all_core_yaml_artifacts_have_typed_schemas():
    expected = set(core_artifact_templates())

    assert expected <= set(available_schemas())


@pytest.mark.parametrize(
    ("artifact_name", "payload", "field_name"),
    [
        (
            "film_supervisor",
            {
                "schema_version": "film_supervisor.v1",
                "status": "approved",
                "decision": "not-a-mapping",
                "next_stages": [],
            },
            "decision",
        ),
        (
            "film_timeline",
            {
                "schema_version": "film_timeline.v1",
                "project": {},
                "tracks": [],
                "coverage": {},
            },
            "tracks",
        ),
        (
            "render_report",
            {"output": "film.mp4", "checks": [], "errors": [], "warnings": []},
            "checks",
        ),
    ],
)
def test_validate_artifact_rejects_invalid_nested_container_types(
    artifact_name, payload, field_name
):
    with pytest.raises(ArtifactValidationError, match=field_name):
        validate_artifact(artifact_name, payload)


def test_load_artifact_validates_canonical_data(tmp_path):
    path = tmp_path / "film_supervisor.yaml"
    path.write_text(
        "schema_version: film_supervisor.v1\n"
        "status: approved\n"
        "decision: []\n"
        "next_stages: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ArtifactValidationError, match="decision"):
        load_artifact("film_supervisor", path)


def test_write_artifact_validates_before_replacing_existing_file(tmp_path):
    path = tmp_path / "film_supervisor.yaml"
    path.write_text("sentinel: keep\n", encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="next_stages"):
        write_artifact(
            "film_supervisor",
            path,
            {
                "schema_version": "film_supervisor.v1",
                "status": "approved",
                "decision": {},
                "next_stages": "qa",
            },
        )

    assert path.read_text(encoding="utf-8") == "sentinel: keep\n"


def test_stage_yaml_loader_validates_canonical_artifacts(tmp_path):
    class ReaderStage(Stage):
        name = "reader"
        depends_on = []

        def run(self, context: StageContext) -> StageResult:
            return StageResult(self.name, True)

    path = tmp_path / "film_supervisor.yaml"
    path.write_text(
        "schema_version: film_supervisor.v1\n"
        "status: approved\n"
        "decision: []\n"
        "next_stages: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ArtifactValidationError, match="decision"):
        ReaderStage()._load_yaml(path)


@pytest.mark.parametrize(
    ("artifact_name", "payload", "missing_field"),
    [
        ("director_contract", {"compile_process": {}, "shots": []}, "schema_version"),
        (
            "reference_plates",
            {
                "schema_version": "reference_plates.v1",
                "status": "ready",
                "plates": [],
            },
            "findings",
        ),
        (
            "rework_plan",
            {
                "schema_version": "rework_plan.v1",
                "status": "approved",
                "actions": [],
            },
            "actions_by_type",
        ),
    ],
)
def test_versioned_artifacts_keep_required_contract_fields(artifact_name, payload, missing_field):
    with pytest.raises(ArtifactValidationError, match=missing_field):
        validate_artifact(artifact_name, payload)
