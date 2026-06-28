"""Budget tracking for API calls to prevent runaway spending.

Tracks cumulative spending across pipeline runs and enforces caps.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

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
        self.spent: float = self._load_spent()

    def _load_spent(self) -> float:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                return float(data.get("spent", 0.0))
            except Exception:
                return 0.0
        return 0.0

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_path, {"spent": round(self.spent, 4)})

    def remaining(self) -> float:
        return max(0.0, self.budget.total_usd - self.spent)

    def can_spend(self, estimated_cost: float) -> tuple[bool, str]:
        """Check if an estimated cost is within budget.

        Returns:
            (allowed, message)
        """
        if self.budget.mode == "observe":
            return True, f"Budget observe: {self.spent:.2f}/{self.budget.total_usd:.2f} USD spent"

        if self.budget.mode == "warn":
            if self.spent + estimated_cost > self.budget.total_usd:
                msg = (
                    f"Budget WARNING: {self.spent + estimated_cost:.2f} USD would exceed "
                    f"cap of {self.budget.total_usd:.2f} USD. Continuing anyway (warn mode)."
                )
                logger.warning(msg)
                return True, msg
            return (
                True,
                f"Budget OK: {self.spent + estimated_cost:.2f}/{self.budget.total_usd:.2f} USD",
            )

        if self.budget.mode == "cap":
            if self.spent + estimated_cost > self.budget.total_usd:
                msg = (
                    f"Budget CAP exceeded: {self.spent:.2f} + {estimated_cost:.2f} = "
                    f"{self.spent + estimated_cost:.2f} USD > {self.budget.total_usd:.2f} USD. "
                    f"Set budget.mode='warn' to override, or increase budget.total_usd."
                )
                logger.error(msg)
                return False, msg
            return (
                True,
                f"Budget OK: {self.spent + estimated_cost:.2f}/{self.budget.total_usd:.2f} USD",
            )

        return True, ""

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

            def update(data: dict) -> None:
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
        def update(data: dict) -> None:
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
        self._save()
