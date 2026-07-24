from __future__ import annotations

from pathlib import Path

import pytest

from narrascape.application import (
    ApprovalService,
    ArtifactService,
    JobService,
    PipelineRunService,
    StageValidationError,
)
from narrascape.config import NarrascapeConfig, ProjectConfig


def _config(tmp_path: Path) -> NarrascapeConfig:
    return NarrascapeConfig(
        project=ProjectConfig(
            name="service-test",
            title="Service Test",
            script_file="scripts/script.yaml",
        ),
        project_dir=tmp_path,
    )


def test_pipeline_run_service_owns_pipeline_execution(tmp_path):
    config = _config(tmp_path)
    calls = []

    class FakePipeline:
        def __init__(self, received_config, **options):
            calls.append((received_config, options))

        def run(self, stages):
            calls.append(("run", stages))
            return {"qa": "ok"}

    service = PipelineRunService(
        config,
        pipeline_factory=FakePipeline,
        pipeline_options={"force": True},
    )

    assert service.run(["qa"]) == {"qa": "ok"}
    assert calls == [(config, {"force": True}), ("run", ["qa"])]


def test_pipeline_run_service_rejects_unknown_stage_before_constructing_pipeline(tmp_path):
    config = _config(tmp_path)

    with pytest.raises(StageValidationError, match="Unknown stage"):
        PipelineRunService(config, pipeline_factory=lambda *args, **kwargs: None).run(
            ["../outside"]
        )


def test_pipeline_run_service_routes_clean_operations(tmp_path):
    config = _config(tmp_path)
    calls = []

    class FakePipeline:
        def __init__(self, received_config, **options):
            pass

        def clean(self, stages):
            calls.append(("stage", stages))

        def clean_cache(self):
            calls.append(("cache", None))

        def clean_all(self):
            calls.append(("all", None))

    service = PipelineRunService(config, pipeline_factory=FakePipeline)
    service.clean_stage("qa")
    service.clean_cache()
    service.clean_all()

    assert calls == [("stage", ["qa"]), ("cache", None), ("all", None)]


def test_approval_service_validates_and_routes_transitions(tmp_path):
    config = _config(tmp_path)
    calls = []

    class FakeApproval:
        def __init__(self, pipeline_dir):
            assert pipeline_dir == config.pipeline_dir

        def approve(self, stage, reviewer, notes):
            calls.append(("approve", stage, reviewer, notes))

        def reject(self, stage, reviewer, notes):
            calls.append(("reject", stage, reviewer, notes))

        def skip(self, stage, reviewer, notes):
            calls.append(("skip", stage, reviewer, notes))

    service = ApprovalService(config, approval_factory=FakeApproval)
    service.approve("qa", reviewer="human", notes="good")
    service.reject("design", reviewer="human", notes="revise")
    service.skip("source_media", reviewer="human", notes="unused")

    assert calls == [
        ("approve", "qa", "human", "good"),
        ("reject", "design", "human", "revise"),
        ("skip", "source_media", "human", "unused"),
    ]
    with pytest.raises(StageValidationError):
        service.approve("../qa")


def test_artifact_service_uses_typed_io(tmp_path):
    path = tmp_path / "film_supervisor.yaml"
    data = {
        "schema_version": "film_supervisor.v1",
        "status": "approved",
        "decision": {},
        "next_stages": [],
    }
    service = ArtifactService()

    service.write("film_supervisor", path, data)

    assert service.load("film_supervisor", path)["status"] == "approved"


def test_job_service_builds_validated_dashboard_commands(tmp_path):
    service = JobService("python", tmp_path)

    assert service.build_stage("qa", force=True, approve=True) == [
        "python",
        "-m",
        "narrascape.cli",
        "build",
        "-p",
        str(tmp_path),
        "--stage",
        "qa",
        "--force",
        "--approve",
    ]
    assert service.clean_stage("qa")[-2:] == ["--stage", "qa"]
    assert service.approve_stage("qa")[-2:] == ["--stage", "qa"]
    with pytest.raises(StageValidationError):
        service.build_stage("not-a-stage")


def test_job_service_submits_persistent_stage_job(monkeypatch, tmp_path):
    service = JobService("python", tmp_path)
    calls = []
    monkeypatch.setattr(
        service._persistent,
        "submit",
        lambda command, **kwargs: calls.append((command, kwargs)) or "job",
    )

    result = service.submit_stage("qa", force=True, approve=True)

    assert result == "job"
    assert calls[0][0][-3:] == ["qa", "--force", "--approve"]
    assert calls[0][1]["stage"] == "qa"
