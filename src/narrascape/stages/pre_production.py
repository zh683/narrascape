"""Pre-production stage — Generate character references, environment references, and storyboard.

Runs BEFORE DesignStage to produce:
- assets/references/character_*.png (character reference sheets)
- assets/references/scene_*.png (environment reference images)
- assets/storyboard/ (storyboard images if generated)
- pre_production.yaml (in pipeline dir, containing all metadata)

This stage is the "visual pre-production" of the AI director workflow:
1. Extract characters and scenes from the script
2. Generate character reference images (anchor, turns, expressions)
3. Generate environment reference images (mood, landmarks)
4. Generate storyboard frames based on script + references
5. Output pre_production.yaml for DesignStage to consume

Usage:
    PreProductionStage is automatically run before DesignStage in the pipeline.
    It can also be run standalone: narrascape pre_production
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import yaml

from narrascape.agent.models import (
    CharacterReferenceImage,
    CharacterReferenceSheet,
    EnvironmentReference,
    EnvironmentReferenceImage,
    PreProductionReport,
    Storyboard,
    StoryboardFrame,
)
from narrascape.api_keys import APIKeys
from narrascape.config import NarrascapeConfig, Script, load_script
from narrascape.prompt_safety import sanitize_prompt_for_provider
from narrascape.providers import select_provider
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.stages.generate_images import GenerateImagesStage

logger = logging.getLogger("narrascape.stages.pre_production")


# ═══════════════════════════════════════════════════════════════════
# PreProductionStage
# ═══════════════════════════════════════════════════════════════════


class PreProductionStage(Stage):
    """Pre-production stage: character refs, environment refs, storyboard.

    Outputs:
    - assets/references/character_*.png
    - assets/references/scene_*.png
    - pipeline/{name}/pre_production.yaml
    """

    name = "pre_production"
    depends_on = []  # Can run as early as possible (needs script)
    outputs = ["assets/references/", "pipeline/{name}/pre_production.yaml"]

    def __init__(
        self,
        llm_client: Any = None,
        style_template: str = "",
        generate_turns: bool = True,
        generate_expressions: bool = True,
        generate_storyboard: bool = True,
        max_characters: int = 5,
        max_scenes: int = 5,
        image_model: str = "doubao-seedream-5-0-260128",
        image_api_key: str | None = None,
    ):
        self.llm_client = llm_client
        self.style_template = style_template
        self.generate_turns = generate_turns
        self.generate_expressions = generate_expressions
        self.generate_storyboard = generate_storyboard
        self.max_characters = max_characters
        self.max_scenes = max_scenes
        self.image_model = image_model
        self.image_api_key = image_api_key

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        config = context.config
        if not config.script_path.exists():
            return False, f"Script not found: {config.script_path}"
        if config.images.provider.value == "local":
            return True, ""
        selection = select_provider(config, "image_generation", intent="reference")
        api_key = self._api_key_for_provider(selection.tool.provider)
        if not api_key:
            required = selection.tool.requires[0] if selection.tool.requires else "API key"
            return False, f"{required} not found. Required for reference image generation."
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        script = load_script(config.script_path)

        logger.info(f"[pre_production] Starting visual pre-production for: {config.project.name}")
        image_provider = self._image_provider(config)

        # Setup directories
        refs_dir = config.project_dir / "assets" / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        storyboard_dir = config.project_dir / "assets" / "storyboard"
        storyboard_dir.mkdir(parents=True, exist_ok=True)
        pipe_dir = config.pipeline_dir
        pipe_dir.mkdir(parents=True, exist_ok=True)

        if config.images.provider.value == "local":
            characters_data, scenes_data = self._extract_characters_and_scenes(script, config)
            character_sheets = [
                self._metadata_only_character_reference(item, refs_dir) for item in characters_data
            ]
            environment_refs = [
                self._metadata_only_environment_reference(item, refs_dir) for item in scenes_data
            ]
            storyboard = self._generate_storyboard_locally(
                script, character_sheets, environment_refs, config
            )
            report = PreProductionReport(
                project_title=config.project.title,
                style_template=self.style_template
                or (config.images.style if config.images else "cinematic documentary"),
                style_anchor_path="",
                characters=character_sheets,
                environments=environment_refs,
                storyboard=storyboard,
            )
            report_path = pipe_dir / "pre_production.yaml"
            with open(report_path, "w", encoding="utf-8") as f:
                yaml.dump(report.to_pre_production_report(), f, allow_unicode=True, sort_keys=False)
            return StageResult(
                stage_name=self.name,
                success=True,
                outputs={
                    "pre_production_report": str(report_path),
                    "references_dir": str(refs_dir),
                    "storyboard_dir": str(storyboard_dir),
                    "style_anchor_path": "",
                },
                metadata={
                    "character_count": len(character_sheets),
                    "scene_count": len(environment_refs),
                    "storyboard_frames": storyboard.total_frames,
                    "mode": "local",
                },
            )

        # ── Step 0: Generate unified style anchor (BEFORE any character or scene) ──
        unified_style = self.style_template or (
            config.images.style if config.images else "cinematic documentary"
        )
        style_anchor_path, _ = self._generate_style_anchor(refs_dir, config, image_provider)
        if style_anchor_path:
            logger.info(f"[pre_production] Style anchor: {style_anchor_path}")
        else:
            logger.warning(
                "[pre_production] No style anchor generated, character and scene references may have inconsistent styles"
            )

        # ── Step 1: Extract characters and scenes from script via LLM ──
        characters_data, scenes_data = self._extract_characters_and_scenes(script, config)
        logger.info(
            f"[pre_production] Extracted {len(characters_data)} characters, {len(scenes_data)} scenes"
        )

        # ── Step 2: Generate character reference images (with style anchor) ──
        character_sheets = []
        for char_data in characters_data:
            sheet = self._generate_character_reference(
                char_data,
                refs_dir,
                config,
                style_anchor_path=style_anchor_path,
                unified_style=unified_style,
                image_provider=image_provider,
            )
            character_sheets.append(sheet)
            logger.info(
                f"[pre_production] Character reference: {sheet.char_id} -> {sheet.primary_reference_path}"
            )

        # ── Step 3: Generate environment reference images (with style anchor) ──
        environment_refs = []
        for scene_data in scenes_data:
            env = self._generate_environment_reference(
                scene_data,
                refs_dir,
                config,
                style_anchor_path=style_anchor_path,
                unified_style=unified_style,
                image_provider=image_provider,
            )
            environment_refs.append(env)
            logger.info(
                f"[pre_production] Environment reference: {env.scene_id} -> {env.primary_reference_path}"
            )

        # ── Step 4: Generate storyboard ──
        storyboard = Storyboard(project_title=config.project.title)
        if self.generate_storyboard:
            storyboard = self._generate_storyboard(
                script, character_sheets, environment_refs, config
            )
            logger.info(
                f"[pre_production] Storyboard: {storyboard.total_frames} frames across {storyboard.total_segments} segments"
            )

        # ── Build report ──
        report = PreProductionReport(
            project_title=config.project.title,
            style_template=self.style_template
            or (config.images.style if config.images else "cinematic documentary"),
            style_anchor_path=style_anchor_path or "",
            characters=character_sheets,
            environments=environment_refs,
            storyboard=storyboard,
        )

        # ── Export ──
        report_path = pipe_dir / "pre_production.yaml"
        report_dict = report.to_pre_production_report()
        with open(report_path, "w", encoding="utf-8") as f:
            yaml.dump(report_dict, f, allow_unicode=True, sort_keys=False)
        logger.info(f"[pre_production] Wrote {report_path}")

        return StageResult(
            stage_name=self.name,
            success=True,
            outputs={
                "pre_production_report": str(report_path),
                "references_dir": str(refs_dir),
                "storyboard_dir": str(storyboard_dir),
                "style_anchor_path": style_anchor_path or "",
            },
            metadata={
                "character_count": len(character_sheets),
                "scene_count": len(environment_refs),
                "storyboard_frames": storyboard.total_frames,
            },
        )

    # ── Step 1: Extract characters and scenes ───────────────────────────

    def _extract_characters_and_scenes(
        self, script: Script, config: NarrascapeConfig
    ) -> tuple[list[dict], list[dict]]:
        """Extract characters and key scenes from the script using the configured LLM."""
        if not self.llm_client:
            logger.info(
                "[pre_production] No LLM client configured; using director notes/script fallback"
            )
            return self._extract_characters_and_scenes_locally(script, config)

        # Build script text for LLM analysis
        script_text = "\n\n".join(f"Segment {seg.id}:\n{seg.text}" for seg in script.segments)

        style = self.style_template or (
            config.images.style if config.images else "cinematic documentary"
        )

        prompt = f"""Analyze the following narration script and extract:
1. CHARACTERS: All distinct characters/entities with visual descriptions
2. SCENES: All key locations/environments with visual descriptions

For each character, provide:
- char_id: short unique ID (e.g., "char_001", "protagonist")
- name: character name if known, else descriptive label
- identity_block: detailed physical appearance description (face, hair, body, clothing, accessories, age, gender, ethnicity, build, posture, distinguishing features)
- face_description: specific facial features
- hair_description: hair color, length, style, texture
- body_description: body type, height, build, proportions
- default_outfit: what they typically wear
- signature_accessories: list of signature items
- negative_anchors: list of what this character is NOT (to prevent AI drift)
- expression_range: list of key emotions they express in the script

For each scene, provide:
- scene_id: short unique ID (e.g., "scene_001")
- scene_name: descriptive name
- scene_type: indoor, outdoor, urban, natural, abstract, etc.
- description: detailed visual description of the environment
- time_of_day: day, night, dawn, dusk, etc.
- weather: clear, rainy, foggy, snowy, etc.
- lighting_signature: dominant lighting style
- color_palette: dominant colors
- key_landmarks: notable features or objects in this scene
- mood: emotional atmosphere

Style context: {style}

Script:
{script_text}

Respond in strict JSON format:
{{
  "characters": [
    {{"char_id": "...", "name": "...", "identity_block": "...", ...}},
    ...
  ],
  "scenes": [
    {{"scene_id": "...", "scene_name": "...", "description": "...", ...}},
    ...
  ]
}}

Limit to max {self.max_characters} most important characters and {self.max_scenes} most important scenes.
"""

        try:
            response = self.llm_client.complete(prompt)
            # Extract JSON from response
            content = response.content if hasattr(response, "content") else str(response)
            # Try to find JSON block
            import re

            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(content)

            characters = data.get("characters", [])[: self.max_characters]
            scenes = data.get("scenes", [])[: self.max_scenes]
            return characters, scenes
        except Exception as e:
            logger.error(f"Failed to extract characters/scenes via LLM: {e}")
            logger.warning("[pre_production] Falling back to director notes/script extraction")
            return self._extract_characters_and_scenes_locally(script, config)

    def _extract_characters_and_scenes_locally(
        self, script: Script, config: NarrascapeConfig
    ) -> tuple[list[dict], list[dict]]:
        """Build usable character and scene metadata without an LLM.

        Curated projects can provide `director_notes.md`; generic projects fall back
        to script-derived scene anchors so pre-production can still run end to end.
        """
        notes_path = config.project_dir / "director_notes.md"
        if notes_path.exists():
            notes = notes_path.read_text(encoding="utf-8")
            characters = self._characters_from_director_notes(notes)[: self.max_characters]
            scenes = self._scenes_from_director_notes(notes)[: self.max_scenes]
            if characters or scenes:
                return characters, scenes

        return [], self._scenes_from_script(script)[: self.max_scenes]

    def _characters_from_director_notes(self, notes: str) -> list[dict]:
        sections = self._markdown_subsections(notes, "Character Bible")
        characters = []
        for raw_id, lines in sections:
            char_id = self._slug(raw_id)
            role = self._bullet_value(lines, "Role")
            age = self._bullet_value(lines, "Age")
            face = self._bullet_value(lines, "Face and body")
            wardrobe = self._bullet_value(lines, "Wardrobe lock")
            behavior = self._bullet_value(lines, "Behavior")
            negative = self._bullet_value(lines, "Negative anchors")
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
                    "signature_accessories": self._accessories_from_text(wardrobe),
                    "negative_anchors": [negative] if negative else [],
                    "expression_range": ["neutral", "tense", "fearful", "resolved"],
                }
            )
        return characters

    def _scenes_from_director_notes(self, notes: str) -> list[dict]:
        sections = self._markdown_subsections(notes, "Scene Bible")
        scenes = []
        for raw_id, lines in sections:
            scene_id = self._slug(raw_id)
            core = self._bullet_value(lines, "Core look")
            lighting = self._bullet_value(lines, "Lighting")
            continuity = self._bullet_value(lines, "Continuity")
            description = ". ".join(part for part in (core, continuity) if part) or raw_id
            scenes.append(
                {
                    "scene_id": scene_id,
                    "scene_name": raw_id.replace("_", " ").title(),
                    "scene_type": self._scene_type(description),
                    "description": description,
                    "time_of_day": self._time_of_day(description),
                    "weather": self._weather(description),
                    "lighting_signature": lighting or "naturalistic period lighting",
                    "color_palette": self._color_palette(description, lighting),
                    "key_landmarks": self._landmarks_from_text(description),
                    "mood": "psychological pressure",
                }
            )
        return scenes

    def _scenes_from_script(self, script: Script) -> list[dict]:
        scenes = []
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

    def _markdown_subsections(self, markdown: str, heading: str) -> list[tuple[str, list[str]]]:
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

    def _bullet_value(self, lines: list[str], label: str) -> str:
        prefix = f"- {label}:"
        for line in lines:
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        return ""

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9_]+", "_", value.lower().replace("-", "_")).strip("_")
        return slug or "item"

    def _accessories_from_text(self, text: str) -> list[str]:
        accessories = []
        for keyword in ("cross", "key", "watch", "spectacles", "cap", "shawl", "coat"):
            if keyword in text.lower():
                accessories.append(keyword)
        return accessories

    def _scene_type(self, text: str) -> str:
        lower = text.lower()
        if any(word in lower for word in ("room", "office", "flat", "apartment")):
            return "indoor"
        if any(word in lower for word in ("street", "yard", "canal", "river", "square")):
            return "urban"
        return "environment"

    def _time_of_day(self, text: str) -> str:
        lower = text.lower()
        if "dawn" in lower:
            return "dawn"
        if "night" in lower:
            return "night"
        if "candle" in lower:
            return "evening"
        return "day"

    def _weather(self, text: str) -> str:
        lower = text.lower()
        if "snow" in lower:
            return "snow"
        if "rain" in lower or "wet" in lower:
            return "rain"
        if "fog" in lower:
            return "fog"
        return "clear"

    def _color_palette(self, description: str, lighting: str) -> str:
        lower = f"{description} {lighting}".lower()
        colors = [
            color
            for color in ("yellow", "gray", "green", "brown", "black", "snow")
            if color in lower
        ]
        return ", ".join(colors) if colors else "muted period palette"

    def _landmarks_from_text(self, text: str) -> list[str]:
        lower = text.lower()
        landmarks = []
        for keyword in ("canal", "door", "keys", "icon", "candle", "river", "snow", "cobblestones"):
            if keyword in lower:
                landmarks.append(keyword)
        return landmarks[:3]

    def _storyboard_intent_from_notes(self, config: NarrascapeConfig) -> dict[str, str]:
        notes_path = config.project_dir / "director_notes.md"
        if not notes_path.exists():
            return {}
        notes = notes_path.read_text(encoding="utf-8")
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

    def _storyboard_scene_from_text(
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

    def _storyboard_characters_from_text(
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

    def _metadata_only_character_reference(
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

    def _metadata_only_environment_reference(
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

    # ── Step 0: Generate unified style anchor ───────────────────────────

    def _image_provider(self, config: NarrascapeConfig) -> str:
        selection = select_provider(config, "image_generation", intent="reference")
        return selection.tool.provider

    def _api_key_for_provider(self, provider: str) -> str | None:
        if self.image_api_key:
            return self.image_api_key
        if provider == "agnes":
            return APIKeys.agnes()
        return APIKeys.ark()

    def _sleep_after_provider_request(self, provider: str) -> None:
        if provider == "agnes":
            time.sleep(65.0)

    def _generate_style_anchor(
        self, refs_dir: Path, config: NarrascapeConfig, image_provider: str
    ) -> tuple[str | None, str]:
        """Generate a unified style anchor image that defines the visual style for ALL references.

        Based on Seedream 5.0 research:
        - Seedream 5.0 supports up to 14 reference images with "feature migration"
        - The reference image defines the overall visual style (tone, lighting, rendering quality)
        - Prompt must explicitly reference the image (e.g., "reference image 1's style")
        - Low sample_strength (0.2-0.4) for style-only migration, high (0.6-0.8) for content+style

        This image is a simple still-life/nature scene without characters. It establishes:
        - Art style (realistic, painterly, anime, etc.)
        - Color palette
        - Lighting quality
        - Texture level
        - Rendering style
        """
        style = self.style_template or (
            config.images.style if config.images else "cinematic documentary"
        )

        # CRITICAL: The prompt must be a complete, self-contained image description.
        # Seedream 5.0 uses the reference image for style migration, but the prompt
        # must still describe a coherent image. Avoid "style-only" prompts that
        # just list adjectives — Seedream 5.0 works best with a concrete scene
        # + reference image for style guidance.
        style_anchor_prompt = (
            f"A simple still-life scene showing a ceramic vase with a single flower on a wooden table, "
            f"near a window with soft natural light streaming in, "
            f"{style}, "
            f"consistent artistic style, uniform rendering quality, "
            f"detailed textures, balanced composition, "
            f"no people, no characters, no text, no logos, "
            f"clean background, subtle shadows, warm and cool color balance"
        )

        anchor_name = "style_anchor"
        anchor_path = refs_dir / f"{anchor_name}.png"

        if anchor_path.exists():
            logger.info(f"[pre_production] Style anchor exists: {anchor_path}")
            return str(anchor_path), style

        img_gen = GenerateImagesStage(
            api_key=self._api_key_for_provider(image_provider),
            model=self.image_model,
            uploader_backend="base64",
        )

        # Seedream 5.0: no reference for the anchor itself, but use seed for consistency
        # Use a fixed seed for reproducibility if possible (seedream 5.0 supports seed)
        anchor_ok = img_gen._generate_one(
            prompt=style_anchor_prompt,
            out_name=anchor_name,
            size="1920x1920",
            ref_image=None,
            images_dir=refs_dir,
            model=self.image_model,
            sample_strength=0.3,  # Low strength: we want this to be the BASE style, not heavily influenced
            seed=42,  # Fixed seed for reproducibility
            provider=image_provider,
        )
        self._sleep_after_provider_request(image_provider)

        if anchor_ok and anchor_path.exists():
            logger.info(f"[pre_production] Generated style anchor: {anchor_path}")
            return str(anchor_path), style
        else:
            logger.warning(
                "[pre_production] Failed to generate style anchor, proceeding without it"
            )
            return None, style

    # ── Step 2: Generate character references ───────────────────────────

    def _generate_character_reference(
        self,
        char_data: dict,
        refs_dir: Path,
        config: NarrascapeConfig,
        style_anchor_path: str | None = None,
        unified_style: str = "cinematic documentary",
        image_provider: str = "seedream",
    ) -> CharacterReferenceSheet:
        """Generate a complete reference sheet for a single character.

        Strategy:
        1. Generate anchor image using style_anchor as reference (for style consistency)
        2. Use anchor as reference to generate turn views (for character consistency)
        3. Use anchor as reference to generate key expressions (for character consistency)
        """
        char_id = char_data["char_id"]
        name = char_data.get("name", char_id)
        identity = char_data.get("identity_block", "")
        style = unified_style
        provider_identity = sanitize_prompt_for_provider(image_provider, identity)
        provider_style = sanitize_prompt_for_provider(image_provider, style)

        sheet = CharacterReferenceSheet(
            char_id=char_id,
            name=name,
            identity_block=identity,
            seedream_model=char_data.get("seedream_model", "jimeng-4.6"),
            seedream_sample_strength=char_data.get("seedream_sample_strength", 0.7),
        )

        # Create image generator helper
        img_gen = GenerateImagesStage(
            api_key=self._api_key_for_provider(image_provider),
            model=self.image_model,
            uploader_backend="base64",
        )

        # ── 2.1 Anchor image (正面全身锚点图) ──
        # CRITICAL: Use style_anchor as reference for style consistency.
        # Seedream 5.0 "feature migration": reference image defines the visual style.
        # Prompt must explicitly reference the image ("参考图1的风格") for best results.
        # sample_strength: 0.6 = moderate influence (style + rendering quality from ref)
        anchor_prompt = (
            "Use reference image 1 for style, color, lighting, and rendering quality. "
            f"Full-body character reference portrait for {name}: {provider_identity}. "
            "Neutral standing pose, calm restrained expression, clean pale gray studio backdrop, "
            f"{provider_style}. "
            "Clear face, locked wardrobe details, realistic human proportions, fine fabric texture, "
            "single character only, no text, no watermark."
        )
        anchor_name = f"char_{char_id}_anchor"
        anchor_path = refs_dir / f"{anchor_name}.png"

        if anchor_path.exists():
            logger.info(f"  Anchor exists: {anchor_path}")
            anchor_ok = True
        else:
            # CRITICAL: Pass style_anchor as reference image
            # When using multiple refs, order matters: [style_anchor, character_ref]
            ref_for_character = style_anchor_path if style_anchor_path else None
            anchor_ok = img_gen._generate_one(
                prompt=anchor_prompt,
                out_name=anchor_name,
                size="1920x1920",
                ref_image=ref_for_character,
                images_dir=refs_dir,
                model=self.image_model,
                sample_strength=0.6,  # Moderate: inherit style from anchor, but character is new
                provider=image_provider,
            )
            self._sleep_after_provider_request(image_provider)

        if anchor_ok:
            anchor_img = CharacterReferenceImage(
                image_id=anchor_name,
                image_type="anchor",
                local_path=str(anchor_path),
                prompt=anchor_prompt,
                model=sheet.seedream_model,
                sample_strength=sheet.seedream_sample_strength,
                description=f"正面全身锚点图 for {name}",
            )
            sheet.anchor_image = anchor_img
            sheet.primary_reference_path = str(anchor_path)

        # ── 2.2 Turn views (转面图) ──
        if self.generate_turns and sheet.primary_reference_path:
            turns = [
                ("turn_front", "正面视图"),
                ("turn_side", "侧面轮廓"),
                ("turn_back", "背面视图"),
            ]
            for turn_type, view_desc in turns:
                turn_name = f"char_{char_id}_{turn_type}"
                turn_path = refs_dir / f"{turn_name}.png"
                if turn_path.exists():
                    sheet.turn_images.append(
                        CharacterReferenceImage(
                            image_id=turn_name,
                            image_type=turn_type,
                            local_path=str(turn_path),
                            description=f"{view_desc} for {name}",
                        )
                    )
                    continue

                # CRITICAL: Use BOTH style_anchor + character_anchor for consistency
                # Character anchor ensures identity, style anchor ensures style
                turn_refs = []
                if style_anchor_path:
                    turn_refs.append(style_anchor_path)
                if sheet.primary_reference_path:
                    turn_refs.append(sheet.primary_reference_path)

                turn_prompt = (
                    "Use reference image 1 for visual style and reference image 2 for the same character identity. "
                    f"{view_desc} full-body character turnaround for {name}: {provider_identity}. "
                    "Maintain the exact same face, hairstyle, clothing, body proportions, and posture language. "
                    f"{provider_style}. Clean pale gray background, consistent rendering quality, no text, no watermark."
                )
                turn_ok = img_gen._generate_one(
                    prompt=turn_prompt,
                    out_name=turn_name,
                    size="1920x1920",
                    ref_image=turn_refs if turn_refs else sheet.primary_reference_path,
                    images_dir=refs_dir,
                    model=self.image_model,
                    sample_strength=0.7,  # Higher: keep character identity + style
                    provider=image_provider,
                )
                self._sleep_after_provider_request(image_provider)
                if turn_ok:
                    sheet.turn_images.append(
                        CharacterReferenceImage(
                            image_id=turn_name,
                            image_type=turn_type,
                            local_path=str(turn_path),
                            prompt=turn_prompt,
                            model=sheet.seedream_model,
                            sample_strength=sheet.seedream_sample_strength,
                            description=f"{view_desc} for {name}",
                        )
                    )

        # ── 2.3 Key expressions (表情图) ──
        if self.generate_expressions and sheet.primary_reference_path:
            expressions = char_data.get("expression_range", ["neutral", "happy", "sad", "angry"])
            for expr in expressions[:4]:  # Max 4 expressions
                expr_name = f"char_{char_id}_expr_{expr}"
                expr_path = refs_dir / f"{expr_name}.png"
                if expr_path.exists():
                    sheet.expression_images.append(
                        CharacterReferenceImage(
                            image_id=expr_name,
                            image_type=f"expression_{expr}",
                            local_path=str(expr_path),
                            description=f"{expr} expression for {name}",
                        )
                    )
                    continue

                # CRITICAL: Use BOTH style_anchor + character_anchor
                expr_refs = []
                if style_anchor_path:
                    expr_refs.append(style_anchor_path)
                if sheet.primary_reference_path:
                    expr_refs.append(sheet.primary_reference_path)

                expr_prompt = (
                    "Use reference image 1 for visual style and reference image 2 for the same character identity. "
                    f"Head-and-shoulders expression sheet for {name}: {provider_identity}. "
                    f"Expression: {expr}. Keep the same face shape, hair, wardrobe, and proportions. "
                    f"{provider_style}. Clean pale gray background, detailed but restrained facial emotion, "
                    "consistent rendering quality, no text, no watermark."
                )
                expr_ok = img_gen._generate_one(
                    prompt=expr_prompt,
                    out_name=expr_name,
                    size="1920x1920",
                    ref_image=expr_refs if expr_refs else sheet.primary_reference_path,
                    images_dir=refs_dir,
                    model=self.image_model,
                    sample_strength=0.7,  # Higher: keep character identity + style
                    provider=image_provider,
                )
                self._sleep_after_provider_request(image_provider)
                if expr_ok:
                    sheet.expression_images.append(
                        CharacterReferenceImage(
                            image_id=expr_name,
                            image_type=f"expression_{expr}",
                            local_path=str(expr_path),
                            prompt=expr_prompt,
                            model=sheet.seedream_model,
                            sample_strength=sheet.seedream_sample_strength,
                            description=f"{expr} expression for {name}",
                        )
                    )

        return sheet

    # ── Step 3: Generate environment references ───────────────────────────

    def _generate_environment_reference(
        self,
        scene_data: dict,
        refs_dir: Path,
        config: NarrascapeConfig,
        style_anchor_path: str | None = None,
        unified_style: str = "cinematic documentary",
        image_provider: str = "seedream",
    ) -> EnvironmentReference:
        """Generate reference images for a single environment/scene.

        Strategy:
        1. Generate mood image using style_anchor as reference (for style consistency with characters)
        2. Optionally generate landmark image using style_anchor as reference
        """
        scene_id = scene_data["scene_id"]
        scene_name = scene_data.get("scene_name", scene_id)
        description = scene_data.get("description", "")
        time_of_day = scene_data.get("time_of_day", "day")
        weather = scene_data.get("weather", "clear")
        lighting = scene_data.get("lighting_signature", "")
        color_palette = scene_data.get("color_palette", "")
        style = unified_style
        provider_description = sanitize_prompt_for_provider(image_provider, description)
        provider_lighting = sanitize_prompt_for_provider(image_provider, lighting)
        provider_palette = sanitize_prompt_for_provider(image_provider, color_palette)
        provider_style = sanitize_prompt_for_provider(image_provider, style)

        env = EnvironmentReference(
            scene_id=scene_id,
            scene_name=scene_name,
            scene_type=scene_data.get("scene_type", "outdoor"),
            time_of_day=time_of_day,
            weather=weather,
            lighting_signature=lighting,
            color_palette=color_palette,
        )

        img_gen = GenerateImagesStage(
            api_key=self._api_key_for_provider(image_provider),
            model=self.image_model,
            uploader_backend="base64",
        )

        # ── 3.1 Mood image (氛围图) ──
        # CRITICAL: Use style_anchor as reference for style consistency.
        # Prompt must explicitly reference the image ("参考图1的风格") for best results.
        # sample_strength: 0.3 = low influence (only style from ref, content is new scene)
        mood_prompt = (
            "Use reference image 1 for style, color, lighting, and rendering quality. "
            f"Pure environment reference image: {provider_description}. "
            f"Time of day: {time_of_day}. Weather: {weather}. "
            f"Lighting: {provider_lighting}. Palette: {provider_palette}. "
            f"{provider_style}. Wide establishing composition, atmospheric perspective, highly detailed period setting, "
            "no people, no characters, no text, no watermark."
        )
        mood_name = f"scene_{scene_id}_mood"
        mood_path = refs_dir / f"{mood_name}.png"

        if mood_path.exists():
            logger.info(f"  Mood exists: {mood_path}")
            mood_ok = True
        else:
            mood_ok = img_gen._generate_one(
                prompt=mood_prompt,
                out_name=mood_name,
                size="2560x1440",
                ref_image=style_anchor_path,  # CRITICAL: use style anchor for consistency!
                images_dir=refs_dir,
                model=self.image_model,
                sample_strength=0.3,  # Low: only extract style, not content
                provider=image_provider,
            )
            self._sleep_after_provider_request(image_provider)

        if mood_ok:
            env.mood_images.append(
                EnvironmentReferenceImage(
                    image_id=mood_name,
                    image_type="mood",
                    local_path=str(mood_path),
                    prompt=mood_prompt,
                    model=self.image_model,
                    description=f"氛围图 for {scene_name}",
                )
            )
            env.primary_reference_path = str(mood_path)

        # ── 3.2 Landmark image (地标图) ──
        landmarks = scene_data.get("key_landmarks", [])
        if landmarks and image_provider != "agnes":
            landmark_desc = landmarks[0] if isinstance(landmarks, list) else landmarks
            provider_landmark = sanitize_prompt_for_provider(image_provider, str(landmark_desc))
            landmark_prompt = (
                "Use reference image 1 for style, color, lighting, and rendering quality. "
                f"Environment landmark reference: {provider_description}. "
                f"Focus on {provider_landmark}. Time of day: {time_of_day}. Weather: {weather}. "
                f"{provider_style}. Detailed architectural and location features, consistent rendering quality, "
                "no people, no text, no watermark."
            )
            landmark_name = f"scene_{scene_id}_landmark"
            landmark_path = refs_dir / f"{landmark_name}.png"

            if not landmark_path.exists():
                landmark_ok = img_gen._generate_one(
                    prompt=landmark_prompt,
                    out_name=landmark_name,
                    size="2560x1440",
                    ref_image=style_anchor_path,  # CRITICAL: use style anchor for consistency!
                    images_dir=refs_dir,
                    model=self.image_model,
                    sample_strength=0.3,  # Low: only extract style, not content
                    provider=image_provider,
                )
                self._sleep_after_provider_request(image_provider)
                if landmark_ok:
                    env.landmark_images.append(
                        EnvironmentReferenceImage(
                            image_id=landmark_name,
                            image_type="landmark",
                            local_path=str(landmark_path),
                            prompt=landmark_prompt,
                            model=self.image_model,
                            description=f"地标图 for {scene_name}",
                        )
                    )
            else:
                env.landmark_images.append(
                    EnvironmentReferenceImage(
                        image_id=landmark_name,
                        image_type="landmark",
                        local_path=str(landmark_path),
                        description=f"地标图 for {scene_name}",
                    )
                )

        return env

    # ── Step 4: Generate storyboard ───────────────────────────

    def _generate_storyboard(
        self,
        script: Script,
        character_sheets: list[CharacterReferenceSheet],
        environment_refs: list[EnvironmentReference],
        config: NarrascapeConfig,
    ) -> Storyboard:
        """Generate storyboard frames using LLM.

        For each script segment, generate 1-3 storyboard frames that describe
        the visual composition, camera movement, and character positions.
        """
        if not self.llm_client:
            return self._generate_storyboard_locally(
                script, character_sheets, environment_refs, config
            )

        style = self.style_template or (
            config.images.style if config.images else "cinematic documentary"
        )

        # Build character reference summary for LLM
        char_summary = []
        for sheet in character_sheets:
            char_summary.append(
                {
                    "char_id": sheet.char_id,
                    "name": sheet.name,
                    "identity": sheet.identity_block,
                    "reference_path": sheet.primary_reference_path,
                }
            )

        # Build scene reference summary for LLM
        scene_summary = []
        for env in environment_refs:
            scene_summary.append(
                {
                    "scene_id": env.scene_id,
                    "scene_name": env.scene_name,
                    "scene_type": env.scene_type,
                    "reference_path": env.primary_reference_path,
                    "time_of_day": env.time_of_day,
                    "weather": env.weather,
                    "lighting": env.lighting_signature,
                    "color_palette": env.color_palette,
                }
            )

        storyboard = Storyboard(project_title=config.project.title)
        total_frames = 0

        for seg in script.segments:
            seg_text = seg.text
            seg_id = seg.id

            prompt = f"""Design a storyboard for the following script segment.

Segment {seg_id}:
{seg_text}

Characters available:
{json.dumps(char_summary, ensure_ascii=False, indent=2)}

Scenes available:
{json.dumps(scene_summary, ensure_ascii=False, indent=2)}

Style: {style}

For this segment, design 1-3 storyboard frames. Each frame should be a key visual moment.

For each frame, provide:
- frame_id: "sb_{seg_id:02d}_01" (or _02, _03)
- description: detailed visual description including composition, character positions, action
- shot_type: wide, medium, close-up, extreme_close-up, etc.
- camera_movement: static, pan, tilt, dolly, zoom, track, etc.
- camera_angle: eye-level, low-angle, high-angle, overhead, dutch, etc.
- character_positions: where each character is in the frame (e.g., "protagonist center-left, looking right")
- emotion: the emotional tone of this frame
- duration_hint: suggested duration in seconds (2-8)
- character_refs: which characters appear
- scene_ref: which scene this takes place in
- reference_image_ids: which reference images should be used
- notes: director notes

Respond in strict JSON format:
{{
  "frames": [
    {{"frame_id": "...", "description": "...", "shot_type": "...", ...}},
    ...
  ]
}}

Guidelines:
- Ensure visual variety across frames (don't repeat same shot type)
- Match character positions to the script action
- Use appropriate camera movement for the emotion
- Reference the correct character and scene images
- Frame 1 should establish the scene, Frame 2 should show the action/moment, Frame 3 (if needed) should show reaction or transition
"""

            try:
                response = self.llm_client.complete(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                import re

                json_match = re.search(r"\{{.*?\}}", content, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    data = json.loads(content)

                frames_data = data.get("frames", [])
                for idx, frame_data in enumerate(frames_data):
                    frame = StoryboardFrame(
                        frame_id=frame_data.get("frame_id", f"sb_{seg_id:02d}_{idx+1:02d}"),
                        segment_id=seg_id,
                        frame_index=idx,
                        description=frame_data.get("description", ""),
                        shot_type=frame_data.get("shot_type", ""),
                        camera_movement=frame_data.get("camera_movement", ""),
                        camera_angle=frame_data.get("camera_angle", ""),
                        character_positions=frame_data.get("character_positions", []),
                        emotion=frame_data.get("emotion", ""),
                        duration_hint=frame_data.get("duration_hint", 3.0),
                        character_refs=frame_data.get("character_refs", []),
                        scene_ref=frame_data.get("scene_ref", ""),
                        reference_image_ids=frame_data.get("reference_image_ids", []),
                        notes=frame_data.get("notes", ""),
                    )
                    storyboard.frames.append(frame)
                    total_frames += 1

            except Exception as e:
                logger.error(f"Failed to generate storyboard for segment {seg_id}: {e}")
                # Fallback: create a single frame with the segment text
                storyboard.frames.append(
                    StoryboardFrame(
                        frame_id=f"sb_{seg_id:02d}_01",
                        segment_id=seg_id,
                        frame_index=0,
                        description=seg_text[:200],
                        shot_type="medium",
                        emotion="neutral",
                        duration_hint=3.0,
                    )
                )
                total_frames += 1

        storyboard.total_frames = total_frames
        storyboard.total_segments = len(script.segments)
        return storyboard

    def _generate_storyboard_locally(
        self,
        script: Script,
        character_sheets: list[CharacterReferenceSheet],
        environment_refs: list[EnvironmentReference],
        config: NarrascapeConfig,
    ) -> Storyboard:
        storyboard = Storyboard(project_title=config.project.title)
        character_ids = [sheet.char_id for sheet in character_sheets]
        scene_ids = [env.scene_id for env in environment_refs]
        style_anchor_ids = (
            ["style_anchor"]
            if (config.project_dir / "assets" / "references" / "style_anchor.png").exists()
            else []
        )
        storyboard_intents = self._storyboard_intent_from_notes(config)

        for index, seg in enumerate(script.segments):
            frame_id = f"sb_{seg.id:02d}_01"
            intent = storyboard_intents.get(frame_id, "")
            scene_ref = self._storyboard_scene_from_text(intent, scene_ids) if intent else ""
            if not scene_ref:
                scene_ref = scene_ids[min(index, len(scene_ids) - 1)] if scene_ids else ""
            character_source = f"{intent} {seg.text}"
            frame_character_ids = [
                char_id
                for char_id in character_ids
                if char_id.replace("_", " ").lower() in character_source.lower()
            ]
            for char_id in self._storyboard_characters_from_text(character_source, character_ids):
                if char_id not in frame_character_ids:
                    frame_character_ids.append(char_id)
            if not frame_character_ids and character_ids:
                frame_character_ids = character_ids[:1]
            reference_ids = style_anchor_ids + frame_character_ids
            if scene_ref:
                reference_ids.append(f"{scene_ref}_mood")

            storyboard.frames.append(
                StoryboardFrame(
                    frame_id=frame_id,
                    segment_id=seg.id,
                    frame_index=0,
                    description=(intent or seg.text)[:220],
                    shot_type=(seg.shot_type.value if seg.shot_type else "medium"),
                    camera_movement="static",
                    camera_angle="eye-level",
                    character_positions=[
                        f"{char_id} holds the dramatic focus in frame"
                        for char_id in frame_character_ids
                    ],
                    emotion="psychological tension",
                    duration_hint=3.0,
                    character_refs=frame_character_ids,
                    scene_ref=scene_ref,
                    reference_image_ids=reference_ids,
                    notes="Local fallback storyboard generated from script and director notes.",
                )
            )

        storyboard.total_frames = len(storyboard.frames)
        storyboard.total_segments = len(script.segments)
        return storyboard
