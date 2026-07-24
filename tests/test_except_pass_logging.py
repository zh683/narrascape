"""Previously-silent `except Exception: pass` sites now log.

Covers the two QA-stage sites (warning level — QA swallowing errors is the
most dangerous): the temp-frame cleanup in _media_average_hash and the
image_gen_state.json parse in _detect_placeholder_residue. Behavior is
unchanged; only logging is added.
"""

import logging
from pathlib import Path

from narrascape.config import NarrascapeConfig, ProjectConfig, Script, ScriptSegment
from narrascape.stages.base import StageContext
from narrascape.stages.qa import QAStage


def _make_context(tmp_path: Path) -> StageContext:
    config = NarrascapeConfig(
        project=ProjectConfig(name="qa-log-test", title="QA Log Test", script_file="s/script.yaml"),
        project_dir=tmp_path,
    )
    config.pipeline_dir.mkdir(parents=True, exist_ok=True)
    script = Script(segments=[ScriptSegment(id=1, text="")])
    return StageContext(config=config, script=script, state={}, dry_run=False)


def test_placeholder_residue_parse_failure_logs_warning_and_returns_false(tmp_path, caplog):
    context = _make_context(tmp_path)
    state_path = context.config.pipeline_dir / "image_gen_state.json"
    state_path.write_text("{ not valid json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="narrascape.stages.qa"):
        result = QAStage()._detect_placeholder_residue(context)

    assert result is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("placeholder-residue" in r.getMessage() for r in warnings)


def test_placeholder_residue_valid_local_image_still_detected(tmp_path, caplog):
    context = _make_context(tmp_path)
    state_path = context.config.pipeline_dir / "image_gen_state.json"
    state_path.write_text('{"provider_selection": {"name": "local_image"}}', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="narrascape.stages.qa"):
        result = QAStage()._detect_placeholder_residue(context)

    assert result is True
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_temp_frame_cleanup_failure_logs_warning_and_still_returns(tmp_path, caplog, monkeypatch):
    """A failing temp-frame unlink must not change the return value."""
    stage = QAStage()
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")

    class _Completed:
        returncode = 0

    def fake_ffmpeg(args, **_kwargs):
        # Emulate ffmpeg producing the extracted frame
        Path(args[-1]).write_bytes(b"frame")
        return _Completed()

    monkeypatch.setattr("narrascape.stages.qa.run_ffmpeg_raw", fake_ffmpeg)

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name.endswith(".qa-frame.jpg"):
            raise OSError("locked by another process")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    # Image.open on bogus bytes raises -> hash is None; cleanup failure must
    # only add a warning, not change that outcome.
    with caplog.at_level(logging.WARNING, logger="narrascape.stages.qa"):
        result = stage._media_average_hash(video)

    assert result is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("QA temp frame" in r.getMessage() for r in warnings)


def test_temp_frame_cleanup_success_logs_no_warning(tmp_path, caplog, monkeypatch):
    stage = QAStage()
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")

    class _Completed:
        returncode = 0

    def fake_ffmpeg(args, **_kwargs):
        Path(args[-1]).write_bytes(b"frame")
        return _Completed()

    monkeypatch.setattr("narrascape.stages.qa.run_ffmpeg_raw", fake_ffmpeg)

    with caplog.at_level(logging.WARNING, logger="narrascape.stages.qa"):
        result = stage._media_average_hash(video)

    assert result is None  # bogus frame bytes still produce no hash
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not (tmp_path / "clip.qa-frame.jpg").exists()
