from __future__ import annotations

from pathlib import Path

import yaml

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.pipeline import Pipeline, _resolve_dependencies, get_stage_map
from narrascape.stages.base import StageContext


def _config(tmp_path: Path) -> NarrascapeConfig:
    project_dir = tmp_path / "remotion_project"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "assets" / "videos").mkdir(parents=True)
    (project_dir / "assets" / "images").mkdir(parents=True)
    (project_dir / "source_media").mkdir(parents=True)
    (project_dir / "scripts" / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "Generated video opens."},
                    {"id": 2, "text": "A painted insert follows."},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "assets" / "videos" / "vid_01.mp4").write_bytes(b"video")
    (project_dir / "assets" / "images" / "img_02.png").write_bytes(b"image")
    (project_dir / "film_timeline.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "film_timeline.v1",
                "project": {"name": "remotion-project", "title": "Remotion Project"},
                "duration": 6.0,
                "coverage": {
                    "generated_video_segments": [1],
                    "source_media_segments": [],
                    "generated_image_segments": [2],
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
                            "source_in": 0.5,
                            "shot_type": "wide",
                            "movement": "slow push",
                            "emotion": "dread",
                        },
                        {
                            "id": "v_002",
                            "segment_id": 2,
                            "source": "generated_image",
                            "asset_ref": "img_02",
                            "path": "assets/images/img_02.png",
                            "start": 3.0,
                            "duration": 3.0,
                            "storyboard_frame_ids": ["sb_02_01"],
                            "composition": "isolated figure near the edge",
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
            name="remotion-project",
            title="Remotion Project",
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


def test_remotion_preview_generates_handoff_project_from_film_timeline(tmp_path):
    from narrascape.stages.remotion_preview import RemotionPreviewStage

    config = _config(tmp_path)

    result = RemotionPreviewStage().run(_context(config))

    assert result.success
    preview_dir = config.pipeline_dir / "remotion_preview"
    report_path = config.pipeline_dir / "remotion_preview.yaml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "remotion_preview.v1"
    assert report["status"] == "ready"
    assert report["composition"]["id"] == "NarrascapeTimeline"
    assert report["composition"]["durationInFrames"] == 150
    assert report["commands"]["studio"] == "npx remotion studio"
    assert (preview_dir / "package.json").exists()
    assert (preview_dir / "src" / "Root.tsx").exists()
    assert (preview_dir / "src" / "TimelineComposition.tsx").exists()
    assert (preview_dir / "public" / "timeline.json").exists()
    assert (preview_dir / "public" / "assets" / "v_001.mp4").read_bytes() == b"video"
    assert (preview_dir / "public" / "assets" / "v_002.png").read_bytes() == b"image"
    timeline_json = (preview_dir / "public" / "timeline.json").read_text(encoding="utf-8")
    assert '"sourceTimeline": "film_timeline.yaml"' in timeline_json
    assert '"remotionAsset": "assets/v_001.mp4"' in timeline_json
    assert '"mediaType": "image"' in timeline_json
    assert "staticFile(clip.remotionAsset)" in (
        preview_dir / "src" / "TimelineComposition.tsx"
    ).read_text(encoding="utf-8")


def test_remotion_preview_reports_missing_assets_without_silent_success(tmp_path):
    from narrascape.stages.remotion_preview import RemotionPreviewStage

    config = _config(tmp_path)
    (config.project_dir / "assets" / "images" / "img_02.png").unlink()

    result = RemotionPreviewStage().run(_context(config))

    assert not result.success
    assert "assets/images/img_02.png" in result.message
    report = yaml.safe_load(
        (config.pipeline_dir / "remotion_preview.yaml").read_text(encoding="utf-8")
    )
    assert report["status"] == "missing_assets"
    assert report["assets"]["missing"][0]["clip_id"] == "v_002"


def test_remotion_preview_stage_is_registered_between_timeline_and_assemble():
    stage_map = get_stage_map()

    assert "remotion_preview" in stage_map
    order = _resolve_dependencies(["film_assemble"], stage_map)

    assert order.index("film_timeline") < order.index("remotion_preview")
    assert order.index("remotion_preview") < order.index("film_assemble")


def test_clean_remotion_preview_removes_handoff_artifacts(tmp_path):
    config = _config(tmp_path)
    preview_dir = config.pipeline_dir / "remotion_preview"
    preview_dir.mkdir(parents=True)
    (preview_dir / "package.json").write_text("{}", encoding="utf-8")
    (config.pipeline_dir / "remotion_preview.yaml").write_text(
        "schema_version: remotion_preview.v1\n", encoding="utf-8"
    )

    Pipeline(config).clean(["remotion_preview"])

    assert not preview_dir.exists()
    assert not (config.pipeline_dir / "remotion_preview.yaml").exists()
