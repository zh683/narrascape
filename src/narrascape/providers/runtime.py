from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from narrascape.utils.retry import retry_with_backoff

T = TypeVar("T")


class BudgetTrackerLike(Protocol):
    reservations: dict[str, float]

    def reserve(self, reservation_id: str, estimated_cost: float) -> tuple[bool, str]: ...

    def commit_reservation(
        self, reservation_id: str, actual_cost: float | None = None
    ) -> tuple[bool, str]: ...

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

    def record_callback(
        self,
        key: str,
        provider: str,
        *,
        event_id: str,
        status: str,
        **metadata: Any,
    ) -> bool:
        current = self.get(key, provider=provider)
        callback_ids = current.get("callback_ids", [])
        ids = [str(value) for value in callback_ids] if isinstance(callback_ids, list) else []
        if event_id in ids:
            return False
        ids.append(event_id)
        current.update(metadata)
        current.update(
            {
                "provider": provider,
                "status": status,
                "callback_ids": ids[-100:],
            }
        )
        self._write(key, current)
        return True

    def recovery_action(self, key: str, *, provider: str) -> str:
        task = self.get(key, provider=provider)
        if not task:
            return "submit"
        status = str(task.get("status") or "")
        if status == "completed":
            return "done"
        if task.get("task_id") or task.get("video_id"):
            return "poll"
        if status in {"submitting", "charged_failed"}:
            return "reconcile"
        return "submit"

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

    def settle_failure(
        self,
        reservation_id: str,
        *,
        charged: bool,
        actual_cost: float | None = None,
    ) -> None:
        if charged:
            committed, message = self.tracker.commit_reservation(reservation_id, actual_cost)
            if not committed:
                raise BudgetReservationError(message)
            return
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
