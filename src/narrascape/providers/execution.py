from __future__ import annotations

from typing import Any

from narrascape.config import NarrascapeConfig
from narrascape.providers.health import health_store_for_project
from narrascape.providers.registry import ProviderCapability, build_default_registry
from narrascape.providers.selector import ProviderSelection, ProviderSelector


def select_provider(
    config: NarrascapeConfig,
    capability: str | ProviderCapability,
    *,
    intent: str = "general",
    task_context: dict[str, Any] | None = None,
) -> ProviderSelection:
    """Select an executable provider for a stage capability."""
    cap = ProviderCapability(capability)
    registry = build_default_registry(config)
    health_store = health_store_for_project(config.project_dir)
    health = health_store.snapshot()
    context = {"intent": intent, "provider_health": health}
    if task_context:
        context.update(task_context)
    return ProviderSelector().select(
        capability=cap.value,
        candidates=registry.by_capability(cap),
        task_context=context,
    )


def selection_metadata(selection: ProviderSelection) -> dict[str, Any]:
    """Serialize a provider selection for stage metadata and state files."""
    return {
        "name": selection.tool.name,
        "provider": selection.tool.provider,
        "capability": selection.tool.capability.value,
        "score": round(selection.score, 6),
        "reason": selection.reason,
        "requires": list(selection.tool.requires),
        "alternatives": [
            {"name": name, "score": round(score, 6)} for name, score in selection.alternatives
        ],
    }


def record_provider_success(config: NarrascapeConfig, provider_name: str) -> None:
    health_store_for_project(config.project_dir).record_success(provider_name)


def record_provider_failure(config: NarrascapeConfig, provider_name: str, error: str) -> None:
    health_store_for_project(config.project_dir).record_failure(provider_name, error)
