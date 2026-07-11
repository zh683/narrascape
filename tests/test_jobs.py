from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from narrascape.jobs import JobConflictError, JobRepository, PersistentJobService


def _wait_for_terminal(service: PersistentJobService, job_id: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.get(job_id)
        if job.status in {"succeeded", "failed", "cancelled", "interrupted"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")


def test_job_repository_persists_records_and_logs(tmp_path: Path):
    repository = JobRepository(tmp_path)
    service = PersistentJobService(repository)

    job = service.submit(
        [sys.executable, "-c", "print('native-workbench')"],
        stage="qa",
        cwd=tmp_path,
    )
    finished = _wait_for_terminal(service, job.id)

    assert finished.status == "succeeded"
    assert finished.return_code == 0
    assert finished.command[-1] == "print('native-workbench')"
    assert service.read_log(job.id).strip() == "native-workbench"
    assert JobRepository(tmp_path).get(job.id).status == "succeeded"


def test_job_service_prevents_concurrent_mutating_jobs_per_project(tmp_path: Path):
    service = PersistentJobService(JobRepository(tmp_path))
    first = service.submit(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stage="generate_video",
        cwd=tmp_path,
    )

    with pytest.raises(JobConflictError, match="active job"):
        service.submit(
            [sys.executable, "-c", "print('second')"],
            stage="qa",
            cwd=tmp_path,
        )

    cancelled = service.cancel(first.id)
    assert cancelled.status == "cancelled"
    assert service.submit(
        [sys.executable, "-c", "print('after-cancel')"],
        stage="qa",
        cwd=tmp_path,
    )


def test_failed_job_can_resume_with_link_to_source(tmp_path: Path):
    service = PersistentJobService(JobRepository(tmp_path))
    failed = service.submit(
        [sys.executable, "-c", "raise SystemExit(7)"],
        stage="design",
        cwd=tmp_path,
    )
    failed = _wait_for_terminal(service, failed.id)

    resumed = service.resume(
        failed.id,
        command=[sys.executable, "-c", "print('resumed')"],
    )
    finished = _wait_for_terminal(service, resumed.id)

    assert failed.status == "failed"
    assert finished.status == "succeeded"
    assert finished.resumed_from == failed.id


def test_repository_recovers_stale_running_job_as_interrupted(tmp_path: Path):
    repository = JobRepository(tmp_path)
    job = repository.create(
        command=["python", "-m", "narrascape.cli"],
        stage="qa",
        cwd=tmp_path,
    )
    repository.mark_running(job.id, pid=999_999_999)

    recovered = repository.recover_interrupted(is_process_alive=lambda _pid: False)

    assert recovered == [job.id]
    assert repository.get(job.id).status == "interrupted"
    assert repository.active() is None
