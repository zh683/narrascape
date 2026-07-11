from __future__ import annotations

import builtins
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from narrascape.utils.safe_io import atomic_write_json, file_lock, open_append_text

TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}
ACTIVE_JOB_STATUSES = {"queued", "running", "cancelling"}


class JobError(RuntimeError):
    """Base error for persistent jobs."""


class JobNotFoundError(JobError):
    """Raised when a job record does not exist."""


class JobConflictError(JobError):
    """Raised when a project already has an active mutating job."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class JobRecord:
    id: str
    command: list[str]
    stage: str
    cwd: str
    status: str
    created_at: str
    updated_at: str
    log_path: str
    pid: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    resumed_from: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobRecord:
        return cls(
            id=str(data["id"]),
            command=[str(item) for item in data.get("command", [])],
            stage=str(data.get("stage") or "pipeline"),
            cwd=str(data.get("cwd") or "."),
            status=str(data.get("status") or "interrupted"),
            created_at=str(data.get("created_at") or _now()),
            updated_at=str(data.get("updated_at") or _now()),
            log_path=str(data.get("log_path") or ""),
            pid=int(data["pid"]) if data.get("pid") is not None else None,
            started_at=str(data["started_at"]) if data.get("started_at") else None,
            finished_at=str(data["finished_at"]) if data.get("finished_at") else None,
            return_code=(int(data["return_code"]) if data.get("return_code") is not None else None),
            resumed_from=str(data["resumed_from"]) if data.get("resumed_from") else None,
            error=str(data["error"]) if data.get("error") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobRepository:
    """Atomic, project-local repository for process job state."""

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir).resolve()
        self.root = self.project_dir / ".narrascape" / "jobs"
        self.records_dir = self.root / "records"
        self.logs_dir = self.root / "logs"
        self.active_path = self.root / "active.json"
        self.guard_path = self.root / "repository"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        command: list[str],
        stage: str,
        cwd: Path,
        resumed_from: str | None = None,
    ) -> JobRecord:
        with file_lock(self.guard_path):
            active = self._active_unlocked()
            if active is not None and active.status in ACTIVE_JOB_STATUSES:
                raise JobConflictError(
                    f"Project already has active job {active.id} for stage {active.stage}"
                )
            job_id = uuid.uuid4().hex
            timestamp = _now()
            record = JobRecord(
                id=job_id,
                command=list(command),
                stage=stage,
                cwd=str(Path(cwd).resolve()),
                status="queued",
                created_at=timestamp,
                updated_at=timestamp,
                log_path=str((self.logs_dir / f"{job_id}.log").resolve()),
                resumed_from=resumed_from,
            )
            self._write_unlocked(record)
            atomic_write_json(self.active_path, {"job_id": job_id}, lock=False)
            return record

    def get(self, job_id: str) -> JobRecord:
        path = self._record_path(job_id)
        if not path.exists():
            raise JobNotFoundError(f"Unknown job: {job_id}")
        data: Any = None
        last_error: OSError | json.JSONDecodeError | None = None
        for attempt in range(8):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                break
            except (OSError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < 7:
                    time.sleep(0.01 * (attempt + 1))
        if last_error is not None and data is None:
            raise JobError(f"Cannot read job {job_id}: {last_error}") from last_error
        if not isinstance(data, dict):
            raise JobError(f"Invalid job record: {job_id}")
        return JobRecord.from_dict(data)

    def list(self, *, limit: int = 100) -> list[JobRecord]:
        records = [self.get(path.stem) for path in self.records_dir.glob("*.json")]
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[: max(0, limit)]

    def active(self) -> JobRecord | None:
        with file_lock(self.guard_path):
            return self._active_unlocked()

    def mark_running(self, job_id: str, *, pid: int) -> JobRecord:
        return self._transition(
            job_id,
            expected={"queued"},
            status="running",
            pid=pid,
            started_at=_now(),
        )

    def mark_cancelling(self, job_id: str) -> JobRecord:
        return self._transition(
            job_id,
            expected={"queued", "running"},
            status="cancelling",
        )

    def finish(
        self,
        job_id: str,
        *,
        status: str,
        return_code: int | None,
        error: str | None = None,
    ) -> JobRecord:
        if status not in TERMINAL_JOB_STATUSES:
            raise ValueError(f"Invalid terminal job status: {status}")
        return self._transition(
            job_id,
            expected=ACTIVE_JOB_STATUSES,
            status=status,
            return_code=return_code,
            error=error,
            finished_at=_now(),
            clear_active=True,
        )

    def recover_interrupted(
        self, *, is_process_alive: Callable[[int], bool] | None = None
    ) -> builtins.list[str]:
        alive = is_process_alive or _is_process_alive
        recovered: builtins.list[str] = []
        for record in self.list(limit=10_000):
            if record.status not in ACTIVE_JOB_STATUSES:
                continue
            if record.pid is not None and alive(record.pid):
                continue
            self.finish(
                record.id,
                status="interrupted",
                return_code=record.return_code,
                error="Process was not running when job state was recovered",
            )
            recovered.append(record.id)
        return recovered

    def _transition(
        self,
        job_id: str,
        *,
        expected: set[str],
        status: str,
        clear_active: bool = False,
        **changes: Any,
    ) -> JobRecord:
        with file_lock(self.guard_path):
            current = self.get(job_id)
            if current.status not in expected:
                return current
            data = current.to_dict()
            data.update(changes)
            data["status"] = status
            data["updated_at"] = _now()
            updated = JobRecord.from_dict(data)
            self._write_unlocked(updated)
            if clear_active:
                active = self._active_unlocked()
                if active is not None and active.id == job_id:
                    self.active_path.unlink(missing_ok=True)
            return updated

    def _record_path(self, job_id: str) -> Path:
        if not job_id or any(char not in "0123456789abcdef" for char in job_id.lower()):
            raise JobNotFoundError(f"Unknown job: {job_id}")
        return self.records_dir / f"{job_id}.json"

    def _write_unlocked(self, record: JobRecord) -> None:
        atomic_write_json(self._record_path(record.id), record.to_dict(), lock=False)

    def _active_unlocked(self) -> JobRecord | None:
        if not self.active_path.exists():
            return None
        try:
            data = json.loads(self.active_path.read_text(encoding="utf-8"))
            job_id = str(data["job_id"])
            record = self.get(job_id)
        except (OSError, KeyError, json.JSONDecodeError, JobError):
            self.active_path.unlink(missing_ok=True)
            return None
        if record.status in TERMINAL_JOB_STATUSES:
            self.active_path.unlink(missing_ok=True)
            return None
        return record


class PersistentJobService:
    """Launch and supervise jobs without sharing UI-session state."""

    def __init__(self, repository: JobRepository):
        self.repository = repository
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._processes_lock = threading.Lock()

    def submit(
        self,
        command: list[str],
        *,
        stage: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        resumed_from: str | None = None,
    ) -> JobRecord:
        working_dir = Path(cwd or self.repository.project_dir)
        record = self.repository.create(
            command=command,
            stage=stage,
            cwd=working_dir,
            resumed_from=resumed_from,
        )
        process_env = os.environ.copy()
        process_env["PYTHONIOENCODING"] = "utf-8"
        if env:
            process_env.update(env)
        log_path = Path(record.log_path)
        # The waiter thread owns and closes this handle after the child exits.
        log_handle = open_append_text(log_path)
        try:
            process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=process_env,
                cwd=str(working_dir),
            )
        except Exception as exc:
            log_handle.close()
            return self.repository.finish(
                record.id, status="failed", return_code=None, error=str(exc)
            )
        with self._processes_lock:
            self._processes[record.id] = process
        running = self.repository.mark_running(record.id, pid=process.pid)
        thread = threading.Thread(
            target=self._wait_for_process,
            args=(record.id, process, log_handle),
            name=f"narrascape-job-{record.id[:8]}",
            daemon=True,
        )
        thread.start()
        return running

    def get(self, job_id: str) -> JobRecord:
        return self.repository.get(job_id)

    def list(self, *, limit: int = 100) -> list[JobRecord]:
        return self.repository.list(limit=limit)

    def read_log(self, job_id: str, *, tail_lines: int | None = None) -> str:
        record = self.get(job_id)
        path = Path(record.log_path)
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        if tail_lines is None:
            return text
        return "\n".join(text.splitlines()[-max(0, tail_lines) :])

    def cancel(self, job_id: str, *, timeout: float = 3.0) -> JobRecord:
        record = self.repository.mark_cancelling(job_id)
        if record.status in TERMINAL_JOB_STATUSES:
            return record
        with self._processes_lock:
            process = self._processes.get(job_id)
        return_code: int | None = None
        try:
            if process is not None:
                process.terminate()
                try:
                    return_code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    return_code = process.wait(timeout=timeout)
            elif record.pid is not None:
                os.kill(record.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        return self.repository.finish(
            job_id,
            status="cancelled",
            return_code=return_code,
            error="Cancelled by operator",
        )

    def resume(
        self,
        job_id: str,
        *,
        command: builtins.list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> JobRecord:
        source = self.get(job_id)
        if source.status not in TERMINAL_JOB_STATUSES:
            raise JobConflictError(f"Cannot resume active job {job_id}")
        return self.submit(
            list(command or source.command),
            stage=source.stage,
            cwd=Path(source.cwd),
            env=env,
            resumed_from=source.id,
        )

    def recover_interrupted(self) -> builtins.list[str]:
        return self.repository.recover_interrupted()

    def _wait_for_process(
        self,
        job_id: str,
        process: subprocess.Popen[str],
        log_handle: Any,
    ) -> None:
        try:
            return_code = process.wait()
            if self.repository.get(job_id).status == "cancelling":
                return
            status = "succeeded" if return_code == 0 else "failed"
            self.repository.finish(job_id, status=status, return_code=return_code)
        finally:
            log_handle.close()
            with self._processes_lock:
                self._processes.pop(job_id, None)


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
