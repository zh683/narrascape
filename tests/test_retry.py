#!/usr/bin/env python3
"""Tests for retry utility."""

from __future__ import annotations

import time
import urllib.error
from unittest.mock import MagicMock

import pytest

from narrascape.utils.retry import is_retryable_provider_error, retry_with_backoff


class TestRetryWithBackoff:
    def test_success_on_first_try(self):
        mock = MagicMock(return_value="success")
        result = retry_with_backoff(mock, max_retries=3, base_delay=0.01)
        assert result == "success"
        assert mock.call_count == 1

    def test_success_after_retries(self):
        mock = MagicMock(side_effect=[RuntimeError("fail1"), RuntimeError("fail2"), "success"])
        result = retry_with_backoff(
            mock,
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(RuntimeError,),
        )
        assert result == "success"
        assert mock.call_count == 3

    def test_exhausts_all_retries(self):
        mock = MagicMock(side_effect=RuntimeError("always fails"))
        with pytest.raises(RuntimeError, match="always fails"):
            retry_with_backoff(
                mock,
                max_retries=2,
                base_delay=0.01,
                retryable_exceptions=(RuntimeError,),
            )
        assert mock.call_count == 3  # initial + 2 retries

    def test_non_retryable_exception_fails_immediately(self):
        mock = MagicMock(side_effect=ValueError("bad input"))
        with pytest.raises(ValueError, match="bad input"):
            retry_with_backoff(
                mock,
                max_retries=3,
                base_delay=0.01,
                retryable_exceptions=(RuntimeError,),  # ValueError not included
            )
        assert mock.call_count == 1

    def test_on_retry_callback(self):
        mock = MagicMock(side_effect=[RuntimeError("fail1"), "success"])
        callback_calls = []

        def on_retry(err, attempt, delay):
            callback_calls.append((type(err).__name__, attempt, delay))

        result = retry_with_backoff(
            mock,
            max_retries=3,
            base_delay=0.05,
            retryable_exceptions=(RuntimeError,),
            on_retry=on_retry,
        )
        assert result == "success"
        assert len(callback_calls) == 1
        assert callback_calls[0][0] == "RuntimeError"
        assert callback_calls[0][1] == 1

    def test_delay_caps_at_max(self):
        # With base=1.0 and max=1.5, attempt 2 would be 4.0s but capped to 1.5s
        start = time.monotonic()
        mock = MagicMock(side_effect=[RuntimeError("fail"), "success"])
        retry_with_backoff(
            mock,
            max_retries=1,
            base_delay=0.1,
            max_delay=0.15,
            retryable_exceptions=(RuntimeError,),
        )
        elapsed = time.monotonic() - start
        # Should be ~0.15s, not 0.2s
        assert elapsed < 0.3

    def test_zero_retries_attempts_once(self):
        mock = MagicMock(side_effect=RuntimeError("once"))

        with pytest.raises(RuntimeError, match="once"):
            retry_with_backoff(
                mock,
                max_retries=0,
                base_delay=0.01,
                retryable_exceptions=(RuntimeError,),
            )

        assert mock.call_count == 1

    def test_none_return_is_success(self):
        mock = MagicMock(return_value=None)

        result = retry_with_backoff(mock, max_retries=3, base_delay=0.01)

        assert result is None
        assert mock.call_count == 1

    @pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
    def test_retryable_provider_http_statuses(self, status):
        error = urllib.error.HTTPError("https://provider.test", status, "failed", {}, None)

        assert is_retryable_provider_error(error) is True

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_permanent_provider_http_statuses_are_not_retryable(self, status):
        error = urllib.error.HTTPError("https://provider.test", status, "failed", {}, None)

        assert is_retryable_provider_error(error) is False

    @pytest.mark.parametrize(
        "error",
        [
            TimeoutError("timeout"),
            urllib.error.URLError(TimeoutError("timeout")),
            ConnectionError("connection reset"),
        ],
    )
    def test_network_failures_are_retryable(self, error):
        assert is_retryable_provider_error(error) is True

    def test_retry_predicate_stops_on_permanent_error(self):
        permanent = urllib.error.HTTPError("https://provider.test", 401, "unauthorized", {}, None)
        mock = MagicMock(side_effect=permanent)

        with pytest.raises(urllib.error.HTTPError):
            retry_with_backoff(
                mock,
                max_retries=3,
                base_delay=0,
                retry_if=is_retryable_provider_error,
            )

        assert mock.call_count == 1

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(429, True), (503, True), (401, False), (422, False)],
    )
    def test_provider_sdk_status_code_is_classified(self, status, expected):
        class SDKError(Exception):
            def __init__(self):
                self.status_code = status

        assert is_retryable_provider_error(SDKError()) is expected

    def test_provider_sdk_response_status_is_classified(self):
        class Response:
            status_code = 429

        class SDKError(Exception):
            response = Response()

        assert is_retryable_provider_error(SDKError()) is True

    def test_provider_sdk_timeout_error_name_is_retryable(self):
        APITimeoutError = type("APITimeoutError", (Exception,), {})

        assert is_retryable_provider_error(APITimeoutError("timed out")) is True
