"""API key and credential management.

Reads API keys from environment variables or .env file.
Supports: MINIMAX_API_KEY, ARK_API_KEY (Volcengine), OPENAI_API_KEY, etc.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Load .env file as key-value dict."""
    env: dict[str, str] = {}
    if path is None:
        # Search upward from cwd
        cwd = Path.cwd()
        for p in [cwd, cwd.parent, cwd.parent.parent]:
            ep = p / ".env"
            if ep.exists():
                path = ep
                break
    if path is None or not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        env[key.strip()] = val.strip().strip('"\'')
    return env


class APIKeys:
    """Centralized API key management."""

    _env_cache: dict[str, str] | None = None

    @classmethod
    def _env(cls) -> dict[str, str]:
        if cls._env_cache is None:
            cls._env_cache = load_env_file()
        return cls._env_cache

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
    def ark_model_id(cls) -> str | None:
        """Volcengine Ark model/endpoint ID (for LLM chat completions)."""
        return cls.get("ARK_MODEL_ID")

    @classmethod
    def openai(cls) -> str | None:
        return cls.get("OPENAI_API_KEY")

    @classmethod
    def reset_cache(cls) -> None:
        cls._env_cache = None
