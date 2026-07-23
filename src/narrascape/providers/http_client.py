"""Unified HTTP client middleware for paid provider APIs.

All provider HTTP traffic (Seedance/Seedream/MiniMax/Agnes) should go through
``ProviderHttpClient`` instead of hand-rolled urllib blocks in stages. The
middleware centralizes:

- JSON GET/POST with mandatory timeouts and dict-shaped responses
- retry with *real* Retry-After application (via ``delay_hint`` in
  ``utils.retry.retry_with_backoff`` — the server-requested wait is actually
  slept, not merely logged)
- per-provider token-bucket rate limiting (process-local; off by default)
- circuit-breaker classification: only transport/server/persistent-429
  failures are recorded into ``ProviderHealthStore``; client 4xx (auth,
  bad params) and business failures (HTTP 200 with provider status != 0,
  judged by the caller) never count against provider health.

Tests that patch ``urllib.request.urlopen`` globally keep working: the
middleware calls it dynamically at request time.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from narrascape.providers.health import ProviderHealthStore
from narrascape.utils.retry import is_retryable_http_error, retry_with_backoff

logger = logging.getLogger("narrascape.providers.http_client")

# Failure categories for circuit-breaker accounting.
ERROR_CATEGORY_TRANSPORT = "transport"  # no response: DNS/TCP/timeout
ERROR_CATEGORY_RATE_LIMITED = "rate_limited"  # 429 persisted through all retries
ERROR_CATEGORY_SERVER = "server"  # 5xx persisted through all retries
ERROR_CATEGORY_CLIENT = "client"  # other 4xx: auth/params — NOT a provider outage

# Categories that count against provider health (circuit breaker input).
HEALTH_FAILURE_CATEGORIES = frozenset(
    {ERROR_CATEGORY_TRANSPORT, ERROR_CATEGORY_RATE_LIMITED, ERROR_CATEGORY_SERVER}
)


def classify_http_error(exc: Exception) -> str:
    """Classify a failure from an HTTP call for circuit-breaker accounting."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            return ERROR_CATEGORY_RATE_LIMITED
        if exc.code >= 500:
            return ERROR_CATEGORY_SERVER
        return ERROR_CATEGORY_CLIENT
    return ERROR_CATEGORY_TRANSPORT


def retry_after_hint(
    exc: Exception,
    *,
    default_for_429: float | None = None,
    minimum: float = 0.0,
) -> float | None:
    """Extract a server-requested wait from an exception, if any.

    Only meaningful for HTTP 429 responses. The ``Retry-After`` header wins;
    providers that omit it but write "N minute(s)" into the body (Agnes) are
    covered by the body fallback. ``default_for_429`` applies when neither is
    parseable; ``minimum`` floors the result. Returns None for non-429 errors
    (no opinion — caller uses its own backoff).
    """
    if not isinstance(exc, urllib.error.HTTPError) or exc.code != 429:
        return None
    header = exc.headers.get("Retry-After") if exc.headers else None
    if header:
        try:
            return max(minimum, float(header))
        except (TypeError, ValueError):
            pass
    try:
        body = exc.read().decode(errors="ignore")
    except Exception:
        body = ""
    minute_match = re.search(r"(\d+)\s+minute", body, flags=re.IGNORECASE)
    if minute_match:
        # Body only says "N minute(s)" with no seconds granularity; providers
        # using this format bill per-minute, so wait a touch over N minutes.
        return max(minimum, float(minute_match.group(1)) * 65.0)
    if default_for_429 is not None:
        return max(minimum, default_for_429)
    return None


class TokenBucketRateLimiter:
    """Process-local token bucket. rate <= 0 means unlimited (current behavior).

    ``sleeper=None`` resolves ``time.sleep`` at call time so tests that
    monkeypatch ``time.sleep`` globally keep working.
    """

    def __init__(
        self,
        rate_per_second: float,
        *,
        burst: float | None = None,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rate = max(0.0, float(rate_per_second))
        self.capacity = float(burst) if burst else max(1.0, self.rate)
        self._tokens = self.capacity
        self._updated = clock()
        self._sleeper = sleeper
        self._clock = clock

    def set_rate(self, rate_per_second: float) -> None:
        self.rate = max(0.0, float(rate_per_second))
        self.capacity = max(self.capacity, self.rate, 1.0)

    def acquire(self) -> None:
        """Block until one token is available; returns immediately when unlimited."""
        if self.rate <= 0:
            return
        while True:
            now = self._clock()
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self.rate
            logger.debug(f"rate limit: waiting {wait:.2f}s")
            (time.sleep if self._sleeper is None else self._sleeper)(wait)


class ProviderHttpClient:
    """Per-provider HTTP client with retry, Retry-After, rate limit, and health hooks."""

    def __init__(
        self,
        provider: str,
        *,
        rate_per_second: float = 0.0,
        health_store: ProviderHealthStore | None = None,
        health_key: str = "",
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.rate_limiter = TokenBucketRateLimiter(rate_per_second, sleeper=sleeper, clock=clock)
        self.health_store = health_store
        self.health_key = health_key or provider
        self._sleeper = sleeper

    def _sleep(self, delay: float) -> None:
        (time.sleep if self._sleeper is None else self._sleeper)(delay)

    def configure(
        self,
        *,
        rate_per_second: float | None = None,
        health_store: ProviderHealthStore | None = None,
        health_key: str | None = None,
    ) -> None:
        """Apply runtime configuration (called by stages once config/selection is known)."""
        if rate_per_second is not None:
            self.rate_limiter.set_rate(rate_per_second)
        if health_store is not None:
            self.health_store = health_store
        if health_key is not None:
            self.health_key = health_key

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        retryable_exceptions: tuple[type[Exception], ...] = (
            urllib.error.URLError,
            urllib.error.HTTPError,
        ),
        on_retry: Callable[[Exception, int, float], None] | None = None,
    ) -> dict[str, Any]:
        """POST a JSON body and return the parsed JSON object ({} for non-objects)."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        for name, value in headers.items():
            req.add_header(name, value)
        return self.execute_request(
            req,
            timeout=timeout,
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            retryable_exceptions=retryable_exceptions,
            on_retry=on_retry,
        )

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        """Single-shot GET (polling paths). Raises on failure; never retried here."""
        self.rate_limiter.acquire()
        req = urllib.request.Request(url, method="GET")
        for name, value in headers.items():
            req.add_header(name, value)
        return _json_object(
            json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
        )

    def execute_request(
        self,
        req: urllib.request.Request,
        *,
        timeout: float,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        retryable_exceptions: tuple[type[Exception], ...] = (
            urllib.error.URLError,
            urllib.error.HTTPError,
        ),
        on_retry: Callable[[Exception, int, float], None] | None = None,
    ) -> dict[str, Any]:
        """Execute a pre-built Request with rate limiting, retry, and health accounting.

        Retry-After hints from 429 responses override the computed backoff for
        the *actual* sleep. When all retries are exhausted, transport/server/
        persistent-429 failures are recorded into the health store (client 4xx
        is re-raised immediately by the retry predicate and never recorded).
        """
        self.rate_limiter.acquire()
        try:
            return retry_with_backoff(
                lambda: _json_object(
                    json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
                ),
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                retryable_exceptions=retryable_exceptions,
                retryable_if=is_retryable_http_error,
                on_retry=on_retry,
                delay_hint=retry_after_hint,
                sleeper=self._sleep,
            )
        except Exception as exc:
            self._record_health_failure(exc)
            raise

    def _record_health_failure(self, exc: Exception) -> None:
        """Circuit-breaker input: only provider-side failures count."""
        if self.health_store is None:
            return
        category = classify_http_error(exc)
        if category not in HEALTH_FAILURE_CATEGORIES:
            logger.info(
                f"{self.provider}: {category} failure does not count against provider health"
            )
            return
        self.health_store.record_failure(self.health_key, f"{category}: {str(exc)[:400]}")


def _json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
