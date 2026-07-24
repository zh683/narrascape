"""API key and credential management.

Reads API keys from environment variables or the .env file in the current
working directory.
Supports: MINIMAX_API_KEY, ARK_API_KEY (Volcengine), AGNES_API_KEY, OPENAI_API_KEY, etc.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def find_env_file(start: Path | None = None) -> Path | None:
    """Return the .env file for the working directory, if present.

    The search is deliberately limited to the working directory itself:
    the previous upward walk (two parent levels) silently loaded unrelated
    .env files when commands ran from a different directory.
    """
    cwd = start or Path.cwd()
    candidate = cwd / ".env"
    return candidate if candidate.is_file() else None


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Load .env file as key-value dict."""
    env: dict[str, str] = {}
    if path is None:
        path = find_env_file()
    if path is None or not path.exists():
        return env
    logger.debug("Loading environment overrides from %s", path)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        env[key.strip()] = val.strip().strip("\"'")
    return env


class APIKeys:
    """Centralized API key management."""

    _env_cache: dict[str, str] | None = None
    _env_cache_key: tuple[str, float] | None = None

    @classmethod
    def _env(cls) -> dict[str, str]:
        # Cache is keyed by (resolved .env path, mtime) so a long-lived
        # process picks up edits and working-directory changes without an
        # explicit reset_cache() call.
        path = find_env_file()
        cache_key = (str(path), path.stat().st_mtime) if path else ("", 0.0)
        if cls._env_cache is None or cls._env_cache_key != cache_key:
            cls._env_cache = load_env_file(path)
            cls._env_cache_key = cache_key
        return dict(cls._env_cache)

    @classmethod
    def get(cls, key: str, default: str | None = None) -> str | None:
        """Get API key from environment or .env file."""
        # 1. Environment variable
        val = os.environ.get(key)
        if val:
            return val
        # 2. .env file
        val = cls._env().get(key)
        if val:
            return val
        return default

    @classmethod
    def minimax(cls) -> str | None:
        return cls.get("MINIMAX_API_KEY")

    @classmethod
    def ark(cls) -> str | None:
        """Volcengine Ark API key (for Seedream)."""
        return cls.get("ARK_API_KEY")

    @classmethod
    def agnes(cls) -> str | None:
        """Agnes AI API key (for image and video generation)."""
        return cls.get("AGNES_API_KEY")

    @classmethod
    def ark_model_id(cls) -> str | None:
        """Volcengine Ark model/endpoint ID (for LLM chat completions)."""
        return cls.get("ARK_MODEL_ID")

    @classmethod
    def openai(cls) -> str | None:
        return cls.get("OPENAI_API_KEY")

    @classmethod
    def reset_cache(cls) -> None:
        cls._env_cache = None
        cls._env_cache_key = None
