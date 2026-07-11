from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"
TRUNCATED = "...[truncated]"

_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|authorization|access[_-]?token|token|secret|password)"
    r"[\"']?\s*[:=]\s*)([\"']?)([^\s,\"'}]+)"
)
_PROVIDER_KEY_PATTERN = re.compile(r"\b(?:sk|rk|ak)-[A-Za-z0-9_-]{6,}\b", re.IGNORECASE)


def sanitize_text(text: str, *, max_chars: int, secrets: Sequence[str] = ()) -> str:
    """Redact common credentials and cap retained diagnostic text."""

    sanitized = text
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        sanitized = sanitized.replace(secret, REDACTED)
    sanitized = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", sanitized)
    sanitized = _PROVIDER_KEY_PATTERN.sub(REDACTED, sanitized)
    sanitized = _SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        sanitized,
    )
    if len(sanitized) <= max_chars:
        return sanitized
    retained = max(0, max_chars - len(TRUNCATED))
    return f"{sanitized[:retained]}{TRUNCATED}"


def sanitize_value(
    value: Any,
    *,
    max_chars: int,
    secrets: Sequence[str] = (),
    max_items: int = 20,
    _depth: int = 0,
) -> Any:
    """Recursively sanitize structured diagnostic data with bounded collections."""

    if _depth >= 6:
        return "[depth-limited]"
    if isinstance(value, str):
        return sanitize_text(value, max_chars=max_chars, secrets=secrets)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:max_items]:
            safe_key = sanitize_text(str(key), max_chars=max_chars, secrets=secrets)
            sanitized[safe_key] = sanitize_value(
                item,
                max_chars=max_chars,
                secrets=secrets,
                max_items=max_items,
                _depth=_depth + 1,
            )
        if len(items) > max_items:
            sanitized["_omitted_items"] = len(items) - max_items
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = list(value)
        sanitized_items = [
            sanitize_value(
                item,
                max_chars=max_chars,
                secrets=secrets,
                max_items=max_items,
                _depth=_depth + 1,
            )
            for item in items[:max_items]
        ]
        if len(items) > max_items:
            sanitized_items.append({"_omitted_items": len(items) - max_items})
        return sanitized_items
    return sanitize_text(repr(value), max_chars=max_chars, secrets=secrets)
