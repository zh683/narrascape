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


def retry_with_backoff(
    func: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError, OSError),
    retry_if: Callable[[Exception], bool] | None = None,
    on_retry: Callable[[Exception, int, float], None] | None = None,
) -> T:
    """Execute a function with exponential backoff retry.

    Args:
        func: The function to execute (should be a lambda or zero-arg callable).
        max_retries: Maximum number of retry attempts (total calls = 1 + max_retries).
        base_delay: Initial delay in seconds between retries.
        max_delay: Maximum delay in seconds between retries.
        retryable_exceptions: Tuple of exception types that should trigger a retry.
        on_retry: Optional callback(error, attempt, next_delay) called before each retry.

    Returns:
        The result of func() on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            if retry_if is not None:
                if not retry_if(e):
                    raise
            elif not isinstance(e, retryable_exceptions):
                raise
            if attempt >= max_retries:
                logger.error(f"All {max_retries} retries exhausted. Last error: {e}")
                raise

            delay = min(base_delay * (2**attempt), max_delay)
            if on_retry:
                on_retry(e, attempt + 1, delay)
            else:
                logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {e}")
            time.sleep(delay)

    raise RuntimeError("retry_with_backoff: unreachable")


RETRYABLE_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


def is_retryable_provider_error(error: Exception) -> bool:
    """Classify transport/provider errors without retrying permanent failures."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRYABLE_HTTP_STATUS
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        status_code = getattr(getattr(error, "response", None), "status_code", None)
    if status_code is not None:
        try:
            return int(status_code) in RETRYABLE_HTTP_STATUS
        except (TypeError, ValueError):
            return False
    if isinstance(error, urllib.error.URLError):
        return True
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    error_name = type(error).__name__.lower()
    return "timeout" in error_name or "connection" in error_name
