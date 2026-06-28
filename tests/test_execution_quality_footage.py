from __future__ import annotations

import json
from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import (
    AudioConfig,
    BGMMap,
    BGMZone,
    ImageConfig,
    ImageProvider,
    MusicAudioConfig,
    MusicProvider,
    NarrascapeConfig,
    ProjectConfig,
    TTSConfig,
    TTSProvider,
)
from narrascape.stages.base import StageContext


def _write_minimal_project(project_dir: Path) -> None:
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump({"segments": [{"id": 1, "text": "A field recording begins."}]}),
        encoding="utf-8",
    )
    (project_dir / "image_prompts.yaml").write_text(
        yaml.safe_dump(
            {
                "prompts": [
                    {
                        "id": "img_01",
                        "shot_type": "medium",
                        "description": "A documentary image of the subject.",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(
            {
                "project_title": "Provider Test",
                "segments": [
                    {
                        "segment_id": 1,
                        "shot_type": "medium",
                        "image_prompt": "A documentary image of the subject.",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _config(tmp_path: Path, *, bgm: bool = False) -> NarrascapeConfig:
    project_dir = tmp_path / "project"
    _write_minimal_project(project_dir)
    bgm_map = (
        BGMMap(
            zones=[
                BGMZone(
                    id="zone_a",
                    covers=[1, 1],
                    label="Zone A",
                    prompt="quiet pulse",
                    min_duration=10,
                )
            ]
        )
        if bgm
        else BGMMap()
    )
    return NarrascapeConfig(
        project=ProjectConfig(
            name="project",
            title="Provider Test",
            script_file="scripts/script.yaml",
        ),
        images=ImageConfig(provider=ImageProvider.LOCAL, width=640, height=480),
        tts=TTSConfig(provider=TTSProvider.LOCAL),
        audio=AudioConfig(music=MusicAudioConfig(provider=MusicProvider.LOCAL)),
        bgm_map=bgm_map,
        project_dir=project_dir,
    )


def _context(config: NarrascapeConfig) -> StageContext:
    from narrascape.config import load_script

    return StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )


def test_generate_images_executes_provider_selected_by_selector(tmp_path):
    from narrascape.stages.generate_images import GenerateImagesStage

    config = _config(tmp_path)
    result = GenerateImagesStage(api_key=None).run(_context(config))

    assert result.success
    assert result.metadata["provider_selection"]["name"] == "local_image"
    state = json.loads((config.pipeline_dir / "image_gen_state.json").read_text(encoding="utf-8"))
    assert state["provider_selection"]["name"] == "local_image"


def test_generate_images_reports_empty_prompt_file_as_stage_failure(tmp_path):
    from narrascape.stages.generate_images import GenerateImagesStage

    config = _config(tmp_path)
    (config.project_dir / "image_prompts.yaml").write_text("", encoding="utf-8")

    result = GenerateImagesStage(api_key=None).run(_context(config))

    assert not result.success
    assert "No prompts" in result.message


def test_provider_selector_uses_health_circuit_breaker(tmp_path):
    from narrascape.providers import record_provider_failure, select_provider

    config = _config(tmp_path)
    config.images.provider = ImageProvider.SEEDREAM
    for _ in range(3):
        record_provider_failure(config, "seedream_image", "temporary outage")

    selection = select_provider(config, "image_generation", intent="creative")

    assert selection.tool.name == "local_image"


def test_provider_health_store_merges_failure_updates_under_lock(tmp_path):
    from narrascape.providers.health import ProviderHealthStore

    path = tmp_path / "provider_health.json"
    first = ProviderHealthStore(path)
    second = ProviderHealthStore(path)

    first.record_failure("seedream_image", "first")
    state = second.record_failure("seedream_image", "second")

    assert state.failure_count == 2
    snapshot = first.snapshot()
    assert snapshot["seedream_image"].failure_count == 2
    assert snapshot["seedream_image"].last_error == "second"


def test_generate_video_failure_records_provider_health(tmp_path, monkeypatch):
    from narrascape.providers.health import health_store_for_project
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    config.pipeline_dir.mkdir(parents=True)
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"not a real png")
    stage = GenerateVideoStage(api_key="fake", sleep_between=0)
    monkeypatch.setattr(stage, "_resolve_first_frame", lambda *args, **kwargs: None)
    monkeypatch.setattr(stage, "_generate_one", lambda *args, **kwargs: False)

    result = stage.run(_context(config))

    assert not result.success
    health = health_store_for_project(config.project_dir).snapshot()
    assert health["seedance_video"].failure_count == 1


def test_ffmpeg_media_args_resolve_dash_prefixed_paths(tmp_path):
    from narrascape.utils.ffmpeg import _normalize_ffmpeg_args, safe_media_arg

    media = tmp_path / "-clip.mp4"
    media.write_bytes(b"video")
    out = tmp_path / "-out.mp4"

    assert safe_media_arg(media) == str(media.resolve())
    args = _normalize_ffmpeg_args(["-i", str(media), "-c", "copy", str(out)])
    assert args[1] == str(media.resolve())
    assert args[-1] == str(out.resolve())

    relative_args = _normalize_ffmpeg_args(["-i", "-clip.mp4", "-c", "copy", "-out.mp4"])
    assert Path(relative_args[1]).is_absolute()
    assert Path(relative_args[-1]).is_absolute()


def test_get_duration_rejects_non_numeric_ffprobe_duration(tmp_path, monkeypatch):
    import subprocess

    import pytest

    from narrascape.utils.ffmpeg import get_duration

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    monkeypatch.setattr("narrascape.utils.ffmpeg.find_ffprobe", lambda: tmp_path / "ffprobe")
    monkeypatch.setattr(
        "narrascape.utils.ffmpeg.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="N/A\n", stderr=""),
    )

    with pytest.raises(RuntimeError, match="invalid ffprobe duration"):
        get_duration(media)


def test_generate_tts_executes_provider_selected_by_selector(tmp_path, monkeypatch):
    from narrascape.stages.generate_tts import GenerateTTSStage

    config = _config(tmp_path)
    stage = GenerateTTSStage(api_key=None)
    monkeypatch.setattr(
        stage, "_generate_local_tone", lambda out, duration, seg_id: out.write_bytes(b"tone")
    )

    result = stage.run(_context(config))

    assert result.success
    assert result.metadata["provider_selection"]["name"] == "local_tts"
    state = json.loads((config.pipeline_dir / "tts_state.json").read_text(encoding="utf-8"))
    assert state["provider_selection"]["name"] == "local_tts"


def test_generate_music_executes_provider_selected_by_selector(tmp_path, monkeypatch):
    from narrascape.stages.generate_music import GenerateMusicStage

    config = _config(tmp_path, bgm=True)
    config.pipeline_dir.mkdir(parents=True)
    (config.pipeline_dir / "timing.json").write_text(json.dumps({"1": 4.0}), encoding="utf-8")
    stage = GenerateMusicStage(api_key=None)
    monkeypatch.setattr(
        stage, "_generate_local_music", lambda out, duration, index: out.write_bytes(b"music")
    )

    result = stage.run(_context(config))

    assert result.success
    assert result.metadata["provider_selection"]["name"] == "local_music"
    state = json.loads((config.pipeline_dir / "bgm_state.json").read_text(encoding="utf-8"))
    assert state["provider_selection"]["name"] == "local_music"


def test_generate_video_checks_selected_provider_requirements(tmp_path):
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"not a real png")

    can_run, reason = GenerateVideoStage(api_key=None).can_run(_context(config))

    assert not can_run
    assert "seedance_video" in reason
    assert "ARK_API_KEY" in reason


def test_generate_video_accepts_pipeline_design_report(tmp_path):
    from narrascape.stages.generate_video import GenerateVideoStage

    config = _config(tmp_path)
    root_report = config.project_dir / "design_report.yaml"
    config.pipeline_dir.mkdir(parents=True)
    (config.pipeline_dir / "design_report.yaml").write_text(
        root_report.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    root_report.unlink()
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"not a real png")

    can_run, reason = GenerateVideoStage(api_key=None).can_run(_context(config))

    assert not can_run
    assert "ARK_API_KEY" in reason
    assert "design_report.yaml not found" not in reason


def test_generate_video_download_failure_does_not_leave_final_file(tmp_path, monkeypatch):
    from narrascape.stages.generate_video import GenerateVideoStage

    videos_dir = tmp_path / "videos"
    videos_dir.mkdir()
    stage = GenerateVideoStage(api_key="fake", sleep_between=0)
    monkeypatch.setattr(stage, "_create_task", lambda *args, **kwargs: "task")
    monkeypatch.setattr(stage, "_poll_task", lambda task_id: "https://example.invalid/out.mp4")

    def fail_download(*args, **kwargs):
        raise OSError("download failed")

    monkeypatch.setattr("narrascape.stages.generate_video.download_to_path", fail_download)

    ok = stage._generate_one("prompt", "vid_01", "model", "720p", None, None, videos_dir)

    assert ok is False
    assert not (videos_dir / "vid_01.mp4").exists()


def test_generate_video_poll_exits_after_repeated_transport_errors(monkeypatch):
    import urllib.error

    from narrascape.stages.generate_video import GenerateVideoStage

    sleeps = []
    attempts = []

    def fail_urlopen(*args, **kwargs):
        attempts.append(1)
        raise urllib.error.URLError("server unavailable")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    stage = GenerateVideoStage(
        api_key="fake",
        poll_interval=10,
        max_poll_time=300,
        max_poll_errors=2,
    )

    assert stage._poll_task("task") is None
    assert len(attempts) == 2
    assert sleeps == [10]


def test_qa_reports_deep_quality_checks(tmp_path, monkeypatch):
    from narrascape.stages.qa import QAStage

    config = _config(tmp_path)
    config.output_dir.mkdir(parents=True)
    config.pipeline_dir.mkdir(parents=True)
    final = config.output_dir / "project-sub.mp4"
    final.write_bytes(b"video")
    (config.pipeline_dir / "subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:00:04,000\nhello\n", encoding="utf-8"
    )
    (config.pipeline_dir / "timing.json").write_text(json.dumps({"1": 10.0}), encoding="utf-8")
    (config.pipeline_dir / "image_gen_state.json").write_text(
        json.dumps({"provider_selection": {"name": "local_image"}}),
        encoding="utf-8",
    )
    config.images_dir.mkdir(parents=True)
    (config.images_dir / "img_01.png").write_bytes(b"same")
    (config.images_dir / "img_02.png").write_bytes(b"same")

    monkeypatch.setattr("narrascape.stages.qa.validate_video", lambda path: True)
    monkeypatch.setattr(
        "narrascape.stages.qa.get_media_info",
        lambda path: {
            "format": {"duration": "4.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        },
    )
    stage = QAStage()
    monkeypatch.setattr(
        stage, "_detect_silence", lambda path: {"ok": False, "mean_volume_db": -90.0}
    )
    monkeypatch.setattr(
        stage, "_detect_black_frames", lambda path, duration: {"risk": True, "black_seconds": 4.0}
    )

    result = stage.run(_context(config))

    assert not result.success
    checks = result.metadata["report"]["checks"]
    assert checks["subtitle_output_present"] is True
    assert checks["duration_within_tolerance"] is False
    assert checks["audio_not_silent"] is False
    assert checks["black_frame_risk"] is True
    assert checks["repeated_shot_risk"] is True
    assert checks["placeholder_residue"] is True


def test_source_media_writes_real_footage_edit_timeline(tmp_path):
    from narrascape.stages.source_media import SourceMediaStage

    config = _config(tmp_path)
    media_dir = config.project_dir / "source_media"
    media_dir.mkdir()
    (media_dir / "archive_clip.mp4").write_bytes(b"video bytes")

    result = SourceMediaStage().run(_context(config))

    assert result.success
    timeline_path = config.project_dir / "footage_timeline.yaml"
    assert timeline_path.exists()
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    assert timeline["strategy"] == "source_media_first"
    assert timeline["edits"][0]["asset_id"] == "asset_001"
    assert timeline["edits"][0]["source_path"].endswith("archive_clip.mp4")
    assert timeline["edits"][0]["role"] == "documentary_footage"


def test_footage_edit_stage_renders_source_media_roughcut(tmp_path, monkeypatch):
    from narrascape.stages.footage_edit import FootageEditStage
    from narrascape.stages.source_media import SourceMediaStage

    config = _config(tmp_path)
    media_dir = config.project_dir / "source_media"
    media_dir.mkdir()
    (media_dir / "archive_clip.mp4").write_bytes(b"video bytes")
    SourceMediaStage().run(_context(config))

    def fake_run_ffmpeg(args, **kwargs):
        Path(args[-1]).write_bytes(b"rendered")
        return True

    monkeypatch.setattr("narrascape.stages.footage_edit.run_ffmpeg", fake_run_ffmpeg)

    result = FootageEditStage().run(_context(config))

    assert result.success
    assert result.outputs[0] == config.pipeline_dir / "footage_roughcut.mp4"
    assert (config.pipeline_dir / "source_media_segments" / "edit_001.mp4").exists()
    assert (config.pipeline_dir / "footage_roughcut.mp4").exists()
