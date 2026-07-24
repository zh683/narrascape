#!/usr/bin/env python3
"""Tests for the unified provider HTTP client middleware."""

from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace

from narrascape.providers.health import ProviderHealthStore
from narrascape.providers.http_client import (
    ProviderHttpClient,
    TokenBucketRateLimiter,
    classify_http_error,
    retry_after_hint,
)
from narrascape.stages.generate_video import GenerateVideoStage


def _http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("https://api.example.com/x", code, "err", headers, None)


def _ok_response(payload):
    return SimpleNamespace(read=lambda: json.dumps(payload).encode())


class TestClassifyHttpError:
    def test_categories(self):
        assert classify_http_error(_http_error(429)) == "rate_limited"
        assert classify_http_error(_http_error(500)) == "server"
        assert classify_http_error(_http_error(503)) == "server"
        assert classify_http_error(_http_error(400)) == "client"
        assert classify_http_error(_http_error(401)) == "client"
        assert classify_http_error(urllib.error.URLError("down")) == "transport"
        assert classify_http_error(TimeoutError("slow")) == "transport"


class TestRetryAfterHint:
    def test_header_wins(self):
        assert retry_after_hint(_http_error(429, retry_after="90")) == 90.0

    def test_minimum_floors_header(self):
        assert retry_after_hint(_http_error(429, retry_after="5"), minimum=65.0) == 65.0

    def test_default_for_unparseable_429(self):
        assert retry_after_hint(_http_error(429), default_for_429=65.0) == 65.0

    def test_no_hint_without_default(self):
        assert retry_after_hint(_http_error(429)) is None

    def test_non_429_has_no_hint(self):
        assert retry_after_hint(_http_error(500)) is None
        assert retry_after_hint(urllib.error.URLError("down")) is None


class TestProviderHttpClient:
    def _client(self, sleeps, **kwargs):
        kwargs.setdefault("sleeper", lambda s: sleeps.append(s))
        return ProviderHttpClient("test_provider", **kwargs)

    def test_post_json_success(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen", lambda req, timeout=None: _ok_response({"id": "t-1"})
        )
        client = self._client([])
        assert client.post_json("https://x", {"a": 1}, headers={}, timeout=5) == {"id": "t-1"}

    def test_retry_after_actually_slept(self, monkeypatch):
        """A 429 with Retry-After: 90 must sleep ~90s for real, not the 2s backoff."""
        calls = []
        sleeps = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            if len(calls) == 1:
                raise _http_error(429, retry_after="90")
            return _ok_response({"id": "t-1"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        client = self._client(sleeps)

        assert client.post_json("https://x", {}, headers={}, timeout=5, base_delay=2.0) == {
            "id": "t-1"
        }
        assert sleeps == [90.0]

    def test_429_exhaustion_records_health_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(_http_error(429, retry_after="1")),
        )
        store = ProviderHealthStore(tmp_path / "health.json")
        client = self._client([], health_store=store, health_key="tool-x")

        try:
            client.post_json("https://x", {}, headers={}, timeout=5, max_retries=1)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError:
            pass

        assert store.snapshot()["tool-x"].failure_count == 1

    def test_server_5xx_exhaustion_records_health_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(_http_error(500)),
        )
        store = ProviderHealthStore(tmp_path / "health.json")
        client = self._client([], health_store=store, health_key="tool-x")

        try:
            client.post_json("https://x", {}, headers={}, timeout=5, max_retries=1)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError:
            pass

        assert store.snapshot()["tool-x"].failure_count == 1

    def test_transport_error_records_health_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("refused")),
        )
        store = ProviderHealthStore(tmp_path / "health.json")
        client = self._client([], health_store=store, health_key="tool-x")

        try:
            client.post_json("https://x", {}, headers={}, timeout=5, max_retries=1)
            raise AssertionError("expected URLError")
        except urllib.error.URLError:
            pass

        assert store.snapshot()["tool-x"].failure_count == 1

    def test_client_4xx_never_records_health_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(_http_error(401)),
        )
        store = ProviderHealthStore(tmp_path / "health.json")
        sleeps = []
        client = self._client(sleeps, health_store=store, health_key="tool-x")

        try:
            client.post_json("https://x", {}, headers={}, timeout=5, max_retries=3)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError:
            pass

        assert store.snapshot() == {}  # auth/param errors are not provider outages
        assert sleeps == []  # 4xx fails fast without retrying

    def test_success_does_not_touch_health_store(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen", lambda req, timeout=None: _ok_response({"ok": True})
        )
        store = ProviderHealthStore(tmp_path / "health.json")
        store.record_failure("tool-x", "earlier outage")
        client = self._client([], health_store=store, health_key="tool-x")

        client.post_json("https://x", {}, headers={}, timeout=5)

        # 中间件只上报失败；清零仍由 stage 的 record_provider_success 负责
        assert store.snapshot()["tool-x"].failure_count == 1


class TestTokenBucketRateLimiter:
    def test_unlimited_by_default(self):
        TokenBucketRateLimiter(0.0).acquire()  # returns immediately, no error

    def test_bucket_enforces_rate(self):
        sleeps = []
        now = [0.0]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        limiter = TokenBucketRateLimiter(2.0, burst=1.0, sleeper=fake_sleep, clock=lambda: now[0])
        limiter.acquire()  # initial token, no wait
        limiter.acquire()  # waits 0.5s
        limiter.acquire()  # waits 0.5s
        assert sleeps == [0.5, 0.5]

    def test_burst_allows_initial_burst(self):
        sleeps = []
        now = [0.0]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        limiter = TokenBucketRateLimiter(1.0, burst=3.0, sleeper=fake_sleep, clock=lambda: now[0])
        for _ in range(3):
            limiter.acquire()
        assert sleeps == []  # burst capacity covers all three
        limiter.acquire()
        assert sleeps == [1.0]


class TestPollRateLimitExemption:
    def test_poll_task_429_waits_and_does_not_count_as_error(self, monkeypatch):
        """429s during polling must not consume the consecutive-error budget."""
        stage = GenerateVideoStage(api_key="fake", poll_interval=0)
        stage.max_poll_errors = 2  # would abort on the 2nd 429 if they counted
        sleeps = []
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            if len(calls) <= 2:
                raise _http_error(429, retry_after="3")
            return _ok_response({"status": "succeeded", "content": {"video_url": "https://v"}})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        assert stage._poll_task("task-1") == "https://v"
        assert len(calls) == 3
        assert sleeps and max(sleeps) >= 3.0  # Retry-After honored for the wait

    def test_poll_task_real_errors_still_abort(self, monkeypatch):
        stage = GenerateVideoStage(api_key="fake", poll_interval=0)
        stage.max_poll_errors = 2

        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (_ for _ in ()).throw(_http_error(500)),
        )
        monkeypatch.setattr("time.sleep", lambda s: None)

        assert stage._poll_task("task-1") is None

    def test_agnes_create_retry_after_actually_slept(self, monkeypatch):
        """The Agnes 429 Retry-After is now applied to the real sleep, not just logged."""
        stage = GenerateVideoStage(api_key="fake")
        sleeps = []
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            if len(calls) == 1:
                raise _http_error(429, retry_after="90")
            return _ok_response({"task_id": "t", "video_id": "v"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

        task_id, video_id = stage._create_agnes_task("p", "agnes-video-v2.0", "720p", None, None)

        assert (task_id, video_id) == ("t", "v")
        assert sleeps == [90.0]  # max(65 computed, 90 hint) — previously only logged
