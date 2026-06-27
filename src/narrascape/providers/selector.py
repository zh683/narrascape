from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from narrascape.providers.registry import ProviderTool


@dataclass(frozen=True)
class ProviderSelection:
    tool: ProviderTool
    score: float
    reason: str
    alternatives: list[tuple[str, float]]


class ProviderSelector:
    weights = {
        "task_fit": 0.30,
        "quality": 0.20,
        "control": 0.15,
        "reliability": 0.15,
        "cost_efficiency": 0.10,
        "latency": 0.05,
        "continuity": 0.05,
    }

    def select(
        self,
        capability: str,
        candidates: list[ProviderTool],
        task_context: dict[str, Any] | None = None,
    ) -> ProviderSelection:
        usable = [tool for tool in candidates if tool.capability.value == capability and tool.status == "available"]
        if not usable:
            raise ValueError(f"No available providers for capability: {capability}")

        scored = [(tool, self.score(tool, task_context or {})) for tool in usable]
        scored.sort(key=lambda item: item[1], reverse=True)
        winner, score = scored[0]
        intent = str((task_context or {}).get("intent", "general"))
        reason = f"selected {winner.name} for {capability}; intent={intent}; score={score:.3f}"
        alternatives = [(tool.name, value) for tool, value in scored[1:]]
        return ProviderSelection(winner, score, reason, alternatives)

    def score(self, tool: ProviderTool, task_context: dict[str, Any]) -> float:
        intent = str(task_context.get("intent", "general")).lower()
        task_fit = tool.task_fit.get(intent, tool.task_fit.get("general", 0.5))
        return (
            task_fit * self.weights["task_fit"]
            + tool.quality * self.weights["quality"]
            + tool.control * self.weights["control"]
            + tool.reliability * self.weights["reliability"]
            + tool.cost_efficiency * self.weights["cost_efficiency"]
            + tool.latency * self.weights["latency"]
            + tool.continuity * self.weights["continuity"]
        )
