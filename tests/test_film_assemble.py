from __future__ import annotations

from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.pipeline import _resolve_dependencies, get_stage_map
from narrascape.stages.base import StageContext


def _config(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "assemble_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "assets" / "videos").mkdir(parents=True)
    (project_dir / "assets" / "images").mkdir(parents=True)
    (project_dir / "source_media").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "Generated video opens."},
                    {"id": 2, "text": "Source footage follows."},
                    {"id": 3, "text": "A still image fills the gap."},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "assets" / "videos" / "vid_01.mp4").write_bytes(b"video")
    (project_dir / "source_media" / "clip.mp4").write_bytes(b"source")
    (project_dir / "assets" / "images" / "img_03.png").write_bytes(b"image")
    (project_dir / "film_timeline.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "film_timeline.v1",
                "project": {"name": "assemble-project", "title": "Assemble Project"},
                "duration": 9.0,
                "coverage": {
                    "generated_video_segments": [1],
                    "source_media_segments": [2],
                    "generated_image_segments": [3],
                    "missing_visual_segments": [],
                },
                "tracks": {
                    "visual": [
                        {
                            "id": "v_001",
                            "segment_id": 1,
                            "source": "generated_video",
                            "asset_ref": "vid_01",
                            "path": "assets/videos/vid_01.mp4",
                            "start": 0.0,
                            "duration": 3.0,
                        },
                        {
                            "id": "v_002",
                            "segment_id": 2,
                            "source": "source_media",
                            "asset_ref": "asset_001",
                            "path": "source_media/clip.mp4",
                            "start": 3.0,
                            "duration": 3.0,
                            "source_in": 0.0,
                        },
                        {
                            "id": "v_003",
                            "segment_id": 3,
                            "source": "generated_image",
                            "asset_ref": "img_03",
                            "path": "assets/images/img_03.png",
                            "start": 6.0,
                            "duration": 3.0,
                        },
                    ],
                    "narration": [],
                    "music": [],
                    "subtitles": [],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="assemble-project",
            title="Assemble Project",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True)
    return config


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )


def test_film_assemble_renders_visual_track_with_video_source_and_image_fallback(
    tmp_path, monkeypatch
):
    from narrascape.stages.film_assemble import FilmAssembleStage

    config = _config(tmp_path)
    commands: list[list[str]] = []

    def fake_run_ffmpeg(args, **kwargs):
        commands.append(args)
        Path(args[-1]).write_bytes(b"rendered")
        return True

    monkeypatch.setattr("narrascape.stages.film_assemble.run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(
        "narrascape.stages.film_assemble.validate_video", lambda path: path.exists()
    )

    result = FilmAssembleStage().run(_context(config))

    assert result.success
    assert result.outputs[0] == config.pipeline_dir / "film_assembled.mp4"
    assert (config.pipeline_dir / "timeline_segments" / "v_001.mp4").exists()
    assert (config.pipeline_dir / "timeline_segments" / "v_002.mp4").exists()
    assert (config.pipeline_dir / "timeline_segments" / "v_003.mp4").exists()
    assert (config.pipeline_dir / "film_assembled.mp4").exists()
    concat_lines = (config.pipeline_dir / "film_assemble.txt").read_text(encoding="utf-8")
    assert str((config.pipeline_dir / "timeline_segments" / "v_001.mp4").resolve()).replace(
        "\\", "/"
    ) in concat_lines
    joined_commands = [" ".join(command) for command in commands]
    assert any(
        "assets\\videos\\vid_01.mp4" in cmd or "assets/videos/vid_01.mp4" in cmd
        for cmd in joined_commands
    )
    assert any("-loop 1" in cmd for cmd in joined_commands)
    assert any("-c:v libx264" in cmd for cmd in joined_commands)


def test_film_assemble_stage_is_default_visual_path_before_audio():
    stage_map = get_stage_map()

    assert "film_assemble" in stage_map
    order = _resolve_dependencies(["audio"], stage_map)

    assert order.index("film_timeline") < order.index("film_assemble")
    assert order.index("film_assemble") < order.index("audio")


def test_film_assemble_respects_timeline_start_gaps(tmp_path, monkeypatch):
    from narrascape.stages.film_assemble import FilmAssembleStage

    config = _config(tmp_path)
    timeline_path = config.project_dir / "film_timeline.yaml"
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    timeline["tracks"]["visual"][1]["start"] = 4.0
    timeline_path.write_text(yaml.safe_dump(timeline, sort_keys=False), encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run_ffmpeg(args, **kwargs):
        commands.append(args)
        Path(args[-1]).write_bytes(b"rendered")
        return True

    monkeypatch.setattr("narrascape.stages.film_assemble.run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(
        "narrascape.stages.film_assemble.validate_video", lambda path: path.exists()
    )

    result = FilmAssembleStage().run(_context(config))

    assert result.success
    assert (config.pipeline_dir / "timeline_segments" / "gap_001.mp4").exists()
    concat_lines = (config.pipeline_dir / "film_assemble.txt").read_text(encoding="utf-8")
    assert "gap_001.mp4" in concat_lines
    assert any("color=c=black" in " ".join(command) for command in commands)


def test_film_assemble_rejects_unknown_clip_source(tmp_path, monkeypatch):
    from narrascape.stages.film_assemble import FilmAssembleStage

    config = _config(tmp_path)
    timeline_path = config.project_dir / "film_timeline.yaml"
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    timeline["tracks"]["visual"][0]["source"] = "mystery_source"
    timeline_path.write_text(yaml.safe_dump(timeline, sort_keys=False), encoding="utf-8")

    calls = []

    def fake_run_ffmpeg(args, **kwargs):
        calls.append(args)
        return True

    monkeypatch.setattr("narrascape.stages.film_assemble.run_ffmpeg", fake_run_ffmpeg)

    result = FilmAssembleStage().run(_context(config))

    assert not result.success
    assert "v_001" in result.message
    assert calls == []
