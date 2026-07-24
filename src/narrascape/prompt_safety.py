"""Provider-specific prompt normalization for external generation APIs."""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from narrascape.utils.safe_io import atomic_write_yaml, load_yaml_mapping

logger = logging.getLogger("narrascape.prompt_safety")

_AGNES_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bmurderer\b", "morally tormented former student"),
    (r"\bmurderess\b", "morally tormented character"),
    (r"\bmurders\b", "grave moral wrongdoings"),
    (r"\bmurdered\b", "caught in a grave moral crisis"),
    (r"\bmurdering\b", "crossing a moral boundary"),
    (r"\bmurder\b", "grave moral wrongdoing"),
    (r"\bcriminal\b", "morally compromised"),
    (r"\bcrimes\b", "moral wrongdoings"),
    (r"\bcrime\b", "hidden wrongdoing"),
    (r"\bvictims\b", "affected figures"),
    (r"\bvictim\b", "affected figure"),
    (r"\baxe\b", "concealed heavy object"),
    (r"\bhatchet\b", "concealed heavy object"),
    (r"\bweapon\b", "dangerous prop"),
    (r"\bweapons\b", "dangerous props"),
    (r"\bgun\b", "modern action prop"),
    (r"\bknife\b", "sharp prop"),
    (r"\bbloodstains?\b", "dark marks"),
    (r"\bblood splatter\b", "messy horror detail"),
    (r"\bblood\b", "dark mark"),
    (r"\bgore\b", "sensational horror detail"),
    (r"\bgraphic injury\b", "explicit injury detail"),
    (r"\bgraphic violence\b", "sensational violent detail"),
    (r"\bviolence\b", "off-screen conflict"),
    (r"\bviolent\b", "tense"),
    (r"\bstolen\b", "hidden"),
    (r"\btheft\b", "secret wrongdoing"),
    (r"谋杀", "道德罪责"),
    (r"凶手", "被罪责折磨的人"),
    (r"受害者", "受影响的人物"),
    (r"犯罪", "隐秘过错"),
    (r"暴力", "画外冲突"),
    (r"血迹", "暗色痕迹"),
    (r"血", "暗色痕迹"),
    (r"斧头", "藏起的沉重物件"),
)

_AGNES_SAFE_SUFFIX = (
    " Restrained non-graphic period literary drama, symbolic psychological tension, "
    "no sensational detail, no readable text, no watermark."
)

# Process-wide audit trail of every rewrite applied by
# sanitize_prompt_for_provider. Generation stages drain it at the end of
# run() and persist it to pipeline/<project>/prompt_safety.yaml, so rewrites
# that used to be silent become visible to the director layer. The stages
# that sanitize (pre_production / generate_images / generate_video) sit in
# different topological levels and never run concurrently, so cross-stage
# attribution stays correct in practice.
_SANITIZE_EVENTS_LOCK = threading.Lock()
_SANITIZE_EVENTS: list[dict[str, Any]] = []


def sanitize_prompt_for_provider(
    provider: str, prompt: str | None, *, append_safety_suffix: bool = True
) -> str:
    """Return a provider-safe prompt while preserving the core creative intent."""
    if not prompt:
        return ""
    text = str(prompt)
    if provider.lower() != "agnes":
        return text

    hits: list[dict[str, Any]] = []
    for pattern, replacement in _AGNES_REPLACEMENTS:
        text, count = re.subn(pattern, replacement, text, flags=re.IGNORECASE)
        if count:
            hits.append({"pattern": pattern, "replacement": replacement, "count": count})
    if hits:
        _record_sanitize_event(provider, hits)
    text = _normalize_prompt_whitespace(text)
    if append_safety_suffix and _AGNES_SAFE_SUFFIX.strip().lower() not in text.lower():
        text = f"{text.rstrip('.')}.{_AGNES_SAFE_SUFFIX}"
    return text


def _record_sanitize_event(provider: str, hits: list[dict[str, Any]]) -> None:
    """Log the rewrite (without the prompt itself) and buffer an audit event."""
    total = sum(int(hit["count"]) for hit in hits)
    categories = ", ".join(str(hit["pattern"]).replace(r"\b", "") for hit in hits)
    logger.warning(
        f"sanitize_prompt_for_provider rewrote a prompt for provider '{provider}': "
        f"{total} replacement(s) across categories [{categories}] "
        f"(audited in pipeline/<project>/prompt_safety.yaml)"
    )
    event: dict[str, Any] = {
        "provider": provider,
        "replacement_count": total,
        "replacements": hits,
    }
    with _SANITIZE_EVENTS_LOCK:
        _SANITIZE_EVENTS.append(event)


def drain_sanitize_events() -> list[dict[str, Any]]:
    """Return all buffered sanitize events and clear the buffer (idempotent)."""
    with _SANITIZE_EVENTS_LOCK:
        events = list(_SANITIZE_EVENTS)
        _SANITIZE_EVENTS.clear()
    return events


def write_sanitize_audit(pipeline_dir: Path, stage_name: str) -> Path | None:
    """Persist drained sanitize events to ``pipeline_dir/prompt_safety.yaml``.

    Returns the audit path when events were written, ``None`` when the buffer
    was empty (no rewrites happened — a clean run creates no file). Events
    are appended when the file already exists: several stages feed the same
    per-project audit, each event tagged with the stage that drained it.
    """
    events = drain_sanitize_events()
    if not events:
        return None
    for event in events:
        event["stage"] = stage_name
    path = pipeline_dir / "prompt_safety.yaml"
    existing: dict[str, Any] = {}
    if path.exists():
        existing = load_yaml_mapping(path, default={})
    recorded = list(existing.get("events", []) or [])
    recorded.extend(events)
    atomic_write_yaml(path, {"schema_version": "prompt_safety.v1", "events": recorded})
    logger.info(f"prompt sanitize audit updated: {path} ({len(events)} new event(s))")
    return path


def _normalize_prompt_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"([,.;:]){2,}", r"\1", text)
    return text.strip()
