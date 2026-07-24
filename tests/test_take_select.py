"""Tests for TakeSelectStage deterministic quality scoring.

Covers the ffmpeg frame-analysis scoring that replaced byte-size proxy
scoring, the per-segment fallback chain, take_selection.yaml schema
additions, and the unchanged LLM-judge override priority.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.stages.base import StageContext
from narrascape.stages.take_select import TakeSelectStage
from narrascape.utils.ffmpeg import find_ffmpeg, find_ffprobe, run_ffmpeg
from narrascape.utils.video_quality import (
    average_hash,
    brightness_score,
    duration_score,
    sharpness_score,
    stability_score,
)

try:
    find_ffmpeg()
    find_ffprobe()
    _HAS_FFMPEG = True
except Exception:
    _HAS_FFMPEG = False

requires_ffmpeg = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe not available")


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────


def _config(tmp_path: Path, durations: dict[int, float] | None = None) -> NarrascapeConfig:
    project_dir = tmp_path / "take_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "assets" / "videos").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "Mira studies the machine."},
                    {"id": 2, "text": "The city glimmers beyond the glass."},
                ]
            }
        ),
        encoding="utf-8",
    )
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="take-project",
            title="Take Project",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True, exist_ok=True)
    if durations:
        (config.pipeline_dir / "director_contract.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": "director_contract.v1",
                    "compile_process": {"mode": "deterministic_prompt_compiler"},
                    "shots": [
                        {"segment_id": segment_id, "generation": {"duration": duration}}
                        for segment_id, duration in durations.items()
                    ],
                }
            ),
            encoding="utf-8",
        )
    return config


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(config=config, script=load_script(config.script_path))


def _videos_dir(config: NarrascapeConfig) -> Path:
    return config.project_dir / "assets" / "videos"


def _write_dummy_take(config: NarrascapeConfig, name: str, size: int) -> Path:
    path = _videos_dir(config) / f"{name}.mp4"
    path.write_bytes(b"\0" * size)
    return path


def _lavfi_take(config: NarrascapeConfig, name: str, source: str, *, duration: float) -> Path:
    """Generate a real fixture video with an ffmpeg lavfi source."""
    path = _videos_dir(config) / f"{name}.mp4"
    ok = run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            source,
            "-t",
            str(duration),
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        desc=f"fixture {name}",
        retries=0,
        validate_output=False,
        timeout=60,
    )
    assert ok, f"failed to generate fixture video {name}"
    return path


def _read_selection(config: NarrascapeConfig) -> dict[str, Any]:
    return yaml.safe_load((config.pipeline_dir / "take_selection.yaml").read_text(encoding="utf-8"))


def _fake_analyze(composites: dict[str, float]):
    def fake(path: Path, *, expected_duration: float | None, work_dir: Path) -> dict[str, Any]:
        composite = composites[path.stem]
        return {
            "status": "ok",
            "composite": composite,
            "sharpness": composite,
            "brightness": 100.0,
            "duration_score": 100.0,
            "stability": 100.0,
            "mean_luminance": 120.0,
            "laplacian_variance": 250.0,
            "duration_seconds": 5.0,
            "expected_duration_seconds": expected_duration,
            "frames_analyzed": 3,
        }

    return fake


# ─────────────────────────────────────────────
# Real-ffmpeg scoring ordering
# ─────────────────────────────────────────────


@requires_ffmpeg
def test_quality_signals_rank_takes(tmp_path):
    """clear > blurry > black/short on the relevant sub-scores and composite."""
    config = _config(tmp_path, durations={1: 5.0})
    _lavfi_take(config, "vid_01_take_01", "testsrc2=size=320x180:rate=24", duration=5.0)
    _lavfi_take(
        config,
        "vid_01_take_02",
        "testsrc2=size=320x180:rate=24,gblur=sigma=6",
        duration=5.0,
    )
    _lavfi_take(config, "vid_01_take_03", "color=black:size=320x180:rate=24", duration=5.0)
    _lavfi_take(config, "vid_01_take_04", "testsrc2=size=320x180:rate=24", duration=2.0)
    _lavfi_take(config, "vid_01_take_05", "color=red:size=320x180:rate=24", duration=5.0)

    result = TakeSelectStage().run(_context(config))

    assert result.success
    selection = _read_selection(config)["selections"][0]
    by_take = {item["take"]: item for item in selection["candidates"]}
    clear = by_take["vid_01_take_01"]
    blurry = by_take["vid_01_take_02"]
    black = by_take["vid_01_take_03"]
    short = by_take["vid_01_take_04"]
    frozen = by_take["vid_01_take_05"]

    # Scores are composites on a 0-100 scale, not byte counts.
    for item in selection["candidates"]:
        assert item["score"] == item["quality"]["composite"]
        assert 0.0 <= item["score"] <= 100.0

    # Clear take wins and outranks every degraded variant.
    assert selection["selected_take"] == "vid_01_take_01"
    for degraded in (blurry, black, short, frozen):
        assert clear["score"] > degraded["score"]

    # Each signal fires on its intended defect.
    assert blurry["quality"]["sharpness"] < clear["quality"]["sharpness"]
    assert black["quality"]["brightness"] == 0.0
    assert black["quality"]["mean_luminance"] < 5.0
    assert short["quality"]["duration_score"] == 0.0
    assert short["quality"]["duration_seconds"] == pytest.approx(2.0, abs=0.3)
    assert short["quality"]["expected_duration_seconds"] == 5.0
    assert frozen["quality"]["stability"] == 0.0
    assert clear["quality"]["stability"] == 100.0

    assert selection["scoring"] == "frame_analysis"
    process = _read_selection(config)["selection_process"]
    assert process["quality_signals"] == ["sharpness", "brightness", "duration", "stability"]
    assert process["bytes_fallback_segments"] == []


@requires_ffmpeg
def test_placeholder_style_videos_remain_selectable(tmp_path):
    """Uniform-color placeholder clips must not break selection: all takes get
    low-but-equal scores and the stage still deterministically picks one."""
    config = _config(tmp_path, durations={1: 3.0})
    _lavfi_take(config, "vid_01_take_01", "color=navy:size=320x180:rate=12", duration=3.0)
    _lavfi_take(config, "vid_01_take_02", "color=navy:size=320x180:rate=12", duration=3.0)

    result = TakeSelectStage().run(_context(config))

    assert result.success
    selection = _read_selection(config)["selections"][0]
    assert selection["scoring"] == "frame_analysis"
    assert selection["selected_take"] in {"vid_01_take_01", "vid_01_take_02"}
    scores = {item["score"] for item in selection["candidates"]}
    assert len(scores) == 1  # identical placeholders tie; take_number breaks the tie


# ─────────────────────────────────────────────
# take_selection.yaml schema additions (mocked analysis)
# ─────────────────────────────────────────────


def test_selection_yaml_has_quality_fields_and_keeps_legacy_fields(tmp_path, monkeypatch):
    config = _config(tmp_path, durations={1: 5.0})
    _write_dummy_take(config, "vid_01_take_01", 1000)
    _write_dummy_take(config, "vid_01_take_02", 500)
    monkeypatch.setattr(
        "narrascape.stages.take_select.analyze_take",
        _fake_analyze({"vid_01_take_01": 80.0, "vid_01_take_02": 60.0}),
    )

    result = TakeSelectStage().run(_context(config))

    assert result.success
    artifact = _read_selection(config)
    assert artifact["schema_version"] == "take_selection.v1"
    process = artifact["selection_process"]
    # Legacy process fields unchanged.
    assert process["mode"] == "deterministic_quality_score"
    assert process["llm_status"] == "not_configured"
    # New audit fields.
    assert process["quality_signals"] == ["sharpness", "brightness", "duration", "stability"]
    assert process["bytes_fallback_segments"] == []

    selection = artifact["selections"][0]
    assert selection["segment_id"] == 1
    assert selection["scoring"] == "frame_analysis"
    assert selection["selected_take"] == "vid_01_take_01"
    assert selection["selected_path"] == "assets/videos/vid_01_take_01.mp4"
    assert selection["reason"]

    candidate = selection["candidates"][0]
    # Legacy candidate fields unchanged...
    assert candidate["take"] == "vid_01_take_01"
    assert candidate["path"] == "assets/videos/vid_01_take_01.mp4"
    assert candidate["bytes"] == 1000
    assert candidate["score"] == 80.0
    # ...plus the new quality audit block.
    quality = candidate["quality"]
    assert quality["status"] == "ok"
    assert quality["composite"] == 80.0
    assert quality["frames_analyzed"] == 3
    assert quality["expected_duration_seconds"] == 5.0


# ─────────────────────────────────────────────
# Fallback chain
# ─────────────────────────────────────────────


def test_failed_analysis_falls_back_to_bytes_for_whole_segment(tmp_path, monkeypatch, caplog):
    config = _config(tmp_path)
    _write_dummy_take(config, "vid_01_take_01", 1000)
    _write_dummy_take(config, "vid_01_take_02", 5000)

    def broken_analyze(path: Path, *, expected_duration: float | None, work_dir: Path) -> dict:
        raise RuntimeError("ffmpeg not available")

    monkeypatch.setattr("narrascape.stages.take_select.analyze_take", broken_analyze)

    with caplog.at_level(logging.WARNING, logger="narrascape.stages.take_select"):
        result = TakeSelectStage().run(_context(config))

    assert result.success
    artifact = _read_selection(config)
    selection = artifact["selections"][0]
    assert selection["scoring"] == "bytes_fallback"
    # Byte-size parity with the legacy behavior: bigger file wins.
    assert selection["selected_take"] == "vid_01_take_02"
    scores = {item["take"]: item["score"] for item in selection["candidates"]}
    assert scores == {"vid_01_take_01": 1000.0, "vid_01_take_02": 5000.0}
    for item in selection["candidates"]:
        assert item["quality"] == {"status": "unavailable"}
    assert artifact["selection_process"]["bytes_fallback_segments"] == [1]
    assert "falls back to byte-size scoring" in caplog.text


# ─────────────────────────────────────────────
# Existing business rules preserved
# ─────────────────────────────────────────────


def test_risk_segment_penalty_stacks_on_quality_score(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_dummy_take(config, "vid_01_take_01", 1000)
    (config.pipeline_dir / "render_report.yaml").write_text(
        yaml.safe_dump({"checks": {"continuity_risk_segments": [1]}, "errors": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "narrascape.stages.take_select.analyze_take",
        _fake_analyze({"vid_01_take_01": 50.0}),
    )

    result = TakeSelectStage().run(_context(config))

    assert result.success
    selection = _read_selection(config)["selections"][0]
    assert selection["candidates"][0]["score"] == 49.0


def test_llm_judge_override_priority_unchanged(tmp_path, monkeypatch):
    class _Response:
        def extract_json_safe(self, default: Any = None) -> dict[str, Any]:
            return {"selected_take": "vid_01_take_02", "reason": "stronger story beat"}

    class _FakeLLM:
        def complete(self, prompt: str, **kwargs: Any) -> _Response:
            return _Response()

    config = _config(tmp_path)
    _write_dummy_take(config, "vid_01_take_01", 1000)
    _write_dummy_take(config, "vid_01_take_02", 500)
    monkeypatch.setattr(
        "narrascape.stages.take_select.analyze_take",
        _fake_analyze({"vid_01_take_01": 80.0, "vid_01_take_02": 60.0}),
    )

    result = TakeSelectStage(llm_client=_FakeLLM()).run(_context(config))

    assert result.success
    artifact = _read_selection(config)
    selection = artifact["selections"][0]
    # The deterministic favorite is take_01, but the LLM judge still wins.
    assert selection["selected_take"] == "vid_01_take_02"
    assert selection["reason"] == "stronger story beat"
    assert artifact["selection_process"]["mode"] == "qa_plus_llm"
    assert artifact["selection_process"]["llm_status"] == "used"


# ─────────────────────────────────────────────
# Signal unit tests (no ffmpeg needed)
# ─────────────────────────────────────────────


def test_sharpness_score_log_scale():
    assert sharpness_score(0.0) == 0.0
    assert sharpness_score(1000.0) == 100.0
    assert sharpness_score(5000.0) == 100.0
    assert 0.0 < sharpness_score(20.0) < 100.0


def test_brightness_score_ramp():
    assert brightness_score(0.0) == 0.0
    assert brightness_score(8.0) == 0.0
    assert brightness_score(48.0) == 100.0
    assert brightness_score(120.0) == 100.0
    assert brightness_score(28.0) == 50.0


def test_duration_score_tolerance():
    assert duration_score(5.0, 5.0) == 100.0
    assert duration_score(4.5, 5.0) == 80.0
    assert duration_score(2.0, 5.0) == 0.0
    assert duration_score(8.0, 5.0) == 0.0
    # No contract expectation -> neutral.
    assert duration_score(2.0, None) == 100.0
    assert duration_score(0.0, 5.0) == 100.0


def test_stability_score_frozen_pairs():
    assert stability_score([]) == 100.0
    assert stability_score(["1010"]) == 100.0
    assert stability_score(["1010", "1010", "1010"]) == 0.0
    assert stability_score(["1010", "0101", "1111"]) == 100.0


def test_average_hash_shape():
    from PIL import Image

    image = Image.new("L", (16, 16), color=200)
    digest = average_hash(image)
    assert len(digest) == 64
    assert set(digest) <= {"0", "1"}


def test_expected_durations_parsing():
    stage = TakeSelectStage()
    contract = {
        "shots": [
            {"segment_id": 1, "generation": {"duration": 5.0}},
            {"segment_id": 2, "generation": {"duration": "not-a-number"}},
            {"segment_id": 3},
            "not-a-shot",
        ]
    }

    assert stage._expected_durations(contract) == {1: 5.0}
    assert stage._expected_durations({}) == {}
