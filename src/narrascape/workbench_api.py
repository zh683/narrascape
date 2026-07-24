from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from narrascape.application import (
    ApprovalService,
    ArtifactService,
    JobService,
    StageValidationError,
    validate_stage_name,
)
from narrascape.config import load_config
from narrascape.dashboard_data import load_timeline_dashboard
from narrascape.dashboard_i18n import zh_stage_label
from narrascape.dashboard_workbench import load_workbench_dashboard
from narrascape.jobs import JobConflictError, JobNotFoundError, JobRecord


class StageRunRequest(BaseModel):
    force: bool = False
    dry_run: bool = False
    approve: bool = False


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject", "skip"]
    reviewer: str = Field(default="workbench", max_length=100)
    notes: str = Field(default="", max_length=4_000)


def create_app(project_dir: Path, *, web_dist: Path | None = None) -> FastAPI:
    project = Path(project_dir).expanduser().resolve()
    config_path = project / "config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"config.yaml not found in {project}")
    config = load_config(config_path)

    app = FastAPI(
        title="Narrascape Workbench API",
        version="1",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.project_dir = project
    app.state.config = config
    app.state.job_service = JobService(sys.executable, project)
    app.state.approval_service = ApprovalService(config)
    app.state.artifact_service = ArtifactService()
    app.state.job_service.recover_interrupted()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "project": config.project.name}

    @app.get("/api/snapshot")
    def snapshot() -> dict[str, Any]:
        workbench = load_workbench_dashboard(project, config.pipeline_dir)
        timeline = load_timeline_dashboard(project, config.pipeline_dir)
        stages = workbench.get("stage_dashboard", {}).get("stages", [])
        localized_stages = [
            {**item, "label_zh": zh_stage_label(str(item.get("name") or ""))}
            for item in stages
            if isinstance(item, dict)
        ]
        active = app.state.job_service.active_job()
        return {
            "project": {
                "name": config.project.name,
                "title": config.project.title,
                "directory": project.as_posix(),
                "pipeline_directory": config.pipeline_dir.as_posix(),
            },
            "stages": localized_stages,
            "workbench": workbench,
            "timeline": timeline,
            "jobs": [_job_dict(item) for item in app.state.job_service.jobs(limit=50)],
            "active_job": _job_dict(active) if active is not None else None,
        }

    @app.post("/api/stages/{stage_name}/run", status_code=status.HTTP_202_ACCEPTED)
    def run_stage(stage_name: str, request: StageRunRequest) -> dict[str, Any]:
        try:
            job = app.state.job_service.submit_stage(
                stage_name,
                force=request.force,
                dry_run=request.dry_run,
                approve=request.approve,
            )
        except StageValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except JobConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _job_dict(job)

    @app.post("/api/stages/{stage_name}/review")
    def review_stage(stage_name: str, request: ReviewRequest) -> dict[str, str]:
        try:
            validate_stage_name(stage_name)
            service: ApprovalService = app.state.approval_service
            transition = getattr(service, request.action)
            transition(stage_name, reviewer=request.reviewer, notes=request.notes)
        except StageValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"stage": stage_name, "status": request.action}

    @app.get("/api/jobs")
    def list_jobs(limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, Any]]:
        return [_job_dict(item) for item in app.state.job_service.jobs(limit=limit)]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return _job_dict(app.state.job_service.get_job(job_id))
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/log")
    def get_job_log(job_id: str, tail: int = Query(default=500, ge=1, le=10_000)) -> dict[str, str]:
        try:
            return {
                "job_id": job_id,
                "log": app.state.job_service.read_job_log(job_id, tail_lines=tail),
            }
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        try:
            return _job_dict(app.state.job_service.cancel_job(job_id))
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/resume", status_code=status.HTTP_202_ACCEPTED)
    def resume_job(job_id: str) -> dict[str, Any]:
        try:
            return _job_dict(app.state.job_service.resume_job(job_id))
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except JobConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/media/{relative_path:path}", response_class=FileResponse)
    def project_media(relative_path: str) -> FileResponse:
        requested = (project / relative_path).resolve()
        try:
            requested.relative_to(project)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Media file not found") from exc
        if not requested.is_file():
            raise HTTPException(status_code=404, detail="Media file not found")
        return FileResponse(requested)

    packaged_distribution = Path(__file__).resolve().parent / "workbench_web"
    source_distribution = Path(__file__).resolve().parents[2] / "web" / "dist"
    distribution = web_dist or (
        packaged_distribution if packaged_distribution.is_dir() else source_distribution
    )
    if distribution.is_dir():
        app.mount("/", StaticFiles(directory=distribution, html=True), name="workbench")
    return app


def _job_dict(job: JobRecord | Any) -> dict[str, Any]:
    if isinstance(job, JobRecord):
        return job.to_dict()
    data = job.to_dict()
    return data if isinstance(data, dict) else {}


def serve(project_dir: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(project_dir), host=host, port=port)
