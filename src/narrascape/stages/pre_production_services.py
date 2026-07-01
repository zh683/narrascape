"""Service objects used by the visual pre-production stage."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from narrascape.agent.models import (
    CharacterReferenceImage,
    CharacterReferenceSheet,
    EnvironmentReference,
    EnvironmentReferenceImage,
)
from narrascape.config import Script
from narrascape.utils.safe_io import atomic_write_yaml


class PreProductionNotesExtractor:
    """Extracts local pre-production metadata from director notes or script text."""

    def __init__(self, max_characters: int = 5, max_scenes: int = 8):
        self.max_characters = max_characters
        self.max_scenes = max_scenes

    def extract_local(
        self,
        script: Script,
        project_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        notes_path = project_dir / "director_notes.md"
        if notes_path.exists():
            notes = notes_path.read_text(encoding="utf-8")
            characters = self.characters_from_director_notes(notes)[: self.max_characters]
            scenes = self.scenes_from_director_notes(notes)[: self.max_scenes]
            if characters or scenes:
                return characters, scenes

        return [], self.scenes_from_script(script)[: self.max_scenes]

    def characters_from_director_notes(self, notes: str) -> list[dict[str, Any]]:
        sections = self.markdown_subsections(notes, "Character Bible")
        characters: list[dict[str, Any]] = []
        for raw_id, lines in sections:
            char_id = self.slug(raw_id)
            role = self.bullet_value(lines, "Role")
            age = self.bullet_value(lines, "Age")
            face = self.bullet_value(lines, "Face and body")
            wardrobe = self.bullet_value(lines, "Wardrobe lock")
            behavior = self.bullet_value(lines, "Behavior")
            negative = self.bullet_value(lines, "Negative anchors")
            identity_parts = [
                part
                for part in (
                    f"Role: {role}" if role else "",
                    f"Age: {age}" if age else "",
                    face,
                    f"Wardrobe: {wardrobe}" if wardrobe else "",
                    f"Behavior: {behavior}" if behavior else "",
                )
                if part
            ]
            characters.append(
                {
                    "char_id": char_id,
                    "name": raw_id.replace("_", " ").title(),
                    "identity_block": ". ".join(identity_parts) or raw_id,
                    "face_description": face,
                    "hair_description": "",
                    "body_description": face,
                    "default_outfit": wardrobe,
                    "signature_accessories": self.accessories_from_text(wardrobe),
                    "negative_anchors": [negative] if negative else [],
                    "expression_range": ["neutral", "tense", "fearful", "resolved"],
                }
            )
        return characters

    def scenes_from_director_notes(self, notes: str) -> list[dict[str, Any]]:
        sections = self.markdown_subsections(notes, "Scene Bible")
        scenes: list[dict[str, Any]] = []
        for raw_id, lines in sections:
            scene_id = self.slug(raw_id)
            core = self.bullet_value(lines, "Core look")
            lighting = self.bullet_value(lines, "Lighting")
            continuity = self.bullet_value(lines, "Continuity")
            description = ". ".join(part for part in (core, continuity) if part) or raw_id
            scenes.append(
                {
                    "scene_id": scene_id,
                    "scene_name": raw_id.replace("_", " ").title(),
                    "scene_type": self.scene_type(description),
                    "description": description,
                    "time_of_day": self.time_of_day(description),
                    "weather": self.weather(description),
                    "lighting_signature": lighting or "naturalistic period lighting",
                    "color_palette": self.color_palette(description, lighting),
                    "key_landmarks": self.landmarks_from_text(description),
                    "mood": "psychological pressure",
                }
            )
        return scenes

    def scenes_from_script(self, script: Script) -> list[dict[str, Any]]:
        scenes: list[dict[str, Any]] = []
        for seg in script.segments[: self.max_scenes]:
            scenes.append(
                {
                    "scene_id": f"script_segment_{seg.id:02d}",
                    "scene_name": f"Script Segment {seg.id}",
                    "scene_type": "story",
                    "description": seg.text[:240],
                    "time_of_day": "day",
                    "weather": "unspecified",
                    "lighting_signature": "cinematic natural light",
                    "color_palette": "story-driven natural contrast",
                    "key_landmarks": [],
                    "mood": "narrative",
                }
            )
        return scenes

    def markdown_subsections(self, markdown: str, heading: str) -> list[tuple[str, list[str]]]:
        in_section = False
        current_title = ""
        current_lines: list[str] = []
        sections: list[tuple[str, list[str]]] = []
        target = f"## {heading}".lower()

        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.lower() == target:
                in_section = True
                continue
            if in_section and stripped.startswith("## "):
                break
            if not in_section:
                continue
            if stripped.startswith("### "):
                if current_title:
                    sections.append((current_title, current_lines))
                current_title = stripped[4:].strip()
                current_lines = []
            elif current_title:
                current_lines.append(stripped)

        if current_title:
            sections.append((current_title, current_lines))
        return sections

    def bullet_value(self, lines: list[str], label: str) -> str:
        prefix = f"- {label}:"
        for line in lines:
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        return ""

    def slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9_]+", "_", value.lower().replace("-", "_")).strip("_")
        return slug or "item"

    def accessories_from_text(self, text: str) -> list[str]:
        accessories = []
        for keyword in ("cross", "key", "watch", "spectacles", "cap", "shawl", "coat"):
            if keyword in text.lower():
                accessories.append(keyword)
        return accessories

    def scene_type(self, text: str) -> str:
        lower = text.lower()
        if any(word in lower for word in ("room", "office", "flat", "apartment")):
            return "indoor"
        if any(word in lower for word in ("street", "yard", "canal", "river", "square")):
            return "urban"
        return "environment"

    def time_of_day(self, text: str) -> str:
        lower = text.lower()
        if "dawn" in lower:
            return "dawn"
        if "night" in lower:
            return "night"
        if "candle" in lower:
            return "evening"
        return "day"

    def weather(self, text: str) -> str:
        lower = text.lower()
        if "snow" in lower:
            return "snow"
        if "rain" in lower or "wet" in lower:
            return "rain"
        if "fog" in lower:
            return "fog"
        return "clear"

    def color_palette(self, description: str, lighting: str) -> str:
        lower = f"{description} {lighting}".lower()
        colors = [
            color
            for color in ("yellow", "gray", "green", "brown", "black", "snow")
            if color in lower
        ]
        return ", ".join(colors) if colors else "muted period palette"

    def landmarks_from_text(self, text: str) -> list[str]:
        lower = text.lower()
        landmarks = []
        for keyword in ("canal", "door", "keys", "icon", "candle", "river", "snow", "cobblestones"):
            if keyword in lower:
                landmarks.append(keyword)
        return landmarks[:3]

    def storyboard_intent_from_project(self, project_dir: Path) -> dict[str, str]:
        notes_path = project_dir / "director_notes.md"
        if not notes_path.exists():
            return {}
        return self.storyboard_intent_from_notes(notes_path.read_text(encoding="utf-8"))

    def storyboard_intent_from_notes(self, notes: str) -> dict[str, str]:
        in_section = False
        intents: dict[str, str] = {}
        for line in notes.splitlines():
            stripped = line.strip()
            if stripped.lower() == "## storyboard intent":
                in_section = True
                continue
            if in_section and stripped.startswith("## "):
                break
            if not in_section:
                continue
            match = re.match(r"-\s+`?(sb_\d+_\d+)`?\s*:\s*(.+)", stripped)
            if match:
                intents[match.group(1)] = match.group(2).strip()
        return intents

    def storyboard_scene_from_text(
        self,
        text: str,
        scene_ids: list[str],
    ) -> str:
        lower = text.lower()
        scene_keywords = {
            "police_office": ("office", "porfiry", "magistrate", "papers", "ink"),
            "sonya_room": ("sonya", "candle", "icon"),
            "rented_room": ("rented room", "attic", "yellow wallpaper", "sloped ceiling"),
            "pawnbroker_flat": ("pawnbroker", "door chain", "keys", "flat"),
            "petersburg_street": ("petersburg", "street", "canal", "cobblestone"),
            "siberian_yard": ("siberian", "siberia", "prison", "snow", "river"),
        }
        for scene_id in scene_ids:
            normalized = scene_id.replace("_", " ")
            if normalized in lower or scene_id.lower() in lower:
                return scene_id
            if any(keyword in lower for keyword in scene_keywords.get(scene_id, ())):
                return scene_id
        return ""

    def storyboard_characters_from_text(
        self,
        text: str,
        character_ids: list[str],
    ) -> list[str]:
        lower = text.lower()
        aliases = {
            "raskolnikov": ("raskolnikov", "student", "former student"),
            "porfiry": ("porfiry", "magistrate"),
            "sonya": ("sonya",),
            "pawnbroker": ("pawnbroker",),
        }
        result = []
        for char_id in character_ids:
            normalized = char_id.replace("_", " ").lower()
            if normalized in lower or any(alias in lower for alias in aliases.get(char_id, ())):
                result.append(char_id)
        return result


class PreProductionReferenceFactory:
    """Builds metadata-only reference models when no image provider is used."""

    def metadata_only_character_reference(
        self,
        char_data: dict[str, Any],
        refs_dir: Path,
    ) -> CharacterReferenceSheet:
        char_id = str(char_data.get("char_id") or "character")
        anchor_path = refs_dir / f"char_{char_id}_anchor.png"
        existing_anchor = str(anchor_path) if anchor_path.exists() else ""
        return CharacterReferenceSheet(
            char_id=char_id,
            name=str(char_data.get("name") or char_id),
            identity_block=str(char_data.get("identity_block") or char_id),
            primary_reference_path=existing_anchor,
            seedream_model=char_data.get("seedream_model", ""),
            seedream_sample_strength=char_data.get("seedream_sample_strength", 0.7),
            anchor_image=(
                CharacterReferenceImage(
                    image_id=f"char_{char_id}_anchor",
                    image_type="anchor",
                    local_path=existing_anchor,
                    description=f"Metadata-only character anchor for {char_id}",
                )
                if existing_anchor
                else None
            ),
        )

    def metadata_only_environment_reference(
        self,
        scene_data: dict[str, Any],
        refs_dir: Path,
    ) -> EnvironmentReference:
        scene_id = str(scene_data.get("scene_id") or "scene")
        mood_path = refs_dir / f"scene_{scene_id}_mood.png"
        existing_mood = str(mood_path) if mood_path.exists() else ""
        return EnvironmentReference(
            scene_id=scene_id,
            scene_name=str(scene_data.get("scene_name") or scene_id),
            scene_type=str(scene_data.get("scene_type") or "environment"),
            primary_reference_path=existing_mood,
            time_of_day=str(scene_data.get("time_of_day") or ""),
            weather=str(scene_data.get("weather") or ""),
            lighting_signature=str(scene_data.get("lighting_signature") or ""),
            color_palette=str(scene_data.get("color_palette") or ""),
            mood_images=(
                [
                    EnvironmentReferenceImage(
                        image_id=f"scene_{scene_id}_mood",
                        image_type="mood",
                        local_path=existing_mood,
                        description=f"Metadata-only scene mood for {scene_id}",
                    )
                ]
                if existing_mood
                else []
            ),
        )


class PreProductionReportWriter:
    """Persists pre-production reports with artifact-safe writes."""

    def write(self, path: Path, report: dict[str, Any]) -> None:
        atomic_write_yaml(path, report)
