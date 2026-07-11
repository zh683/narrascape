from __future__ import annotations

from pathlib import Path

import yaml
from PIL import Image, ImageStat

from narrascape.cache import BuildCache
from narrascape.config import NarrascapeConfig, ProjectConfig, load_script
from narrascape.stages.base import StageContext


def _write_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (480, 270), color).save(path)


def _project(tmp_path: Path, *, with_images: bool) -> NarrascapeConfig:
    project_dir = tmp_path / "storyboard-sheet-project"
    scripts_dir = project_dir / "scripts"
    pipeline_dir = project_dir / "pipeline" / "storyboard-sheet-project"
    images_dir = project_dir / "assets" / "images"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    (scripts_dir / "script.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "text": "Raskolnikov enters the room."},
                    {"id": 2, "text": "He stares at the letter in silence."},
                ]
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    pre_production = {
        "project_title": "Storyboard Sheet Test",
        "style_template": "gritty literary thriller",
        "style_anchor_path": "assets/references/style_anchor.png",
        "storyboard": {
            "total_frames": 2,
            "total_segments": 2,
            "frames": [
                {
                    "frame_id": "sb_01_01",
                    "segment_id": 1,
                    "frame_index": 0,
                    "description": "The room feels cramped and airless.",
                    "shot_type": "medium",
                    "camera_movement": "still",
                    "camera_angle": "eye-level",
                    "character_positions": ["Raskolnikov center-left"],
                    "emotion": "unease",
                    "duration_hint": 4.0,
                    "character_refs": ["char_raskolnikov"],
                    "scene_ref": "scene_room",
                    "reference_image_ids": ["img_01", "char_raskolnikov_anchor"],
                    "notes": "Hold on the silence.",
                },
                {
                    "frame_id": "sb_02_01",
                    "segment_id": 2,
                    "frame_index": 0,
                    "description": "The letter becomes the focus of the frame.",
                    "shot_type": "close_up",
                    "camera_movement": "push_in",
                    "camera_angle": "eye-level",
                    "character_positions": ["letter foreground, hands edge frame"],
                    "emotion": "tension",
                    "duration_hint": 3.0,
                    "character_refs": ["char_raskolnikov"],
                    "scene_ref": "scene_room",
                    "reference_image_ids": ["img_02", "scene_room_mood"],
                    "notes": "Isolate the paper.",
                },
            ],
        },
    }
    (pipeline_dir / "pre_production.yaml").write_text(
        yaml.safe_dump(pre_production, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    director_contract = {
        "schema_version": "director_contract.v1",
        "compile_process": {"mode": "local"},
        "shots": [
            {
                "segment_id": 1,
                "shot_id": "shot_01",
                "story_reason": "Establish the room and isolation.",
                "storyboard_binding": {
                    "storyboard_frame_ids": ["sb_01_01"],
                    "character_positions": ["Raskolnikov center-left"],
                    "scene_ref": "scene_room",
                    "wardrobe_lock": "worn coat",
                    "composition_requirements": ["negative space", "low key light"],
                    "reference_image_ids": ["img_01", "scene_room_mood"],
                },
                "generation": {"compiled_prompts": {}},
            },
            {
                "segment_id": 2,
                "shot_id": "shot_02",
                "story_reason": "Keep the letter tightly framed.",
                "storyboard_binding": {
                    "storyboard_frame_ids": ["sb_02_01"],
                    "character_positions": ["letter foreground"],
                    "scene_ref": "scene_room",
                    "wardrobe_lock": "worn coat",
                    "composition_requirements": ["tight crop", "paper edge visible"],
                    "reference_image_ids": ["img_02", "scene_room_mood"],
                },
                "generation": {"compiled_prompts": {}},
            },
        ],
    }
    (pipeline_dir / "director_contract.yaml").write_text(
        yaml.safe_dump(director_contract, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    reference_plates = {
        "schema_version": "reference_plates.v1",
        "status": "ready",
        "findings": [],
        "blocking": False,
        "plate_count": 2,
        "plates": [
            {
                "segment_id": 1,
                "shot_id": "shot_01",
                "storyboard_frame_ids": ["sb_01_01"],
                "character_positions": ["Raskolnikov center-left"],
                "scene_ref": "scene_room",
                "wardrobe_lock": "worn coat",
                "composition_requirements": ["negative space", "low key light"],
                "storyboard_reference_image_ids": ["img_01", "scene_room_mood"],
                "expected_reference_ids": ["img_01", "scene_room_mood"],
                "missing_reference_ids": [],
                "reference_assets": [
                    {
                        "requested_id": "img_01",
                        "asset_id": "img_01",
                        "role": "reference",
                        "source": "assets/images",
                        "path": str((images_dir / "img_01.png").as_posix()),
                        "url": "",
                        "exists": with_images,
                    }
                ],
            },
            {
                "segment_id": 2,
                "shot_id": "shot_02",
                "storyboard_frame_ids": ["sb_02_01"],
                "character_positions": ["letter foreground"],
                "scene_ref": "scene_room",
                "wardrobe_lock": "worn coat",
                "composition_requirements": ["tight crop", "paper edge visible"],
                "storyboard_reference_image_ids": ["img_02", "scene_room_mood"],
                "expected_reference_ids": ["img_02", "scene_room_mood"],
                "missing_reference_ids": [] if with_images else ["img_02"],
                "reference_assets": (
                    [
                        {
                            "requested_id": "img_02",
                            "asset_id": "img_02",
                            "role": "reference",
                            "source": "assets/images",
                            "path": str((images_dir / "img_02.png").as_posix()),
                            "url": "",
                            "exists": with_images,
                        }
                    ]
                    if with_images
                    else []
                ),
            },
        ],
    }
    (pipeline_dir / "reference_plates.yaml").write_text(
        yaml.safe_dump(reference_plates, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    (project_dir / "image_map.yaml").write_text(
        yaml.safe_dump(
            {
                "segments": [
                    {"id": 1, "images": ["img_01"]},
                    {"id": 2, "images": ["img_02"]},
                ]
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    if with_images:
        _write_image(images_dir / "img_01.png", (72, 84, 96))
        _write_image(images_dir / "img_02.png", (98, 68, 84))

    return NarrascapeConfig(
        project=ProjectConfig(
            name="storyboard-sheet-project",
            title="Storyboard Sheet Test",
            script_file="scripts/script.yaml",
        ),
        project_dir=project_dir,
    )


def _context(config: NarrascapeConfig) -> StageContext:
    return StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
    )


def test_storyboard_sheet_renders_pdf_png_and_yaml(tmp_path):
    from narrascape.stages.storyboard_sheet import StoryboardSheetStage

    config = _project(tmp_path, with_images=True)

    result = StoryboardSheetStage().run(_context(config))

    assert result.success is True
    report_path = config.pipeline_dir / "storyboard_sheet.yaml"
    png_path = config.pipeline_dir / "storyboard_sheet.png"
    pdf_path = config.pipeline_dir / "storyboard_sheet.pdf"
    assert report_path.exists()
    assert png_path.exists()
    assert pdf_path.exists()

    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "storyboard_sheet.v1"
    assert report["status"] == "ready"
    assert report["shot_count"] == 2
    assert report["page_count"] == 1
    assert report["pages"][0]["cards"][0]["preview_source_kind"] == "generated_image"
    assert report["pages"][0]["cards"][0]["frame_ids"] == ["sb_01_01"]

    with Image.open(png_path) as image:
        assert image.size[0] >= 1600
        assert image.size[1] >= 1000
        assert image.getbbox() is not None
        stat = ImageStat.Stat(image.convert("RGB"))
        assert any(low != high for low, high in stat.extrema)

    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_storyboard_sheet_promotes_rendered_outputs_atomically(tmp_path, monkeypatch):
    from narrascape.stages.storyboard_sheet import StoryboardSheetStage

    config = _project(tmp_path, with_images=True)
    promotions: list[Path] = []

    def fake_atomic_promote_file(temp_path, path, *, lock=True):
        promotions.append(Path(path))
        Path(temp_path).replace(path)

    monkeypatch.setattr(
        "narrascape.stages.storyboard_sheet.atomic_promote_file", fake_atomic_promote_file
    )

    result = StoryboardSheetStage().run(_context(config))

    assert result.success is True
    assert config.pipeline_dir / "storyboard_sheet.png" in promotions
    assert config.pipeline_dir / "storyboard_sheet.pdf" in promotions


def test_storyboard_sheet_falls_back_when_preview_images_are_missing(tmp_path):
    from narrascape.stages.storyboard_sheet import StoryboardSheetStage

    config = _project(tmp_path, with_images=False)

    result = StoryboardSheetStage().run(_context(config))

    assert result.success is True
    report = yaml.safe_load(
        (config.pipeline_dir / "storyboard_sheet.yaml").read_text(encoding="utf-8")
    )
    assert report["status"] == "degraded"
    assert report["findings"]
    assert report["pages"][0]["cards"][1]["preview_source_kind"] == "placeholder"
    assert (config.pipeline_dir / "storyboard_sheet.png").exists()
    assert (config.pipeline_dir / "storyboard_sheet.pdf").exists()


def test_storyboard_sheet_is_registered_in_the_pipeline_graph():
    from narrascape.pipeline import _resolve_dependencies, get_stage_map

    stage_map = get_stage_map()

    assert "storyboard_sheet" in stage_map
    order = _resolve_dependencies(["storyboard_sheet"], stage_map)
    assert order.index("reference_plate") < order.index("storyboard_sheet")
