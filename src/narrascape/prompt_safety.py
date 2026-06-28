"""Provider-specific prompt normalization for external generation APIs."""

from __future__ import annotations

import re

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


def sanitize_prompt_for_provider(
    provider: str, prompt: str | None, *, append_safety_suffix: bool = True
) -> str:
    """Return a provider-safe prompt while preserving the core creative intent."""
    if not prompt:
        return ""
    text = str(prompt)
    if provider.lower() != "agnes":
        return text

    for pattern, replacement in _AGNES_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = _normalize_prompt_whitespace(text)
    if append_safety_suffix and _AGNES_SAFE_SUFFIX.strip().lower() not in text.lower():
        text = f"{text.rstrip('.')}.{_AGNES_SAFE_SUFFIX}"
    return text


def _normalize_prompt_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"([,.;:]){2,}", r"\1", text)
    return text.strip()
