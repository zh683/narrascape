from __future__ import annotations

import json
from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.pipeline import _resolve_dependencies, get_stage_map
from narrascape.stages.base import StageContext


def _project(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "film_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "assets" / "images").mkdir(parents=True)
    (project_dir / "assets" / "tts").mkdir(parents=True)
    (project_dir / "assets" / "videos").mkdir(parents=True)
    (project_dir / "source_media").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "The archive footage opens the film."},
                    {"id": 2, "text": "A generated insert fills the missing scene."},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(
            {
                "project_title": "Film Timeline Test",
                "segments": [
                    {
                        "segment_id": 1,
                        "shot_type": "wide_env",
                        "movement": "pan_left",
                        "image_prompt": "Archive opening shot.",
                    },
                    {
                        "segment_id": 2,
                        "shot_type": "detail",
                        "movement": "push_in",
                        "image_prompt": "Generated insert shot.",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "image_map.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "images": ["img_01"]},
                    {"id": 2, "images": ["img_02", "img_03"], "timing": [0.4, 0.6]},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "assets" / "images" / "img_02.png").write_bytes(b"image")
    (project_dir / "assets" / "images" / "img_03.png").write_bytes(b"image")
    (project_dir / "assets" / "tts" / "seg_01.mp3").write_bytes(b"tts")
    (project_dir / "assets" / "tts" / "seg_02.mp3").write_bytes(b"tts")
    (project_dir / "source_media" / "archive_clip.mp4").write_bytes(b"video")
    (project_dir / "asset_manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "assets": [
                    {
                        "id": "asset_001",
                        "path": "source_media/archive_clip.mp4",
                        "type": "video",
                        "provider": "local",
                        "source": "local_library",
                        "license": "user_provided",
                        "metadata": {"duration_seconds": 5.0},
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "footage_timeline.yaml").write_text(
        yaml.safe_dump(
            {
                "strategy": "source_media_first",
                "project": "film-project",
                "total_duration": 5.0,
                "edits": [
                    {
                        "id": "edit_001",
                        "asset_id": "asset_001",
                        "source_path": "source_media/archive_clip.mp4",
                        "source_type": "video",
                        "role": "documentary_footage",
                        "target_segment_id": 1,
                        "timeline_start": 0.0,
                        "duration": 5.0,
                        "source_in": 0.0,
                        "source_out": 5.0,
                        "transition": "cut",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="film-project",
            title="Film Timeline Test",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True)
    (config.pipeline_dir / "timing.json").write_text(
        json.dumps({"1": 5.0, "2": 7.0}, indent=2),
        encoding="utf-8",
    )
    (config.pipeline_dir / "subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:00:05,000\narchive\n",
        encoding="utf-8",
    )
    return config


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )


def test_film_timeline_unifies_source_footage_generated_assets_and_audio(tmp_path):
    from narrascape.stages.film_timeline import FilmTimelineStage

    config = _project(tmp_path)

    result = FilmTimelineStage().run(_context(config))

    assert result.success
    timeline_path = config.project_dir / "film_timeline.yaml"
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    assert timeline["schema_version"] == "film_timeline.v1"
    assert timeline["project"]["name"] == "film-project"
    assert timeline["coverage"]["source_media_segments"] == [1]
    assert timeline["coverage"]["generated_image_segments"] == [2]
    assert timeline["coverage"]["missing_visual_segments"] == []

    visual = timeline["tracks"]["visual"]
    assert visual[0]["segment_id"] == 1
    assert visual[0]["source"] == "source_media"
    assert visual[0]["asset_ref"] == "asset_001"
    assert visual[1]["segment_id"] == 2
    assert visual[1]["source"] == "generated_image"
    assert visual[1]["asset_ref"] == "img_02"

    narration = timeline["tracks"]["narration"]
    assert [clip["asset_ref"] for clip in narration] == ["tts_01", "tts_02"]
    assert timeline["tracks"]["subtitles"][0]["path"].endswith("subtitles.srt")
    assert result.metadata["coverage"]["source_media_segments"] == [1]


def test_film_timeline_stage_is_registered_after_design_and_tts():
    stage_map = get_stage_map()

    assert "film_timeline" in stage_map
    order = _resolve_dependencies(["film_timeline"], stage_map)

    assert order.index("design") < order.index("film_timeline")
    assert order.index("generate_tts") < order.index("film_timeline")


def test_film_timeline_can_run_requires_design_report(tmp_path):
    from narrascape.stages.film_timeline import FilmTimelineStage

    config = _project(tmp_path)
    (config.project_dir / "design_report.yaml").unlink()

    can_run, reason = FilmTimelineStage().can_run(_context(config))

    assert not can_run
    assert "design_report.yaml not found" in reason


def test_film_timeline_prefers_generated_video_over_source_and_image(tmp_path):
    from narrascape.stages.film_timeline import FilmTimelineStage

    config = _project(tmp_path)
    (config.project_dir / "assets" / "videos" / "vid_01.mp4").write_bytes(b"generated video")
    (config.project_dir / "assets" / "videos" / "vid_02.mp4").write_bytes(b"generated video")
    (config.pipeline_dir / "video_gen_state.json").write_text(
        json.dumps({"done": ["vid_01", "vid_02"]}, indent=2),
        encoding="utf-8",
    )

    result = FilmTimelineStage().run(_context(config))

    assert result.success
    timeline = yaml.safe_load(
        (config.project_dir / "film_timeline.yaml").read_text(encoding="utf-8")
    )
    assert timeline["strategy"]["visual_priority"] == [
        "generated_video",
        "source_media",
        "generated_image",
    ]
    assert timeline["coverage"]["generated_video_segments"] == [1, 2]
    assert timeline["coverage"]["source_media_segments"] == []
    assert timeline["coverage"]["generated_image_segments"] == []
    story_clips = [
        clip for clip in timeline["tracks"]["visual"] if clip.get("segment_id") is not None
    ]
    assert [clip["source"] for clip in story_clips] == ["generated_video", "generated_video"]
    assert timeline["tracks"]["visual"][0]["asset_ref"] == "vid_01"


def test_film_timeline_ignores_invalid_external_segment_ids(tmp_path):
    from narrascape.stages.film_timeline import FilmTimelineStage

    config = _project(tmp_path)
    (config.project_dir / "design_report.yaml").write_text(
        yaml.safe_dump(
            {
                "project_title": "Film Timeline Test",
                "segments": [
                    {"segment_id": "bad", "shot_type": "wide_env"},
                    {"segment_id": 2, "shot_type": "detail"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config.project_dir / "image_map.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": "not-an-int", "images": ["ignored"]},
                    {"id": 2, "images": ["img_02"]},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config.project_dir / "footage_timeline.yaml").write_text(
        yaml.safe_dump(
            {
                "edits": [
                    {
                        "id": "bad",
                        "asset_id": "asset_001",
                        "source_path": "source_media/archive_clip.mp4",
                        "target_segment_id": "bad",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = FilmTimelineStage().run(_context(config))

    assert result.success is False
    assert "missing visuals for segments: [1]" in result.message
