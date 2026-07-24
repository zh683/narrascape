"""Dependency lock hygiene.

pyproject.toml keeps lower bounds only (library anti-pattern to add caps
without evidence); requirements-lock.txt pins the resolved test environment
for reproducible CI/dev installs. The lock must stay loadable, fully pinned,
and cover every direct runtime dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

LOCK_PATH = Path("requirements-lock.txt")


def _lock_entries() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, version = line.partition("==")
        entries[name.strip().lower()] = version.strip()
    return entries


def test_lock_file_exists_and_is_fully_pinned():
    assert LOCK_PATH.exists(), "requirements-lock.txt is missing"
    raw = LOCK_PATH.read_text(encoding="utf-8").splitlines()
    pins = [line.strip() for line in raw if line.strip() and not line.startswith("#")]
    assert pins, "lock file has no pinned entries"
    for line in pins:
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+==\S+", line), f"unpinned lock entry: {line}"
        assert "file:" not in line and "@" not in line, f"local/URL entry in lock: {line}"


def test_lock_excludes_the_project_itself():
    assert "narrascape" not in _lock_entries()


def test_lock_covers_direct_runtime_dependencies():
    from packaging.markers import Marker

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    direct = data["project"]["dependencies"]
    lock = _lock_entries()
    missing = []
    for dep in direct:
        requirement, _, marker_text = dep.partition(";")
        if marker_text.strip() and not Marker(marker_text.strip()).evaluate():
            continue  # marker-gated dep (e.g. tomli on <3.11) absent from this snapshot
        name = re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip().lower()
        if name not in lock:
            missing.append(dep)
    assert not missing, f"runtime dependencies missing from lock: {missing}"


def test_lock_covers_key_dev_tools():
    lock = _lock_entries()
    for tool in ("pytest", "black", "ruff", "mypy"):
        assert tool in lock, f"{tool} missing from lock"
