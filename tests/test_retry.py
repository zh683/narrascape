#!/usr/bin/env python3
"""Tests for retry utility."""

from __future__ import annotations

import io
import time
import urllib.error
from unittest.mock import MagicMock

import pytest

from narrascape.utils.retry import is_retryable_http_error, retry_with_backoff


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.example.com/x", code, "error", {}, io.BytesIO(b""))


class TestIsRetryableHttpError:
    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_permanent_4xx_not_retryable(self, code):
        assert is_retryable_http_error(_http_error(code)) is False

    @pytest.mark.parametrize("code", [408, 429, 500, 502, 503])
    def test_transient_status_retryable(self, code):
        assert is_retryable_http_error(_http_error(code)) is True

    def test_non_http_errors_retryable(self):
        assert is_retryable_http_error(urllib.error.URLError("boom")) is True
        assert is_retryable_http_error(TimeoutError("boom")) is True
        assert is_retryable_http_error(ConnectionError("boom")) is True

    def test_http_error_is_also_url_error(self):
        # HTTPError subclasses URLError; the predicate must distinguish by code.
        assert isinstance(_http_error(404), urllib.error.URLError)
        assert is_retryable_http_error(_http_error(404)) is False


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


class TestRetryableIfPredicate:
    HTTP_EXCEPTIONS = (urllib.error.URLError, urllib.error.HTTPError)

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_permanent_4xx_fails_immediately_without_retry(self, code):
        mock = MagicMock(side_effect=_http_error(code))

        with pytest.raises(urllib.error.HTTPError) as excinfo:
            retry_with_backoff(
                mock,
                max_retries=3,
                base_delay=0.01,
                retryable_exceptions=self.HTTP_EXCEPTIONS,
                retryable_if=is_retryable_http_error,
            )

        assert excinfo.value.code == code
        assert mock.call_count == 1

    @pytest.mark.parametrize("code", [408, 429, 500, 503])
    def test_transient_http_status_is_retried(self, code):
        mock = MagicMock(side_effect=[_http_error(code), _http_error(code), "ok"])

        result = retry_with_backoff(
            mock,
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=self.HTTP_EXCEPTIONS,
            retryable_if=is_retryable_http_error,
        )

        assert result == "ok"
        assert mock.call_count == 3

    def test_url_error_still_retried_with_predicate(self):
        mock = MagicMock(side_effect=[urllib.error.URLError("boom"), "ok"])

        result = retry_with_backoff(
            mock,
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=self.HTTP_EXCEPTIONS,
            retryable_if=is_retryable_http_error,
        )

        assert result == "ok"
        assert mock.call_count == 2

    def test_without_predicate_http_error_retried_as_before(self):
        # Existing callers that do not pass retryable_if keep the old behavior.
        mock = MagicMock(side_effect=[_http_error(400), "ok"])

        result = retry_with_backoff(
            mock,
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=self.HTTP_EXCEPTIONS,
        )

        assert result == "ok"
        assert mock.call_count == 2
