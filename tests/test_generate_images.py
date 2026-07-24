#!/usr/bin/env python3
"""Regression tests for the generate_images stage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from narrascape.stages.generate_images import GenerateImagesStage


def _patch_successful_api(stage: GenerateImagesStage, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        stage,
        "_post_image_request",
        lambda req, *, provider: {"data": [{"url": "https://example.com/img.jpg"}]},
    )


class TestGenerateOneFailurePath:
    def test_download_failure_returns_false_without_raising(self, tmp_path, monkeypatch):
        """Failed downloads must return False cleanly.

        Regression: the finally block used to call out_png.stat() after the
        except handler had deleted out_png, raising FileNotFoundError and
        masking the intended `return False`.
        """
        stage = GenerateImagesStage(api_key="test-key")
        _patch_successful_api(stage, monkeypatch)

        def boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("network down")

        monkeypatch.setattr("narrascape.stages.generate_images.download_to_path", boom)

        ok = stage._generate_one("a prompt", "img_01", "1024x1024", None, tmp_path)

        assert ok is False
        assert not (tmp_path / "img_01.png").exists()
        assert not (tmp_path / "_tmp_img_01.jpg").exists()

    def test_ffmpeg_failure_returns_false_without_raising(self, tmp_path, monkeypatch):
        stage = GenerateImagesStage(api_key="test-key")
        _patch_successful_api(stage, monkeypatch)

        def fake_download(url: str, dest: Path, **kwargs: Any) -> None:
            dest.write_bytes(b"\xff\xd8" + b"0" * 200)

        monkeypatch.setattr("narrascape.stages.generate_images.download_to_path", fake_download)
        monkeypatch.setattr(
            "narrascape.stages.generate_images.run_ffmpeg_raw",
            lambda args, timeout=60: SimpleNamespace(returncode=1, stderr="boom"),
        )

        ok = stage._generate_one("a prompt", "img_02", "1024x1024", None, tmp_path)

        assert ok is False
        assert not (tmp_path / "img_02.png").exists()

    def test_success_still_logs_size_and_returns_true(self, tmp_path, monkeypatch, caplog):
        """Success path behavior (including the OK <size>KB log) is unchanged."""
        stage = GenerateImagesStage(api_key="test-key")
        _patch_successful_api(stage, monkeypatch)

        def fake_download(url: str, dest: Path, **kwargs: Any) -> None:
            dest.write_bytes(b"\xff\xd8" + b"0" * 200)

        def fake_ffmpeg(args: list[str], timeout: int = 60) -> Any:
            Path(args[-1]).write_bytes(b"\x89PNG" + b"0" * 2048)
            return SimpleNamespace(returncode=0, stderr="")

        monkeypatch.setattr("narrascape.stages.generate_images.download_to_path", fake_download)
        monkeypatch.setattr("narrascape.stages.generate_images.run_ffmpeg_raw", fake_ffmpeg)

        with caplog.at_level("INFO", logger="narrascape.stages.generate_images"):
            ok = stage._generate_one("a prompt", "img_03", "1024x1024", None, tmp_path)

        assert ok is True
        assert (tmp_path / "img_03.png").exists()
        assert not (tmp_path / "_tmp_img_03.jpg").exists()
        assert any(record.message.startswith("OK ") for record in caplog.records)
