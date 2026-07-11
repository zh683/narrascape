# Release Readiness

## 0.2.0-beta.1 Status

Narrascape 0.2.0-beta.1 is a supervised evaluation release. It is **not production-ready**
until real users complete at least 10 distinct production
projects and the benchmark gate reports ready.

The gate requires all of the following:

- At least 10 distinct projects marked as real-user and `production` runs.
- Coverage of `golden-sample`, `documentary`, and `crime-and-punishment`.
- At least 80% successful runs.
- At least 70/100 average final human quality score.
- Recorded cost, elapsed time, manual rework count, and operator identity for
  every run.

Offline and synthetic runs are retained in aggregate reports but never count
toward the real-project total, even if they are accidentally marked as a real
user run. Existing records created before run-mode tracking are `unknown` and
also excluded.

## Acceptance Workflow

After a project is reviewed, record the result explicitly:

```bash
narrascape benchmark record \
  --benchmark golden-sample \
  --project-id customer-project-001 \
  --operator-id reviewer-001 \
  --real-user \
  --run-mode production \
  --success \
  --cost-usd 12.40 \
  --elapsed-seconds 5400 \
  --manual-reworks 2 \
  --quality-score 82
```

Inspect the current decision:

```bash
narrascape benchmark report
```

The default database is `.narrascape/benchmarks.sqlite3`. Preserve this file
as release evidence. Do not change the project count or quality thresholds
based on synthetic CI results.

## Beta Limitations

- Provider behavior and generated media quality still vary by account, region,
  model revision, and source material.
- Human review remains required for creative quality, rights, factual claims,
  and final publication approval.
- SQLite is the supported single-host coordination store for this beta.
  PostgreSQL is deferred until multi-host operation is justified by usage.
- The worker is an independent local process, not yet a distributed queue.
