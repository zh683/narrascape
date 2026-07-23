"""Retry utilities for API calls with exponential backoff.

No external dependencies (e.g. tenacity) — pure stdlib.
"""

from __future__ import annotations

import logging
import time
import urllib.error
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
logger = logging.getLogger("narrascape.retry")

# HTTP status codes that are worth retrying: request timeout and rate limiting.
# Other 4xx responses (400/401/403/404/422/...) are permanent and must fail fast.
RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 429})


def is_retryable_http_error(exc: Exception) -> bool:
    """Return True if an exception raised by an HTTP call is worth retrying.

    Non-HTTP network errors (URLError, TimeoutError, ...) are considered
    transient and retryable. ``urllib.error.HTTPError`` is retryable only for
    status 408, 429, or any 5xx; other 4xx codes are permanent failures.
    """
    if not isinstance(exc, urllib.error.HTTPError):
        return True
    return exc.code in RETRYABLE_HTTP_STATUS_CODES or exc.code >= 500


def retry_with_backoff(
    func: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError, OSError),
    retryable_if: Callable[[Exception], bool] | None = None,
    on_retry: Callable[[Exception, int, float], None] | None = None,
    delay_hint: Callable[[Exception], float | None] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> T:
    """Execute a function with exponential backoff retry.

    Args:
        func: The function to execute (should be a lambda or zero-arg callable).
        max_retries: Maximum number of retry attempts (total calls = 1 + max_retries).
        base_delay: Initial delay in seconds between retries.
        max_delay: Maximum delay in seconds between retries.
        retryable_exceptions: Tuple of exception types that should trigger a retry.
        retryable_if: Optional predicate called with a caught exception; when it
            returns False the exception is re-raised immediately without retrying.
            When None (default), every caught retryable exception is retried.
        on_retry: Optional callback(error, attempt, next_delay) called before each retry.
        delay_hint: Optional callback(error) -> suggested delay in seconds (e.g. a
            server-provided Retry-After). When it returns a value, the actual sleep
            is ``max(computed_backoff, hint)`` so server backpressure is honored for
            real instead of only being logged.
        sleeper: Sleep function (injectable for tests). None (default) resolves
            ``time.sleep`` at call time, so monkeypatching ``time.sleep`` keeps
            working exactly as before this parameter existed.

    Returns:
        The result of func() on success.

    Raises:
        The last exception if all retries are exhausted, or immediately when
        retryable_if rejects the exception.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            if retryable_if is not None and not retryable_if(e):
                raise
            if attempt >= max_retries:
                logger.error(f"All {max_retries} retries exhausted. Last error: {e}")
                raise

            delay = min(base_delay * (2**attempt), max_delay)
            if delay_hint is not None:
                hint = delay_hint(e)
                if hint is not None:
                    delay = max(delay, hint)
            if on_retry:
                on_retry(e, attempt + 1, delay)
            else:
                logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {e}")
            (time.sleep if sleeper is None else sleeper)(delay)

    raise RuntimeError("retry_with_backoff: unreachable")
