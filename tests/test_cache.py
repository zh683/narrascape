#!/usr/bin/env python3
"""Tests for build cache."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from narrascape.cache import BuildCache


class TestBuildCache:
    def test_compute_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = BuildCache(Path(tmp) / "cache")

            # Create test input file
            input_file = Path(tmp) / "input.txt"
            input_file.write_text("hello world")

            key = cache.compute_key({"input": input_file}, {"zoom": 0.15})
            assert len(key) == 20  # 20-char hex prefix
            assert key == cache.compute_key({"input": input_file}, {"zoom": 0.15})

            # Different content → different key
            input_file.write_text("goodbye world")
            key2 = cache.compute_key({"input": input_file}, {"zoom": 0.15})
            assert key != key2

    def test_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache = BuildCache(cache_dir)

            input_file = Path(tmp) / "input.txt"
            input_file.write_text("test content")
            output_file = Path(tmp) / "output.mp4"
            output_file.write_text("fake video")

            key = cache.compute_key({"input": input_file}, {"version": 1})
            assert cache.get_output(key) is None

            cache.put(key, {"input": input_file}, {"version": 1}, output_file)
            assert cache.get_output(key) == output_file

            # Invalidation
            cache.invalidate(key)
            assert cache.get_output(key) is None
