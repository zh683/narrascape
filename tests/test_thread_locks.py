"""Bounded _THREAD_LOCKS: the per-file thread-lock dict must not grow
forever in long-running processes (dashboard). Entries are LRU-evicted
past a capacity cap, but never while a thread holds or waits on them.
"""

from __future__ import annotations

import threading

from narrascape.utils import safe_io
from narrascape.utils.safe_io import (
    _THREAD_LOCKS,
    _THREAD_LOCKS_MAX,
    file_lock,
)


def test_thread_locks_dict_stays_bounded(tmp_path):
    for index in range(_THREAD_LOCKS_MAX * 3):
        with file_lock(tmp_path / f"file_{index}.json"):
            pass

    assert len(_THREAD_LOCKS) <= _THREAD_LOCKS_MAX


def test_thread_locks_entries_released_after_use(tmp_path):
    with file_lock(tmp_path / "state.json"):
        pass

    users = [entry.users for entry in _THREAD_LOCKS.values()]
    assert all(count == 0 for count in users)


def test_thread_locks_never_evict_a_held_lock(tmp_path):
    """While a lock is held, the dict may exceed the cap rather than evict
    the live entry — mutual exclusion beats memory tidiness."""
    held_path = tmp_path / "held.json"
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def holder() -> None:
        try:
            with file_lock(held_path):
                entered.set()
                release.wait(timeout=10)
        except BaseException as exc:  # pragma: no cover - failure surface
            errors.append(exc)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(timeout=10)
    try:
        held_key = str(held_path.with_name("held.json.lock").resolve())
        for index in range(_THREAD_LOCKS_MAX * 2):
            with file_lock(tmp_path / f"other_{index}.json"):
                pass
        entry = _THREAD_LOCKS.get(held_key)
        assert entry is not None, "held lock must not be evicted"
        assert entry.users == 1
    finally:
        release.set()
        thread.join(timeout=10)
    assert not errors


def test_thread_locks_reuses_entry_for_same_path(tmp_path):
    from narrascape.utils.safe_io import _release_thread_lock_entry, _thread_lock_entry_for

    lock_path = tmp_path / "state.json.lock"
    first = _thread_lock_entry_for(lock_path)
    second = _thread_lock_entry_for(lock_path)
    try:
        assert first is second
        assert first.users == 2
    finally:
        _release_thread_lock_entry(first)
        _release_thread_lock_entry(second)
    assert first.users == 0


def test_file_lock_still_serializes_same_file_access(tmp_path):
    """Cross-thread mutual exclusion is preserved after the refactor."""
    target = tmp_path / "counter.json"
    order: list[str] = []
    first_inside = threading.Event()

    def worker(name: str, hold: bool) -> None:
        with file_lock(target):
            order.append(f"{name}-enter")
            if hold:
                first_inside.set()
                threading.Event().wait(0.2)
            order.append(f"{name}-exit")

    slow = threading.Thread(target=worker, args=("slow", True))
    fast = threading.Thread(target=worker, args=("fast", False))
    slow.start()
    assert first_inside.wait(timeout=10)
    fast.start()
    slow.join(timeout=10)
    fast.join(timeout=10)

    assert order == ["slow-enter", "slow-exit", "fast-enter", "fast-exit"]


def test_release_on_lock_timeout(tmp_path, monkeypatch):
    """A timed-out file_lock must still release its entry refcount."""
    import os

    target = tmp_path / "busy.json"
    real_open = os.open

    def always_exists(path, flags, mode=0o777):
        if str(path).endswith(".lock"):
            raise FileExistsError(str(path))
        return real_open(path, flags, mode)

    monkeypatch.setattr(safe_io.os, "open", always_exists)
    before = dict(_THREAD_LOCKS)

    try:
        with file_lock(target, timeout=0.2, stale_after=10_000):
            pass  # pragma: no cover
    except TimeoutError:
        pass

    key = str(target.with_name("busy.json.lock").resolve())
    entry = _THREAD_LOCKS.get(key)
    if key in before:
        assert entry is before[key]
        assert entry.users == 0
    elif entry is not None:
        assert entry.users == 0
