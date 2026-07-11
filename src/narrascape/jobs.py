from __future__ import annotations

import builtins
import json
import os
import signal
import sqlite3
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from narrascape.utils.safe_io import atomic_write_text, open_append_text

TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}
ACTIVE_JOB_STATUSES = {"queued", "starting", "running", "cancelling"}
RECOVERABLE_PROCESS_STATUSES = {"starting", "running", "cancelling"}


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
    command: builtins.list[str]
    stage: str
    cwd: str
    status: str
    created_at: str
    updated_at: str
    log_path: str
    env: dict[str, str] = field(default_factory=dict)
    pid: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    resumed_from: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobRecord:
        raw_env = data.get("env", {})
        return cls(
            id=str(data["id"]),
            command=[str(item) for item in data.get("command", [])],
            stage=str(data.get("stage") or "pipeline"),
            cwd=str(data.get("cwd") or "."),
            status=str(data.get("status") or "interrupted"),
            created_at=str(data.get("created_at") or _now()),
            updated_at=str(data.get("updated_at") or _now()),
            log_path=str(data.get("log_path") or ""),
            env=(
                {str(key): str(value) for key, value in raw_env.items()}
                if isinstance(raw_env, dict)
                else {}
            ),
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
    """Project-local SQLite repository for durable process jobs."""

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir).resolve()
        self.root = self.project_dir / ".narrascape" / "jobs"
        self.logs_dir = self.root / "logs"
        self.records_dir = self.root / "records"
        self.database_path = self.root / "jobs.sqlite3"
        self.legacy_marker = self.root / ".legacy-json-imported"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._import_legacy_json()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    command_json TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    log_path TEXT NOT NULL,
                    env_json TEXT NOT NULL DEFAULT '{}',
                    pid INTEGER,
                    started_at TEXT,
                    finished_at TEXT,
                    return_code INTEGER,
                    resumed_from TEXT,
                    error TEXT
                )
                """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_created_idx ON jobs(created_at DESC)"
            )
            connection.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active_idx ON jobs((1))
                WHERE status IN ('queued', 'starting', 'running', 'cancelling')
                """)

    def create(
        self,
        *,
        command: builtins.list[str],
        stage: str,
        cwd: Path,
        env: dict[str, str] | None = None,
        resumed_from: str | None = None,
    ) -> JobRecord:
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
            env=dict(env or {}),
            resumed_from=resumed_from,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                active = self._active_with(connection)
                if active is not None:
                    raise JobConflictError(
                        f"Project already has active job {active.id} for stage {active.stage}"
                    )
                self._insert(connection, record)
        except sqlite3.IntegrityError as exc:
            raise JobConflictError("Project already has an active job") from exc
        return record

    def get(self, job_id: str) -> JobRecord:
        self._validate_id(job_id)
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(f"Unknown job: {job_id}")
        return self._from_row(row)

    def list(self, *, limit: int = 100) -> builtins.list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(0, limit),)
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def active(self) -> JobRecord | None:
        with self._connect() as connection:
            return self._active_with(connection)

    def claim(self, job_id: str | None = None) -> JobRecord | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if job_id is None:
                row = connection.execute(
                    "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
                ).fetchone()
            else:
                self._validate_id(job_id)
                row = connection.execute(
                    "SELECT * FROM jobs WHERE id = ? AND status = 'queued'", (job_id,)
                ).fetchone()
            if row is None:
                return None
            record = self._from_row(row)
            timestamp = _now()
            connection.execute(
                "UPDATE jobs SET status = 'starting', updated_at = ? WHERE id = ?",
                (timestamp, record.id),
            )
        return self.get(record.id)

    def mark_running(self, job_id: str, *, pid: int) -> JobRecord:
        return self._transition(
            job_id,
            expected={"starting", "queued"},
            status="running",
            pid=pid,
            started_at=_now(),
        )

    def mark_cancelling(self, job_id: str) -> JobRecord:
        current = self.get(job_id)
        if current.status == "queued":
            return self.finish(job_id, status="cancelled", return_code=None, error="Cancelled")
        return self._transition(
            job_id,
            expected={"starting", "running"},
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
        )

    def recover_interrupted(
        self, *, is_process_alive: Callable[[int], bool] | None = None
    ) -> builtins.list[str]:
        alive = is_process_alive or _is_process_alive
        recovered: builtins.list[str] = []
        for record in self.list(limit=10_000):
            if record.status not in RECOVERABLE_PROCESS_STATUSES:
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
        **changes: Any,
    ) -> JobRecord:
        self._validate_id(job_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise JobNotFoundError(f"Unknown job: {job_id}")
            current = self._from_row(row)
            if current.status not in expected:
                return current
            values = current.to_dict()
            values.update(changes)
            values["status"] = status
            values["updated_at"] = _now()
            updated = JobRecord.from_dict(values)
            connection.execute(
                """
                UPDATE jobs SET command_json=?, stage=?, cwd=?, status=?, created_at=?,
                    updated_at=?, log_path=?, env_json=?, pid=?, started_at=?, finished_at=?,
                    return_code=?, resumed_from=?, error=? WHERE id=?
                """,
                self._sql_values(updated)[1:] + (updated.id,),
            )
        return updated

    def _insert(self, connection: sqlite3.Connection, record: JobRecord) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO jobs (
                id, command_json, stage, cwd, status, created_at, updated_at, log_path,
                env_json, pid, started_at, finished_at, return_code, resumed_from, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._sql_values(record),
        )

    @staticmethod
    def _sql_values(record: JobRecord) -> tuple[Any, ...]:
        return (
            record.id,
            json.dumps(record.command, ensure_ascii=False),
            record.stage,
            record.cwd,
            record.status,
            record.created_at,
            record.updated_at,
            record.log_path,
            json.dumps(record.env, ensure_ascii=False),
            record.pid,
            record.started_at,
            record.finished_at,
            record.return_code,
            record.resumed_from,
            record.error,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> JobRecord:
        return JobRecord.from_dict(
            {
                "id": row["id"],
                "command": json.loads(row["command_json"]),
                "stage": row["stage"],
                "cwd": row["cwd"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "log_path": row["log_path"],
                "env": json.loads(row["env_json"]),
                "pid": row["pid"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "return_code": row["return_code"],
                "resumed_from": row["resumed_from"],
                "error": row["error"],
            }
        )

    @staticmethod
    def _active_with(connection: sqlite3.Connection) -> JobRecord | None:
        row = connection.execute("""
            SELECT * FROM jobs
            WHERE status IN ('queued', 'starting', 'running', 'cancelling')
            ORDER BY created_at LIMIT 1
            """).fetchone()
        return JobRepository._from_row(row) if row is not None else None

    @staticmethod
    def _validate_id(job_id: str) -> None:
        if not job_id or any(char not in "0123456789abcdef" for char in job_id.lower()):
            raise JobNotFoundError(f"Unknown job: {job_id}")

    def _import_legacy_json(self) -> None:
        if self.legacy_marker.exists():
            return
        if self.records_dir.is_dir():
            with self._connect() as connection:
                for path in sorted(self.records_dir.glob("*.json")):
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            self._insert(connection, JobRecord.from_dict(data))
                    except (OSError, ValueError, KeyError, json.JSONDecodeError):
                        continue
        atomic_write_text(self.legacy_marker, _now())


class JobWorker:
    """Independent executor that claims and completes queued jobs."""

    def __init__(self, repository: JobRepository):
        self.repository = repository

    def run_once(self, job_id: str | None = None) -> JobRecord | None:
        record = self.repository.claim(job_id)
        if record is None:
            return None
        log_handle = open_append_text(Path(record.log_path))
        process_env = os.environ.copy()
        process_env["PYTHONIOENCODING"] = "utf-8"
        process_env.update(record.env)
        try:
            process = subprocess.Popen(
                record.command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=process_env,
                cwd=record.cwd,
            )
        except Exception as exc:
            log_handle.close()
            return self.repository.finish(
                record.id, status="failed", return_code=None, error=str(exc)
            )
        try:
            self.repository.mark_running(record.id, pid=process.pid)
            return_code = process.wait()
            current = self.repository.get(record.id)
            if current.status in TERMINAL_JOB_STATUSES:
                return current
            if current.status == "cancelling":
                return self.repository.finish(
                    record.id,
                    status="cancelled",
                    return_code=return_code,
                    error="Cancelled by operator",
                )
            return self.repository.finish(
                record.id,
                status="succeeded" if return_code == 0 else "failed",
                return_code=return_code,
            )
        finally:
            log_handle.close()


WorkerLauncher = Callable[[JobRecord], None]


class PersistentJobService:
    """Queue jobs and coordinate independent workers."""

    def __init__(
        self,
        repository: JobRepository,
        worker_launcher: WorkerLauncher | None = None,
    ):
        self.repository = repository
        self.worker_launcher = worker_launcher or _launch_detached_worker

    def submit(
        self,
        command: builtins.list[str],
        *,
        stage: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        resumed_from: str | None = None,
    ) -> JobRecord:
        record = self.repository.create(
            command=command,
            stage=stage,
            cwd=Path(cwd or self.repository.project_dir),
            env=env,
            resumed_from=resumed_from,
        )
        try:
            self.worker_launcher(record)
        except Exception as exc:
            return self.repository.finish(
                record.id, status="failed", return_code=None, error=f"Worker launch failed: {exc}"
            )
        return self.repository.get(record.id)

    def get(self, job_id: str) -> JobRecord:
        return self.repository.get(job_id)

    def list(self, *, limit: int = 100) -> builtins.list[JobRecord]:
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
        del timeout
        record = self.repository.mark_cancelling(job_id)
        if record.status in TERMINAL_JOB_STATUSES:
            return record
        if record.pid is not None:
            try:
                os.kill(record.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
        return self.repository.finish(
            job_id,
            status="cancelled",
            return_code=None,
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
            env=env or source.env,
            resumed_from=source.id,
        )

    def recover_interrupted(self) -> builtins.list[str]:
        return self.repository.recover_interrupted()


def _launch_detached_worker(record: JobRecord) -> None:
    command = [
        sys.executable,
        "-m",
        "narrascape.worker",
        "--project",
        record.cwd,
        "--job",
        record.id,
    ]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": record.cwd,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
