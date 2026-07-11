from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

from narrascape.utils import ffmpeg


def test_ffprobe_uses_bounded_default_timeout(monkeypatch, tmp_path: Path):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="1.25\n", stderr=""))
    monkeypatch.setattr(ffmpeg, "find_ffprobe", lambda: Path("ffprobe"))
    monkeypatch.setattr(subprocess, "run", run)

    assert ffmpeg.get_duration(tmp_path / "clip.mp4") == 1.25
    assert run.call_args.kwargs["timeout"] == ffmpeg.DEFAULT_FFPROBE_TIMEOUT


def test_run_ffmpeg_uses_default_timeout_and_atomically_promotes(monkeypatch, tmp_path: Path):
    final_path = tmp_path / "render.mp4"
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["timeout"] = kwargs["timeout"]
        Path(command[-1]).write_bytes(b"valid-media")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(ffmpeg, "validate_video", lambda path: path.read_bytes() == b"valid-media")

    assert ffmpeg.run_ffmpeg(["-i", "source.mp4", str(final_path)], retries=0)
    command = seen["command"]
    assert isinstance(command, list)
    assert Path(command[-1]) != final_path
    assert Path(command[-1]).parent == final_path.parent
    assert seen["timeout"] == ffmpeg.DEFAULT_FFMPEG_TIMEOUT
    assert final_path.read_bytes() == b"valid-media"
    assert not Path(command[-1]).exists()


def test_run_ffmpeg_removes_temporary_output_after_failure(monkeypatch, tmp_path: Path):
    final_path = tmp_path / "failed.mp4"
    temporary: Path | None = None

    def fake_run(command, **_kwargs):
        nonlocal temporary
        temporary = Path(command[-1])
        temporary.write_bytes(b"partial")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert not ffmpeg.run_ffmpeg(["-i", "source.mp4", str(final_path)], retries=0)
    assert temporary is not None
    assert not temporary.exists()
    assert not final_path.exists()
