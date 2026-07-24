from __future__ import annotations

from pathlib import Path

import pytest
from click import unstyle
from typer.testing import CliRunner

from narrascape.benchmarks import BenchmarkCatalog, BenchmarkRunInput, BenchmarkRunRepository
from narrascape.cli import app

CATALOG_PATH = Path("benchmarks/catalog.yaml")


def _run(
    benchmark_id: str,
    project_id: str,
    *,
    real_user: bool = True,
    run_mode: str = "production",
    success: bool = True,
    quality_score: float = 80.0,
) -> BenchmarkRunInput:
    return BenchmarkRunInput(
        benchmark_id=benchmark_id,
        project_id=project_id,
        operator_id=f"operator-{project_id}",
        real_user=real_user,
        run_mode=run_mode,
        success=success,
        cost_usd=1.25,
        elapsed_seconds=120.0,
        manual_reworks=1,
        quality_score=quality_score,
        notes="reviewed",
    )


def test_catalog_defines_three_fixed_existing_production_benchmarks():
    catalog = BenchmarkCatalog.load(CATALOG_PATH)

    assert [item.id for item in catalog.benchmarks] == [
        "golden-sample",
        "documentary",
        "crime-and-punishment",
    ]
    assert all(Path(item.project_path).is_dir() for item in catalog.benchmarks)
    assert catalog.release_gate.minimum_real_projects == 10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cost_usd", -0.01),
        ("elapsed_seconds", -1.0),
        ("manual_reworks", -1),
        ("quality_score", 100.1),
    ],
)
def test_benchmark_metrics_reject_invalid_values(field: str, value: object):
    values = _run("golden-sample", "project-1").to_dict()
    values[field] = value

    with pytest.raises(ValueError, match=field):
        BenchmarkRunInput.from_dict(values)


def test_repository_persists_and_aggregates_required_metrics(tmp_path: Path):
    catalog = BenchmarkCatalog.load(CATALOG_PATH)
    repository = BenchmarkRunRepository(tmp_path / "benchmarks.sqlite3", catalog)

    first = repository.record(_run("golden-sample", "project-1"))
    repository.record(
        BenchmarkRunInput(
            benchmark_id="documentary",
            project_id="project-2",
            operator_id="operator-2",
            real_user=False,
            success=False,
            cost_usd=2.75,
            elapsed_seconds=240.0,
            manual_reworks=3,
            quality_score=60.0,
        )
    )

    reopened = BenchmarkRunRepository(tmp_path / "benchmarks.sqlite3", catalog)
    report = reopened.report()

    assert reopened.get(first.id).project_id == "project-1"
    assert report["overall"] == {
        "run_count": 2,
        "success_rate": 0.5,
        "total_cost_usd": 4.0,
        "average_cost_usd": 2.0,
        "total_elapsed_seconds": 360.0,
        "average_elapsed_seconds": 180.0,
        "total_manual_reworks": 4,
        "average_manual_reworks": 2.0,
        "average_quality_score": 70.0,
    }
    assert report["by_benchmark"]["golden-sample"]["success_rate"] == 1.0
    assert report["release_gate"]["real_project_count"] == 1
    assert report["release_gate"]["ready"] is False


def test_release_gate_requires_ten_distinct_real_projects_and_all_benchmarks(tmp_path: Path):
    catalog = BenchmarkCatalog.load(CATALOG_PATH)
    repository = BenchmarkRunRepository(tmp_path / "benchmarks.sqlite3", catalog)
    benchmark_ids = [item.id for item in catalog.benchmarks]

    for index in range(10):
        repository.record(_run(benchmark_ids[index % 3], f"real-project-{index}"))
    repository.record(_run("golden-sample", "offline-project", real_user=False))
    repository.record(_run("golden-sample", "real-project-0"))

    gate = repository.report()["release_gate"]

    assert gate["real_project_count"] == 10
    assert gate["benchmarks_covered"] == benchmark_ids
    assert gate["ready"] is True


def test_release_gate_excludes_offline_and_synthetic_runs_even_if_marked_real(tmp_path: Path):
    catalog = BenchmarkCatalog.load(CATALOG_PATH)
    repository = BenchmarkRunRepository(tmp_path / "benchmarks.sqlite3", catalog)
    benchmark_ids = catalog.ids()

    for index in range(10):
        mode = "offline" if index % 2 else "synthetic"
        repository.record(_run(benchmark_ids[index % 3], f"non-production-{index}", run_mode=mode))

    gate = repository.report()["release_gate"]

    assert gate["real_project_count"] == 0
    assert gate["excluded_non_production_runs"] == 10
    assert gate["ready"] is False


def test_repository_rejects_unknown_benchmark(tmp_path: Path):
    catalog = BenchmarkCatalog.load(CATALOG_PATH)
    repository = BenchmarkRunRepository(tmp_path / "benchmarks.sqlite3", catalog)

    with pytest.raises(ValueError, match="unknown benchmark"):
        repository.record(_run("not-registered", "project-1"))


def test_benchmark_cli_records_and_reports_run(tmp_path: Path):
    database = tmp_path / "runs.sqlite3"
    runner = CliRunner()

    recorded = runner.invoke(
        app,
        [
            "benchmark",
            "record",
            "--catalog",
            str(CATALOG_PATH),
            "--database",
            str(database),
            "--benchmark",
            "golden-sample",
            "--project-id",
            "cli-project",
            "--operator-id",
            "cli-operator",
            "--real-user",
            "--run-mode",
            "production",
            "--success",
            "--cost-usd",
            "2.5",
            "--elapsed-seconds",
            "90",
            "--manual-reworks",
            "2",
            "--quality-score",
            "85",
        ],
    )
    reported = runner.invoke(
        app,
        [
            "benchmark",
            "report",
            "--catalog",
            str(CATALOG_PATH),
            "--database",
            str(database),
        ],
    )

    assert recorded.exit_code == 0, recorded.output
    assert "cli-project" in unstyle(recorded.output)
    assert reported.exit_code == 0, reported.output
    assert "1/10" in unstyle(reported.output)
