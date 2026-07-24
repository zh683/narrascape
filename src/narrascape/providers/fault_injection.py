from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ProviderRateLimitError(RuntimeError):
    status_code = 429


class ChargedProviderError(RuntimeError):
    """Provider accepted and charged work but did not return a usable result."""

    charged = True


class PartialProviderOutputError(ValueError):
    """Provider response claims completion without required output fields."""


@dataclass(frozen=True)
class FaultStep:
    kind: str
    payload: Any = None


class FaultInjectingProvider:
    """Deterministic provider simulator for recovery and staging tests."""

    def __init__(self, steps: list[FaultStep]):
        self.steps = list(steps)
        self.call_count = 0

    def call(self) -> Any:
        self.call_count += 1
        if not self.steps:
            raise RuntimeError("fault script exhausted")
        step = self.steps.pop(0)
        if step.kind == "timeout":
            raise TimeoutError("injected provider timeout")
        if step.kind == "rate_limit":
            raise ProviderRateLimitError("injected provider HTTP 429")
        if step.kind == "charged_failure":
            raise ChargedProviderError("injected failure after provider charge")
        if step.kind in {"success", "partial"}:
            return step.payload
        raise ValueError(f"unknown fault step: {step.kind}")


def validate_provider_output(
    payload: Any,
    *,
    required_fields: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PartialProviderOutputError("provider output must be a mapping")
    missing = [field for field in required_fields if payload.get(field) in (None, "", [], {})]
    if missing:
        raise PartialProviderOutputError(
            f"provider output is incomplete; missing: {', '.join(missing)}"
        )
    return dict(payload)
