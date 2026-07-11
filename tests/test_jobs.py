from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from narrascape.jobs import (
    JobConflictError,
    JobRepository,
    JobWorker,
    PersistentJobService,
)


def _queued_service(repository: JobRepository) -> tuple[PersistentJobService, list[str]]:
    launched: list[str] = []
    service = PersistentJobService(
        repository,
        worker_launcher=lambda record: launched.append(record.id),
    )
    return service, launched


def _wait_for_status(
    repository: JobRepository,
    job_id: str,
    statuses: set[str],
    timeout: float = 5.0,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = repository.get(job_id)
        if record.status in statuses:
            return record
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {statuses}")


def test_job_repository_uses_sqlite_and_worker_persists_logs(tmp_path: Path):
    repository = JobRepository(tmp_path)
    service, launched = _queued_service(repository)

    job = service.submit(
        [sys.executable, "-c", "print('native-workbench')"],
        stage="qa",
        cwd=tmp_path,
    )

    assert job.status == "queued"
    assert launched == [job.id]
    assert repository.database_path.name == "jobs.sqlite3"
    assert repository.database_path.is_file()

    finished = JobWorker(JobRepository(tmp_path)).run_once(job.id)

    assert finished is not None
    assert finished.status == "succeeded"
    assert finished.return_code == 0
    assert service.read_log(job.id).strip() == "native-workbench"
    assert JobRepository(tmp_path).get(job.id).status == "succeeded"


def test_submit_does_not_create_ui_owned_waiter_thread(monkeypatch, tmp_path: Path):
    repository = JobRepository(tmp_path)
    service, launched = _queued_service(repository)
    monkeypatch.setattr(
        threading,
        "Thread",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("UI thread created")),
    )

    job = service.submit([sys.executable, "-c", "print('queued')"], stage="qa")

    assert job.status == "queued"
    assert launched == [job.id]


def test_default_launcher_executes_in_detached_worker_process(tmp_path: Path):
    repository = JobRepository(tmp_path)
    service = PersistentJobService(repository)

    job = service.submit(
        [sys.executable, "-c", "print('detached-worker')"],
        stage="qa",
        cwd=tmp_path,
    )
    finished = _wait_for_status(repository, job.id, {"succeeded", "failed"}, timeout=10)

    assert finished.status == "succeeded"
    assert service.read_log(job.id).strip() == "detached-worker"


def test_sqlite_transaction_prevents_concurrent_mutating_jobs(tmp_path: Path):
    first_repository = JobRepository(tmp_path)
    second_repository = JobRepository(tmp_path)
    first = first_repository.create(command=["first"], stage="generate_video", cwd=tmp_path)

    with pytest.raises(JobConflictError, match="active job"):
        second_repository.create(command=["second"], stage="qa", cwd=tmp_path)

    first_repository.finish(first.id, status="cancelled", return_code=None)
    assert second_repository.create(command=["after"], stage="qa", cwd=tmp_path)


def test_failed_job_can_resume_with_link_to_source(tmp_path: Path):
    repository = JobRepository(tmp_path)
    service, _ = _queued_service(repository)
    failed = service.submit(
        [sys.executable, "-c", "raise SystemExit(7)"],
        stage="design",
        cwd=tmp_path,
    )
    failed = JobWorker(repository).run_once(failed.id)
    assert failed is not None

    resumed = service.resume(
        failed.id,
        command=[sys.executable, "-c", "print('resumed')"],
    )
    finished = JobWorker(repository).run_once(resumed.id)

    assert failed.status == "failed"
    assert finished is not None
    assert finished.status == "succeeded"
    assert finished.resumed_from == failed.id


def test_repository_recovers_stale_running_job_but_keeps_queued_work(tmp_path: Path):
    repository = JobRepository(tmp_path)
    running = repository.create(command=["python"], stage="qa", cwd=tmp_path)
    repository.mark_running(running.id, pid=999_999_999)

    recovered = repository.recover_interrupted(is_process_alive=lambda _pid: False)

    assert recovered == [running.id]
    assert repository.get(running.id).status == "interrupted"
    queued = repository.create(command=["python"], stage="qa", cwd=tmp_path)
    assert repository.recover_interrupted(is_process_alive=lambda _pid: False) == []
    assert repository.get(queued.id).status == "queued"


def test_repository_imports_legacy_json_records_once(tmp_path: Path):
    root = tmp_path / ".narrascape" / "jobs"
    records = root / "records"
    records.mkdir(parents=True)
    legacy_id = "a" * 32
    (records / f"{legacy_id}.json").write_text(
        json.dumps(
            {
                "id": legacy_id,
                "command": ["python", "-c", "print('legacy')"],
                "stage": "qa",
                "cwd": str(tmp_path),
                "status": "succeeded",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:01+00:00",
                "log_path": str(root / "logs" / f"{legacy_id}.log"),
                "return_code": 0,
            }
        ),
        encoding="utf-8",
    )

    repository = JobRepository(tmp_path)

    assert repository.get(legacy_id).status == "succeeded"
    assert repository.list() == [repository.get(legacy_id)]
    assert (root / ".legacy-json-imported").is_file()


def test_running_worker_can_be_cancelled_from_another_repository(tmp_path: Path):
    repository = JobRepository(tmp_path)
    service, _ = _queued_service(repository)
    job = service.submit(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stage="generate_video",
        cwd=tmp_path,
    )
    thread = threading.Thread(target=JobWorker(repository).run_once, args=(job.id,), daemon=True)
    thread.start()
    _wait_for_status(repository, job.id, {"running"})

    cancelled = PersistentJobService(JobRepository(tmp_path)).cancel(job.id)
    thread.join(timeout=5)

    assert cancelled.status == "cancelled"
    assert repository.get(job.id).status == "cancelled"
