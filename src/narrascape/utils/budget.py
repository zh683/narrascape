"""Budget tracking for API calls to prevent runaway spending.

Tracks cumulative spending across pipeline runs and enforces caps.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from narrascape.config import BudgetConfig
from narrascape.utils.safe_io import atomic_write_json, update_json_mapping

logger = logging.getLogger("narrascape.budget")


# Default cost estimates (USD per item) — override via config.budget.*_estimated
DEFAULT_COSTS = {
    "tts_per_segment": 0.001,
    "image_per_image": 0.05,
    "music_per_zone": 0.02,
    "video_per_segment": 0.5,
}


class BudgetTracker:
    """Track API spending and enforce budget caps.

    State is persisted to a JSON file so it survives across runs.
    """

    def __init__(self, budget: BudgetConfig, state_path: Path):
        self.budget = budget
        self.state_path = state_path
        self.spent, self.reservations = self._load_state()

    def _load_state(self) -> tuple[float, dict[str, float]]:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                reservations = data.get("reservations", {})
                return float(data.get("spent", 0.0)), {
                    str(key): float(value)
                    for key, value in reservations.items()
                    if isinstance(value, (int, float))
                }
            except Exception:
                return 0.0, {}
        return 0.0, {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.state_path,
            {"spent": round(self.spent, 4), "reservations": self.reservations},
        )

    def remaining(self) -> float:
        return max(0.0, self.budget.total_usd - self.spent - sum(self.reservations.values()))

    def can_spend(self, estimated_cost: float) -> tuple[bool, str]:
        """Check if an estimated cost is within budget.

        Returns:
            (allowed, message)
        """
        committed_and_reserved = self.spent + sum(self.reservations.values())
        if self.budget.mode == "observe":
            return True, f"Budget observe: {self.spent:.2f}/{self.budget.total_usd:.2f} USD spent"

        if self.budget.mode == "warn":
            if committed_and_reserved + estimated_cost > self.budget.total_usd:
                msg = (
                    f"Budget WARNING: {committed_and_reserved + estimated_cost:.2f} USD would exceed "
                    f"cap of {self.budget.total_usd:.2f} USD. Continuing anyway (warn mode)."
                )
                logger.warning(msg)
                return True, msg
            return (
                True,
                f"Budget OK: {committed_and_reserved + estimated_cost:.2f}/{self.budget.total_usd:.2f} USD",
            )

        if self.budget.mode == "cap":
            if committed_and_reserved + estimated_cost > self.budget.total_usd:
                msg = (
                    f"Budget CAP exceeded: {committed_and_reserved:.2f} + {estimated_cost:.2f} = "
                    f"{committed_and_reserved + estimated_cost:.2f} USD > {self.budget.total_usd:.2f} USD. "
                    f"Set budget.mode='warn' to override, or increase budget.total_usd."
                )
                logger.error(msg)
                return False, msg
            return (
                True,
                f"Budget OK: {committed_and_reserved + estimated_cost:.2f}/{self.budget.total_usd:.2f} USD",
            )

        return True, ""

    def reserve(self, reservation_id: str, estimated_cost: float) -> tuple[bool, str]:
        """Atomically reserve budget before a consequential provider call."""
        if not reservation_id.strip():
            return False, "Budget reservation id is required"
        if estimated_cost < 0:
            return False, f"Ignoring negative cost: {estimated_cost}"
        blocked = ""

        def update(data: dict[str, Any]) -> None:
            nonlocal blocked
            reservations = data.setdefault("reservations", {})
            if not isinstance(reservations, dict):
                reservations = {}
                data["reservations"] = reservations
            if reservation_id in reservations:
                blocked = f"Budget reservation {reservation_id!r} is already pending"
                return
            spent = float(data.get("spent", 0.0))
            reserved = sum(float(value) for value in reservations.values())
            if (
                self.budget.mode == "cap"
                and spent + reserved + estimated_cost > self.budget.total_usd
            ):
                blocked = (
                    f"Budget CAP exceeded: {spent:.2f} spent + {reserved:.2f} reserved + "
                    f"{estimated_cost:.2f} requested > {self.budget.total_usd:.2f} USD."
                )
                return
            reservations[reservation_id] = round(estimated_cost, 4)

        data = update_json_mapping(
            self.state_path,
            update,
            default={"spent": 0.0, "reservations": {}},
        )
        self._sync_state(data)
        if blocked:
            return False, blocked
        return True, (
            f"Budget reserved: {estimated_cost:.2f} USD for {reservation_id}; "
            f"{self.remaining():.2f} USD remaining"
        )

    def commit_reservation(
        self, reservation_id: str, actual_cost: float | None = None
    ) -> tuple[bool, str]:
        """Move a provider-call reservation into committed spend."""
        missing = False
        committed = 0.0

        def update(data: dict[str, Any]) -> None:
            nonlocal missing, committed
            reservations = data.setdefault("reservations", {})
            if not isinstance(reservations, dict) or reservation_id not in reservations:
                missing = True
                return
            reserved = float(reservations.pop(reservation_id))
            committed = reserved if actual_cost is None else actual_cost
            if committed < 0:
                raise ValueError("actual cost must be non-negative")
            data["spent"] = round(float(data.get("spent", 0.0)) + committed, 4)

        data = update_json_mapping(
            self.state_path,
            update,
            default={"spent": 0.0, "reservations": {}},
        )
        self._sync_state(data)
        if missing:
            return False, f"Budget reservation {reservation_id!r} was not found"
        return True, f"Budget committed: {committed:.2f} USD for {reservation_id}"

    def release_reservation(self, reservation_id: str) -> None:
        """Release a reservation after a provider rejects a call before accepting work."""

        def update(data: dict[str, Any]) -> None:
            reservations = data.setdefault("reservations", {})
            if isinstance(reservations, dict):
                reservations.pop(reservation_id, None)

        data = update_json_mapping(
            self.state_path,
            update,
            default={"spent": 0.0, "reservations": {}},
        )
        self._sync_state(data)

    def _sync_state(self, data: dict[str, Any]) -> None:
        self.spent = float(data.get("spent", 0.0))
        reservations = data.get("reservations", {})
        self.reservations = (
            {str(key): float(value) for key, value in reservations.items()}
            if isinstance(reservations, dict)
            else {}
        )

    def record(self, actual_cost: float) -> None:
        """Record actual spending."""
        if actual_cost < 0:
            logger.warning(f"Ignoring negative cost: {actual_cost}")
            return
        self.try_spend(actual_cost)
        logger.info(f"Budget: {self.spent:.2f}/{self.budget.total_usd:.2f} USD spent")

    def try_spend(self, actual_cost: float) -> tuple[bool, str]:
        """Atomically check and record spending for concurrent pipeline stages."""
        if actual_cost < 0:
            return False, f"Ignoring negative cost: {actual_cost}"
        if self.budget.mode == "observe":
            self._atomic_add(actual_cost)
            return True, f"Budget observe: {self.spent:.2f}/{self.budget.total_usd:.2f} USD spent"
        if self.budget.mode == "warn":
            self._atomic_add(actual_cost)
            if self.spent > self.budget.total_usd:
                msg = (
                    f"Budget WARNING: {self.spent:.2f} USD exceeds "
                    f"cap of {self.budget.total_usd:.2f} USD. Continuing anyway (warn mode)."
                )
                logger.warning(msg)
                return True, msg
            return True, f"Budget OK: {self.spent:.2f}/{self.budget.total_usd:.2f} USD"
        if self.budget.mode == "cap":
            blocked = ""

            def update(data: dict[str, Any]) -> None:
                nonlocal blocked
                spent_before = float(data.get("spent", 0.0))
                if spent_before + actual_cost > self.budget.total_usd:
                    blocked = (
                        f"Budget CAP exceeded: {spent_before:.2f} + {actual_cost:.2f} = "
                        f"{spent_before + actual_cost:.2f} USD > {self.budget.total_usd:.2f} USD."
                    )
                    return
                data["spent"] = round(spent_before + actual_cost, 4)

            data = update_json_mapping(self.state_path, update, default={"spent": 0.0})
            self.spent = float(data.get("spent", 0.0))
            if blocked:
                logger.error(blocked)
                return False, blocked
            return True, f"Budget OK: {self.spent:.2f}/{self.budget.total_usd:.2f} USD"
        self._atomic_add(actual_cost)
        return True, ""

    def _atomic_add(self, actual_cost: float) -> None:
        def update(data: dict[str, Any]) -> None:
            data["spent"] = round(float(data.get("spent", 0.0)) + actual_cost, 4)

        data = update_json_mapping(self.state_path, update, default={"spent": 0.0})
        self.spent = float(data.get("spent", 0.0))

    def get_cost_estimate(self, item_type: str, count: int) -> float:
        """Get estimated cost for a batch of items."""
        defaults = {
            "tts": self._configured_or_default(
                self.budget.tts_estimated, DEFAULT_COSTS["tts_per_segment"]
            ),
            "image": self._configured_or_default(
                self.budget.images_estimated, DEFAULT_COSTS["image_per_image"]
            ),
            "music": self._configured_or_default(
                self.budget.music_estimated, DEFAULT_COSTS["music_per_zone"]
            ),
            "video": self._configured_or_default(
                self.budget.video_estimated, DEFAULT_COSTS["video_per_segment"]
            ),
        }
        per_item = defaults.get(item_type, 0.0)
        return per_item * count

    def _configured_or_default(self, configured: float | None, default: float) -> float:
        return default if configured is None else configured

    def reset(self) -> None:
        """Reset spent counter."""
        self.spent = 0.0
        self.reservations = {}
        self._save()
