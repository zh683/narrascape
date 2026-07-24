from __future__ import annotations

from pathlib import Path

from narrascape.cache import BuildCache
from narrascape.config import EndingConfig, NarrascapeConfig, ProjectConfig, Script, ScriptSegment
from narrascape.stages.base import StageContext


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(
        config=config,
        script=Script(segments=[ScriptSegment(id=1, text="A single shot.")]),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )


def _config(tmp_path: Path, *, name: str) -> NarrascapeConfig:
    project_dir = tmp_path / name
    return NarrascapeConfig(
        project=ProjectConfig(
            name=name,
            title=name.replace("-", " ").title(),
            script_file="scripts/script.yaml",
        ),
        ending=EndingConfig(enabled=False),
        project_dir=project_dir,
    )


def test_concat_stage_fallback_uses_atomic_copy_file(tmp_path, monkeypatch):
    from narrascape.stages.concat import ConcatStage

    config = _config(tmp_path, name="concat-copy-test")
    segment_path = config.pipeline_dir / "video_segments" / "seg_01.mp4"
    segment_path.parent.mkdir(parents=True)
    segment_path.write_bytes(b"segment")
    copies: list[tuple[Path, Path]] = []

    def fake_validate_video(path):
        return Path(path).exists()

    def fake_run_ffmpeg(args, desc, validate_output=True):
        Path(args[-1]).write_bytes(b"body")
        return True

    def fake_atomic_copy_file(source, path):
        copies.append((Path(source), Path(path)))
        Path(path).write_bytes(Path(source).read_bytes())

    monkeypatch.setattr("narrascape.stages.concat.validate_video", fake_validate_video)
    monkeypatch.setattr("narrascape.stages.concat.run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr("narrascape.utils.ffmpeg.get_duration", lambda path: 1.0)
    monkeypatch.setattr("narrascape.stages.concat.atomic_copy_file", fake_atomic_copy_file)

    result = ConcatStage().run(_context(config))

    assert result.success is True
    assert copies == [
        (config.pipeline_dir / "body_concat.mp4", config.pipeline_dir / "final_nosub.mp4")
    ]


def test_audio_stage_alignment_uses_atomic_copy_file(tmp_path, monkeypatch):
    from narrascape.stages.audio import AudioStage

    config = _config(tmp_path, name="audio-copy-test")
    config.pipeline_dir.mkdir(parents=True)
    final_video = config.pipeline_dir / "final_nosub.mp4"
    mixed_audio = config.pipeline_dir / "mixed_audio.mp3"
    final_video.write_bytes(b"video")
    mixed_audio.write_bytes(b"mixed-audio")
    copies: list[tuple[Path, Path]] = []

    def fake_duration(path):
        return 5.0 if Path(path).suffix == ".mp4" else 10.0

    def fake_atomic_copy_file(source, path):
        copies.append((Path(source), Path(path)))
        Path(path).write_bytes(Path(source).read_bytes())

    def fake_run_ffmpeg(args, desc, validate_output=True):
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_bytes(b"clean")
        return True

    monkeypatch.setattr("narrascape.stages.audio.get_duration", fake_duration)
    monkeypatch.setattr("narrascape.stages.audio.atomic_copy_file", fake_atomic_copy_file)
    monkeypatch.setattr("narrascape.stages.audio.run_ffmpeg", fake_run_ffmpeg)

    result = AudioStage().run(_context(config))

    assert result.success is True
    assert copies == [
        (config.pipeline_dir / "mixed_audio.mp3", config.pipeline_dir / "mixed_audio_aligned.mp3")
    ]
