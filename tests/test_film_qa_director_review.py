from __future__ import annotations

from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.stages.base import StageContext


def _config(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "review_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "output").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "The hero enters the lab."},
                    {"id": 2, "text": "The scene jumps to a mismatched night street."},
                    {"id": 3, "text": "A missing shot should be regenerated."},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = NarrascapeConfig(
        project=ProjectConfig(
            name="review-project",
            title="Review Project",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )
    config.pipeline_dir.mkdir(parents=True)
    (config.output_dir / "review-project-sub.mp4").write_bytes(b"video")
    (config.pipeline_dir / "subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:00:04,000\nhello\n",
        encoding="utf-8",
    )
    (project_dir / "film_timeline.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "film_timeline.v1",
                "project": {"name": "review-project", "title": "Review Project"},
                "duration": 15.0,
                "coverage": {
                    "generated_video_segments": [1],
                    "source_media_segments": [],
                    "generated_image_segments": [2],
                    "missing_visual_segments": [3],
                },
                "tracks": {
                    "visual": [
                        {
                            "id": "v_001",
                            "segment_id": 1,
                            "source": "generated_video",
                            "path": "assets/videos/vid_01.mp4",
                            "duration": 2.0,
                            "character_ids": ["hero"],
                            "location_id": "lab",
                        },
                        {
                            "id": "v_002",
                            "segment_id": 2,
                            "source": "generated_image",
                            "path": "assets/images/img_02.png",
                            "duration": 12.0,
                            "character_ids": ["hero"],
                            "location_id": "night_street",
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
    return config


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )


def test_qa_reports_film_level_checks_from_timeline(tmp_path, monkeypatch):
    from narrascape.stages.qa import QAStage

    config = _config(tmp_path)
    monkeypatch.setattr("narrascape.stages.qa.validate_video", lambda path: True)
    monkeypatch.setattr(
        "narrascape.stages.qa.get_media_info",
        lambda path: {
            "format": {"duration": "15.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        },
    )
    stage = QAStage()
    monkeypatch.setattr(stage, "_detect_silence", lambda path: {"ok": True, "mean_volume_db": -18.0})
    monkeypatch.setattr(stage, "_detect_black_frames", lambda path, duration: {"risk": False, "black_seconds": 0.0})

    result = stage.run(_context(config))

    checks = result.metadata["report"]["checks"]
    assert checks["shot_coverage_ratio"] == 2 / 3
    assert checks["missing_visual_segments"] == [3]
    assert checks["missing_generated_video_segments"] == [2, 3]
    assert checks["continuity_risk"] is True
    assert checks["pacing_risk"] is True
    assert not result.success
    assert any("shot coverage incomplete" in error for error in result.metadata["errors"])


def test_director_review_marks_failed_shots_for_regeneration_and_recuts(tmp_path):
    from narrascape.stages.director_review import DirectorReviewStage

    config = _config(tmp_path)
    (config.pipeline_dir / "render_report.yaml").write_text(
        yaml.safe_dump(
            {
                "output": "output/review-project-sub.mp4",
                "checks": {
                    "missing_visual_segments": [3],
                    "missing_generated_video_segments": [2, 3],
                    "missing_video_clips": [1],
                    "continuity_risk_segments": [2],
                    "pacing_risk_segments": [2],
                },
                "errors": ["shot coverage incomplete"],
                "warnings": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = DirectorReviewStage().run(_context(config))

    assert result.success
    review_path = config.pipeline_dir / "director_review.yaml"
    review = yaml.safe_load(review_path.read_text(encoding="utf-8"))
    assert review["status"] == "needs_rework"
    assert {"segment_id": 3, "action": "regenerate_video", "reason": "missing_visual"} in review["rework_queue"]
    assert {"segment_id": 2, "action": "regenerate_video", "reason": "missing_generated_video"} in review["rework_queue"]
    assert {"segment_id": 1, "action": "regenerate_video", "reason": "missing_video_clip"} in review["rework_queue"]
    assert {"segment_id": 2, "action": "recut", "reason": "pacing_risk"} in review["rework_queue"]


def test_qa_detects_repeated_shots_in_film_timeline_segments(tmp_path, monkeypatch):
    from narrascape.stages.qa import QAStage

    config = _config(tmp_path)
    segment_dir = config.pipeline_dir / "timeline_segments"
    segment_dir.mkdir(parents=True)
    (segment_dir / "v_001.mp4").write_bytes(b"same rendered shot")
    (segment_dir / "v_002.mp4").write_bytes(b"same rendered shot")
    monkeypatch.setattr("narrascape.stages.qa.validate_video", lambda path: True)
    monkeypatch.setattr(
        "narrascape.stages.qa.get_media_info",
        lambda path: {
            "format": {"duration": "15.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        },
    )
    stage = QAStage()
    monkeypatch.setattr(stage, "_detect_silence", lambda path: {"ok": True, "mean_volume_db": -18.0})
    monkeypatch.setattr(stage, "_detect_black_frames", lambda path, duration: {"risk": False, "black_seconds": 0.0})

    result = stage.run(_context(config))

    assert result.metadata["report"]["checks"]["repeated_shot_risk"] is True


def test_qa_reports_missing_timeline_video_clip_files(tmp_path, monkeypatch):
    from narrascape.stages.qa import QAStage

    config = _config(tmp_path)
    timeline_path = config.project_dir / "film_timeline.yaml"
    timeline = yaml.safe_load(timeline_path.read_text(encoding="utf-8"))
    timeline["tracks"]["visual"][0]["path"] = "assets/videos/missing_vid_01.mp4"
    timeline_path.write_text(yaml.safe_dump(timeline, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr("narrascape.stages.qa.validate_video", lambda path: True)
    monkeypatch.setattr(
        "narrascape.stages.qa.get_media_info",
        lambda path: {
            "format": {"duration": "15.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        },
    )
    stage = QAStage()
    monkeypatch.setattr(stage, "_detect_silence", lambda path: {"ok": True, "mean_volume_db": -18.0})
    monkeypatch.setattr(stage, "_detect_black_frames", lambda path, duration: {"risk": False, "black_seconds": 0.0})

    result = stage.run(_context(config))

    checks = result.metadata["report"]["checks"]
    assert checks["missing_video_clips"] == [1]
    assert any("timeline video clips missing" in error for error in result.metadata["errors"])
