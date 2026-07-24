from __future__ import annotations

from pathlib import Path

from narrascape.application import JobService


def build_stage_command(
    python_executable: str,
    project_dir: Path,
    stage_name: str,
    *,
    force: bool = False,
    dry_run: bool = False,
    approve: bool = False,
) -> list[str]:
    return JobService(python_executable, project_dir).build_stage(
        stage_name, force=force, dry_run=dry_run, approve=approve
    )


def clean_stage_command(python_executable: str, project_dir: Path, stage_name: str) -> list[str]:
    return JobService(python_executable, project_dir).clean_stage(stage_name)


def approve_stage_command(
    python_executable: str,
    project_dir: Path,
    stage_name: str,
) -> list[str]:
    return JobService(python_executable, project_dir).approve_stage(stage_name)


def build_full_pipeline_command(
    python_executable: str,
    project_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[str]:
    return JobService(python_executable, project_dir).build_full(force=force, dry_run=dry_run)
