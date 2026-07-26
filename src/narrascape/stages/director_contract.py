from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from narrascape.artifacts import write_artifact
from narrascape.catalog import design_report_candidates
from narrascape.contracts import DirectorContract
from narrascape.contracts.qa_taxonomy import QA_DIMENSIONS, normalize_assertions
from narrascape.director_contract_quality import contract_semantic_errors
from narrascape.llm import PromptTemplate, is_assistant_bridge_provider
from narrascape.prompt_compiler import SCHEMA_VERSION, compile_video_prompts
from narrascape.stages.base import Stage, StageContext, StageResult


class DirectorContractStage(Stage):
    """Compile director thinking into prompts and QA assertions for every shot."""

    name = "director_contract"
    depends_on = ["screenplay_structure"]

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client
        self._style_anchor = "cinematic, coherent with the project style bible"
        self._provider_flow = "first_frame_plus_references"
        self._coverage_mode = "single"
        self._max_coverage_shots = 1

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        design_path = self._first_existing(*design_report_candidates(context.config))
        if not design_path.exists():
            return False, f"design_report.yaml not found: {design_path}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        self._style_anchor = str(config.images.style or self._style_anchor)
        image_provider = str(getattr(config.images.provider, "value", config.images.provider))
        video_provider = str(getattr(config.video.provider, "value", config.video.provider))
        self._provider_flow = f"{image_provider}_to_{video_provider}"
        self._coverage_mode = str(config.video.coverage_mode)
        self._max_coverage_shots = (
            int(config.video.max_coverage_shots) if self._coverage_mode == "director" else 1
        )
        output = config.pipeline_dir / "director_contract.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        design = self._load_yaml(self._first_existing(*design_report_candidates(config)))
        structure = self._load_yaml(config.pipeline_dir / "screenplay_structure.yaml")
        continuity = self._load_yaml(config.pipeline_dir / "continuity_bible.yaml")
        pre_production = self._load_yaml(config.pipeline_dir / "pre_production.yaml")
        storyboard_by_segment = self._storyboard_by_segment(pre_production)
        design_by_segment = self._design_by_segment(design)
        preproduction_index = self._preproduction_index(pre_production)
        rewrite_segment_ids = self._segment_ids_from_queue(
            config.pipeline_dir / "director_contract_rewrite_queue.yaml"
        )

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
        if rewrite_segment_ids:
            previous_contract = self._load_yaml(output)
            shots = self._merge_rewritten_shots(
                previous_contract.get("shots", []),
                shots,
                rewrite_segment_ids,
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
                "rework_segment_ids": sorted(rewrite_segment_ids),
            },
            "shots": shots,
        }
        # Structural/type validation runs first so malformed values retain the
        # precise Pydantic error contract expected by callers.
        DirectorContract.model_validate(contract)
        semantic_errors = contract_semantic_errors(
            shots,
            expected_segment_ids=[int(segment.id) for segment in context.script.segments],
            max_shots_per_segment=self._max_coverage_shots,
            require_advanced=True,
            require_compiled=True,
        )
        if semantic_errors:
            raise ValueError(
                "director contract semantic validation failed: " + "; ".join(semantic_errors)
            )
        write_artifact("director_contract", output, contract)
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
        if self._per_segment_llm_calls(context):
            # llm.bridge_batch=false: one small task per shot so assistants
            # answer reliably; each task carries only that segment's slice.
            raw_shots: list[dict[str, Any]] = []
            for segment in context.script.segments:
                segment_id = int(segment.id)
                prompt = self._llm_prompt(
                    [segment.model_dump()],
                    {**design, "segments": [design_by_segment.get(segment_id, {})]},
                    structure,
                    continuity,
                    {segment_id: storyboard_by_segment.get(segment_id, [])},
                    scope_note=(
                        f"Design the contract for segment {segment_id} ONLY. "
                        'Return JSON only: {"shots":[<ordered shot objects>]} using the schema above.'
                    ),
                )
                data = self._request_shots(
                    prompt,
                    [segment_id],
                    max_shots_per_segment=self._max_coverage_shots,
                )
                items = data["shots"]
                raw_shots.extend(items)
        else:
            prompt = self._llm_prompt(
                [segment.model_dump() for segment in context.script.segments],
                design,
                structure,
                continuity,
                storyboard_by_segment,
                scope_note="",
            )
            expected_ids = [int(segment.id) for segment in context.script.segments]
            data = self._request_shots(
                prompt,
                expected_ids,
                max_shots_per_segment=self._max_coverage_shots,
            )
            raw_shots = data["shots"]
        if not isinstance(raw_shots, list) or not raw_shots:
            raise ValueError("LLM returned no shots")
        normalized = [
            self._with_compiled_prompts(
                self._normalize_shot(item, design_by_segment, storyboard_by_segment, context)
            )
            for item in raw_shots
        ]
        normalized.sort(key=lambda item: (int(item["segment_id"]), int(item["shot_order"])))
        errors = contract_semantic_errors(
            normalized,
            expected_segment_ids=[int(segment.id) for segment in context.script.segments],
            max_shots_per_segment=self._max_coverage_shots,
            require_advanced=True,
            require_compiled=True,
        )
        if errors:
            raise ValueError(
                "LLM director contract is semantically incomplete: " + "; ".join(errors)
            )
        return normalized

    def _request_shots(
        self,
        prompt: str,
        expected_ids: list[int],
        *,
        max_shots_per_segment: int = 1,
    ) -> dict[str, Any]:
        """Request and strictly validate the shot set before normalization."""
        validated = getattr(self.llm_client, "run_template_validated", None)
        require_exact_ids = callable(validated) or len(expected_ids) == 1

        def validator(data: Any) -> tuple[bool, str]:
            valid, error = self._validate_shot_response(
                data,
                expected_ids,
                require_exact_ids,
                max_shots_per_segment=max_shots_per_segment,
            )
            if not valid:
                return valid, error
            if not isinstance(data, dict):
                return False, "response must be a JSON object"
            shots = data.get("shots", [])
            errors = contract_semantic_errors(
                shots,
                expected_segment_ids=expected_ids,
                max_shots_per_segment=max_shots_per_segment,
                require_advanced=True,
                require_compiled=False,
            )
            return (not errors, "; ".join(errors))

        if callable(validated):
            data = cast(Callable[..., Any], validated)(
                PromptTemplate(user="{prompt}", output_format="Return ONLY valid JSON."),
                validator=validator,
                prompt=prompt,
            )
        else:
            # Lightweight test doubles and legacy clients expose only complete().
            response = cast(Callable[..., Any], self.llm_client.complete)(prompt, json_mode=True)
            extract = getattr(response, "extract_json", None)
            extract_safe = getattr(response, "extract_json_safe", None)
            if callable(extract):
                data = cast(Callable[[], Any], extract)()
            elif callable(extract_safe):
                data = cast(Callable[..., Any], extract_safe)(default={})
            else:
                data = json.loads(getattr(response, "content", "{}"))
        valid, error = validator(data)
        if not valid:
            raise ValueError(error)
        if not isinstance(data, dict):  # Narrows the validated result for type checkers.
            raise ValueError("response must be a JSON object")
        return data

    @staticmethod
    def _validate_shot_response(
        data: Any,
        expected_ids: list[int],
        require_exact_ids: bool = True,
        *,
        max_shots_per_segment: int = 1,
    ) -> tuple[bool, str]:
        if not isinstance(data, dict):
            return False, "response must be a JSON object"
        shots = data.get("shots")
        if not isinstance(shots, list) or not shots:
            return False, "response.shots must be a non-empty array"
        if not all(isinstance(item, dict) for item in shots):
            return False, "every response.shots item must be an object"
        try:
            actual_ids = [int(item.get("segment_id")) for item in shots]
        except (TypeError, ValueError):
            return False, "every shot must contain an integer segment_id"
        if require_exact_ids and (
            set(actual_ids) != set(expected_ids)
            or (max_shots_per_segment == 1 and len(actual_ids) != len(expected_ids))
        ):
            return (
                False,
                f"shots must cover exactly segment_ids {expected_ids}; got {actual_ids}",
            )
        counts = {segment_id: actual_ids.count(segment_id) for segment_id in set(actual_ids)}
        overflow = {
            segment_id: count
            for segment_id, count in counts.items()
            if count > max_shots_per_segment
        }
        if overflow:
            return False, f"shots exceed max {max_shots_per_segment} per segment: {overflow}"
        return True, ""

    def _per_segment_llm_calls(self, context: StageContext) -> bool:
        """True when bridge-backed and llm.bridge_batch disables batch tasks."""
        provider = str(getattr(getattr(self.llm_client, "config", None), "provider", "") or "")
        if not is_assistant_bridge_provider(provider):
            return False
        return not bool(getattr(getattr(context.config, "llm", None), "bridge_batch", True))

    def _llm_prompt(
        self,
        script_payload: list[dict[str, Any]],
        design: dict[str, Any],
        structure: dict[str, Any],
        continuity: dict[str, Any],
        storyboard_by_segment: dict[int, list[dict[str, Any]]],
        scope_note: str = "",
    ) -> str:
        scope = f"{scope_note}\n\n" if scope_note else ""
        coverage_instruction = (
            f"Create 1-{self._max_coverage_shots} complementary shots per segment. Use ordered "
            "coverage roles such as master, medium, reaction, insert, or detail; every shot_id "
            "must be unique and shot_order must be contiguous from 1."
            if self._coverage_mode == "director"
            else "Create exactly one primary shot per segment with shot_order 1."
        )
        return (
            "You are a top-tier film director and prompt compiler for AI video generation. "
            "For each shot, translate director thinking into an executable contract: story reason, "
            "a separate observable subject action, emotional target, film language, temporal action "
            "beats, editorial intent, continuity constraints, video prompt, negative prompt, duration, "
            "motion, storyboard binding, and QA assertions. Keep every artistic idea grounded in "
            "generation instructions. "
            f"{coverage_instruction}\n\n"
            f"{scope}"
            f"Project visual style: {self._style_anchor}\n"
            f"Configured provider flow: {self._provider_flow}\n"
            f"Script: {json.dumps(script_payload, ensure_ascii=False)}\n"
            f"Design report: {json.dumps(design, ensure_ascii=False)}\n"
            f"Screenplay structure: {json.dumps(structure, ensure_ascii=False)}\n"
            f"Continuity bible: {json.dumps(continuity, ensure_ascii=False)}\n\n"
            f"Storyboard frames by segment: {json.dumps(storyboard_by_segment, ensure_ascii=False)}\n\n"
            "Tag every QA assertion with exactly one dimension from the stable checklist "
            f"taxonomy: {json.dumps(QA_DIMENSIONS, ensure_ascii=False)}. "
            "Provide 3-6 assertions per shot in qa.assertions covering the dimensions "
            "most at risk for that shot.\n\n"
            'Return JSON only: {"shots":[{"segment_id":1,"shot_id":"shot_001_01","shot_order":1,'
            '"coverage_role":"master","story_reason":"why this edit exists",'
            '"subject_action":"one observable action","emotional_target":"...",'
            '"film_language":{"shot_type":"...","camera_motion":"...","lighting":"...",'
            '"composition":"...","focal_length":"50mm","aperture":"f/2.8",'
            '"camera_angle":"eye level","camera_height":"subject eye line",'
            '"depth_of_field":"...","color_palette":"...","blocking":["..."],'
            '"eyeline":"...","screen_axis":"..."},'
            '"temporal_plan":{"subject_action":"...","start_state":"...",'
            '"beats":[{"phase":"middle","at":0.5,"subject_action":"...",'
            '"camera_action":"..."}],"end_state":"...","performance_notes":"..."},'
            '"editorial_intent":{"coverage_role":"master","cut_motivation":"...",'
            '"transition_in":"cut","transition_out":"cut","handles_seconds":0.25},'
            '"continuity_constraints":{"characters":[],"location":"...","wardrobe":"...","lighting":"..."},'
            '"storyboard_binding":{"storyboard_frame_ids":[],"character_positions":[],"scene_ref":"...",'
            '"wardrobe_lock":"...","composition_requirements":[],"reference_image_ids":[]},'
            '"generation":{"video_prompt":"...","negative_prompt":"...","duration":5,"motion":"..."},'
            '"qa":{"must_show":[],"must_not_show":[],"assertions":[{"dimension":"...","check":"..."}]}}]}.'
        )

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
            subject_action = self._subject_action(
                design_item,
                segment.text,
                show_target,
                frames=frames,
            )
            film_language = self._local_film_language(
                design_item,
                metadata,
                storyboard_binding,
                shot_type,
                movement,
                lighting,
            )
            temporal_plan = self._default_temporal_plan(subject_action, movement)
            video_prompt = (
                f"Subject action: {subject_action}. Emotional target: {emotional_target}. "
                f"Story purpose: {story_reason}. "
                f"{shot_type} shot, {movement} camera movement, {lighting}. "
                f"Show {show_target} in {location_text}, wearing {wardrobe_text}. "
                f"{character_blocks} {scene_block} "
                f"Keep {show_target} visible throughout the clip with the same face, age, body, and wardrobe from the reference image. "
                f"Maintain a character-led frame with clear story action and coherent scene geography. "
                f"Storyboard frames {', '.join(storyboard_binding['storyboard_frame_ids']) or 'none'}; "
                f"character positions: {', '.join(storyboard_binding['character_positions']) or 'unspecified'}; "
                f"composition requirements: {', '.join(storyboard_binding['composition_requirements']) or 'serve the story beat'}. "
                f"Visual details: {image_prompt}. Project style: {self._style_anchor}. "
                "Cinematic motion, coherent continuity, high quality."
            )
            base_shot = {
                "segment_id": segment_id,
                "shot_id": (
                    f"shot_{segment_id:03d}_01"
                    if self._coverage_mode == "director"
                    else f"shot_{segment_id:03d}"
                ),
                "shot_order": 1,
                "coverage_role": "master",
                "story_reason": story_reason,
                "subject_action": subject_action,
                "emotional_target": emotional_target,
                "film_language": film_language,
                "temporal_plan": temporal_plan,
                "editorial_intent": self._default_editorial_intent("master", story_reason),
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
                    "must_show": self._must_show(characters, location_text, wardrobe_text),
                    "must_not_show": self._must_not_show(negative),
                    "assertions": self._default_assertions(
                        characters,
                        location_text,
                        wardrobe_text,
                        shot_type,
                        movement,
                        lighting,
                        story_reason,
                        segment.text,
                    ),
                },
            }
            for coverage_shot in self._local_coverage_variants(base_shot, segment.text):
                shots.append(self._with_compiled_prompts(coverage_shot))
        return shots

    def _subject_action(
        self,
        design_item: dict[str, Any],
        segment_text: str,
        show_target: str,
        *,
        frames: list[dict[str, Any]] | None = None,
    ) -> str:
        metadata = (
            design_item.get("metadata", {}) if isinstance(design_item.get("metadata"), dict) else {}
        )
        explicit = design_item.get("subject_action") or metadata.get("subject_action")
        if explicit:
            return str(explicit).strip()
        for frame in frames or []:
            description = str(frame.get("description") or "").strip()
            if description:
                return f"{show_target} visibly enacts this storyboard beat: {description}"
        return (
            f"{show_target} turns toward the story focus, completes one restrained hand gesture, "
            f"then settles into a clear end pose as this narrated beat unfolds: {segment_text.strip()}"
        )

    def _local_film_language(
        self,
        design_item: dict[str, Any],
        metadata: dict[str, Any],
        binding: dict[str, Any],
        shot_type: str,
        movement: str,
        lighting: str,
    ) -> dict[str, Any]:
        positions = [str(item) for item in binding.get("character_positions", []) or []]

        def value(key: str, fallback: str) -> str:
            return str(design_item.get(key) or metadata.get(key) or fallback)

        return {
            "shot_type": shot_type,
            "camera_motion": movement,
            "lighting": lighting,
            "composition": value(
                "composition",
                ", ".join(binding.get("composition_requirements", []) or [])
                or "subject anchored on a clear visual axis with motivated negative space",
            ),
            "focal_length": value("focal_length", "50mm natural perspective"),
            "aperture": value("aperture", "f/2.8"),
            "camera_angle": value("camera_angle", "eye level"),
            "camera_height": value("camera_height", "subject eye line"),
            "depth_of_field": value("depth_of_field", "moderate depth, subject separated"),
            "color_palette": value("color_palette", "locked to the scene reference palette"),
            "blocking": positions or ["subject position follows the bound storyboard frame"],
            "eyeline": value("eyeline", "preserve the established eyeline"),
            "screen_axis": value("screen_axis", "preserve the established 180-degree axis"),
        }

    def _default_temporal_plan(self, subject_action: str, movement: str) -> dict[str, Any]:
        return {
            "subject_action": subject_action,
            "start_state": "establish the subject pose and scene geography before movement",
            "beats": [
                {
                    "phase": "middle",
                    "at": 0.5,
                    "subject_action": subject_action,
                    "camera_action": f"execute one controlled {movement} movement",
                }
            ],
            "end_state": "complete the action and hold a clean frame for the edit",
            "performance_notes": "one readable action, restrained performance, no pose drift",
        }

    def _default_editorial_intent(self, coverage_role: str, story_reason: str) -> dict[str, Any]:
        return {
            "coverage_role": coverage_role,
            "cut_motivation": f"Cut to this {coverage_role} view to {story_reason}",
            "transition_in": "cut",
            "transition_out": "cut",
            "handles_seconds": 0.25,
        }

    def _local_coverage_variants(
        self,
        base_shot: dict[str, Any],
        segment_text: str,
    ) -> list[dict[str, Any]]:
        variants = [base_shot]
        if self._coverage_mode != "director" or self._max_coverage_shots <= 1:
            return variants
        segment_id = int(base_shot["segment_id"])
        characters = list(base_shot["continuity_constraints"].get("characters") or [])
        secondary = json.loads(json.dumps(base_shot, ensure_ascii=False))
        secondary["shot_id"] = f"shot_{segment_id:03d}_02"
        secondary["shot_order"] = 2
        secondary["coverage_role"] = "reaction" if characters else "detail"
        target = ", ".join(characters) if characters else "the story detail"
        secondary["subject_action"] = (
            f"{target} turns toward the result and holds one readable reaction before settling, "
            f"revealing the immediate consequence of this beat: {segment_text.strip()}"
            if characters
            else f"The camera isolates {target} as it shifts once and settles into a clean detail frame, "
            f"revealing the consequence of this beat: {segment_text.strip()}"
        )
        secondary["film_language"].update(
            {
                "shot_type": "close_up" if characters else "detail",
                "camera_motion": "still",
                "focal_length": "85mm compressed perspective" if characters else "70mm detail lens",
                "aperture": "f/2.0",
                "depth_of_field": "shallow depth focused on the reaction or story detail",
                "blocking": [
                    "isolate the reaction or detail without crossing the established axis"
                ],
            }
        )
        secondary["temporal_plan"] = self._default_temporal_plan(
            secondary["subject_action"], "still"
        )
        secondary["editorial_intent"] = self._default_editorial_intent(
            str(secondary["coverage_role"]), "reveal the consequence of the primary action"
        )
        secondary["generation"]["video_prompt"] = (
            f"Subject action: {secondary['subject_action']}. "
            f"Use a {secondary['film_language']['shot_type']} shot with stable framing. "
            f"Project style: {self._style_anchor}. Preserve all continuity and reference locks."
        )
        variants.append(secondary)
        return variants[: self._max_coverage_shots]

    def _normalize_shot(
        self,
        shot: dict[str, Any],
        design_by_segment: dict[int, dict[str, Any]],
        storyboard_by_segment: dict[int, list[dict[str, Any]]],
        context: StageContext,
    ) -> dict[str, Any]:
        segment_id = _to_int(shot.get("segment_id"))
        if segment_id is None:
            segment_id = 0
        design_item = design_by_segment.get(segment_id, {})
        generation = shot.get("generation", {}) if isinstance(shot.get("generation"), dict) else {}
        qa = shot.get("qa", {}) if isinstance(shot.get("qa"), dict) else {}
        film_language = (
            shot.get("film_language", {}) if isinstance(shot.get("film_language"), dict) else {}
        )
        temporal_plan = (
            shot.get("temporal_plan", {}) if isinstance(shot.get("temporal_plan"), dict) else {}
        )
        editorial_intent = (
            shot.get("editorial_intent", {})
            if isinstance(shot.get("editorial_intent"), dict)
            else {}
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
        try:
            shot_order = max(1, int(shot.get("shot_order") or 1))
        except (TypeError, ValueError):
            shot_order = 1
        coverage_role = str(
            shot.get("coverage_role")
            or editorial_intent.get("coverage_role")
            or ("master" if shot_order == 1 else "coverage")
        )
        script_segment = context.script.get_segment(segment_id)
        subject_action = str(
            shot.get("subject_action")
            or temporal_plan.get("subject_action")
            or self._subject_action(
                design_item,
                (
                    script_segment.text
                    if script_segment
                    else str(design_item.get("image_prompt") or "")
                ),
                ", ".join(continuity.get("characters") or []) or "the named character",
            )
        ).strip()
        beats: list[dict[str, Any]] = []
        for raw_beat in temporal_plan.get("beats", []) or []:
            if not isinstance(raw_beat, dict):
                continue
            try:
                at = float(str(raw_beat.get("at")))
            except (TypeError, ValueError):
                at = 0.5
            beats.append(
                {
                    "phase": str(raw_beat.get("phase") or "middle"),
                    "at": min(1.0, max(0.0, at)),
                    "subject_action": str(raw_beat.get("subject_action") or subject_action),
                    "camera_action": str(
                        raw_beat.get("camera_action")
                        or generation.get("motion")
                        or film_language.get("camera_motion")
                        or "hold the planned framing"
                    ),
                }
            )
        if not beats:
            beats = self._default_temporal_plan(
                subject_action,
                str(generation.get("motion") or film_language.get("camera_motion") or "still"),
            )["beats"]
        default_editorial = self._default_editorial_intent(
            coverage_role, str(shot.get("story_reason") or "execute the scripted beat")
        )
        return {
            "segment_id": segment_id,
            "shot_id": shot.get("shot_id")
            or (
                f"shot_{segment_id:03d}_{shot_order:02d}"
                if self._coverage_mode == "director"
                else f"shot_{segment_id:03d}"
            ),
            "shot_order": shot_order,
            "coverage_role": coverage_role,
            "story_reason": shot.get("story_reason", ""),
            "subject_action": subject_action,
            "emotional_target": shot.get("emotional_target", ""),
            "film_language": {
                "shot_type": film_language.get("shot_type", "medium"),
                "camera_motion": film_language.get("camera_motion", "still"),
                "lighting": film_language.get("lighting", ""),
                "composition": film_language.get("composition", ""),
                "focal_length": film_language.get("focal_length", ""),
                "aperture": film_language.get("aperture", ""),
                "camera_angle": film_language.get("camera_angle", ""),
                "camera_height": film_language.get("camera_height", ""),
                "depth_of_field": film_language.get("depth_of_field", ""),
                "color_palette": film_language.get("color_palette", ""),
                "blocking": list(film_language.get("blocking") or []),
                "eyeline": film_language.get("eyeline", ""),
                "screen_axis": film_language.get("screen_axis", ""),
            },
            "temporal_plan": {
                "subject_action": str(temporal_plan.get("subject_action") or subject_action),
                "start_state": str(temporal_plan.get("start_state") or ""),
                "beats": beats,
                "end_state": str(temporal_plan.get("end_state") or ""),
                "performance_notes": str(temporal_plan.get("performance_notes") or ""),
            },
            "editorial_intent": {
                "coverage_role": str(editorial_intent.get("coverage_role") or coverage_role),
                "cut_motivation": str(
                    editorial_intent.get("cut_motivation") or default_editorial["cut_motivation"]
                ),
                "transition_in": str(
                    editorial_intent.get("transition_in") or default_editorial["transition_in"]
                ),
                "transition_out": str(
                    editorial_intent.get("transition_out") or default_editorial["transition_out"]
                ),
                "handles_seconds": float(
                    str(
                        editorial_intent.get("handles_seconds")
                        if editorial_intent.get("handles_seconds") is not None
                        else default_editorial["handles_seconds"]
                    )
                ),
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
                "assertions": normalize_assertions(qa.get("assertions")),
            },
        }

    def _with_compiled_prompts(self, shot: dict[str, Any]) -> dict[str, Any]:
        generation = shot.setdefault("generation", {})
        generation["prompt_blueprint"] = self._prompt_blueprint(shot)
        generation["prompt_schema_version"] = SCHEMA_VERSION
        generation["compiled_prompts"] = compile_video_prompts(shot)
        return shot

    def _prompt_blueprint(self, shot: dict[str, Any]) -> dict[str, Any]:
        film_language = (
            shot.get("film_language", {}) if isinstance(shot.get("film_language"), dict) else {}
        )
        continuity = (
            shot.get("continuity_constraints", {})
            if isinstance(shot.get("continuity_constraints"), dict)
            else {}
        )
        binding = (
            shot.get("storyboard_binding", {})
            if isinstance(shot.get("storyboard_binding"), dict)
            else {}
        )
        generation = shot.get("generation", {}) if isinstance(shot.get("generation"), dict) else {}
        qa = shot.get("qa", {}) if isinstance(shot.get("qa"), dict) else {}
        temporal_plan = (
            shot.get("temporal_plan", {}) if isinstance(shot.get("temporal_plan"), dict) else {}
        )
        editorial_intent = (
            shot.get("editorial_intent", {})
            if isinstance(shot.get("editorial_intent"), dict)
            else {}
        )
        return {
            "schema_version": "prompt_blueprint.v1",
            "narrative_intent": str(shot.get("story_reason") or ""),
            "emotional_target": str(shot.get("emotional_target") or ""),
            "subject_action": str(shot.get("subject_action") or ""),
            "camera_plan": {
                "shot_type": str(film_language.get("shot_type") or "medium"),
                "motion": str(
                    generation.get("motion") or film_language.get("camera_motion") or "still"
                ),
                "lighting": str(film_language.get("lighting") or continuity.get("lighting") or ""),
                "composition": str(film_language.get("composition") or ""),
                "focal_length": str(film_language.get("focal_length") or ""),
                "aperture": str(film_language.get("aperture") or ""),
                "camera_angle": str(film_language.get("camera_angle") or ""),
                "camera_height": str(film_language.get("camera_height") or ""),
                "depth_of_field": str(film_language.get("depth_of_field") or ""),
                "color_palette": str(film_language.get("color_palette") or ""),
                "blocking": list(film_language.get("blocking") or []),
                "eyeline": str(film_language.get("eyeline") or ""),
                "screen_axis": str(film_language.get("screen_axis") or ""),
            },
            "temporal_plan": {
                "subject_action": str(
                    temporal_plan.get("subject_action") or shot.get("subject_action") or ""
                ),
                "start_state": str(temporal_plan.get("start_state") or ""),
                "beats": [
                    dict(item) for item in temporal_plan.get("beats", []) if isinstance(item, dict)
                ],
                "end_state": str(temporal_plan.get("end_state") or ""),
                "performance_notes": str(temporal_plan.get("performance_notes") or ""),
            },
            "editorial_intent": {
                "coverage_role": str(
                    editorial_intent.get("coverage_role") or shot.get("coverage_role") or "primary"
                ),
                "cut_motivation": str(editorial_intent.get("cut_motivation") or ""),
                "transition_in": str(editorial_intent.get("transition_in") or "cut"),
                "transition_out": str(editorial_intent.get("transition_out") or "cut"),
                "handles_seconds": float(editorial_intent.get("handles_seconds") or 0.25),
            },
            "continuity_locks": {
                "characters": list(continuity.get("characters") or []),
                "location": str(continuity.get("location") or binding.get("scene_ref") or ""),
                "wardrobe": str(continuity.get("wardrobe") or binding.get("wardrobe_lock") or ""),
                "lighting": str(continuity.get("lighting") or film_language.get("lighting") or ""),
            },
            "storyboard_locks": {
                "storyboard_frame_ids": list(binding.get("storyboard_frame_ids") or []),
                "character_positions": list(binding.get("character_positions") or []),
                "scene_ref": str(binding.get("scene_ref") or ""),
                "wardrobe_lock": str(binding.get("wardrobe_lock") or ""),
                "composition_requirements": list(binding.get("composition_requirements") or []),
            },
            "reference_strategy": {
                "required_reference_image_ids": list(binding.get("reference_image_ids") or []),
                "provider_flow": self._provider_flow,
                "identity_priority": "character_reference, wardrobe_lock, scene_reference, style_anchor",
            },
            "style_anchor": self._style_anchor,
            "quality_bar": [
                "one concrete subject action",
                "one camera movement only",
                "stable character identity",
                "locked wardrobe and scene geography",
                "no readable text or watermark",
            ],
            "qa_assertions": {
                "must_show": list(qa.get("must_show") or []),
                "must_not_show": list(qa.get("must_not_show") or []),
                "assertions": normalize_assertions(qa.get("assertions")),
            },
        }

    def _must_show(self, characters: list[str], location: str, wardrobe: str) -> list[str]:
        values = [*characters, location, wardrobe]
        return [value for value in values if value]

    def _must_not_show(self, negative_prompt: str) -> list[str]:
        return [part.strip() for part in negative_prompt.split(",") if part.strip()]

    def _default_assertions(
        self,
        characters: list[str],
        location_text: str,
        wardrobe_text: str,
        shot_type: str,
        movement: str,
        lighting: str,
        story_reason: str,
        segment_text: str,
    ) -> list[dict[str, str]]:
        """Deterministic per-shot QA checklist covering every taxonomy dimension."""
        show_target = ", ".join(characters) if characters else "the named character"
        beat = segment_text.strip()
        if len(beat) > 120:
            beat = beat[:117].rstrip() + "..."
        checks = [
            (
                "identity_continuity",
                f"{show_target} keeps the same face, age, body, and wardrobe "
                f"({wardrobe_text}) as the character references throughout the clip.",
            ),
            (
                "dialogue_attribution",
                f"The subject acting the story beat on screen is {show_target}; "
                f"the action matches the narration: {beat or 'the scripted beat'}.",
            ),
            (
                "camera_language",
                f"The clip executes the planned {shot_type} shot with {movement} "
                f"camera movement and {lighting}.",
            ),
            (
                "motion_plausibility",
                f"The story action ({story_reason}) and camera movement stay "
                "physically plausible — no warping, ghosting, frozen frames, or "
                "impossible motion.",
            ),
            (
                "scene_consistency",
                f"The location reads as {location_text} with coherent scene "
                "geography and props across the clip.",
            ),
            (
                "technical_quality",
                "No readable text, watermark, flicker, compression artifacts, or "
                "low-quality frames.",
            ),
        ]
        return [
            {"id": f"{dimension}:{index + 1}", "dimension": dimension, "check": check}
            for index, (dimension, check) in enumerate(checks)
        ]

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
        result: dict[int, dict[str, Any]] = {}
        for item in design.get("segments", []) or []:
            if not isinstance(item, dict):
                continue
            segment_id = _to_int(item.get("segment_id"))
            if segment_id is None:
                continue
            result[segment_id] = item
        return result

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
        return super()._load_yaml(path)

    def _segment_ids_from_queue(self, path: Path) -> set[int]:
        if not path.exists():
            return set()
        data = self._load_yaml(path)
        ids: set[int] = set()
        for action in data.get("actions", []) or []:
            if not isinstance(action, dict):
                continue
            segment_id = _to_int(action.get("segment_id"))
            if segment_id is not None:
                ids.add(segment_id)
        return ids

    def _merge_rewritten_shots(
        self,
        previous_shots: Any,
        candidate_shots: list[dict[str, Any]],
        rewrite_segment_ids: set[int],
    ) -> list[dict[str, Any]]:
        previous_by_segment: dict[int, list[dict[str, Any]]] = {}
        if isinstance(previous_shots, list):
            for shot in previous_shots:
                if not isinstance(shot, dict):
                    continue
                segment_id = _to_int(shot.get("segment_id"))
                if segment_id is not None:
                    previous_by_segment.setdefault(segment_id, []).append(shot)

        candidate_by_segment: dict[int, list[dict[str, Any]]] = {}
        for shot in candidate_shots:
            segment_id = _to_int(shot.get("segment_id"))
            if segment_id is None:
                continue
            candidate_by_segment.setdefault(segment_id, []).append(shot)

        merged: list[dict[str, Any]] = []
        for segment_id, candidates in candidate_by_segment.items():
            selected = (
                candidates
                if segment_id in rewrite_segment_ids or segment_id not in previous_by_segment
                else previous_by_segment[segment_id]
            )
            merged.extend(selected)
        merged.sort(
            key=lambda item: (
                int(item.get("segment_id") or 0),
                int(item.get("shot_order") or 1),
            )
        )
        return merged

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
