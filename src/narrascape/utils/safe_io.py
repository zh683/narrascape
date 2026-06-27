from __future__ import annotations

import json
import os
import shutil
import threading
import time
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml


class ArtifactLoadError(ValueError):
    """Raised when an artifact cannot be loaded as the expected data type."""


_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


@contextmanager
def file_lock(path: Path, *, timeout: float = 30.0, stale_after: float = 600.0) -> Iterator[None]:
    """Cross-process and same-process lock for a target file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(f"{target.name}.lock")
    thread_lock = _thread_lock_for(lock_path)
    deadline = time.monotonic() + timeout

    with thread_lock:
        fd: int | None = None
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
                break
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    if age > stale_after:
                        lock_path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for lock: {lock_path}")
                time.sleep(0.05)

        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8", lock: bool = True) -> None:
    target = Path(path)
    if lock:
        with file_lock(target):
            _atomic_write_text_unlocked(target, text, encoding=encoding)
    else:
        _atomic_write_text_unlocked(target, text, encoding=encoding)


def atomic_write_bytes(path: Path, data: bytes, *, lock: bool = True) -> None:
    target = Path(path)
    if lock:
        with file_lock(target):
            _atomic_write_bytes_unlocked(target, data)
    else:
        _atomic_write_bytes_unlocked(target, data)


def atomic_write_json(path: Path, data: Any, *, lock: bool = True, indent: int | None = 2) -> None:
    atomic_write_text(
        path,
        json.dumps(data, indent=indent, ensure_ascii=False),
        encoding="utf-8",
        lock=lock,
    )


def atomic_write_yaml(path: Path, data: Any, *, lock: bool = True) -> None:
    atomic_write_text(
        path,
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
        lock=lock,
    )


def update_json_mapping(
    path: Path,
    updater: Callable[[dict[str, Any]], None],
    *,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = Path(path)
    with file_lock(target):
        data = load_json_mapping(target, default=default or {})
        updater(data)
        atomic_write_json(target, data, lock=False)
    return data


def load_json_mapping(path: Path, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return dict(default or {})
    try:
        text = target.read_text(encoding="utf-8")
        if not text.strip():
            return dict(default or {})
        data = json.loads(text)
    except Exception as exc:
        raise ArtifactLoadError(f"Invalid JSON artifact {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise ArtifactLoadError(f"Invalid JSON artifact {target}: expected mapping")
    return data


def load_yaml_mapping(path: Path, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return dict(default or {})
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ArtifactLoadError(f"Invalid YAML artifact {target}: {exc}") from exc
    except OSError as exc:
        raise ArtifactLoadError(f"Cannot read YAML artifact {target}: {exc}") from exc
    if data is None:
        return dict(default or {})
    if not isinstance(data, dict):
        raise ArtifactLoadError(f"Invalid YAML artifact {target}: expected mapping")
    return data


def ensure_min_free_space(
    path: Path,
    *,
    min_free_mb: float = 64.0,
    purpose: str = "write output",
) -> None:
    """Fail before writes when the destination volume is nearly full."""
    if os.environ.get("NARRASCAPE_SKIP_DISK_CHECK") == "1":
        return
    override = os.environ.get("NARRASCAPE_MIN_FREE_MB")
    if override:
        try:
            min_free_mb = float(override)
        except ValueError:
            pass
    probe = Path(path)
    if not probe.exists() or probe.is_file():
        probe = probe.parent
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    required = int(min_free_mb * 1024 * 1024)
    if free < required:
        free_mb = free / 1024 / 1024
        raise RuntimeError(
            f"Insufficient disk space to {purpose}: {free_mb:.1f} MB free, "
            f"requires at least {min_free_mb:.1f} MB at {probe}"
        )


def download_to_path(
    url: str,
    path: Path,
    *,
    timeout: float = 300.0,
    min_bytes: int = 1,
    min_free_mb: float = 64.0,
    expected_content_prefixes: tuple[str, ...] = (),
) -> None:
    """Stream a URL to a sibling temp file, then atomically promote it."""
    target = Path(path)
    ensure_min_free_space(target, min_free_mb=min_free_mb, purpose=f"download {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.download")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, open(tmp, "wb") as fh:
            status = response.getcode()
            if status and int(status) >= 400:
                raise RuntimeError(f"HTTP download failed with status {status}: {url}")
            content_type = response.getheader("Content-Type", "")
            if expected_content_prefixes and content_type:
                normalized = content_type.lower()
                if not any(
                    normalized.startswith(prefix.lower()) for prefix in expected_content_prefixes
                ):
                    raise RuntimeError(f"Unexpected content type for {target.name}: {content_type}")
            shutil.copyfileobj(response, fh, length=1024 * 1024)
            fh.flush()
            os.fsync(fh.fileno())
        if tmp.stat().st_size < min_bytes:
            raise RuntimeError(f"Downloaded file is too small: {tmp.stat().st_size} bytes")
        with file_lock(target):
            os.replace(tmp, target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_text_unlocked(path: Path, text: str, *, encoding: str) -> None:
    data = text.encode(encoding)
    _atomic_write_bytes_unlocked(path, data)


def _atomic_write_bytes_unlocked(path: Path, data: bytes) -> None:
    target = Path(path)
    ensure_min_free_space(target, min_free_mb=1.0, purpose=f"write {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
