from __future__ import annotations

import argparse
import time
from pathlib import Path

from narrascape.jobs import JobRepository, JobWorker


def run_worker(
    project_dir: Path,
    *,
    job_id: str | None = None,
    once: bool = True,
    poll_interval: float = 0.5,
) -> int:
    worker = JobWorker(JobRepository(project_dir))
    if job_id is not None:
        record = worker.run_once(job_id)
        return 0 if record is not None and record.status == "succeeded" else 1
    while True:
        record = worker.run_once()
        if record is not None:
            if once:
                return 0 if record.status == "succeeded" else 1
            continue
        if once:
            return 0
        time.sleep(max(0.05, poll_interval))


def main() -> None:
    parser = argparse.ArgumentParser(description="Narrascape independent job worker")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--job")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=0.5)
    args = parser.parse_args()
    raise SystemExit(
        run_worker(
            args.project,
            job_id=args.job,
            once=not args.loop,
            poll_interval=args.poll_interval,
        )
    )


if __name__ == "__main__":
    main()
