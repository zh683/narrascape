"""Provider discovery, selection, and runtime health helpers."""

from narrascape.providers.execution import (
    record_provider_failure,
    record_provider_success,
    select_provider,
    selection_metadata,
)
from narrascape.providers.registry import (
    ProviderCapability,
    ProviderRegistry,
    ProviderTool,
    build_default_registry,
)
from narrascape.providers.selector import ProviderSelection, ProviderSelector

__all__ = [
    "ProviderCapability",
    "ProviderRegistry",
    "ProviderTool",
    "ProviderSelection",
    "ProviderSelector",
    "build_default_registry",
    "record_provider_failure",
    "record_provider_success",
    "select_provider",
    "selection_metadata",
]
