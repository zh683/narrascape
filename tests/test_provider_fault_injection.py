from __future__ import annotations

from typing import Any

import pytest

from narrascape.providers.fault_injection import (
    ChargedProviderError,
    FaultInjectingProvider,
    FaultStep,
    PartialProviderOutputError,
    validate_provider_output,
)
from narrascape.providers.runtime import (
    BudgetReservationCoordinator,
    ProviderTaskRepository,
    RetryPolicy,
)
from narrascape.utils.retry import is_retryable_provider_error


class FakeBudget:
    def __init__(self):
        self.reservations: dict[str, float] = {}
        self.spent = 0.0
        self.released: list[str] = []

    def reserve(self, reservation_id: str, estimated_cost: float) -> tuple[bool, str]:
        self.reservations[reservation_id] = estimated_cost
        return True, "reserved"

    def commit_reservation(
        self, reservation_id: str, actual_cost: float | None = None
    ) -> tuple[bool, str]:
        reserved = self.reservations.pop(reservation_id)
        self.spent += reserved if actual_cost is None else actual_cost
        return True, "committed"

    def release_reservation(self, reservation_id: str) -> None:
        self.reservations.pop(reservation_id, None)
        self.released.append(reservation_id)


@pytest.mark.parametrize("fault", ["timeout", "rate_limit"])
def test_retry_policy_recovers_timeout_and_429(fault: str):
    provider = FaultInjectingProvider(
        [FaultStep(fault), FaultStep("success", {"task_id": "task-1"})]
    )
    policy = RetryPolicy(max_retries=1, base_delay=0, retry_if=is_retryable_provider_error)

    result = policy.execute(provider.call)

    assert result == {"task_id": "task-1"}
    assert provider.call_count == 2


def test_duplicate_provider_callback_is_idempotent():
    state: dict[str, Any] = {}
    repository = ProviderTaskRepository(state)
    repository.mark_submitted("shot-1", "seedance", task_id="task-1")

    first = repository.record_callback(
        "shot-1",
        "seedance",
        event_id="callback-1",
        status="completed",
        output_url="https://example.invalid/video.mp4",
    )
    duplicate = repository.record_callback(
        "shot-1",
        "seedance",
        event_id="callback-1",
        status="failed",
        error="duplicate must not overwrite completion",
    )

    assert first is True
    assert duplicate is False
    assert repository.get("shot-1")["status"] == "completed"
    assert repository.get("shot-1")["callback_ids"] == ["callback-1"]


def test_partial_provider_output_is_rejected_before_completion():
    provider = FaultInjectingProvider(
        [FaultStep("partial", {"task_id": "task-1", "status": "completed"})]
    )

    with pytest.raises(PartialProviderOutputError, match="output_url"):
        validate_provider_output(provider.call(), required_fields=("task_id", "output_url"))


def test_charged_failure_commits_cost_instead_of_releasing_reservation():
    budget = FakeBudget()
    coordinator = BudgetReservationCoordinator(budget)
    task = {"task_id": "task-1", "status": "submitted"}
    coordinator.reserve("video:1", 1.5, task=task)
    provider = FaultInjectingProvider([FaultStep("charged_failure")])

    with pytest.raises(ChargedProviderError):
        provider.call()
    coordinator.settle_failure("video:1", charged=True, actual_cost=1.25)

    assert budget.spent == 1.25
    assert budget.released == []
    assert budget.reservations == {}


def test_unaccepted_failure_releases_reservation():
    budget = FakeBudget()
    coordinator = BudgetReservationCoordinator(budget)
    coordinator.reserve("video:1", 1.5, task={})

    coordinator.settle_failure("video:1", charged=False)

    assert budget.spent == 0
    assert budget.released == ["video:1"]


def test_persisted_task_recovers_by_polling_without_duplicate_submission():
    state: dict[str, Any] = {}
    first = ProviderTaskRepository(state)
    first.mark_submitted("shot-1", "seedance", task_id="task-1")
    resumed = ProviderTaskRepository(state)
    budget = FakeBudget()
    budget.reservations["video:1"] = 1.5

    action = resumed.recovery_action("shot-1", provider="seedance")
    BudgetReservationCoordinator(budget).reserve("video:1", 1.5, task=resumed.get("shot-1"))

    assert action == "poll"
    assert budget.reservations == {"video:1": 1.5}
