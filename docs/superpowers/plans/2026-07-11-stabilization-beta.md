# Narrascape 0.2 Stabilization Beta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `0.2.0-beta.1` with measurable production benchmarks, durable SQLite jobs and an independent worker, provider fault recovery tests, perceptual media QA, and replayable artifact migrations.

**Architecture:** Project-local SQLite databases become the durable coordination boundary for jobs and benchmark observations. HTTP/UI processes enqueue only; `narrascape.worker` owns command execution. Media perception and artifact migration remain deterministic library services consumed by QA and replay tests.

**Tech Stack:** Python 3.10+, stdlib SQLite/subprocess/wave/array, FFmpeg/ffprobe, Pillow, Pydantic, Typer, pytest.

---

### Task 1: Fixed Production Benchmarks

**Files:**
- Create: `benchmarks/catalog.yaml`
- Create: `src/narrascape/benchmarks.py`
- Create: `tests/test_benchmarks.py`
- Modify: `src/narrascape/cli.py`

- [x] Write tests that load exactly `golden-sample`, `documentary`, and `crime-and-punishment`, reject invalid metrics, retain run history in SQLite, aggregate success/cost/time/rework/quality, and require ten distinct real projects for release readiness.
- [x] Run `pytest tests/test_benchmarks.py --no-cov` and confirm missing benchmark APIs fail.
- [x] Implement typed benchmark definitions, SQLite run records, aggregate reports, and CLI `benchmark list|record|report` commands.
- [x] Re-run the benchmark tests and confirm they pass.

### Task 2: SQLite Job Repository And Independent Worker

**Files:**
- Modify: `src/narrascape/jobs.py`
- Create: `src/narrascape/worker.py`
- Modify: `src/narrascape/application.py`
- Modify: `src/narrascape/cli.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_jobs.py`

- [x] Write tests for SQLite persistence, one-active-job transactions, legacy JSON import, worker claiming, subprocess completion, cancellation, recovery, and enqueue-without-thread behavior.
- [x] Run the focused tests and confirm they fail against the JSON/thread implementation.
- [x] Replace JSON records with WAL-mode SQLite, preserve file logs, and migrate legacy records once.
- [x] Implement `JobWorker` and `narrascape-worker`; make application services enqueue and launch a detached worker process instead of a UI-owned waiter thread.
- [x] Re-run job, application, and Workbench API tests.

### Task 3: Provider Fault Injection And Settlement Recovery

**Files:**
- Create: `src/narrascape/providers/fault_injection.py`
- Modify: `src/narrascape/providers/runtime.py`
- Create: `tests/test_provider_fault_injection.py`

- [x] Write deterministic tests for timeout, HTTP 429, duplicate callback, partial output, charged failure, and resume after persisted provider task state.
- [x] Confirm the tests fail because no reusable fault harness or charged-failure settlement exists.
- [x] Implement scripted fault outcomes, idempotent callback transitions, output validation, and reservation settlement states (`reserved`, `charged`, `released`, `committed`).
- [x] Re-run provider, budget, retry, and fault-injection tests.

### Task 4: Perceptual Frame And Audio QA

**Files:**
- Create: `src/narrascape/media_analysis.py`
- Modify: `src/narrascape/stages/qa.py`
- Modify: `src/narrascape/artifacts.py`
- Create: `tests/test_media_analysis.py`
- Modify: `tests/test_film_qa_director_review.py`

- [x] Write unit and FFmpeg-backed tests for deterministic frame sampling, dark/frozen-frame ratios, RMS/peak/clipping/silence measurements, and QA report integration.
- [x] Confirm tests fail because perceptual metrics are absent.
- [x] Implement bounded FFmpeg frame extraction and PCM audio decoding with Pillow/stdlib statistics.
- [x] Add a `perceptual` block to render QA and convert threshold breaches into stable warnings/errors.
- [x] Re-run media and QA tests.

### Task 5: Artifact Schema Migrations And Historical Replay

**Files:**
- Create: `src/narrascape/artifact_migrations.py`
- Modify: `src/narrascape/artifacts.py`
- Create: `tests/fixtures/history/v0/*.yaml`
- Create: `tests/fixtures/history/v0/*.json`
- Create: `tests/test_artifact_migrations.py`

- [x] Write tests proving every canonical artifact has a target version and migration path, unknown future versions fail, migrations are idempotent, and YAML/JSON historical snapshots replay through current models.
- [x] Confirm tests fail against strict current-version validation.
- [x] Implement ordered migration registration, target-version normalization, provenance metadata, and JSON/YAML replay loading.
- [x] Update canonical writes to persist normalized current versions and re-run all artifact/stage tests.

### Task 6: Beta Release Contract

**Files:**
- Modify: `src/narrascape/__init__.py`
- Create: `CHANGELOG.md`
- Create: `docs/release-readiness.md`
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`

- [x] Write release tests that assert version `0.2.0-beta.1`, fixed benchmark coverage, migration replay, distribution install, and the ten-project gate remains unsatisfied by synthetic/offline runs.
- [x] Bump the package version and document beta limitations and real-user acceptance fields.
- [x] Run ruff, Black, mypy, all Python tests, benchmark replay, frontend build/E2E, wheel/sdist installation, and Docker CI configuration checks.
