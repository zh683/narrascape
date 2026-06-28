from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from narrascape.artifacts import validate_artifact
from narrascape.prompt_compiler import SCHEMA_VERSION, compile_video_prompts
from narrascape.stages.base import Stage, StageContext, StageResult


class DirectorContractStage(Stage):
    """Compile director thinking into prompts and QA assertions for every shot."""

    name = "director_contract"
    depends_on = ["screenplay_structure"]

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        design_path = self._first_existing(
            context.config.project_dir / "design_report.yaml",
            context.config.pipeline_dir / "design_report.yaml",
        )
        if not design_path.exists():
            return False, f"design_report.yaml not found: {design_path}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "director_contract.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        design = self._load_yaml(
            self._first_existing(
                config.project_dir / "design_report.yaml",
                config.pipeline_dir / "design_report.yaml",
            )
        )
        structure = self._load_yaml(config.pipeline_dir / "screenplay_structure.yaml")
        continuity = self._load_yaml(config.pipeline_dir / "continuity_bible.yaml")
        pre_production = self._load_yaml(config.pipeline_dir / "pre_production.yaml")
        storyboard_by_segment = self._storyboard_by_segment(pre_production)
        design_by_segment = self._design_by_segment(design)
        preproduction_index = self._preproduction_index(pre_production)

        llm_status = "not_configured"
        llm_error = ""
        if self.llm_client:
            try:
                shots = self._shots_from_llm(
                    design, structure, continuity, storyboard_by_segment, context
                )
                llm_status = "used"
            except Exception as exc:
                shots = self._compile_locally(
                    design_by_segment,
                    storyboard_by_segment,
                    preproduction_index,
                    context,
                )
                llm_status = "fallback_after_error"
                llm_error = str(exc)
        else:
            shots = self._compile_locally(
                design_by_segment,
                storyboard_by_segment,
                preproduction_index,
                context,
            )

        contract = {
            "schema_version": "director_contract.v1",
            "project": {"name": config.project.name, "title": config.project.title},
            "compile_process": {
                "mode": (
                    "llm_prompt_compiler"
                    if llm_status == "used"
                    else "deterministic_prompt_compiler"
                ),
                "llm_status": llm_status,
                "llm_error": llm_error,
            },
            "shots": shots,
        }
        validate_artifact("director_contract", contract)
        output.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(shots)} director contract shot(s)",
            metadata={"shot_count": len(shots), "contract": output.as_posix()},
        )

    def _shots_from_llm(
        self,
        design: dict[str, Any],
        structure: dict[str, Any],
        continuity: dict[str, Any],
        storyboard_by_segment: dict[int, list[dict[str, Any]]],
        context: StageContext,
    ) -> list[dict[str, Any]]:
        design_by_segment = self._design_by_segment(design)
        prompt = (
            "You are a top-tier film director and prompt compiler for AI video generation. "
            "For each shot, translate director thinking into an executable contract: story reason, "
            "emotional target, film language, continuity constraints, video prompt, negative prompt, "
            "duration, motion, storyboard binding, and QA assertions. Keep every artistic idea grounded in generation instructions.\n\n"
            f"Script: {json.dumps([segment.model_dump() for segment in context.script.segments], ensure_ascii=False)}\n"
            f"Design report: {json.dumps(design, ensure_ascii=False)}\n"
            f"Screenplay structure: {json.dumps(structure, ensure_ascii=False)}\n"
            f"Continuity bible: {json.dumps(continuity, ensure_ascii=False)}\n\n"
            f"Storyboard frames by segment: {json.dumps(storyboard_by_segment, ensure_ascii=False)}\n\n"
            'Return JSON only: {"shots":[{"segment_id":1,"story_reason":"...","emotional_target":"...",'
            '"film_language":{"shot_type":"...","camera_motion":"...","lighting":"...","composition":"..."},'
            '"continuity_constraints":{"characters":[],"location":"...","wardrobe":"...","lighting":"..."},'
            '"storyboard_binding":{"storyboard_frame_ids":[],"character_positions":[],"scene_ref":"...",'
            '"wardrobe_lock":"...","composition_requirements":[],"reference_image_ids":[]},'
            '"generation":{"video_prompt":"...","negative_prompt":"...","duration":5,"motion":"..."},'
            '"qa":{"must_show":[],"must_not_show":[]}}]}.'
        )
        response = self.llm_client.complete(prompt, json_mode=True)
        if hasattr(response, "extract_json_safe"):
            data = response.extract_json_safe(default={})
        else:
            data = json.loads(getattr(response, "content", "{}"))
        if not isinstance(data, dict):
            raise ValueError("LLM returned non-object JSON")
        shots = data.get("shots", [])
        if not isinstance(shots, list) or not shots:
            raise ValueError("LLM returned no shots")
        return [
            self._with_compiled_prompts(
                self._normalize_shot(item, design_by_segment, storyboard_by_segment, context)
            )
            for item in shots
        ]

    def _compile_locally(
        self,
        design_by_segment: dict[int, dict[str, Any]],
        storyboard_by_segment: dict[int, list[dict[str, Any]]],
        preproduction_index: dict[str, dict[str, dict[str, Any]]],
        context: StageContext,
    ) -> list[dict[str, Any]]:
        shots = []
        for segment in context.script.segments:
            segment_id = int(segment.id)
            design_item = design_by_segment.get(segment_id, {})
            frames = storyboard_by_segment.get(segment_id, [])
            metadata = (
                design_item.get("metadata", {})
                if isinstance(design_item.get("metadata"), dict)
                else {}
            )
            story_reason = self._story_reason(design_item, frames, segment.text)
            emotional_target = design_item.get("emotion") or "focused"
            shot_type = design_item.get("shot_type") or "medium"
            movement = design_item.get("movement") or "still"
            lighting = metadata.get("lighting_scheme") or "motivated cinematic lighting"
            storyboard_binding = self._storyboard_binding(segment_id, design_item, frames)
            characters = self._characters_from_design(design_item)
            if not characters:
                characters = self._characters_from_storyboard(frames)
            location = design_item.get("location_id") or storyboard_binding.get("scene_ref")
            character_profiles = preproduction_index["characters"]
            scene_profiles = preproduction_index["scenes"]
            wardrobe = (
                metadata.get("wardrobe")
                or storyboard_binding.get("wardrobe_lock")
                or self._wardrobe_for_characters(characters, character_profiles)
            )
            if wardrobe and not storyboard_binding.get("wardrobe_lock"):
                storyboard_binding["wardrobe_lock"] = wardrobe
            if not lighting or lighting == "motivated cinematic lighting":
                lighting = self._scene_lighting(location or "", scene_profiles) or lighting
            character_blocks = self._character_blocks(characters, character_profiles)
            scene_block = self._scene_block(location or "", scene_profiles)
            image_prompt = design_item.get("image_prompt") or segment.text
            negative = (
                metadata.get("negative_prompt")
                or "text, watermark, low quality, inconsistent character, extra characters"
            )
            show_target = ", ".join(characters) if characters else "the named character"
            location_text = location or "the specified scene"
            wardrobe_text = wardrobe or "the locked wardrobe"
            negative = self._video_negative_prompt(negative)
            video_prompt = (
                f"{story_reason} Emotional target: {emotional_target}. "
                f"{shot_type} shot, {movement} camera movement, {lighting}. "
                f"Show {show_target} in {location_text}, wearing {wardrobe_text}. "
                f"{character_blocks} {scene_block} "
                f"Keep {show_target} visible throughout the clip with the same face, age, body, and wardrobe from the reference image. "
                f"Maintain a character-led frame with clear story action and coherent scene geography. "
                f"Storyboard frames {', '.join(storyboard_binding['storyboard_frame_ids']) or 'none'}; "
                f"character positions: {', '.join(storyboard_binding['character_positions']) or 'unspecified'}; "
                f"composition requirements: {', '.join(storyboard_binding['composition_requirements']) or 'serve the story beat'}. "
                f"Visual details: {image_prompt}. Cinematic motion, coherent continuity, high quality."
            )
            shots.append(
                self._with_compiled_prompts(
                    {
                        "segment_id": segment_id,
                        "shot_id": f"shot_{segment_id:03d}",
                        "story_reason": story_reason,
                        "emotional_target": emotional_target,
                        "film_language": {
                            "shot_type": shot_type,
                            "camera_motion": movement,
                            "lighting": lighting,
                            "composition": metadata.get("composition")
                            or "composition serves the story beat",
                        },
                        "continuity_constraints": {
                            "characters": characters,
                            "location": location_text,
                            "wardrobe": wardrobe_text,
                            "lighting": lighting,
                        },
                        "storyboard_binding": storyboard_binding,
                        "generation": {
                            "video_prompt": video_prompt,
                            "negative_prompt": negative,
                            "duration": float(design_item.get("duration") or 5.0),
                            "motion": movement,
                        },
                        "qa": {
                            "must_show": self._must_show(characters, location, wardrobe),
                            "must_not_show": self._must_not_show(negative),
                        },
                    }
                )
            )
        return shots

    def _normalize_shot(
        self,
        shot: dict[str, Any],
        design_by_segment: dict[int, dict[str, Any]],
        storyboard_by_segment: dict[int, list[dict[str, Any]]],
        context: StageContext,
    ) -> dict[str, Any]:
        segment_id = int(shot.get("segment_id"))
        design_item = design_by_segment.get(segment_id, {})
        generation = shot.get("generation", {}) if isinstance(shot.get("generation"), dict) else {}
        qa = shot.get("qa", {}) if isinstance(shot.get("qa"), dict) else {}
        film_language = (
            shot.get("film_language", {}) if isinstance(shot.get("film_language"), dict) else {}
        )
        continuity = (
            shot.get("continuity_constraints", {})
            if isinstance(shot.get("continuity_constraints"), dict)
            else {}
        )
        storyboard_binding = self._storyboard_binding(
            segment_id,
            design_item,
            storyboard_by_segment.get(segment_id, []),
            (
                shot.get("storyboard_binding", {})
                if isinstance(shot.get("storyboard_binding"), dict)
                else {}
            ),
        )
        return {
            "segment_id": segment_id,
            "shot_id": shot.get("shot_id") or f"shot_{segment_id:03d}",
            "story_reason": shot.get("story_reason", ""),
            "emotional_target": shot.get("emotional_target", ""),
            "film_language": {
                "shot_type": film_language.get("shot_type", "medium"),
                "camera_motion": film_language.get("camera_motion", "still"),
                "lighting": film_language.get("lighting", ""),
                "composition": film_language.get("composition", ""),
            },
            "continuity_constraints": {
                "characters": list(continuity.get("characters") or []),
                "location": continuity.get("location", ""),
                "wardrobe": continuity.get("wardrobe", ""),
                "lighting": continuity.get("lighting", ""),
            },
            "storyboard_binding": storyboard_binding,
            "generation": {
                "video_prompt": self._append_storyboard_to_prompt(
                    generation.get("video_prompt", ""),
                    storyboard_binding,
                ),
                "negative_prompt": generation.get("negative_prompt", ""),
                "duration": float(generation.get("duration") or 5.0),
                "motion": generation.get("motion", film_language.get("camera_motion", "still")),
            },
            "qa": {
                "must_show": list(qa.get("must_show") or []),
                "must_not_show": list(qa.get("must_not_show") or []),
            },
        }

    def _with_compiled_prompts(self, shot: dict[str, Any]) -> dict[str, Any]:
        generation = shot.setdefault("generation", {})
        generation["prompt_schema_version"] = SCHEMA_VERSION
        generation["compiled_prompts"] = compile_video_prompts(shot)
        return shot

    def _must_show(self, characters: list[str], location: str, wardrobe: str) -> list[str]:
        values = [*characters, location, wardrobe]
        return [value for value in values if value]

    def _must_not_show(self, negative_prompt: str) -> list[str]:
        return [part.strip() for part in negative_prompt.split(",") if part.strip()]

    def _video_negative_prompt(self, negative_prompt: str) -> str:
        standard = [
            "still-life replacement",
            "empty room",
            "generic scenery",
            "unrelated props",
            "readable text",
            "watermark",
        ]
        parts = [part.strip() for part in str(negative_prompt or "").split(",") if part.strip()]
        lower_parts = {part.lower() for part in parts}
        for item in standard:
            if item.lower() not in lower_parts:
                parts.append(item)
        return ", ".join(parts)

    def _story_reason(
        self,
        design_item: dict[str, Any],
        frames: list[dict[str, Any]],
        segment_text: str,
    ) -> str:
        director_vision = str(design_item.get("director_vision") or "")
        if director_vision and not self._is_template_director_vision(director_vision):
            return director_vision
        for frame in frames:
            description = str(frame.get("description") or "").strip()
            if description:
                return f"Execute storyboard beat: {description}"
        return f"Translate the narration into a clear cinematic beat: {segment_text}"

    def _is_template_director_vision(self, value: str) -> bool:
        return value.lower().startswith("visualize the narration as a clear ")

    def _design_by_segment(self, design: dict[str, Any]) -> dict[int, dict[str, Any]]:
        return {
            int(item.get("segment_id")): item
            for item in design.get("segments", []) or []
            if item.get("segment_id") is not None
        }

    def _characters_from_design(self, design_item: dict[str, Any]) -> list[str]:
        return list(design_item.get("character_ids") or design_item.get("character_refs") or [])

    def _storyboard_by_segment(
        self, pre_production: dict[str, Any]
    ) -> dict[int, list[dict[str, Any]]]:
        frames = pre_production.get("storyboard", {}).get("frames", []) or []
        result: dict[int, list[dict[str, Any]]] = {}
        for frame in frames:
            try:
                segment_id = int(frame.get("segment_id"))
            except (TypeError, ValueError):
                continue
            result.setdefault(segment_id, []).append(frame)
        for segment_frames in result.values():
            segment_frames.sort(key=lambda item: int(item.get("frame_index") or 0))
        return result

    def _preproduction_index(
        self,
        pre_production: dict[str, Any],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        return {
            "characters": {
                str(item.get("char_id")): item
                for item in pre_production.get("characters", []) or []
                if item.get("char_id")
            },
            "scenes": {
                str(item.get("scene_id")): item
                for item in pre_production.get("environments", []) or []
                if item.get("scene_id")
            },
        }

    def _characters_from_storyboard(self, frames: list[dict[str, Any]]) -> list[str]:
        values = [ref for frame in frames for ref in (frame.get("character_refs") or [])]
        return self._list_or(values, [])

    def _wardrobe_for_characters(
        self,
        characters: list[str],
        character_profiles: dict[str, dict[str, Any]],
    ) -> str:
        wardrobes: list[str] = []
        for char_id in characters:
            profile = character_profiles.get(char_id, {})
            wardrobe = profile.get("default_outfit") or self._extract_identity_value(
                profile.get("identity_block", ""), "Wardrobe"
            )
            if wardrobe:
                wardrobes.append(str(wardrobe))
        if len(wardrobes) == 1:
            return wardrobes[0]
        labeled = []
        for char_id, wardrobe in zip(characters, wardrobes, strict=False):
            labeled.append(f"{char_id}: {wardrobe}")
        if labeled:
            return "; ".join(labeled)
        return "; ".join(wardrobes)

    def _character_blocks(
        self,
        characters: list[str],
        character_profiles: dict[str, dict[str, Any]],
    ) -> str:
        blocks = []
        for char_id in characters:
            profile = character_profiles.get(char_id, {})
            identity = profile.get("identity_block") or profile.get("name") or char_id
            blocks.append(f"{char_id} identity lock: {identity}")
        return " ".join(blocks)

    def _scene_block(
        self,
        scene_id: str,
        scene_profiles: dict[str, dict[str, Any]],
    ) -> str:
        scene = scene_profiles.get(scene_id, {})
        if not scene:
            return ""
        parts = [
            scene.get("scene_name") or scene_id,
            scene.get("description"),
            scene.get("lighting_signature"),
            scene.get("color_palette"),
        ]
        return "Scene lock: " + "; ".join(str(part) for part in parts if part) + "."

    def _scene_lighting(
        self,
        scene_id: str,
        scene_profiles: dict[str, dict[str, Any]],
    ) -> str:
        return str(scene_profiles.get(scene_id, {}).get("lighting_signature") or "")

    def _extract_identity_value(self, identity: str, label: str) -> str:
        marker = f"{label}:"
        if marker not in identity:
            return ""
        value = identity.split(marker, 1)[1]
        return value.split(".", 1)[0].strip()

    def _storyboard_binding(
        self,
        segment_id: int,
        design_item: dict[str, Any],
        frames: list[dict[str, Any]],
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = (
            design_item.get("metadata", {}) if isinstance(design_item.get("metadata"), dict) else {}
        )
        existing = existing or {}
        frame_ids = self._list_or(
            existing.get("storyboard_frame_ids"),
            [frame.get("frame_id") for frame in frames],
        )
        character_positions = self._list_or(
            existing.get("character_positions"),
            [pos for frame in frames for pos in (frame.get("character_positions") or [])],
        )
        scene_ref = existing.get("scene_ref") or self._first_value(
            frame.get("scene_ref") for frame in frames
        )
        composition_requirements = self._list_or(
            existing.get("composition_requirements"),
            [
                value
                for frame in frames
                for value in (frame.get("description"), frame.get("notes"))
                if value
            ],
        )
        reference_image_ids = self._list_or(
            existing.get("reference_image_ids"),
            [ref for frame in frames for ref in (frame.get("reference_image_ids") or [])],
        )
        return {
            "storyboard_frame_ids": frame_ids,
            "character_positions": character_positions,
            "scene_ref": scene_ref or design_item.get("location_id") or "",
            "wardrobe_lock": existing.get("wardrobe_lock") or metadata.get("wardrobe") or "",
            "composition_requirements": composition_requirements,
            "reference_image_ids": reference_image_ids,
        }

    def _append_storyboard_to_prompt(self, prompt: str, binding: dict[str, Any]) -> str:
        if not binding or not any(binding.values()):
            return prompt
        parts = [prompt] if prompt else []
        if binding.get("storyboard_frame_ids"):
            parts.append(f"Storyboard frames: {', '.join(binding['storyboard_frame_ids'])}.")
        if binding.get("scene_ref"):
            parts.append(f"Scene reference: {binding['scene_ref']}.")
        if binding.get("wardrobe_lock"):
            parts.append(f"Wardrobe lock: {binding['wardrobe_lock']}.")
        if binding.get("character_positions"):
            parts.append(f"Character positions: {', '.join(binding['character_positions'])}.")
        if binding.get("composition_requirements"):
            parts.append(
                f"Composition requirements: {', '.join(binding['composition_requirements'])}."
            )
        return " ".join(part for part in parts if part).strip()

    def _list_or(self, value: Any, fallback: list[Any]) -> list[str]:
        source = value if value else fallback
        result: list[str] = []
        for item in source or []:
            if item is None:
                continue
            text = str(item)
            if text and text not in result:
                result.append(text)
        return result

    def _first_value(self, values: Any) -> str:
        for value in values:
            if value:
                return str(value)
        return ""

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]
