from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    failure_count: int = 0
    disabled_until: float = 0.0
    last_error: str = ""

    @property
    def available(self) -> bool:
        return time.time() >= self.disabled_until


class ProviderHealthStore:
    """Small JSON-backed provider health and circuit-breaker store."""

    def __init__(
        self,
        path: Path,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: int = 300,
    ) -> None:
        self.path = path
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

    def snapshot(self) -> dict[str, ProviderHealth]:
        data = self._load()
        return {
            name: ProviderHealth(
                name=name,
                failure_count=int(item.get("failure_count", 0)),
                disabled_until=float(item.get("disabled_until", 0.0)),
                last_error=str(item.get("last_error", "")),
            )
            for name, item in data.items()
            if isinstance(item, dict)
        }

    def record_success(self, provider_name: str) -> None:
        data = self._load()
        data.pop(provider_name, None)
        self._save(data)

    def record_failure(self, provider_name: str, error: str) -> ProviderHealth:
        data = self._load()
        item = data.get(provider_name, {})
        failure_count = int(item.get("failure_count", 0)) + 1
        disabled_until = 0.0
        if failure_count >= self.failure_threshold:
            disabled_until = time.time() + self.cooldown_seconds
        data[provider_name] = {
            "failure_count": failure_count,
            "disabled_until": disabled_until,
            "last_error": error[:500],
            "updated_at": time.time(),
        }
        self._save(data)
        return ProviderHealth(
            name=provider_name,
            failure_count=failure_count,
            disabled_until=disabled_until,
            last_error=error[:500],
        )

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def health_store_for_project(project_dir: Path) -> ProviderHealthStore:
    return ProviderHealthStore(project_dir / ".narrascape" / "provider_health.json")
