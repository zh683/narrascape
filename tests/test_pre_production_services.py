from __future__ import annotations

from pathlib import Path

from narrascape.config import Script


def test_pre_production_notes_extractor_reads_director_notes(tmp_path: Path) -> None:
    from narrascape.stages.pre_production_services import PreProductionNotesExtractor

    (tmp_path / "director_notes.md").write_text(
        """# Director Notes

## Character Bible

### mira-stone

- Role: field scientist
- Age: late 30s
- Face and body: sharp cheekbones, tired eyes
- Wardrobe lock: blue field coat, brass watch
- Behavior: guarded stillness
- Negative anchors: not glamorous

## Scene Bible

### field_lab

- Core look: cramped room, green monitors, sealed glass door
- Lighting: green practicals and gray dawn
- Continuity: never clean or spacious
""",
        encoding="utf-8",
    )
    script = Script(segments=[{"id": 1, "text": "Mira waits in the lab."}])
    extractor = PreProductionNotesExtractor(max_characters=5, max_scenes=5)

    characters, scenes = extractor.extract_local(script, tmp_path)

    assert characters[0]["char_id"] == "mira_stone"
    assert "blue field coat" in characters[0]["identity_block"]
    assert characters[0]["signature_accessories"] == ["watch", "coat"]
    assert scenes[0]["scene_id"] == "field_lab"
    assert scenes[0]["scene_type"] == "indoor"
    assert "green" in scenes[0]["color_palette"]


def test_pre_production_reference_factory_uses_existing_reference_files(
    tmp_path: Path,
) -> None:
    from narrascape.stages.pre_production_services import PreProductionReferenceFactory

    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    (refs_dir / "char_mira_anchor.png").write_bytes(b"png")
    (refs_dir / "scene_lab_mood.png").write_bytes(b"png")
    factory = PreProductionReferenceFactory()

    character = factory.metadata_only_character_reference(
        {"char_id": "mira", "name": "Mira", "identity_block": "Mira in a blue coat."},
        refs_dir,
    )
    scene = factory.metadata_only_environment_reference(
        {
            "scene_id": "lab",
            "scene_name": "Lab",
            "scene_type": "indoor",
            "time_of_day": "dawn",
        },
        refs_dir,
    )

    assert character.primary_reference_path.endswith("char_mira_anchor.png")
    assert character.anchor_image is not None
    assert scene.primary_reference_path.endswith("scene_lab_mood.png")
    assert scene.mood_images[0].image_id == "scene_lab_mood"
