from __future__ import annotations

import builtins
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from narrascape.utils.safe_io import load_yaml_mapping


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BenchmarkDefinition:
    id: str
    project_path: str
    production_type: str
    quality_dimensions: list[str]


@dataclass(frozen=True)
class ReleaseGate:
    minimum_real_projects: int
    minimum_success_rate: float
    minimum_average_quality: float


@dataclass(frozen=True)
class BenchmarkCatalog:
    schema_version: str
    release_gate: ReleaseGate
    benchmarks: list[BenchmarkDefinition]

    @classmethod
    def load(cls, path: Path) -> BenchmarkCatalog:
        data = load_yaml_mapping(path)
        if data.get("schema_version") != "benchmark_catalog.v1":
            raise ValueError("benchmark catalog must use benchmark_catalog.v1")
        gate = data.get("release_gate")
        items = data.get("benchmarks")
        if not isinstance(gate, dict) or not isinstance(items, list):
            raise ValueError("benchmark catalog requires release_gate and benchmarks")
        definitions = [
            BenchmarkDefinition(
                id=str(item["id"]),
                project_path=str(item["project_path"]),
                production_type=str(item["production_type"]),
                quality_dimensions=[str(value) for value in item["quality_dimensions"]],
            )
            for item in items
            if isinstance(item, dict)
        ]
        if len(definitions) != len(items) or len({item.id for item in definitions}) != len(items):
            raise ValueError("benchmark definitions must be mappings with unique ids")
        return cls(
            schema_version="benchmark_catalog.v1",
            release_gate=ReleaseGate(
                minimum_real_projects=int(gate["minimum_real_projects"]),
                minimum_success_rate=float(gate["minimum_success_rate"]),
                minimum_average_quality=float(gate["minimum_average_quality"]),
            ),
            benchmarks=definitions,
        )

    def ids(self) -> list[str]:
        return [item.id for item in self.benchmarks]


@dataclass(frozen=True)
class BenchmarkRunInput:
    benchmark_id: str
    project_id: str
    operator_id: str
    real_user: bool
    success: bool
    cost_usd: float
    elapsed_seconds: float
    manual_reworks: int
    quality_score: float
    run_mode: str = "synthetic"
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.benchmark_id:
            raise ValueError("benchmark_id is required")
        if not self.project_id:
            raise ValueError("project_id is required")
        if not self.operator_id:
            raise ValueError("operator_id is required")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must be non-negative")
        if self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be non-negative")
        if self.manual_reworks < 0:
            raise ValueError("manual_reworks must be non-negative")
        if not 0 <= self.quality_score <= 100:
            raise ValueError("quality_score must be between 0 and 100")
        if self.run_mode not in {"production", "offline", "synthetic"}:
            raise ValueError("run_mode must be production, offline, or synthetic")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkRunInput:
        return cls(
            benchmark_id=str(data["benchmark_id"]),
            project_id=str(data["project_id"]),
            operator_id=str(data["operator_id"]),
            real_user=bool(data["real_user"]),
            success=bool(data["success"]),
            cost_usd=float(data["cost_usd"]),
            elapsed_seconds=float(data["elapsed_seconds"]),
            manual_reworks=int(data["manual_reworks"]),
            quality_score=float(data["quality_score"]),
            run_mode=str(data.get("run_mode") or "synthetic"),
            notes=str(data.get("notes") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkRun(BenchmarkRunInput):
    id: str = ""
    created_at: str = ""


class BenchmarkRunRepository:
    def __init__(self, database_path: Path, catalog: BenchmarkCatalog):
        self.database_path = Path(database_path)
        self.catalog = catalog
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    id TEXT PRIMARY KEY,
                    benchmark_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    real_user INTEGER NOT NULL CHECK (real_user IN (0, 1)),
                    success INTEGER NOT NULL CHECK (success IN (0, 1)),
                    cost_usd REAL NOT NULL CHECK (cost_usd >= 0),
                    elapsed_seconds REAL NOT NULL CHECK (elapsed_seconds >= 0),
                    manual_reworks INTEGER NOT NULL CHECK (manual_reworks >= 0),
                    quality_score REAL NOT NULL CHECK (quality_score BETWEEN 0 AND 100),
                    run_mode TEXT NOT NULL CHECK (
                        run_mode IN ('production', 'offline', 'synthetic', 'unknown')
                    ),
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS benchmark_runs_created_idx "
                "ON benchmark_runs(created_at DESC)"
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(benchmark_runs)").fetchall()
            }
            if "run_mode" not in columns:
                connection.execute(
                    "ALTER TABLE benchmark_runs ADD COLUMN run_mode TEXT NOT NULL DEFAULT 'unknown'"
                )

    def record(self, values: BenchmarkRunInput) -> BenchmarkRun:
        if values.benchmark_id not in self.catalog.ids():
            raise ValueError(f"unknown benchmark: {values.benchmark_id}")
        record = BenchmarkRun(
            **values.to_dict(),
            id=uuid.uuid4().hex,
            created_at=_now(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO benchmark_runs (
                    id, benchmark_id, project_id, operator_id, real_user, success,
                    cost_usd, elapsed_seconds, manual_reworks, quality_score, notes, created_at
                    , run_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.benchmark_id,
                    record.project_id,
                    record.operator_id,
                    int(record.real_user),
                    int(record.success),
                    record.cost_usd,
                    record.elapsed_seconds,
                    record.manual_reworks,
                    record.quality_score,
                    record.notes,
                    record.created_at,
                    record.run_mode,
                ),
            )
        return record

    def get(self, run_id: str) -> BenchmarkRun:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM benchmark_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown benchmark run: {run_id}")
        return self._from_row(row)

    def list(self, *, limit: int = 1000) -> list[BenchmarkRun]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM benchmark_runs ORDER BY created_at DESC LIMIT ?",
                (max(0, limit),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def report(self) -> dict[str, Any]:
        records = self.list(limit=1_000_000)
        by_benchmark = {
            benchmark_id: self._aggregate(
                [record for record in records if record.benchmark_id == benchmark_id]
            )
            for benchmark_id in self.catalog.ids()
        }
        real_records = [
            record for record in records if record.real_user and record.run_mode == "production"
        ]
        excluded_non_production = sum(
            record.real_user and record.run_mode != "production" for record in records
        )
        real_projects = {record.project_id for record in real_records}
        real_metrics = self._aggregate(real_records)
        covered = [
            benchmark_id
            for benchmark_id in self.catalog.ids()
            if any(record.benchmark_id == benchmark_id for record in real_records)
        ]
        gate = self.catalog.release_gate
        ready = (
            len(real_projects) >= gate.minimum_real_projects
            and covered == self.catalog.ids()
            and real_metrics["success_rate"] >= gate.minimum_success_rate
            and real_metrics["average_quality_score"] >= gate.minimum_average_quality
        )
        return {
            "schema_version": "benchmark_report.v1",
            "overall": self._aggregate(records),
            "by_benchmark": by_benchmark,
            "release_gate": {
                "ready": ready,
                "real_project_count": len(real_projects),
                "required_real_projects": gate.minimum_real_projects,
                "benchmarks_covered": covered,
                "required_benchmarks": self.catalog.ids(),
                "success_rate": real_metrics["success_rate"],
                "minimum_success_rate": gate.minimum_success_rate,
                "average_quality_score": real_metrics["average_quality_score"],
                "minimum_average_quality": gate.minimum_average_quality,
                "excluded_non_production_runs": excluded_non_production,
            },
        }

    @staticmethod
    def _aggregate(records: builtins.list[BenchmarkRun]) -> dict[str, Any]:
        count = len(records)
        successes = sum(1 for record in records if record.success)
        cost = sum(record.cost_usd for record in records)
        elapsed = sum(record.elapsed_seconds for record in records)
        reworks = sum(record.manual_reworks for record in records)
        quality = sum(record.quality_score for record in records)
        return {
            "run_count": count,
            "success_rate": round(successes / count, 4) if count else 0.0,
            "total_cost_usd": round(cost, 4),
            "average_cost_usd": round(cost / count, 4) if count else 0.0,
            "total_elapsed_seconds": round(elapsed, 3),
            "average_elapsed_seconds": round(elapsed / count, 3) if count else 0.0,
            "total_manual_reworks": reworks,
            "average_manual_reworks": round(reworks / count, 3) if count else 0.0,
            "average_quality_score": round(quality / count, 3) if count else 0.0,
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> BenchmarkRun:
        return BenchmarkRun(
            id=str(row["id"]),
            benchmark_id=str(row["benchmark_id"]),
            project_id=str(row["project_id"]),
            operator_id=str(row["operator_id"]),
            real_user=bool(row["real_user"]),
            success=bool(row["success"]),
            cost_usd=float(row["cost_usd"]),
            elapsed_seconds=float(row["elapsed_seconds"]),
            manual_reworks=int(row["manual_reworks"]),
            quality_score=float(row["quality_score"]),
            run_mode=str(row["run_mode"]),
            notes=str(row["notes"]),
            created_at=str(row["created_at"]),
        )
