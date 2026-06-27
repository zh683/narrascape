from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("narrascape.cache")


class CacheEntry(BaseModel):
    """A single cache entry."""
    key: str
    input_hashes: dict[str, str]
    config_hash: str
    output_path: str
    created_at: float


class BuildCache:
    """Content-hash driven incremental build cache.

    Each cached artifact is keyed by SHA256 of (input file contents + config parameters).
    This avoids the "file exists but content changed" bug of simple mtime checking.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir / "index.json"
        self._index: dict[str, CacheEntry] = self._load_index()

    def _load_index(self) -> dict[str, CacheEntry]:
        if not self.index_path.exists():
            return {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            return {k: CacheEntry(**v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"Cache index corrupted, starting fresh: {e}")
            return {}

    def _save_index(self) -> None:
        data = {k: v.model_dump() for k, v in self._index.items()}
        self.index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    @staticmethod
    def _hash_config(config: Any) -> str:
        if isinstance(config, BaseModel):
            data = config.model_dump_json()
        elif isinstance(config, dict):
            import json
            data = json.dumps(config, sort_keys=True, ensure_ascii=False)
        else:
            data = str(config)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]

    def compute_key(
        self,
        inputs: dict[str, Path],
        config: Any,
        version: str = "v1",
    ) -> str:
        """Compute a cache key from inputs and config.

        Args:
            inputs: Mapping of input names to file paths
            config: Serializable configuration object
            version: Cache schema version (bump to invalidate)
        """
        input_hashes = {name: self._hash_file(path) for name, path in inputs.items() if path.exists()}
        config_hash = self._hash_config(config)
        combined = json.dumps({"inputs": input_hashes, "config": config_hash, "version": version}, sort_keys=True)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:20]

    def is_cached(self, key: str, output_path: Path) -> bool:
        """Check if a valid cached entry exists for the given key."""
        if key not in self._index:
            return False
        entry = self._index[key]
        if not Path(entry.output_path).exists():
            return False
        # Validate input hashes haven't changed
        for name, expected_hash in entry.input_hashes.items():
            input_path = self.cache_dir.parent.parent / name  # heuristic: resolve relative to project
            if not input_path.exists() or self._hash_file(input_path) != expected_hash:
                return False
        return True

    def get_output(self, key: str) -> Path | None:
        """Get cached output path if valid."""
        if key not in self._index:
            return None
        entry = self._index[key]
        path = Path(entry.output_path)
        if path.exists():
            return path
        return None

    def put(
        self,
        key: str,
        inputs: dict[str, Path],
        config: Any,
        output_path: Path,
    ) -> None:
        """Register a new cache entry."""
        import time
        input_hashes = {name: self._hash_file(path) for name, path in inputs.items() if path.exists()}
        entry = CacheEntry(
            key=key,
            input_hashes=input_hashes,
            config_hash=self._hash_config(config),
            output_path=str(output_path),
            created_at=time.time(),
        )
        self._index[key] = entry
        self._save_index()
        logger.info(f"[cache] Cached: {key} -> {output_path.name}")

    def invalidate(self, key: str) -> None:
        """Remove a cache entry."""
        if key in self._index:
            del self._index[key]
            self._save_index()
            logger.info(f"[cache] Invalidated: {key}")

    def clear(self) -> None:
        """Clear all cache entries."""
        self._index.clear()
        self._save_index()
        logger.info("[cache] Cleared all entries")
