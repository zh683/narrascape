# Changelog

All notable changes to Narrascape are documented in this file.

## 0.2.0-beta.1 - 2026-07-11

This stabilization beta adds the operational controls needed for supervised
real-project evaluation. It is not a production-availability declaration.

### Added

- Three fixed production benchmarks with durable success, cost, elapsed time,
  manual rework, and human quality metrics.
- SQLite-backed jobs, one-active-job concurrency protection, cancellation,
  recovery, and an independent `narrascape-worker` process.
- Deterministic provider fault injection for timeout, 429, duplicate callback,
  partial output, charged failure, and persisted recovery.
- Real decoded-frame sampling and PCM audio analysis in render QA.
- Version migration and YAML/JSON historical replay for every canonical
  artifact schema.
- A release gate requiring 10 distinct real-user production projects across
  all fixed benchmarks before production-readiness can be considered.

### Changed

- Canonical stage outputs now use validated atomic artifact writes.
- Offline and synthetic benchmark observations remain reportable but cannot
  satisfy the real-project release gate.
