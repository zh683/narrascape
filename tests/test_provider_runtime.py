from __future__ import annotations

from types import SimpleNamespace

import pytest

from narrascape.providers.runtime import (
    BudgetReservationCoordinator,
    PendingReservationError,
    ProviderTaskRepository,
    RetryPolicy,
)


def test_provider_task_repository_persists_each_transition():
    mapping: dict[str, object] = {}
    snapshots = []
    repository = ProviderTaskRepository(mapping, lambda: snapshots.append(dict(mapping)))

    repository.mark_submitting("shot-1", "seedance")
    repository.mark_submitted("shot-1", "seedance", task_id="task-1")
    repository.mark_status("shot-1", "completed", output="clip.mp4")

    assert repository.get("shot-1")["task_id"] == "task-1"
    assert repository.get("shot-1")["output"] == "clip.mp4"
    assert [item["shot-1"]["status"] for item in snapshots] == [
        "submitting",
        "submitted",
        "completed",
    ]


def test_budget_coordinator_blocks_orphaned_reservation():
    tracker = SimpleNamespace(
        reservations={"video:shot-1": 1.0},
        reserve=lambda _id, _cost: (True, "reserved"),
        commit_reservation=lambda _id: (True, "committed"),
        release_reservation=lambda _id: None,
    )
    coordinator = BudgetReservationCoordinator(tracker)

    with pytest.raises(PendingReservationError, match="without a recoverable provider task"):
        coordinator.reserve("video:shot-1", 1.0, task={})

    coordinator.reserve("video:shot-1", 1.0, task={"task_id": "task-1"})
    coordinator.commit("video:shot-1")


def test_retry_policy_retries_only_classified_errors():
    attempts = []
    policy = RetryPolicy(
        max_retries=2, base_delay=0, retry_if=lambda exc: isinstance(exc, TimeoutError)
    )

    def eventually_succeeds():
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError("slow")
        return "ok"

    assert policy.execute(eventually_succeeds) == "ok"
    with pytest.raises(ValueError):
        policy.execute(lambda: (_ for _ in ()).throw(ValueError("permanent")))
