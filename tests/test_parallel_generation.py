#!/usr/bin/env python3
"""Tests for opt-in per-asset concurrency in generation stages and the
thread-safety of the shared HTTP middleware (token bucket rate limiter)."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

from narrascape.config import NarrascapeConfig, ProjectConfig, Script, TTSConfig
from narrascape.providers.http_client import TokenBucketRateLimiter
from narrascape.stages.base import StageContext
from narrascape.stages.generate_tts import GenerateTTSStage


class TestTokenBucketThreadSafety:
    def test_concurrent_acquire_never_overdraws(self):
        """Concurrent acquire() must never drive the bucket negative.

        Uses a simulated clock: sleepers advance shared time, which lets all
        waiters wake nearly simultaneously — the lock is the only thing
        preventing a check-then-decrement race from over-drawing tokens.
        """
        now = [0.0]
        now_lock = threading.Lock()

        def clock() -> float:
            with now_lock:
                return now[0]

        def sleeper(delay: float) -> None:
            with now_lock:
                now[0] += delay

        limiter = TokenBucketRateLimiter(2.0, burst=1.0, clock=clock, sleeper=sleeper)
        limiter.acquire()  # drain the initial token

        done: list[int] = []
        threads = [
            threading.Thread(target=lambda: (limiter.acquire(), done.append(1))) for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(done) == 4
        assert limiter._tokens >= 0.0

    def test_set_rate_during_acquire_is_safe(self):
        limiter = TokenBucketRateLimiter(0.0)
        threads = [
            threading.Thread(target=limiter.acquire),
            threading.Thread(target=lambda: limiter.set_rate(5.0)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert limiter.rate == 5.0


def _tts_config(tmp_path, *, max_concurrency: int = 1) -> NarrascapeConfig:
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="tts-parallel-test",
            title="TTS Parallel Test",
            script_file="scripts/script.yaml",
        ),
        tts=TTSConfig(max_concurrency=max_concurrency),
        project_dir=tmp_path,
    )
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "script.yaml").write_text(
        "segments:\n"
        "- id: 1\n  text: First segment text.\n"
        "- id: 2\n  text: Second segment text.\n",
        encoding="utf-8",
    )
    return config


def _fake_tts_selection():
    return SimpleNamespace(
        tool=SimpleNamespace(
            name="minimax_tts",
            provider="minimax",
            requires=["MINIMAX_API_KEY"],
            capability=SimpleNamespace(value="tts"),
        ),
        alternatives=[],
        score=1.0,
        reason="test",
    )


def _make_stage(tmp_path, monkeypatch, max_concurrency: int):
    config = _tts_config(tmp_path, max_concurrency=max_concurrency)
    stage = GenerateTTSStage(api_key="fake")
    monkeypatch.setattr(
        "narrascape.stages.generate_tts.select_provider",
        lambda *args, **kwargs: _fake_tts_selection(),
    )
    monkeypatch.setattr("narrascape.stages.generate_tts.get_duration", lambda path: 1.0)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    context = StageContext(config=config, script=Script.model_construct(segments=[]))
    return config, stage, context


def _ok_response() -> dict:
    return {
        "base_resp": {"status_code": 0, "status_msg": "ok"},
        "data": {"audio": b"fakeaudio".hex()},
    }


class TestTTSParallelGeneration:
    def test_segments_generated_concurrently(self, tmp_path, monkeypatch):
        config, stage, context = _make_stage(tmp_path, monkeypatch, max_concurrency=4)
        barrier = threading.Barrier(2)
        call_threads: list[int] = []

        def fake_post(url, payload, *, headers, timeout, max_retries, base_delay):
            call_threads.append(threading.get_ident())
            # Serial execution would break the barrier and fail the segment.
            barrier.wait(timeout=10)
            return _ok_response()

        monkeypatch.setattr(stage._http, "post_json", fake_post)
        result = stage.run(context)

        assert result.success is True
        assert len(call_threads) == 2
        assert len(set(call_threads)) == 2  # actually ran on different threads
        tts_dir = config.tts_dir
        assert (tts_dir / "seg_01.mp3").exists()
        assert (tts_dir / "seg_02.mp3").exists()
        state = json.loads((config.pipeline_dir / "tts_state.json").read_text())
        assert sorted(state["done"]) == [1, 2]
        assert state["errors"] == []
        assert set(state["fingerprints"]) == {"1", "2"}

    def test_default_path_is_serial(self, tmp_path, monkeypatch):
        config, stage, context = _make_stage(tmp_path, monkeypatch, max_concurrency=1)
        call_threads: list[int] = []

        def fake_post(url, payload, *, headers, timeout, max_retries, base_delay):
            call_threads.append(threading.get_ident())
            return _ok_response()

        monkeypatch.setattr(stage._http, "post_json", fake_post)
        result = stage.run(context)

        assert result.success is True
        assert len(call_threads) == 2
        assert len(set(call_threads)) == 1  # same (main) thread
        assert (config.tts_dir / "seg_01.mp3").exists()
        assert (config.tts_dir / "seg_02.mp3").exists()

    def test_cached_segments_skipped_in_parallel_mode(self, tmp_path, monkeypatch):
        config, stage, context = _make_stage(tmp_path, monkeypatch, max_concurrency=4)
        calls: list[str] = []

        def fake_post(url, payload, *, headers, timeout, max_retries, base_delay):
            calls.append(payload["text"])
            return _ok_response()

        monkeypatch.setattr(stage._http, "post_json", fake_post)
        first = stage.run(context)
        assert first.success is True
        assert len(calls) == 2

        # Second run: fingerprints match, no paid calls.
        second = stage.run(context)
        assert second.success is True
        assert len(calls) == 2
