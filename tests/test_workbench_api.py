from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from narrascape.workbench_api import create_app


def _project(tmp_path: Path) -> Path:
    (tmp_path / "config.yaml").write_text(
        "project:\n"
        "  name: api-test\n"
        "  title: API Test\n"
        "  script_file: scripts/script.yaml\n",
        encoding="utf-8",
    )
    return tmp_path


def test_workbench_snapshot_is_project_native_and_chinese(tmp_path: Path):
    app = create_app(_project(tmp_path))
    client = TestClient(app)

    response = client.get("/api/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["project"]["name"] == "api-test"
    assert body["stages"][0]["label_zh"]
    assert "workbench" in body
    assert "timeline" in body
    assert body["active_job"] is None


def test_workbench_submits_stage_through_application_service(tmp_path: Path):
    app = create_app(_project(tmp_path))
    submitted = []
    app.state.job_service.submit_stage = lambda stage, **options: submitted.append(
        (stage, options)
    ) or SimpleNamespace(to_dict=lambda: {"id": "job-1", "status": "running"})
    client = TestClient(app)

    response = client.post(
        "/api/stages/qa/run",
        json={"force": True, "dry_run": False, "approve": True},
    )

    assert response.status_code == 202
    assert response.json()["id"] == "job-1"
    assert submitted == [("qa", {"force": True, "dry_run": False, "approve": True})]


def test_workbench_rejects_unknown_stage_and_path_escape(tmp_path: Path):
    app = create_app(_project(tmp_path))
    client = TestClient(app)

    assert client.post("/api/stages/not-real/run", json={}).status_code == 404
    assert client.get("/api/media/../config.yaml").status_code == 404
