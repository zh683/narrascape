from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest
from PIL import Image

from narrascape.media_analysis import analyze_audio_samples, analyze_frame_images, analyze_media
from narrascape.utils.ffmpeg import find_ffmpeg, run_ffmpeg_raw


def test_frame_analysis_detects_dark_low_detail_and_frozen_frames():
    frames = [
        Image.new("RGB", (32, 18), color=(0, 0, 0)),
        Image.new("RGB", (32, 18), color=(0, 0, 0)),
        Image.new("RGB", (32, 18), color=(255, 255, 255)),
    ]

    metrics = analyze_frame_images(frames)

    assert metrics["sample_count"] == 3
    assert metrics["dark_frame_ratio"] == pytest.approx(2 / 3)
    assert metrics["low_detail_ratio"] == 1.0
    assert metrics["frozen_pair_ratio"] == 0.5
    assert metrics["mean_luminance"] == pytest.approx(1 / 3, abs=0.01)


def test_changing_solid_colors_are_not_reported_as_frozen():
    frames = [
        Image.new("RGB", (32, 18), color=(20, 20, 20)),
        Image.new("RGB", (32, 18), color=(180, 180, 180)),
    ]

    metrics = analyze_frame_images(frames)

    assert metrics["frozen_pair_ratio"] == 0.0


def test_audio_analysis_measures_rms_peak_clipping_and_silence():
    sample_rate = 8_000
    samples = [int(16_000 * math.sin(2 * math.pi * 440 * i / sample_rate)) for i in range(800)]
    raw = struct.pack(f"<{len(samples)}h", *samples)

    metrics = analyze_audio_samples(raw, sample_rate=sample_rate)

    assert metrics["sample_count"] == 800
    assert metrics["duration_seconds"] == pytest.approx(0.1)
    assert 0.34 < metrics["rms"] < 0.35
    assert 0.48 < metrics["peak"] < 0.49
    assert metrics["clipping_ratio"] == 0.0
    assert metrics["silence_ratio"] < 0.05


def test_audio_analysis_detects_silence_and_clipping():
    raw = struct.pack("<10h", 0, 0, 0, 0, 0, 32_767, -32_768, 0, 0, 0)

    metrics = analyze_audio_samples(raw, sample_rate=10)

    assert metrics["silence_ratio"] == 0.8
    assert metrics["clipping_ratio"] == 0.2


def test_analyze_media_samples_real_frames_and_audio(tmp_path: Path):
    try:
        find_ffmpeg()
    except RuntimeError:
        pytest.skip("ffmpeg is not installed")
    video = tmp_path / "sample.mp4"
    result = run_ffmpeg_raw(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=12:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=8000:duration=2",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        timeout=30,
    )
    assert result.returncode == 0

    report = analyze_media(video, frame_count=6, timeout=30)

    assert report["status"] == "ok"
    assert report["frames"]["sample_count"] == 6
    assert report["frames"]["low_detail_ratio"] < 1.0
    assert report["audio"]["duration_seconds"] == pytest.approx(2.0, abs=0.1)
    assert report["audio"]["rms"] > 0.01
