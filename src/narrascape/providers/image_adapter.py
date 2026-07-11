from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from narrascape.providers.runtime import BudgetReservationCoordinator


@dataclass
class ReferenceImageProviderAdapter:
    """Provider boundary for budgeted pre-production reference generation."""

    generator: Any
    provider: str
    coordinator: BudgetReservationCoordinator
    estimated_cost: float

    def generate(self, **kwargs: Any) -> bool:
        out_name = str(kwargs.get("out_name") or "reference")
        reservation_id = f"pre_production:{self.provider}:{out_name}"
        self.coordinator.reserve(reservation_id, self.estimated_cost, task={})
        generated = cast(bool, self.generator._generate_one(**kwargs))
        if generated:
            self.coordinator.commit(reservation_id)
        return generated
