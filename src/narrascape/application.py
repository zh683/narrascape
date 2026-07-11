from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

from narrascape.artifacts import load_artifact, write_artifact
from narrascape.config import NarrascapeConfig
from narrascape.jobs import JobRecord, JobRepository, PersistentJobService
from narrascape.pipeline import Pipeline, get_stage_map
from narrascape.pipeline_approval import PipelineApproval


class StageValidationError(ValueError):
    """Raised when an application action targets an unknown stage."""


def validate_stage_name(stage_name: str) -> str:
    if stage_name not in get_stage_map():
        raise StageValidationError(f"Unknown stage: {stage_name}")
    return stage_name


class PipelineLike(Protocol):
    def run(self, stages: list[str] | None) -> Any: ...

    def clean(self, stages: list[str] | None = None) -> None: ...

    def clean_all(self) -> None: ...

    def clean_cache(self) -> None: ...


class PipelineRunService:
    """Application boundary for pipeline execution and cleanup."""

    def __init__(
        self,
        config: NarrascapeConfig,
        *,
        pipeline_factory: Callable[..., PipelineLike] = Pipeline,
        pipeline_options: dict[str, Any] | None = None,
    ):
        self.config = config
        self.pipeline_factory = pipeline_factory
        self.pipeline_options = dict(pipeline_options or {})

    def run(self, stages: list[str] | None = None) -> Any:
        validated = self._validated_stages(stages)
        return self._pipeline().run(validated)

    def clean_stage(self, stage_name: str) -> None:
        self._pipeline().clean([validate_stage_name(stage_name)])

    def clean_cache(self) -> None:
        self._pipeline().clean_cache()

    def clean_all(self) -> None:
        self._pipeline().clean_all()

    def _pipeline(self) -> PipelineLike:
        return self.pipeline_factory(self.config, **self.pipeline_options)

    def _validated_stages(self, stages: Iterable[str] | None) -> list[str] | None:
        if stages is None:
            return None
        return [validate_stage_name(stage) for stage in stages]


class ApprovalService:
    """Application boundary for stage approval transitions."""

    def __init__(
        self,
        config: NarrascapeConfig,
        *,
        approval_factory: Callable[[Path], Any] = PipelineApproval,
    ):
        self.approval = approval_factory(config.pipeline_dir)

    def approve(self, stage: str, *, reviewer: str = "human", notes: str = "") -> None:
        self.approval.approve(validate_stage_name(stage), reviewer=reviewer, notes=notes)

    def reject(self, stage: str, *, reviewer: str = "human", notes: str = "") -> None:
        self.approval.reject(validate_stage_name(stage), reviewer=reviewer, notes=notes)

    def skip(self, stage: str, *, reviewer: str = "human", notes: str = "") -> None:
        self.approval.skip(validate_stage_name(stage), reviewer=reviewer, notes=notes)


class ArtifactService:
    """Application boundary for typed canonical artifact IO."""

    def load(self, name: str, path: Path) -> dict[str, Any]:
        return load_artifact(name, path)

    def write(self, name: str, path: Path, data: dict[str, Any]) -> None:
        write_artifact(name, path, data)


class JobService:
    """Build and launch validated CLI jobs for desktop or web control surfaces."""

    def __init__(self, python_executable: str, project_dir: Path):
        self.python_executable = python_executable
        self.project_dir = Path(project_dir)
        self._persistent = PersistentJobService(JobRepository(self.project_dir))

    def build_stage(
        self,
        stage_name: str,
        *,
        force: bool = False,
        dry_run: bool = False,
        approve: bool = False,
    ) -> list[str]:
        command = [*self._base("build"), "--stage", validate_stage_name(stage_name)]
        if force:
            command.append("--force")
        if dry_run:
            command.append("--dry-run")
        if approve:
            command.append("--approve")
        return command

    def build_full(self, *, force: bool = False, dry_run: bool = False) -> list[str]:
        command = self._base("build")
        if force:
            command.append("--force")
        if dry_run:
            command.append("--dry-run")
        return command

    def clean_stage(self, stage_name: str) -> list[str]:
        return [*self._base("clean"), "--stage", validate_stage_name(stage_name)]

    def approve_stage(self, stage_name: str) -> list[str]:
        return [*self._base("approve"), "--stage", validate_stage_name(stage_name)]

    def start(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen[str]:
        process_env = os.environ.copy()
        process_env["PYTHONIOENCODING"] = "utf-8"
        if env:
            process_env.update(env)
        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=process_env,
            cwd=str(cwd or self.project_dir),
        )

    def submit_stage(
        self,
        stage_name: str,
        *,
        force: bool = False,
        dry_run: bool = False,
        approve: bool = False,
    ) -> JobRecord:
        stage = validate_stage_name(stage_name)
        return self._persistent.submit(
            self.build_stage(stage, force=force, dry_run=dry_run, approve=approve),
            stage=stage,
            cwd=self.project_dir,
        )

    def submit_full(self, *, force: bool = False, dry_run: bool = False) -> JobRecord:
        return self._persistent.submit(
            self.build_full(force=force, dry_run=dry_run),
            stage="full_pipeline",
            cwd=self.project_dir,
        )

    def submit_command(self, command: list[str], *, stage: str) -> JobRecord:
        """Submit a command produced by this service's validated command builders."""
        expected_prefix = [self.python_executable, "-m", "narrascape.cli"]
        if command[:3] != expected_prefix or len(command) < 6:
            raise ValueError("Job command did not originate from Narrascape application services")
        if command[3] not in {"build", "clean", "approve"}:
            raise ValueError(f"Unsupported dashboard job action: {command[3]}")
        return self._persistent.submit(command, stage=stage, cwd=self.project_dir)

    def jobs(self, *, limit: int = 100) -> list[JobRecord]:
        return self._persistent.list(limit=limit)

    def active_job(self) -> JobRecord | None:
        return self._persistent.repository.active()

    def get_job(self, job_id: str) -> JobRecord:
        return self._persistent.get(job_id)

    def read_job_log(self, job_id: str, *, tail_lines: int = 500) -> str:
        return self._persistent.read_log(job_id, tail_lines=tail_lines)

    def cancel_job(self, job_id: str) -> JobRecord:
        return self._persistent.cancel(job_id)

    def resume_job(self, job_id: str) -> JobRecord:
        return self._persistent.resume(job_id)

    def recover_interrupted(self) -> list[str]:
        return self._persistent.recover_interrupted()

    def _base(self, action: str) -> list[str]:
        return [
            self.python_executable,
            "-m",
            "narrascape.cli",
            action,
            "-p",
            str(self.project_dir),
        ]
