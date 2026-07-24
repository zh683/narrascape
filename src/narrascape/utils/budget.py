"""Budget tracking for API calls to prevent runaway spending.

Tracks cumulative spending across pipeline runs and enforces caps.

State file (budget_state.json) schema:
    {
        "spent": 12.34,
        "entries": [
            {
                "timestamp": "...", "kind": "video", "status": "failed",
                "cost": 0.5, "stage": "generate_video", "provider": "seedance",
                "model": "", "detail": "vid_01",
                "prompt_tokens": 0, "completion_tokens": 0, "estimated": false
            },
            ...
        ]
    }

Older state files that only contain {"spent": ...} load transparently.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from narrascape.config import BudgetConfig, LLMTokenRate, NarrascapeConfig
from narrascape.utils.safe_io import (
    atomic_write_json,
    atomic_write_yaml,
    load_json_mapping,
    update_json_mapping,
)

logger = logging.getLogger("narrascape.budget")


# Default cost estimates (USD per item) — override via config.budget.*_estimated
DEFAULT_COSTS = {
    "tts_per_segment": 0.001,
    "image_per_image": 0.05,
    "music_per_zone": 0.02,
    "video_per_segment": 0.5,
}

# Keep the persisted entry list bounded across many runs.
MAX_ENTRIES = 2000

# Entry status values
ENTRY_STATUS_SUCCESS = "success"
ENTRY_STATUS_FAILED = "failed"
ENTRY_STATUS_NETWORK_ERROR = "network_error"


def estimate_tokens(text: str) -> int:
    """Rough token estimate when a provider does not report usage (~4 chars/token)."""
    return max(1, len(text) // 4)


def estimate_llm_cost(
    rates: dict[str, LLMTokenRate],
    default_rate: LLMTokenRate,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Estimate LLM call cost in USD from token usage and configured rates.

    Unknown models fall back to the conservative default rate.
    """
    rate = rates.get(model, default_rate)
    return round(
        prompt_tokens * rate.input_per_million_usd / 1_000_000
        + completion_tokens * rate.output_per_million_usd / 1_000_000,
        6,
    )


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
            {"spent": round(self.spent, 4), "entries": [], "reservations": self.reservations},
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

    def _append_entry(self, data: dict[str, Any], entry: dict[str, Any]) -> None:
        entries = data.setdefault("entries", [])
        if isinstance(entries, list):
            entries.append(entry)
            if len(entries) > MAX_ENTRIES:
                del entries[: len(entries) - MAX_ENTRIES]

    def _make_entry(
        self,
        actual_cost: float,
        *,
        kind: str,
        status: str,
        stage: str,
        provider: str,
        model: str,
        detail: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated: bool,
    ) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "status": status,
            "cost": round(actual_cost, 6),
            "stage": stage,
            "provider": provider,
            "model": model,
            "detail": detail,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated": estimated,
        }

    def record_actual(
        self,
        actual_cost: float,
        *,
        kind: str,
        status: str = ENTRY_STATUS_SUCCESS,
        stage: str = "",
        provider: str = "",
        model: str = "",
        detail: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated: bool = False,
    ) -> None:
        """Record spending that has already been incurred, unconditionally.

        Used for post-hoc accounting: provider-billed failed calls (task
        failed/expired, business error status), LLM token usage, and
        zero-cost network-failure entries. Unlike try_spend this never blocks
        — the money is already spent. Cap enforcement happens on the next
        can_spend/try_spend check.
        """
        if actual_cost < 0:
            logger.warning(f"Ignoring negative cost: {actual_cost}")
            return
        entry = self._make_entry(
            actual_cost,
            kind=kind,
            status=status,
            stage=stage,
            provider=provider,
            model=model,
            detail=detail,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated=estimated,
        )

        def update(data: dict[str, Any]) -> None:
            data["spent"] = round(float(data.get("spent", 0.0)) + actual_cost, 4)
            self._append_entry(data, entry)

        data = update_json_mapping(self.state_path, update, default={"spent": 0.0, "entries": []})
        self.spent = float(data.get("spent", 0.0))

    def try_spend(
        self,
        actual_cost: float,
        *,
        kind: str = "generic",
        status: str = ENTRY_STATUS_SUCCESS,
        stage: str = "",
        provider: str = "",
        detail: str = "",
    ) -> tuple[bool, str]:
        """Atomically check and record spending for concurrent pipeline stages."""
        if actual_cost < 0:
            return False, f"Ignoring negative cost: {actual_cost}"
        entry = self._make_entry(
            actual_cost,
            kind=kind,
            status=status,
            stage=stage,
            provider=provider,
            model="",
            detail=detail,
            prompt_tokens=0,
            completion_tokens=0,
            estimated=False,
        )
        if self.budget.mode == "observe":
            self._atomic_add(actual_cost, entry)
            return True, f"Budget observe: {self.spent:.2f}/{self.budget.total_usd:.2f} USD spent"
        if self.budget.mode == "warn":
            self._atomic_add(actual_cost, entry)
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
                self._append_entry(data, entry)

            data = update_json_mapping(self.state_path, update, default={"spent": 0.0})
            self.spent = float(data.get("spent", 0.0))
            if blocked:
                logger.error(blocked)
                return False, blocked
            return True, f"Budget OK: {self.spent:.2f}/{self.budget.total_usd:.2f} USD"
        self._atomic_add(actual_cost, entry)
        return True, ""

    def _atomic_add(self, actual_cost: float, entry: dict[str, Any] | None = None) -> None:
        def update(data: dict[str, Any]) -> None:
            data["spent"] = round(float(data.get("spent", 0.0)) + actual_cost, 4)
            if entry is not None:
                self._append_entry(data, entry)

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


# ───────────────────────────────────────────
# Cost report
# ───────────────────────────────────────────


def _group_sum(entries: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for entry in entries:
        name = str(entry.get(key) or "unknown")
        group = groups.setdefault(name, {"calls": 0, "failed": 0, "cost_usd": 0.0})
        group["calls"] += 1
        if entry.get("status") != ENTRY_STATUS_SUCCESS:
            group["failed"] += 1
        group["cost_usd"] = round(group["cost_usd"] + float(entry.get("cost", 0.0)), 6)
    return groups


def build_cost_report(state: dict[str, Any], budget: BudgetConfig) -> dict[str, Any]:
    """Aggregate budget_state.json content into a cost report mapping."""
    entries = [e for e in state.get("entries", []) if isinstance(e, dict)]
    spent = float(state.get("spent", 0.0))
    llm_entries = [e for e in entries if e.get("kind") == "llm"]
    failed_entries = [e for e in entries if e.get("status") == ENTRY_STATUS_FAILED]
    return {
        "schema_version": "cost_report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget": {
            "mode": budget.mode,
            "total_usd": budget.total_usd,
            "spent_usd": round(spent, 6),
            "remaining_usd": round(max(0.0, budget.total_usd - spent), 6),
        },
        "totals": {
            "calls": len(entries),
            "succeeded": sum(1 for e in entries if e.get("status") == ENTRY_STATUS_SUCCESS),
            "failed": len(failed_entries),
            "network_errors": sum(
                1 for e in entries if e.get("status") == ENTRY_STATUS_NETWORK_ERROR
            ),
            "cost_usd": round(spent, 6),
            "failed_cost_usd": round(sum(float(e.get("cost", 0.0)) for e in failed_entries), 6),
        },
        "by_kind": _group_sum(entries, "kind"),
        "by_stage": _group_sum(entries, "stage"),
        "by_provider": _group_sum(entries, "provider"),
        "llm": {
            "calls": len(llm_entries),
            "prompt_tokens": sum(int(e.get("prompt_tokens", 0)) for e in llm_entries),
            "completion_tokens": sum(int(e.get("completion_tokens", 0)) for e in llm_entries),
            "estimated_calls": sum(1 for e in llm_entries if e.get("estimated")),
            "cost_usd": round(sum(float(e.get("cost", 0.0)) for e in llm_entries), 6),
        },
    }


def write_cost_report(config: NarrascapeConfig) -> Path:
    """Write pipeline/<name>/cost_report.yaml from budget_state.json."""
    state_path = config.pipeline_dir / "budget_state.json"
    state = load_json_mapping(state_path, default={"spent": 0.0, "entries": []})
    report = build_cost_report(state, config.budget)
    out_path = config.pipeline_dir / "cost_report.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(out_path, report)
    return out_path
