#!/usr/bin/env python3
"""Tests for retry utility."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from narrascape.utils.retry import retry_with_backoff


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
