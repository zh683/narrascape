from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from narrascape.utils.retry import retry_with_backoff

T = TypeVar("T")


class BudgetTrackerLike(Protocol):
    reservations: dict[str, float]

    def reserve(self, reservation_id: str, estimated_cost: float) -> tuple[bool, str]: ...

    def commit_reservation(self, reservation_id: str) -> tuple[bool, str]: ...

    def release_reservation(self, reservation_id: str) -> None: ...


class BudgetReservationError(RuntimeError):
    """Raised when a provider call cannot obtain or settle its budget reservation."""


class PendingReservationError(BudgetReservationError):
    """Raised when a reservation exists without a recoverable provider task."""


class ProviderTaskRepository:
    """Persist provider task transitions through a stage-owned atomic state writer."""

    def __init__(self, mapping: dict[str, Any], persist: Callable[[], None] | None = None):
        self.mapping = mapping
        self.persist = persist

    def get(self, key: str, *, provider: str | None = None) -> dict[str, Any]:
        value = self.mapping.get(key, {})
        if not isinstance(value, dict):
            return {}
        if provider is not None and value.get("provider") != provider:
            return {}
        return dict(value)

    def mark_submitting(self, key: str, provider: str) -> dict[str, Any]:
        return self._write(key, {"provider": provider, "status": "submitting"})

    def mark_submitted(
        self,
        key: str,
        provider: str,
        *,
        task_id: str | None = None,
        video_id: str | None = None,
    ) -> dict[str, Any]:
        return self._write(
            key,
            {
                "provider": provider,
                "task_id": task_id,
                "video_id": video_id,
                "status": "submitted",
            },
        )

    def mark_status(self, key: str, status: str, **metadata: Any) -> dict[str, Any]:
        current = self.get(key)
        current.update(metadata)
        current["status"] = status
        return self._write(key, current)

    def _write(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        self.mapping[key] = value
        if self.persist is not None:
            self.persist()
        return dict(value)


class BudgetReservationCoordinator:
    """Coordinates reserve/commit/release around resumable provider tasks."""

    def __init__(self, tracker: BudgetTrackerLike):
        self.tracker = tracker

    def reserve(self, reservation_id: str, estimated_cost: float, *, task: dict[str, Any]) -> None:
        if reservation_id in self.tracker.reservations:
            if not (task.get("task_id") or task.get("video_id")):
                raise PendingReservationError(
                    f"Budget reservation {reservation_id!r} is pending without a recoverable provider task"
                )
            return
        allowed, message = self.tracker.reserve(reservation_id, estimated_cost)
        if not allowed:
            raise BudgetReservationError(message)

    def commit(self, reservation_id: str) -> None:
        committed, message = self.tracker.commit_reservation(reservation_id)
        if not committed:
            raise BudgetReservationError(message)

    def release(self, reservation_id: str) -> None:
        self.tracker.release_reservation(reservation_id)


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    retry_if: Callable[[Exception], bool] | None = None

    def execute(self, operation: Callable[[], T]) -> T:
        return retry_with_backoff(
            operation,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            retry_if=self.retry_if,
        )
