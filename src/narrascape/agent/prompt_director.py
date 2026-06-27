"""PromptDirector — The ultimate AI director for image generation prompts.

This is NOT a template engine. It is a true LLM Agent that:
1. Receives cinematic knowledge as context (not rules)
2. Makes autonomous creative decisions as a film director
3. Designs complete prompts with lighting, composition, camera, and negative prompts
4. Ensures sequence consistency for video generation workflows
5. Self-critiques and iterates on designs
6. Generates multiple candidate shots for key moments

Usage:
    director = PromptDirector(llm_client=my_llm)
    designs = director.design_sequence(segments, analysis_list, config)
    # Each design contains: full prompt, negative prompt, shot reasoning, style fingerprint

Note: PromptDirector requires an LLM. It does NOT fall back to keyword rules.
    If no LLM is available, it raises a clear error.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from narrascape.llm import LLMClient, OutputValidator, is_assistant_bridge_provider
from narrascape.llm.prompts import get_prompt
from narrascape.config import NarrascapeConfig, ShotType, MovementType

logger = logging.getLogger("narrascape.agent.prompt_director")


# ═══════════════════════════════════════════════════════════════════
# PromptDirector Agent
# ═══════════════════════════════════════════════════════════════════

class PromptDirector:
    """AI Director that designs cinematic image generation prompts with full director autonomy.

    Unlike the old AgentDirector which used keyword rules, PromptDirector:
    - Passes comprehensive cinematography knowledge to LLM as context
    - Lets LLM make autonomous creative decisions as a film director
    - Designs complete prompts with lighting, camera, composition, color, atmosphere
    - Generates negative prompts to prevent AI artifacts
    - Self-critiques designs before finalizing
    - Generates multiple candidates for key shots (opening, climax, ending)
    - Ensures sequence consistency for video keyframe workflows
    - Records quality feedback for continuous improvement

    REQUIREMENT: LLM client must be provided. No keyword-based fallback.
    """

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client
        # Feedback log for closed-loop optimization (Problem 8)
        self._feedback_log: list[dict] = []
        # Character and scene consistency anchors
        self._characters: list[Any] = []
        self._scene_style: Any | None = None
        self._character_id_map: dict[str, str] = {}
        self._reference_image_chains: list[Any] = []

    # ── Public API ───────────────────────────

    def get_consistency_anchor(self) -> dict:
        """Return the full consistency anchor (characters + scene style + reference chains) for external use."""
        return {
            "characters": [
                {
                    "char_id": c.char_id,
                    "name": c.name,
                    "identity_block": c.identity_block,
                    "face_description": c.face_description,
                    "hair_description": c.hair_description,
                    "body_description": c.body_description,
                    "default_outfit": c.default_outfit,
                    "signature_accessories": c.signature_accessories,
                    "negative_anchors": c.negative_anchors,
                    "reference_image_url": c.reference_image_url,
                }
                for c in self._characters
            ],
            "scene_style": {
                "style_id": self._scene_style.style_id if self._scene_style else "default",
                "style_name": self._scene_style.style_name if self._scene_style else "",
                "base_color_temperature": self._scene_style.base_color_temperature if self._scene_style else "",
                "color_palette": self._scene_style.color_palette if self._scene_style else "",
                "lighting_signature": self._scene_style.lighting_signature if self._scene_style else "",
                "texture_palette": self._scene_style.texture_palette if self._scene_style else "",
                "atmosphere_signature": self._scene_style.atmosphere_signature if self._scene_style else "",
                "depth_signature": self._scene_style.depth_signature if self._scene_style else "",
                "lens_signature": self._scene_style.lens_signature if self._scene_style else "",
                "style_references": self._scene_style.style_references if self._scene_style else [],
                "world_rules": self._scene_style.world_rules if self._scene_style else [],
                "consistency_notes": self._scene_style.consistency_notes if self._scene_style else "",
            } if self._scene_style else None,
            "reference_image_chains": [
                {
                    "chain_id": r.chain_id,
                    "chain_type": r.chain_type,
                    "reference_urls": r.reference_urls,
                    "reference_local_paths": r.reference_local_paths,
                    "target_model": r.target_model,
                    "usage_mode": r.usage_mode,
                    "sample_strength": r.sample_strength,
                    "consistency_target": r.consistency_target,
                    "description": r.description,
                    "generated_images": r.generated_images,
                }
                for r in self._reference_image_chains
            ],
        }

    def design_sequence(
        self,
        segments: list[Any],
        analysis_list: list[Any],
        config: NarrascapeConfig,
        video_model: str = "generic",
        generate_variations: bool = True,
        storyboard: Any = None,
    ) -> list[Any]:
        """Design a complete sequence of shots with consistency checks and self-critique.

        Args:
            segments: List of ScriptSegment objects
            analysis_list: List of SegmentAnalysis objects
            config: Project configuration
            video_model: Target video model for differentiated advice (runway, sora, kling, veo, generic)
            generate_variations: Whether to generate multiple candidates for key shots

        Returns:
            List of ShotDesign objects with full prompts

        Raises:
            RuntimeError: If no LLM client is available (should not happen with ai_assistant mode).
        """
        # AI Assistant mode: llm_client is always available
        # This assertion protects against initialization bugs
        assert self.llm_client is not None, "PromptDirector requires LLM client — initialization bug"

        overall_tone = analysis_list[0].emotion if analysis_list else "neutral"
        style_template = config.images.style if config.images else "cinematic documentary"
        total = len(segments)

        # Phase 0: Build character profiles and scene style for consistency anchoring
        # This happens BEFORE any shot design to ensure all shots reference the same anchors
        # Bridge-backed assistant modes use one batch task; batch design handles consistency.
        is_bridge_backed = (
            getattr(self.llm_client, 'config', None)
            and is_assistant_bridge_provider(self.llm_client.config.provider)
        )
        if not is_bridge_backed:
            self._build_character_profiles(segments, analysis_list)
            self._build_scene_style(segments, analysis_list, style_template)

        # Build character profiles string for template injection
        character_profiles_str = self._format_character_profiles_for_template()
        scene_style_str = self._format_scene_style_for_template()

        # Bridge-backed assistant modes use batch design to reduce task files.
        if is_bridge_backed:
            logger.info("[PromptDirector] AI assistant bridge mode: using batch design for all segments")
            raw_designs = self._design_sequence_batch(
                segments, analysis_list, config,
                overall_tone=overall_tone,
                style_template=style_template,
                character_profiles_str=character_profiles_str,
                scene_style_str=scene_style_str,
                video_model=video_model,
                storyboard=storyboard,
            )
            # Bridge mode: skip consistency checks (batch design already considers consistency)
            self._build_reference_image_chains(raw_designs)
            return raw_designs

        # Phase 1: Design each shot individually with full context (including character anchors)
        raw_designs: list[Any] = []
        for i, (seg, analysis) in enumerate(zip(segments, analysis_list)):
            # Inject storyboard context into segment if available
            original_text = None
            if storyboard:
                sb_frames = storyboard.frames_for_segment(seg.id)
                if sb_frames:
                    sb_text = self._format_storyboard_for_segment(sb_frames)
                    original_text = seg.text
                    seg.text = f"{original_text}\n\n[STORYBOARD GUIDANCE]\n{sb_text}"
            
            try:
                # Identify key shots that deserve multiple candidates (Problem 5)
                is_key_shot = i == 0 or i == total - 1 or i == total // 2 or analysis.intensity > 0.7
                design = self._design_single_shot(
                    seg, analysis, config,
                    overall_tone=overall_tone,
                    style_template=style_template,
                    all_segments=segments,
                    all_analysis=analysis_list,
                    index=i,
                    video_model=video_model,
                    generate_variations=generate_variations and is_key_shot,
                    character_profiles_str=character_profiles_str,
                    scene_style_str=scene_style_str,
                )
                raw_designs.append(design)
            finally:
                # Restore original text if modified
                if original_text is not None:
                    seg.text = original_text
            
            logger.info(
                f"[PromptDirector] Designed shot {seg.id}: {design.shot_type.value} | "
                f"{design.movement.value if design.movement else 'still'} | "
                f"characters={design.character_refs} | style={design.style_ref}"
            )

        # Phase 2: Check sequence consistency and APPLY fixes (Problem 3)
        if len(raw_designs) > 1:
            raw_designs = self._check_sequence_consistency(raw_designs)

        # Phase 3: Verify character consistency across all shots
        self._verify_character_consistency(raw_designs)

        # Phase 4: Build reference image chains for Seedream/Seedance multi-reference workflow
        self._build_reference_image_chains(raw_designs)

        return raw_designs

    def _design_sequence_batch(
        self,
        segments: list[Any],
        analysis_list: list[Any],
        config: NarrascapeConfig,
        overall_tone: str,
        style_template: str,
        character_profiles_str: str,
        scene_style_str: str,
        video_model: str = "generic",
        storyboard: Any = None,
    ) -> list[Any]:
        """Batch design all shots in a single LLM call (bridge mode optimization)."""
        from narrascape.agent.models import ShotDesign
        from narrascape.config import ShotType, MovementType
        
        # Build segments description
        segments_desc = []
        for i, (seg, analysis) in enumerate(zip(segments, analysis_list)):
            position = "opening" if i == 0 else "climax" if i == len(segments) - 1 else f"middle ({i+1}/{len(segments)})"
            segments_desc.append(f"""
Segment {seg.id} ({position}):
- Text: {seg.text}
- Emotion: {analysis.emotion} (intensity: {analysis.intensity:.1f})
- Scene type: {analysis.scene_type}
- Key entities: {', '.join(analysis.key_entities)}
- Visual keywords: {', '.join(analysis.visual_keywords)}
- Pacing: {analysis.pacing}
""")
        
        prompt = f"""You are an AI Director designing cinematic shots for a documentary video.

Design ALL shots in the sequence below. For each segment, create a complete shot design.

Style template: {style_template}
Overall tone: {overall_tone}
Target video model: {video_model}

{character_profiles_str}
{scene_style_str}

Segments:
{chr(10).join(segments_desc)}

For EACH segment, return an object with these exact fields:
{{
    "segment_id": <segment number>,
    "shot_type": "<close_up/medium_shot/long_shot/establishing/insert/extreme_close_up>",
    "movement": "<none/pan/zoom/tracking/dolly/truck/crane/handheld>",
    "director_vision": "<Layer 1: Creative brief in painter's language. Describe the visual world without technical terms.>",
    "cinematic_format": "<Layer 3: Standardized cinematic shot-list format. EXT./INT., SHOT SIZE, LENS, ANGLE, MOVEMENT, LIGHTING, COMPOSITION, COLOR, DEPTH, ATMOSPHERE, MOOD, DURATION>",
    "image_prompt": "<Layer 2: Distilled AI image generation prompt. 60-80 words maximum. Include subject, action, environment, lighting, camera, style, and mood.>",
    "negative_prompt": "<What to avoid: blurry, distorted, low quality, wrong anatomy, etc.>",
    "reasoning": "<Why this shot was chosen>",
    "emotion": "<dominant emotion>",
    "intensity": <0.0-1.0>,
    "metadata": {{
        "focal_length": "<e.g., 85mm>",
        "aperture": "<e.g., f/2.8>",
        "camera_angle": "<e.g., eye level, low angle>",
        "lighting_scheme": "<key light direction, fill, backlight>",
        "light_sources": ["<list of light sources>"],
        "composition": "<e.g., rule of thirds, centered, leading lines>",
        "color_palette": "<warm amber + cool teal, etc.>",
        "atmosphere": "<e.g., misty, dust particles, golden hour glow>",
        "depth_of_field": "<shallow or deep>",
        "style_fingerprint": "<style identifier for consistency>"
    }}
}}

Return ONLY a valid JSON array containing one object per segment, in order.

Guidelines:
- Ensure visual variety across the sequence (don't use the same shot type for every segment)
- Maintain emotional continuity between adjacent segments
- Use professional cinematography terminology
- Image prompts should be specific and visual (60-80 words)
- Consider the overall narrative arc: opening, development, climax, resolution
"""

        resp = self.llm_client.complete(prompt, json_mode=True)
        data = resp.extract_json()
        
        if not isinstance(data, list):
            raise ValueError(f"Expected JSON array, got {type(data)}")
        
        # Build ShotDesign objects from response
        raw_designs = []
        for i, item in enumerate(data):
            seg_id = item.get("segment_id", segments[i].id if i < len(segments) else 0)
            
            # Map shot type string to ShotType enum (with aliases)
            shot_type_str = item.get("shot_type", "medium")
            shot_type = self._parse_shot_type(shot_type_str)
            
            # Map movement string to MovementType enum (with aliases)
            movement_str = item.get("movement", "none")
            movement = self._parse_movement_type(movement_str)
            
            metadata = item.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            
            design = ShotDesign(
                segment_id=seg_id,
                shot_type=shot_type,
                movement=movement,
                director_vision=item.get("director_vision", ""),
                cinematic_format=item.get("cinematic_format", ""),
                image_prompt=item.get("image_prompt", ""),
                reasoning=item.get("reasoning", ""),
                emotion=item.get("emotion", ""),
                intensity=float(item.get("intensity", 0.5)),
                metadata=metadata,
                negative_prompt=item.get("negative_prompt", ""),
                style_prefix=style_template,
            )
            raw_designs.append(design)
            logger.info(f"[PromptDirector] Batch-designed shot {seg_id}: {shot_type.value}")
        
        return raw_designs
    
    def _parse_shot_type(self, shot_type_str: str) -> ShotType:
        """Parse shot type string to ShotType enum with aliases."""
        aliases = {
            "medium_shot": "MEDIUM",
            "medium": "MEDIUM",
            "long_shot": "WIDE_ENV",
            "wide": "WIDE_ENV",
            "wide_shot": "WIDE_ENV",
            "close_up": "CLOSE_UP",
            "close-up": "CLOSE_UP",
            "closeup": "CLOSE_UP",
            "extreme_close_up": "EXTREME_CLOSE_UP",
            "extreme_closeup": "EXTREME_CLOSE_UP",
            "extreme_close-up": "EXTREME_CLOSE_UP",
            "ecu": "EXTREME_CLOSE_UP",
            "insert": "INSERT",
            "detail": "DETAIL",
            "establishing": "ESTABLISHING",
            "establishing_shot": "ESTABLISHING",
            "two_shot": "TWO_SHOT",
            "two-shot": "TWO_SHOT",
            "over_shoulder": "OVER_SHOULDER",
            "over-shoulder": "OVER_SHOULDER",
            "shoulder": "OVER_SHOULDER",
            "silhouette": "SILHOUETTE",
            "group_shot": "GROUP_SHOT",
            "group": "GROUP_SHOT",
            "aerial": "AERIAL",
            "drone": "AERIAL",
            "black": "BLACK",
            "wide_angle": "WIDE_ANGLE",
            "wide-angle": "WIDE_ANGLE",
        }
        key = shot_type_str.lower().strip()
        enum_name = aliases.get(key, key.upper().replace("-", "_"))
        try:
            return ShotType[enum_name]
        except KeyError:
            logger.warning(f"Unknown shot type '{shot_type_str}', defaulting to MEDIUM")
            return ShotType.MEDIUM
    
    def _parse_movement_type(self, movement_str: str) -> MovementType | None:
        """Parse movement string to MovementType enum with aliases."""
        if not movement_str or movement_str.lower() in ("none", "", "null", "still"):
            return None
        aliases = {
            "zoom_in": "ZOOM_IN",
            "zoom_in_slow": "ZOOM_IN_SLOW",
            "zoom_slow": "ZOOM_SLOW",
            "zoom_out": "ZOOM_OUT",
            "zoom_out_slow": "ZOOM_OUT_SLOW",
            "push_in": "PUSH_IN",
            "push-in": "PUSH_IN",
            "pull_out": "PULL_OUT",
            "pull-out": "PULL_OUT",
            "pan_left": "PAN_LEFT",
            "pan-left": "PAN_LEFT",
            "pan_left_slow": "PAN_LEFT",
            "pan_right": "PAN_RIGHT",
            "pan-right": "PAN_RIGHT",
            "pan_right_slow": "PAN_RIGHT",
            "pan": "PAN_LEFT",
            "dolly": "PUSH_IN",
            "dolly_in": "PUSH_IN",
            "dolly_out": "PULL_OUT",
            "tracking": "PAN_LEFT",
            "truck_left": "PAN_LEFT",
            "truck_right": "PAN_RIGHT",
            "crane_up": "ZOOM_OUT",
            "crane_down": "ZOOM_IN",
            "handheld": "ZOOM_SLOW",
        }
        key = movement_str.lower().strip()
        enum_name = aliases.get(key, key.upper().replace("-", "_"))
        try:
            return MovementType[enum_name]
        except KeyError:
            logger.warning(f"Unknown movement type '{movement_str}', defaulting to None")
            return None

    # ── Reference Image Chains (Problem 10) ───────────────────────────

    def _design_single_shot(
        self,
        seg: Any,
        analysis: Any,
        config: NarrascapeConfig,
        overall_tone: str,
        style_template: str,
        all_segments: list[Any],
        all_analysis: list[Any],
        index: int,
        video_model: str = "generic",
        generate_variations: bool = False,
        character_profiles_str: str = "",
        scene_style_str: str = "",
    ) -> Any:
        """Design one shot with structured LLM prompting, self-critique, and optional variations."""
        text = seg.text
        seg_id = seg.id
        duration = self._estimate_duration(text, config)

        # Build neighbor context
        prev_context = "(first segment — no previous)"
        if index > 0:
            prev_seg = all_segments[index - 1]
            prev_ana = all_analysis[index - 1]
            prev_context = (
                f"'{prev_seg.text[:50]}...' (emotion: {prev_ana.emotion}, "
                f"scene: {prev_ana.scene_type})"
            )

        next_context = "(last segment — no next)"
        if index < len(all_segments) - 1:
            next_seg = all_segments[index + 1]
            next_ana = all_analysis[index + 1]
            next_context = (
                f"'{next_seg.text[:50]}...' (emotion: {next_ana.emotion}, "
                f"scene: {next_ana.scene_type})"
            )

        position = (
            "opening"
            if index == 0
            else "climax"
            if index == len(all_segments) - 1
            else f"middle ({index + 1}/{len(all_segments)})"
        )

        # Select relevant knowledge (Problem 4: smart cropping)
        cinematography_knowledge = self._select_knowledge_for_shot(
            analysis.scene_type, analysis.emotion, analysis.pacing
        )

        # Smart template selection based on context length
        template = self._select_template(
            text=text,
            cinematography_knowledge=cinematography_knowledge,
            character_profiles=character_profiles_str,
            scene_style=scene_style_str,
            video_model=video_model,
        )

        # Build validator for all required fields including three-layer model
        validator = OutputValidator.combine(
            OutputValidator.has_keys(
                "director_vision", "cinematic_format", "shot_type", "movement",
                "focal_length", "aperture", "camera_angle", "lighting_scheme",
                "light_sources", "composition", "color_palette", "atmosphere",
                "depth_of_field", "style_fingerprint", "image_prompt",
                "negative_prompt", "reasoning"
            ),
            OutputValidator.non_empty("director_vision"),
            OutputValidator.non_empty("cinematic_format"),
            OutputValidator.non_empty("image_prompt"),
            OutputValidator.non_empty("negative_prompt"),
            OutputValidator.type_check("light_sources", list),
        )

        try:
            # DEBUG
            template_user = getattr(template, "user", "")[:80]
            print(f"DEBUG template: {repr(template_user)}")
            print(f"DEBUG profiles: {repr(character_profiles_str)[:150]}")
            print(f"DEBUG style: {repr(scene_style_str)[:150]}")
            
            design_data = self.llm_client.run_template_validated(
                template,
                validator=validator,
                cinematography_knowledge=cinematography_knowledge,
                character_profiles=character_profiles_str,
                scene_style=scene_style_str,
                seg_id=seg_id,
                text=text,
                duration=f"{duration:.1f}",
                emotion=analysis.emotion,
                intensity=f"{analysis.intensity:.1f}",
                scene_type=analysis.scene_type,
                entities=(
                    ", ".join(analysis.key_entities[:5])
                    if analysis.key_entities
                    else "none"
                ),
                visual_keywords=(
                    ", ".join(analysis.visual_keywords[:5])
                    if analysis.visual_keywords
                    else "none"
                ),
                narrative_function=getattr(analysis, "narrative_function", "exposition"),
                pacing=analysis.pacing,
                style=style_template or "cinematic documentary",
                overall_tone=overall_tone,
                prev_context=prev_context,
                next_context=next_context,
                position=position,
                max_format_retries=2,
            )

            design = self._build_shot_design(design_data, seg_id, text, analysis)

            # Optional: generate multiple variations for key shots (Problem 5)
            if generate_variations:
                design.metadata["variations"] = self._generate_variations(
                    design, seg_id, text, analysis, cinematography_knowledge,
                    style_template, overall_tone, prev_context, next_context, position,
                    video_model,
                )

            # Self-critique (Problem 6)
            critique = self._critique_design(design, text, analysis)
            if critique:
                design.metadata["critique"] = critique
                # If critique reveals serious issues, redesign with constraints
                if critique.get("score", 1.0) < 0.6:
                    logger.info(
                        f"[PromptDirector] Redesigning shot {seg_id} after critique "
                        f"(score: {critique['score']:.2f})"
                    )
                    design = self._redesign_with_constraints(
                        design, critique["issues"], text, analysis, cinematography_knowledge,
                        style_template, overall_tone, prev_context, next_context, position,
                    )

            # Add video model specific notes (Problem 7)
            design.metadata["video_model_notes"] = self._video_model_notes(
                video_model, design
            )

            return design

        except Exception as e:
            logger.error(f"PromptDirector failed for segment {seg_id}: {e}")
            raise RuntimeError(
                f"PromptDirector failed to design shot {seg_id}. "
                f"Error: {e}\n"
                f"This is a critical failure — PromptDirector does not fall back to rules."
            ) from e

    # ── Sequence Consistency (Problem 3: write, not just read) ───────────────────────────

    def _check_sequence_consistency(self, designs: list[Any]) -> list[Any]:
        """Review sequence consistency and APPLY fixes to designs."""
        if len(designs) < 2 or not self.llm_client:
            return designs

        # Build shots_data: each shot's cinematic_format + key visual params
        # Layer 3 (cinematic_format) is the primary source for consistency checking
        shots_data = []
        for d in designs:
            shot_info = {
                "id": d.segment_id,
                "cinematic_format": d.cinematic_format or d.director_vision or d.image_prompt or "",
                "director_vision": d.director_vision or "",
                "emotion": d.emotion or "",
                "key_entities": d.metadata.get("key_entities", ""),
                "light_sources": d.metadata.get("light_sources", ""),
                "color_palette": d.metadata.get("color_palette", ""),
                "atmosphere": d.metadata.get("atmosphere", ""),
                "shot_type": d.shot_type.value if d.shot_type else "",
                "movement": d.movement.value if d.movement else "still",
                # Also include style_fingerprint as fallback for legacy designs
                "style_fingerprint": d.style_prefix or "",
            }
            shots_data.append(shot_info)

        template = get_prompt("sequence_consistency")

        try:
            data = self.llm_client.run_template_validated(
                template,
                validator=OutputValidator.has_nested_keys(
                    "consistency_score",
                    "issues",
                    "suggested_adjustments",
                    "world_logic_score",
                    "style_coherence_score",
                    "narrative_coherence_score",
                ),
                count=len(designs),
                shots_data=json.dumps(shots_data, ensure_ascii=False, indent=2),
                max_format_retries=1,
            )

            if not isinstance(data, list):
                logger.warning("Sequence consistency check returned invalid format")
                return designs

            for i, item in enumerate(data):
                if i >= len(designs):
                    break
                design = designs[i]
                issues = item.get("issues", [])
                adjustments = item.get("suggested_adjustments", "")
                score = item.get("consistency_score", 1.0)
                world_logic = item.get("world_logic_score", 1.0)
                style_coherence = item.get("style_coherence_score", 1.0)
                narrative_coherence = item.get("narrative_coherence_score", 1.0)
                sequence_role = item.get("sequence_role", "")
                positive_observation = item.get("positive_observation", "")

                # Record findings in metadata
                design.metadata["consistency_issues"] = issues
                design.metadata["consistency_score"] = score
                design.metadata["world_logic_score"] = world_logic
                design.metadata["style_coherence_score"] = style_coherence
                design.metadata["narrative_coherence_score"] = narrative_coherence
                design.metadata["sequence_role"] = sequence_role
                design.metadata["consistency_adjustments"] = adjustments
                design.metadata["positive_observation"] = positive_observation

                if issues:
                    logger.info(
                        f"[PromptDirector] Shot {design.segment_id} consistency issues: "
                        f"{issues}"
                    )

                # Apply adjustments: if overall consistency score is low, trigger redesign
                if score < 0.5 and adjustments and adjustments.lower() not in (
                    "none", "无", "none.", ""
                ):
                    logger.info(
                        f"[PromptDirector] Redesigning shot {design.segment_id} "
                        f"due to low consistency score ({score:.2f})"
                    )
                    # Rebuild with consistency constraints
                    design = self._apply_consistency_adjustments(design, adjustments)
                    designs[i] = design

                # Also apply minor adjustments directly to metadata if no redesign needed
                elif adjustments and adjustments.lower() not in (
                    "none", "无", "none.", ""
                ):
                    design.metadata["consistency_applied"] = True
                    # Parse and apply specific prompt adjustments
                    self._apply_prompt_adjustments(design, adjustments)

            return designs
        except Exception as e:
            logger.warning(f"Sequence consistency check failed: {e}")
            return designs

    def _apply_consistency_adjustments(self, design: Any, adjustments: str) -> Any:
        """Redesign a shot with consistency constraints baked into the cinematic_format."""
        # Build a correction prompt that focuses on cinematic_format (Layer 3)
        correction_prompt = (
            f"You are a director fixing a shot for visual world consistency.\n\n"
            f"Original director_vision (Layer 1): {design.director_vision or design.image_prompt}\n\n"
            f"Original cinematic_format (Layer 3): {design.cinematic_format or 'not provided'}\n\n"
            f"Required adjustments (from sequence consistency review): {adjustments}\n\n"
            f"Your task:\n"
            f"1. FIRST, rewrite the director_vision to incorporate these adjustments while preserving the shot's core emotional and visual intent.\n"
            f"2. THEN, rewrite the cinematic_format using standard cinematic language. It must include: EXT./INT., SHOT SIZE, LENS, ANGLE, MOVEMENT, LIGHTING (with specific Kelvin values), COMPOSITION, COLOR (with specific hex values), DEPTH OF FIELD (with aperture), ATMOSPHERE, MOOD, DURATION.\n"
            f"3. FINALLY, based on the corrected director_vision and cinematic_format, derive all technical parameters.\n\n"
            f"Return ONLY a JSON object:\n"
            f'{{"director_vision": "...", "cinematic_format": "...", "image_prompt": "...", "negative_prompt": "...", '
            f'"light_sources": "...", "color_palette": "...", "atmosphere": "...", '
            f'"movement": "...", "emotion": "...", "key_entities": "..."}}'
        )

        try:
            from narrascape.llm.models import Message
            resp = self.llm_client.chat(
                [Message(role="user", content=correction_prompt)]
            )
            data = resp.extract_json_safe()
            if data and isinstance(data, dict):
                if data.get("director_vision"):
                    design.director_vision = data["director_vision"]
                if data.get("cinematic_format"):
                    design.cinematic_format = data["cinematic_format"]
                if data.get("image_prompt"):
                    design.image_prompt = data["image_prompt"]
                if data.get("negative_prompt"):
                    design.metadata["negative_prompt"] = data["negative_prompt"]
                if data.get("light_sources"):
                    design.light_sources = data["light_sources"]
                if data.get("color_palette"):
                    design.color_palette = data["color_palette"]
                if data.get("atmosphere"):
                    design.atmosphere = data["atmosphere"]
                if data.get("movement"):
                    design.movement = data["movement"]
                if data.get("emotion"):
                    design.emotion = data["emotion"]
                if data.get("key_entities"):
                    design.key_entities = data["key_entities"]
                design.reasoning += f" [Consistency fix: {adjustments}]"
        except Exception as e:
            logger.warning(f"Failed to apply consistency adjustments: {e}")

        return design

    def _apply_prompt_adjustments(self, design: Any, adjustments: str) -> None:
        """Apply minor adjustments to director_vision directly (no LLM call)."""
        adj_lower = adjustments.lower()

        # If adjustments suggest modifying director_vision, do a lightweight rewrite
        if "director_vision" in adj_lower or "director vision" in adj_lower:
            # Try to extract the suggested modification
            # Heuristic: look for quoted text after the suggestion
            import re
            match = re.search(r'''["\'](.+?)["\']''', adjustments)
            if match and design.director_vision:
                new_vision = match.group(1)
                design.director_vision = new_vision
                design.reasoning += f" [Minor consistency adjustment: rewritten director_vision]"
            return

        # Simple heuristics: extract keyword adjustments for metadata hints
        # Color temperature adjustments
        if "warm" in adj_lower and "cool" in adj_lower:
            pass  # ambiguous
        elif "warm" in adj_lower or "golden" in adj_lower:
            design.metadata["color_temperature_hint"] = "warm"
        elif "cool" in adj_lower or "blue" in adj_lower or "teal" in adj_lower:
            design.metadata["color_temperature_hint"] = "cool"

        # Light direction adjustments
        if "screen left" in adj_lower or "left" in adj_lower:
            design.metadata["light_direction_hint"] = "screen left"
        elif "screen right" in adj_lower or "right" in adj_lower:
            design.metadata["light_direction_hint"] = "screen right"

        # Weather/atmosphere adjustments
        if "rain" in adj_lower:
            design.metadata["weather_hint"] = "rain"
        elif "fog" in adj_lower or "mist" in adj_lower:
            design.metadata["weather_hint"] = "fog"
        elif "clear" in adj_lower or "sunny" in adj_lower:
            design.metadata["weather_hint"] = "clear"

        design.metadata["adjustments_parsed"] = True

    # ── Character & Scene Consistency Anchors ───────────────────────────

    def _build_character_profiles(
        self,
        segments: list[Any],
        analysis_list: list[Any],
    ) -> None:
        """Build character profiles from the full script for consistency anchoring.

        This runs BEFORE any shot design to ensure all shots reference the same
        character identities. Uses the configured LLM or AI Assistant bridge to extract characters from all segments.
        """
        # AI Assistant mode: llm_client always available, proceed directly
        try:
            from narrascape.agent.models import CharacterProfile

            # Build segments and analysis JSON for the prompt
            segments_json = json.dumps(
                [{"id": seg.id, "text": seg.text} for seg in segments],
                ensure_ascii=False,
            )
            analysis_json = json.dumps(
                [
                    {
                        "segment_id": a.segment_id,
                        "emotion": a.emotion,
                        "scene_type": a.scene_type,
                        "key_entities": a.key_entities,
                        "visual_keywords": a.visual_keywords,
                    }
                    for a in analysis_list
                ],
                ensure_ascii=False,
            )

            template = get_prompt("character_profile")
            from narrascape.llm.models import Message

            resp = self.llm_client.chat(
                [Message(
                    role="user",
                    content=template.user.format(
                        segments_json=segments_json,
                        analysis_json=analysis_json,
                    ),
                )]
            )
            data = resp.extract_json_safe()

            if isinstance(data, list):
                profiles = []
                char_id_map = {}
                for item in data:
                    if isinstance(item, dict) and item.get("char_id"):
                        profile = CharacterProfile(
                            char_id=item["char_id"],
                            name=item.get("name", ""),
                            identity_block=item.get("identity_block", ""),
                            face_description=item.get("face_description", ""),
                            hair_description=item.get("hair_description", ""),
                            body_description=item.get("body_description", ""),
                            default_outfit=item.get("default_outfit", ""),
                            signature_accessories=item.get("signature_accessories", []),
                            negative_anchors=item.get("negative_anchors", []),
                            reference_image_url=item.get("reference_image_url", ""),
                        )
                        profiles.append(profile)
                        # Map entity names to char_id for auto-referencing
                        if profile.name:
                            char_id_map[profile.name.lower()] = profile.char_id
                        # Also map common variations
                        char_id_map[profile.char_id.lower()] = profile.char_id

                self._characters = profiles
                self._character_id_map = char_id_map
                logger.info(
                    f"[PromptDirector] Built {len(profiles)} character profiles: "
                    f"{[p.char_id for p in profiles]}"
                )
            else:
                self._characters = []
                logger.info("[PromptDirector] No characters detected in segments")

        except Exception as e:
            logger.warning(f"[PromptDirector] Failed to build character profiles: {e}")
            self._characters = []

    def _build_scene_style(
        self,
        segments: list[Any],
        analysis_list: list[Any],
        style_template: str,
    ) -> None:
        """Build scene style from the full script for visual world consistency.

        This runs BEFORE any shot design to ensure all shots share the same
        visual world rules.
        """
        # AI Assistant mode: llm_client always available, proceed directly
        try:
            from narrascape.agent.models import SceneStyle

            segments_json = json.dumps(
                [{"id": seg.id, "text": seg.text} for seg in segments],
                ensure_ascii=False,
            )
            analysis_json = json.dumps(
                [
                    {
                        "segment_id": a.segment_id,
                        "emotion": a.emotion,
                        "scene_type": a.scene_type,
                        "visual_keywords": a.visual_keywords,
                    }
                    for a in analysis_list
                ],
                ensure_ascii=False,
            )

            template = get_prompt("scene_style")
            from narrascape.llm.models import Message

            resp = self.llm_client.chat(
                [Message(
                    role="user",
                    content=template.user.format(
                        segments_json=segments_json,
                        analysis_json=analysis_json,
                    ),
                )]
            )
            data = resp.extract_json_safe()

            if isinstance(data, dict) and data.get("style_id"):
                self._scene_style = SceneStyle(
                    style_id=data.get("style_id", "main_style"),
                    style_name=data.get("style_name", ""),
                    base_color_temperature=data.get("base_color_temperature", ""),
                    color_palette=data.get("color_palette", ""),
                    lighting_signature=data.get("lighting_signature", ""),
                    texture_palette=data.get("texture_palette", ""),
                    atmosphere_signature=data.get("atmosphere_signature", ""),
                    depth_signature=data.get("depth_signature", ""),
                    lens_signature=data.get("lens_signature", ""),
                    style_references=data.get("style_references", []),
                    world_rules=data.get("world_rules", []),
                    consistency_notes=data.get("consistency_notes", ""),
                )
                logger.info(
                    f"[PromptDirector] Built scene style: {self._scene_style.style_id} "
                    f"({self._scene_style.style_name})"
                )
            else:
                self._scene_style = None
                logger.info("[PromptDirector] No scene style built")

        except Exception as e:
            logger.warning(f"[PromptDirector] Failed to build scene style: {e}")
            self._scene_style = None

    def _format_character_profiles_for_template(self) -> str:
        """Format character profiles for injection into shot design template."""
        if not self._characters:
            return "No characters in this sequence. Landscape/abstract shots only."

        formatted = []
        for c in self._characters:
            profile = (
                f'{{"char_id": "{c.char_id}", '
                f'"identity_block": "{c.identity_block}", '
                f'"face_description": "{c.face_description}", '
                f'"hair_description": "{c.hair_description}", '
                f'"body_description": "{c.body_description}", '
                f'"default_outfit": "{c.default_outfit}", '
                f'"signature_accessories": {json.dumps(c.signature_accessories)}, '
                f'"negative_anchors": {json.dumps(c.negative_anchors)}' + '}'
            )
            formatted.append(profile)

        result = "[\n" + ",\n".join(formatted) + "\n]"
        return result.replace("{", "{{").replace("}", "}}")

    def _format_scene_style_for_template(self) -> str:
        """Format scene style for injection into shot design template."""
        if not self._scene_style:
            return "No scene style defined. Use director's discretion."

        s = self._scene_style
        result = (
            f'{{"style_id": "{s.style_id}", '
            f'"style_name": "{s.style_name}", '
            f'"base_color_temperature": "{s.base_color_temperature}", '
            f'"color_palette": "{s.color_palette}", '
            f'"lighting_signature": "{s.lighting_signature}", '
            f'"texture_palette": "{s.texture_palette}", '
            f'"atmosphere_signature": "{s.atmosphere_signature}", '
            f'"depth_signature": "{s.depth_signature}", '
            f'"lens_signature": "{s.lens_signature}", '
            f'"style_references": {json.dumps(s.style_references)}, '
            f'"world_rules": {json.dumps(s.world_rules)}}}'
        )
        return result.replace("{", "{{").replace("}", "}}")

    def _build_reference_image_chains(self, designs: list[Any]) -> None:
        """Build reference image chains for Seedream/Seedance multi-reference workflow.

        Automatically creates chains from:
        - Character profiles (one chain per character with reference_image_url)
        - Scene style (one chain for style references)
        - Per-shot generated images (linked via reference_chain_ids)

        These chains are used by:
        - Seedream 4.0+ for multi-reference image generation
        - Seedance 2.0 for first/last frame and multi-modal reference
        """
        from narrascape.agent.models import ReferenceImageChain

        chains: list[Any] = []

        # Character reference chains
        for char in self._characters:
            if char.reference_image_url:
                chains.append(ReferenceImageChain(
                    chain_id=f"char_{char.char_id}",
                    chain_type="character",
                    reference_urls=[char.reference_image_url] if isinstance(char.reference_image_url, str) else char.reference_image_url,
                    target_model=char.seedream_model or "seedream_4.6",
                    usage_mode="reference",
                    sample_strength=char.seedream_sample_strength or 0.5,
                    consistency_target="face",
                    description=f"Character reference: {char.name}",
                ))

        # Scene style reference chain
        if self._scene_style and self._scene_style.style_references:
            chains.append(ReferenceImageChain(
                chain_id=f"style_{self._scene_style.style_id}",
                chain_type="style",
                reference_urls=self._scene_style.style_references,
                target_model="seedream_5.0",
                usage_mode="style",
                sample_strength=0.3,
                consistency_target="style",
                description=f"Style reference: {self._scene_style.style_name}",
            ))

        # Per-shot generated image chains (for video first/last frame linking)
        for design in designs:
            if design.reference_chain_ids:
                for chain_id in design.reference_chain_ids:
                    # Link to existing chain or create new
                    existing = [c for c in chains if c.chain_id == chain_id]
                    if not existing:
                        chains.append(ReferenceImageChain(
                            chain_id=chain_id,
                            chain_type="scene",
                            reference_urls=[],
                            target_model=design.seedance_model or "seedance_2.0",
                            usage_mode="first_frame",
                            sample_strength=0.5,
                            consistency_target="all",
                            description=f"Scene chain for segment {design.segment_id}",
                        ))

        self._reference_image_chains = chains
        logger.info(f"[PromptDirector] Built {len(chains)} reference image chains")

    def _verify_character_consistency(self, designs: list[Any]) -> None:
        """Verify that characters remain consistent across all shots.

        This is a lightweight heuristic check (no LLM call) to catch obvious
        character drift before images are generated.
        """
        if not self._characters or len(designs) < 2:
            return

        # Build a mapping of char_id -> expected identity_block
        identity_map = {c.char_id: c.identity_block for c in self._characters}

        for design in designs:
            if not design.character_refs:
                continue

            for char_id in design.character_refs:
                if char_id not in identity_map:
                    continue

                expected_identity = identity_map[char_id].lower()
                image_prompt = design.image_prompt.lower()
                director_vision = design.director_vision.lower()

                # Check 1: Does image_prompt contain key identity terms?
                # Extract key nouns/adjectives from identity_block (simple heuristic)
                key_terms = [word for word in expected_identity.split()
                            if len(word) > 3 and word not in (
                                "with", "wearing", "and", "the", "his", "her", "has",
                                "have", "had", "been", "were", "are", "from", "this",
                                "that", "for", "not", "but", "you", "she", "they",
                            )]

                missing_terms = []
                for term in key_terms[:10]:  # Check top 10 most significant terms
                    if term not in image_prompt:
                        missing_terms.append(term)

                if missing_terms:
                    logger.warning(
                        f"[PromptDirector] Character '{char_id}' in shot {design.segment_id} "
                        f"may be missing identity terms in image_prompt: {missing_terms}"
                    )
                    design.metadata["character_drift_warning"] = (
                        f"Missing identity terms for {char_id}: {missing_terms}"
                    )

                # Check 2: Does negative_prompt contain anti-drift terms?
                negative = design.metadata.get("negative_prompt", "").lower()
                anti_drift_terms = ["different hair", "different face", "different outfit",
                                   "different age", "smooth skin", "deformed face"]
                has_protection = any(term in negative for term in anti_drift_terms)

                if not has_protection and design.character_refs:
                    logger.warning(
                        f"[PromptDirector] Shot {design.segment_id} negative_prompt lacks "
                        f"character drift protection for {char_id}"
                    )
                    # Auto-add basic protection
                    if negative:
                        design.metadata["negative_prompt"] = (
                            negative + ", different hair color, different face, different outfit, "
                            "different age, smooth skin, deformed face, extra limbs, mutated hands"
                        )
                    else:
                        design.metadata["negative_prompt"] = (
                            "different hair color, different face, different outfit, different age, "
                            "smooth skin, deformed face, extra limbs, mutated hands, bad anatomy"
                        )

                # Check 3: Does director_vision match identity_block (should contain similar terms)?
                overlap = sum(1 for term in key_terms[:5] if term in director_vision)
                if overlap < 2:  # At least 2 key terms should appear in director_vision
                    logger.warning(
                        f"[PromptDirector] Character '{char_id}' in shot {design.segment_id} "
                        f"director_vision may not match identity_block (overlap: {overlap}/5)"
                    )

    # ── Smart Knowledge Selection (Problem 4) ───────────────────────────

    def _select_knowledge_for_shot(
        self, scene_type: str, emotion: str, pacing: str
    ) -> str:
        """Select the most relevant cinematography knowledge for this shot.

        Instead of sending the entire ~15KB knowledge base, we prioritize chapters
        based on the shot's needs and return only the most relevant sections.
        """
        from narrascape.agent.cinematography_knowledge import (
            SHOT_TYPE_KNOWLEDGE,
            CAMERA_LENS_KNOWLEDGE,
            LIGHTING_KNOWLEDGE,
            COMPOSITION_KNOWLEDGE,
            COLOR_ATMOSPHERE_KNOWLEDGE,
            NEGATIVE_PROMPT_KNOWLEDGE,
            VIDEO_FIRST_KNOWLEDGE,
        )

        # Priority 1: Shot type knowledge (always essential)
        selected = [SHOT_TYPE_KNOWLEDGE]

        # Priority 2: Scene-specific knowledge
        scene_type_lower = scene_type.lower()
        if scene_type_lower in ("landscape", "outdoor", "wilderness", "seascape"):
            selected.append(CAMERA_LENS_KNOWLEDGE)  # focal length matters most for landscapes
        elif scene_type_lower in ("portrait", "indoor", "domestic"):
            selected.append(LIGHTING_KNOWLEDGE)  # lighting is critical for indoor
        else:
            # General: include both but truncated
            selected.append(CAMERA_LENS_KNOWLEDGE[:1500])
            selected.append(LIGHTING_KNOWLEDGE[:1500])

        # Priority 3: Emotion-specific knowledge
        emotion_lower = emotion.lower()
        if emotion_lower in ("tense", "dramatic", "mysterious", "melancholic"):
            # Lighting is most important for mood
            selected.append(LIGHTING_KNOWLEDGE)
        elif emotion_lower in ("nostalgic", "awe", "hopeful"):
            # Color palette is most important
            selected.append(COLOR_ATMOSPHERE_KNOWLEDGE)

        # Priority 4: Composition (always useful)
        selected.append(COMPOSITION_KNOWLEDGE)

        # Priority 5: Negative prompts (always needed for AI generation)
        selected.append(NEGATIVE_PROMPT_KNOWLEDGE)

        # Priority 6: Video-first (if the output is for video)
        if pacing in ("slow", "normal"):
            selected.append(VIDEO_FIRST_KNOWLEDGE)

        # Combine and ensure we don't exceed a reasonable token budget
        combined = "\n".join(selected)
        # Rough estimate: ~4 chars per token. Target ~6000 chars (~1500 tokens).
        max_chars = 6000
        if len(combined) > max_chars:
            # Truncate with a clear indicator
            combined = combined[:max_chars] + (
                "\n\n[Knowledge base truncated for length. Prioritized sections relevant to this shot.]"
            )

        return combined

    # ── Smart Template Selection (Problem 3) ───────────────────────────

    def _select_template(
        self,
        text: str,
        cinematography_knowledge: str,
        character_profiles: str = "",
        scene_style: str = "",
        video_model: str = "generic",
    ) -> str:
        """Select the optimal template based on estimated context length.

        Decision tree:
        - If total context > ~12K tokens (Claude limit): use COMPACT
        - If total context > ~8K tokens (GPT-4 / DeepSeek limit): use COMPACT
        - Otherwise: use FULL (SHOT_DESIGN_PROMPT)

        Context includes: text, knowledge, character profiles, scene style.
        """
        # Rough token estimate: ~4 chars per token for mixed CJK/English
        total_chars = len(text) + len(cinematography_knowledge)
        if character_profiles:
            total_chars += len(character_profiles)
        if scene_style:
            total_chars += len(scene_style)

        estimated_tokens = total_chars // 4

        # Claude models have the most generous context
        if video_model in ("claude-3-5-sonnet", "claude-3-opus"):
            threshold = 15000
        # GPT-4o has moderate context
        elif video_model in ("gpt-4o", "gpt-4-turbo"):
            threshold = 10000
        # GPT-4 / Doubao / Llama / Generic have limited context
        elif video_model in ("gpt-4", "doubao-pro", "llama-3"):
            threshold = 7000
        # DeepSeek has even less
        elif video_model in ("deepseek-v3", "deepseek-v2"):
            threshold = 6000
        # Generic fallback
        else:
            threshold = 8000

        if estimated_tokens > threshold:
            logger.info(
                f"[PromptDirector] Context length {estimated_tokens} tokens exceeds "
                f"threshold {threshold} for {video_model}. Switching to COMPACT template."
            )
            return get_prompt("compact_shot_design")
        else:
            return get_prompt("shot_design")

    # ── Multi-Variation Generation (Problem 5) ───────────────────────────

    def _generate_variations(
        self,
        design: Any,
        seg_id: int,
        text: str,
        analysis: Any,
        cinematography_knowledge: str,
        style_template: str,
        overall_tone: str,
        prev_context: str,
        next_context: str,
        position: str,
        video_model: str,
    ) -> list[dict]:
        """Generate 2-3 alternative shot designs for key moments.

        Uses a cheaper, faster approach: ask AI Assistant to suggest 2 variations
        with different camera angles or focal lengths.
        """
        # AI Assistant mode: llm_client always available, proceed directly
        try:
            variation_prompt = (
                f"You are a cinematographer. The following shot has been designed for a documentary.\n\n"
                f"Original design:\n"
                f"- shot_type: {design.shot_type.value}\n"
                f"- focal_length: {design.metadata.get('focal_length', 'unknown')}\n"
                f"- camera_angle: {design.metadata.get('camera_angle', 'unknown')}\n"
                f"- movement: {design.movement.value if design.movement else 'still'}\n"
                f"- image_prompt: {design.image_prompt[:200]}\n\n"
                f"Generate 2 alternative approaches (different shot type, focal length, or angle) "
                f"that could also work for this moment. Each should be a valid creative choice.\n\n"
                f'Return ONLY a JSON array of 2 objects: '
                f'[{{"shot_type": "...", "focal_length": "...", "camera_angle": "...", '
                f'"movement": "...", "image_prompt": "...", "reasoning": "..."}}, ...]'
            )

            from narrascape.llm.models import Message
            resp = self.llm_client.chat([Message(role="user", content=variation_prompt)])
            data = resp.extract_json_safe()

            if isinstance(data, list) and len(data) >= 2:
                variations = []
                for v in data[:2]:
                    if isinstance(v, dict) and v.get("image_prompt"):
                        variations.append({
                            "shot_type": v.get("shot_type", design.shot_type.value),
                            "focal_length": v.get("focal_length", ""),
                            "camera_angle": v.get("camera_angle", ""),
                            "movement": v.get("movement", ""),
                            "image_prompt": v.get("image_prompt", ""),
                            "reasoning": v.get("reasoning", "Alternative design"),
                        })
                return variations

        except Exception as e:
            logger.warning(f"Failed to generate variations for shot {seg_id}: {e}")

        return []

    # ── Self-Critique (Problem 6) ───────────────────────────

    def _critique_design(self, design: Any, text: str, analysis: Any) -> dict | None:
        """Critique a shot design and return a score + improvement suggestions."""
        # AI Assistant mode: llm_client always available, proceed directly
        try:
            critique_prompt = (
                f"You are a cinematography critic. Critique this shot design:\n\n"
                f"Narration text: '{text}'\n"
                f"Emotion: {analysis.emotion} (intensity: {analysis.intensity})\n"
                f"Scene type: {analysis.scene_type}\n\n"
                f"Designed shot:\n"
                f"- image_prompt: {design.image_prompt}\n"
                f"- negative_prompt: {design.metadata.get('negative_prompt', '')}\n"
                f"- focal_length: {design.metadata.get('focal_length', '')}\n"
                f"- lighting: {design.metadata.get('lighting_scheme', '')}\n"
                f"- composition: {design.metadata.get('composition', '')}\n\n"
                f"Evaluate on:\n"
                f"1. Does the image_prompt contain concrete visual details (not vague words)?\n"
                f"2. Does the lighting description specify direction and source?\n"
                f"3. Does the composition match the emotion?\n"
                f"4. Does the negative_prompt cover common AI artifacts?\n"
                f"5. Does the shot serve the narration (not just look pretty)?\n\n"
                f'Return ONLY a JSON object: '
                f'{{"score": 0.0-1.0, "issues": ["..."], "suggestions": ["..."]}}'
            )

            from narrascape.llm.models import Message
            resp = self.llm_client.chat([Message(role="user", content=critique_prompt)])
            data = resp.extract_json_safe()

            if isinstance(data, dict) and "score" in data:
                return {
                    "score": float(data.get("score", 1.0)),
                    "issues": data.get("issues", []),
                    "suggestions": data.get("suggestions", []),
                }

        except Exception as e:
            logger.warning(f"Self-critique failed for shot {design.segment_id}: {e}")

        return None

    # ── Redesign with Constraints ───────────────────────────

    def _redesign_with_constraints(
        self,
        design: Any,
        issues: list[str],
        text: str,
        analysis: Any,
        cinematography_knowledge: str,
        style_template: str,
        overall_tone: str,
        prev_context: str,
        next_context: str,
        position: str,
    ) -> Any:
        """Redesign a shot after critique or consistency issues."""
        constraints = "; ".join(issues) if isinstance(issues, list) else str(issues)

        # Reuse the original shot design but with constraints appended
        template = self._select_template(
            text=text,
            cinematography_knowledge=cinematography_knowledge,
            video_model="generic",  # redesign uses default
        )
        validator = OutputValidator.combine(
            OutputValidator.has_keys(
                "shot_type", "movement", "focal_length", "aperture",
                "camera_angle", "lighting_scheme", "light_sources",
                "composition", "color_palette", "atmosphere",
                "depth_of_field", "style_fingerprint", "image_prompt",
                "negative_prompt", "reasoning"
            ),
            OutputValidator.non_empty("image_prompt"),
            OutputValidator.non_empty("negative_prompt"),
        )

        try:
            design_data = self.llm_client.run_template_validated(
                template,
                validator=validator,
                cinematography_knowledge=cinematography_knowledge,
                seg_id=design.segment_id,
                text=text,
                duration="5.0",
                emotion=analysis.emotion,
                intensity=f"{analysis.intensity:.1f}",
                scene_type=analysis.scene_type,
                entities=(
                    ", ".join(analysis.key_entities[:5])
                    if analysis.key_entities
                    else "none"
                ),
                visual_keywords=(
                    ", ".join(analysis.visual_keywords[:5])
                    if analysis.visual_keywords
                    else "none"
                ),
                narrative_function=getattr(analysis, "narrative_function", "exposition"),
                pacing=analysis.pacing,
                style=style_template or "cinematic documentary",
                overall_tone=overall_tone,
                prev_context=prev_context,
                next_context=next_context,
                position=position,
                max_format_retries=2,
            )

            new_design = self._build_shot_design(design_data, design.segment_id, text, analysis)
            new_design.reasoning += f" [Redesigned with constraints: {constraints}]"
            return new_design

        except Exception as e:
            logger.warning(f"Redesign failed for shot {design.segment_id}: {e}")
            return design  # Return original if redesign fails

    # ── Video Model Notes (Problem 7) ───────────────────────────

    def _video_model_notes(self, video_model: str, design: Any) -> dict:
        """Generate model-specific notes for video generation."""
        notes = {}
        vm = video_model.lower()

        if vm == "runway" or vm == "gen3":
            notes["model"] = "Runway Gen-3"
            notes["resolution"] = "1280x768"
            notes["requirements"] = [
                "Ensure natural motion in the image (subjects in natural poses)",
                "Leave motion space for camera movement (don't crop too tightly)",
                "Avoid extreme motion blur in the still image",
                "High contrast helps motion detection",
            ]
            notes["aspect_ratio"] = "16:9"
        elif vm == "sora":
            notes["model"] = "Sora"
            notes["resolution"] = "1920x1080+"
            notes["requirements"] = [
                "Include clear depth layers (foreground, midground, background)",
                "Physical world consistency is critical (correct lighting, gravity, materials)",
                "Leave room for temporal continuity (subjects not edge-locked)",
                "High dynamic range helps video quality",
            ]
            notes["aspect_ratio"] = "16:9 or 2.39:1"
        elif vm == "kling":
            notes["model"] = "Kling"
            notes["resolution"] = "1280x720"
            notes["requirements"] = [
                "Moderate motion amplitude works best (not too subtle, not too extreme)",
                "Cinematic framing with stable composition",
                "Good for Chinese cultural aesthetics if applicable",
                "Avoid overexposed or underexposed regions",
            ]
            notes["aspect_ratio"] = "16:9"
        elif vm == "veo":
            notes["model"] = "Google Veo"
            notes["resolution"] = "1280x768"
            notes["requirements"] = [
                "Object consistency across frames is key",
                "Smooth gradients in sky/water/skin reduce banding",
                "Gradual motion (not sudden jumps) preferred",
                "Clear subject with unambiguous edges",
            ]
            notes["aspect_ratio"] = "16:9"
        elif vm == "seedance" or vm == "seedance2" or vm == "jimeng":
            notes["model"] = "火山引擎 Seedance 2.0"
            notes["resolution"] = "720p or 1080p"
            notes["api_params"] = {
                "model": "jimeng-video-seedance-2.0 (full features) or jimeng-video-seedance-2.0-fast (cost-effective)",
                "filePath": "Array of image paths/URLs. First element = first frame, second = last frame. Max 2 elements.",
                "resolution": "720p or 1080p",
                "prompt": "Text description of the video",
            }
            notes["requirements"] = [
                "Seedance 2.0 supports 4-modal reference: image, video, audio, text. Up to 12 files mixed reference.",
                "Character consistency is EXTREMELY strong. Multi-character, multi-shot precise consistency.",
                "Use generated Seedream images as first_frame for zero-loss workflow.",
                "For character consistency: upload character reference image as first_frame.",
                "For style consistency: upload style reference image alongside text prompt.",
                "Seedance 2.0 has native audio sync. Single/multi-person lip sync supported.",
                "Motion can be precisely replicated from reference video.",
                "Video extension is smooth and natural. Supports intelligent continuation.",
            ]
            notes["reference_workflow"] = [
                "Step 1: Generate character images using Seedream (recommend jimeng-4.6 for face consistency)",
                "Step 2: Use generated image URL as filePath[0] (first_frame) for Seedance video generation",
                "Step 3: If needed, add filePath[1] (last_frame) for video with defined ending",
                "Step 4: Text prompt should describe motion, camera movement, and scene transitions",
            ]
            notes["aspect_ratio"] = "16:9"
            notes["seedance_fast"] = {
                "model": "jimeng-video-seedance-2.0-fast",
                "benefits": "30-50% fewer credits, no queue, faster generation",
                "recommended_for": "Batch production, draft previews, non-critical shots",
            }
            notes["character_consistency"] = {
                "method": "Upload character reference image as first_frame",
                "effectiveness": "Very high - Seedance 2.0 uses multi-modal feature alignment",
                "tips": "Use the same character image across multiple video segments for consistent appearance",
            }
        elif vm == "seedream" or vm == "seedream_img":
            notes["model"] = "火山引擎 Seedream (即梦)"
            notes["resolution"] = "1024x1024 default, customizable"
            notes["api_params"] = {
                "model": "jimeng-5.0 (default, precise response) | jimeng-4.6 (better face consistency, cost-effective) | jimeng-4.0 (multi-reference, series generation) | jimeng-4.1 (professional aesthetics)",
                "prompt": "Text description. Seedream has native Chinese advantage - mix Chinese and English naturally.",
                "filePath": "Reference image path/URL for image-mixing generation. Supports local path or web URL.",
                "width/height": "Image dimensions",
                "sample_strength": "0.0-1.0, default 0.5. Higher = more influence from reference image. Recommend 0.6-0.8 for character consistency.",
                "negative_prompt": "What to exclude",
            }
            notes["requirements"] = [
                "Seedream has native Chinese prompt understanding advantage. Use natural Chinese descriptions.",
                "For character consistency: use jimeng-4.6 + upload character reference image via filePath.",
                "For multi-reference: use jimeng-4.0, supports multiple reference images and series generation.",
                "For professional aesthetics: use jimeng-4.1, better creative and consistency maintenance.",
                "Material detail rendering is excellent. Emphasize specific textures in prompt (e.g., 'rough oak grain', 'worn leather').",
                "When using filePath, model auto-switches to jimeng-2.0-pro for image mixing.",
            ]
            notes["model_selection_guide"] = {
                "jimeng-5.0": "Default. Precise instruction response, smartest generation. Use when no special consistency needs.",
                "jimeng-4.6": "BEST for face consistency. Cost-effective. RECOMMENDED for character portraits.",
                "jimeng-4.5": "Enhanced consistency, style, and text-image response. Good for brand content.",
                "jimeng-4.1": "Professional creative aesthetics. Better for artistic/documentary style.",
                "jimeng-4.0": "Multi-reference support, series generation. Use for multi-character scenes.",
            }
            notes["reference_workflow"] = [
                "Step 1: Generate base character image with identity_block in prompt",
                "Step 2: Save generated image URL",
                "Step 3: For subsequent shots, use same image URL as filePath + identity_block in prompt",
                "Step 4: Set sample_strength 0.6-0.8 for strong character preservation",
            ]
        else:
            notes["model"] = "Generic / Unknown"
            notes["resolution"] = "1920x1080 (recommended)"
            notes["requirements"] = [
                "High resolution keyframe (1080p minimum)",
                "Clear subject and background separation",
                "Consistent lighting and color across the sequence",
                "Leave headroom for camera motion",
            ]
            notes["aspect_ratio"] = "16:9"

        notes["universal"] = [
            "Keyframe should be 20%+ higher resolution than target video",
            "Ken Burns zoom requires resolution headroom",
            "Parallax layers (foreground/midground/background) improve motion",
        ]

        return notes

    # ── Closed-Loop Feedback (Problem 8) ───────────────────────────

    def record_image_quality(
        self,
        segment_id: int,
        image_prompt: str,
        negative_prompt: str,
        accepted: bool,
        issues: list[str] | None = None,
    ) -> None:
        """Record feedback on generated image quality for future optimization.

        This builds a feedback log that can be used to:
        - Identify patterns in negative prompt failures
        - Optimize prompts for specific AI image generators
        - Improve future designs
        """
        entry = {
            "segment_id": segment_id,
            "image_prompt": image_prompt[:300],  # Truncate for storage
            "negative_prompt": negative_prompt[:300],
            "accepted": accepted,
            "issues": issues or [],
        }
        self._feedback_log.append(entry)

        if not accepted and issues:
            # Log patterns for optimization
            logger.info(
                f"[PromptDirector] Image rejected for segment {segment_id}: {issues}"
            )
            # Could trigger negative prompt optimization here
            # For now, just log it

    def get_feedback_summary(self) -> dict:
        """Get a summary of recorded feedback for prompt optimization."""
        if not self._feedback_log:
            return {"total": 0, "acceptance_rate": 0.0, "common_issues": []}

        total = len(self._feedback_log)
        accepted = sum(1 for e in self._feedback_log if e["accepted"])

        # Count common issues
        from collections import Counter
        issue_counts = Counter()
        for e in self._feedback_log:
            for issue in e.get("issues", []):
                issue_counts[issue] += 1

        return {
            "total": total,
            "acceptance_rate": accepted / total if total > 0 else 0.0,
            "common_issues": issue_counts.most_common(5),
        }

    def optimize_negative_prompts(self, base_negative: str) -> str:
        """Optimize negative prompts based on accumulated feedback."""
        if not self._feedback_log:
            return base_negative

        summary = self.get_feedback_summary()
        common_issues = [issue for issue, _ in summary.get("common_issues", [])]

        if not common_issues:
            return base_negative

        # Add commonly missed terms to the negative prompt
        additions = []
        issue_map = {
            "extra limbs": "extra limbs, deformed hands, fused fingers",
            "blurry": "blurry, out of focus, low resolution",
            "wrong style": "cartoon, anime, illustration, 3D render",
            "bad anatomy": "bad anatomy, disfigured, malformed",
            "plastic skin": "plastic skin, smooth skin, porcelain texture",
            "flat lighting": "flat lighting, even lighting, no shadows",
            "inconsistent colors": "inconsistent colors, oversaturated",
        }

        for issue in common_issues:
            for key, terms in issue_map.items():
                if key in issue.lower() and terms not in base_negative.lower():
                    additions.append(terms)

        if additions:
            optimized = base_negative + ", " + ", ".join(additions)
            logger.info(f"[PromptDirector] Optimized negative prompt with: {additions}")
            return optimized

        return base_negative

    # ── Helpers ───────────────────────────

    def _build_shot_design(self, design_data: dict, seg_id: int, text: str, analysis: Any) -> Any:
        """Build a ShotDesign from LLM output data with three-layer model + character consistency."""
        from narrascape.agent.models import ShotDesign

        # Layer 1: director_vision is the creative core
        director_vision = design_data.get("director_vision", "")
        if not director_vision:
            director_vision = design_data.get("image_prompt", text)
            logger.warning(f"[PromptDirector] Shot {seg_id}: director_vision missing from LLM output. Using image_prompt as fallback.")

        # Layer 3: cinematic_format is the standardized cinematic language representation
        cinematic_format = design_data.get("cinematic_format", "")
        if not cinematic_format:
            logger.warning(f"[PromptDirector] Shot {seg_id}: cinematic_format missing from LLM output. Constructing fallback.")
            cinematic_format = self._build_cinematic_format_fallback(design_data, seg_id)

        # Verify three-layer consistency (prevent LLM from cutting corners)
        self._verify_three_layer_consistency(design_data, director_vision, cinematic_format, seg_id)

        # Extract character_refs and style_ref from LLM output
        character_refs = design_data.get("character_refs", [])
        # If LLM didn't provide character_refs, try to infer from key_entities
        if not character_refs and self._character_id_map:
            key_entities = design_data.get("key_entities", "")
            if isinstance(key_entities, str):
                key_entities_lower = key_entities.lower()
                for name, char_id in self._character_id_map.items():
                    if name in key_entities_lower and char_id not in character_refs:
                        character_refs.append(char_id)

        style_ref = design_data.get("style_ref", "")
        # If LLM didn't provide style_ref, use the scene style if available
        if not style_ref and self._scene_style:
            style_ref = self._scene_style.style_id

        # Build image_prompt with character identity injection
        image_prompt = design_data.get("image_prompt", text)
        image_prompt = self._inject_character_identity(image_prompt, character_refs)

        # Auto-select Seedream/Seedance model based on content
        seedream_model = design_data.get("seedream_model", "")
        seedance_model = design_data.get("seedance_model", "")
        seedance_resolution = design_data.get("seedance_resolution", "720p")
        
        if not seedream_model:
            seedream_model = self._select_seedream_model(character_refs)
        if not seedance_model:
            seedance_model = self._select_seedance_model()
        if self._scene_style:
            seedance_resolution = self._scene_style.seedance_resolution

        return ShotDesign(
            segment_id=seg_id,
            shot_type=self._parse_shot_type(design_data.get("shot_type", "medium")),
            movement=self._parse_movement(design_data.get("movement", "still")),
            size=self._derive_size(design_data.get("shot_type", "medium")),
            director_vision=director_vision,
            cinematic_format=cinematic_format,
            image_prompt=image_prompt,
            reasoning=design_data.get("reasoning", "LLM designed"),
            style_prefix=design_data.get("style_fingerprint", ""),
            emotion=design_data.get("emotion", analysis.emotion),
            intensity=float(design_data.get("intensity", analysis.intensity)),
            character_refs=character_refs,
            style_ref=style_ref,
            reference_chain_ids=design_data.get("reference_chain_ids", []),
            seedream_model=seedream_model,
            seedance_model=seedance_model,
            seedance_resolution=seedance_resolution,
            metadata={
                "focal_length": design_data.get("focal_length", ""),
                "aperture": design_data.get("aperture", ""),
                "camera_angle": design_data.get("camera_angle", ""),
                "lighting_scheme": design_data.get("lighting_scheme", ""),
                "light_sources": design_data.get("light_sources", []),
                "composition": design_data.get("composition", ""),
                "color_palette": design_data.get("color_palette", ""),
                "atmosphere": design_data.get("atmosphere", ""),
                "depth_of_field": design_data.get("depth_of_field", ""),
                "negative_prompt": design_data.get("negative_prompt", ""),
                "consistency_notes": design_data.get("consistency_notes", ""),
                "video_readiness": design_data.get("video_readiness", ""),
                "seedream_specific": design_data.get("seedream_specific", ""),
                "key_entities": design_data.get("key_entities", ""),
                "director_vision_backup": director_vision,
            },
        )

    def _inject_character_identity(self, image_prompt: str, character_refs: list[str]) -> str:
        """Inject character identity descriptions into image_prompt for consistency.

        If the image_prompt doesn't already contain the character's identity_block,
        prepend it. This ensures the AI sees the exact same description every time.
        """
        if not character_refs or not self._characters:
            return image_prompt

        # Build a mapping of char_id -> CharacterProfile
        char_map = {c.char_id: c for c in self._characters}

        identity_parts = []
        for char_id in character_refs:
            char = char_map.get(char_id)
            if not char:
                continue

            # Check if identity_block is already in image_prompt
            identity_lower = char.identity_block.lower()
            prompt_lower = image_prompt.lower()

            # Simple heuristic: check if key identity terms are present
            key_terms = [word for word in identity_lower.split()
                        if len(word) > 4 and word not in (
                            "with", "wearing", "and", "the", "his", "her", "has",
                            "have", "been", "were", "are", "from", "this", "that",
                        )]
            overlap = sum(1 for term in key_terms[:5] if term in prompt_lower)

            if overlap >= 2:
                # Identity already present, don't duplicate
                continue

            # Prepend identity block to ensure it's seen first
            identity_parts.append(char.identity_block)

        if not identity_parts:
            return image_prompt

        # Combine identity parts with original prompt
        injected = ". ".join(identity_parts) + ". " + image_prompt
        logger.info(
            f"[PromptDirector] Injected character identity into image_prompt: "
            f"{[c for c in character_refs if c in char_map]}"
        )
        return injected

    # ── Model Selection for Seedream/Seedance ───────────────────────────

    def _select_seedream_model(self, character_refs: list[str]) -> str:
        """Auto-select Seedream model based on shot content.

        Model selection strategy:
        - jimeng-4.6: BEST for face consistency (cost-effective)
        - jimeng-4.0: Multi-reference support, series generation
        - jimeng-4.1: Professional aesthetics and consistency
        - jimeng-5.0: Default, precise response
        """
        if not character_refs:
            # No characters, use default
            return "jimeng-5.0"

        # Check if any character has a specific model preference
        char_map = {c.char_id: c for c in self._characters}
        for char_id in character_refs:
            char = char_map.get(char_id)
            if char and char.seedream_model:
                return char.seedream_model

        # If shot has characters, use jimeng-4.6 for better face consistency
        if len(character_refs) > 1:
            # Multi-character scene, use jimeng-4.0 for multi-reference
            return "jimeng-4.0"
        else:
            # Single character, use jimeng-4.6 for best face consistency
            return "jimeng-4.6"

    def _select_seedance_model(self) -> str:
        """Auto-select Seedance model based on project requirements.

        Model selection strategy:
        - jimeng-video-seedance-2.0: Full features, 4-modal reference
        - jimeng-video-seedance-2.0-fast: 30-50% fewer credits, no queue
        """
        # Default to full features for quality
        return "jimeng-video-seedance-2.0"

    def _build_cinematic_format_fallback(self, design_data: dict, seg_id: int) -> str:
        """Construct a basic cinematic_format when LLM doesn't provide one."""
        parts = []
        
        # Location/Time (best effort from scene_type)
        scene_type = design_data.get("scene_type", "")
        if "outdoor" in scene_type.lower() or "landscape" in scene_type.lower():
            parts.append("EXT. LOCATION — TIME")
        elif "indoor" in scene_type.lower():
            parts.append("INT. LOCATION — TIME")
        else:
            parts.append("EXT./INT. LOCATION — TIME")
        
        # Shot size
        shot_type = design_data.get("shot_type", "medium shot")
        parts.append(shot_type.upper().replace("_", " "))
        
        # Lens
        focal_length = design_data.get("focal_length", "")
        if focal_length:
            parts.append(f"{focal_length}")
        
        # Angle
        camera_angle = design_data.get("camera_angle", "")
        if camera_angle:
            parts.append(camera_angle.upper().replace("-", " "))
        
        # Movement
        movement = design_data.get("movement", "")
        if movement and movement.lower() != "still":
            parts.append(movement.upper().replace("_", " "))
        
        # Lighting
        lighting = design_data.get("lighting_scheme", "")
        if lighting:
            parts.append(f"LIGHTING: {lighting.upper()}")
        
        # Depth
        dof = design_data.get("depth_of_field", "")
        if dof:
            parts.append(f"DEPTH: {dof.upper()}")
        
        # Color
        color = design_data.get("color_palette", "")
        if color:
            parts.append(f"COLOR: {color.upper()}")
        
        # Mood
        emotion = design_data.get("emotion", "")
        if emotion:
            parts.append(f"MOOD: {emotion.upper()}")
        
        return ". ".join(parts) + "."

    def _verify_three_layer_consistency(
        self,
        design_data: dict | Any,
        director_vision: str | None = None,
        cinematic_format: str | None = None,
        seg_id: int = 0,
    ) -> bool:
        """Verify that all three layers are consistent. Log warnings if not.

        Supports single-argument mode for external callers: if director_vision
        is None, design_data is treated as a dict-like object and fields are
        extracted automatically.

        Returns True if consistent, False if warnings were found.
        """
        # Single-argument mode: extract fields from design_data
        if director_vision is None:
            if isinstance(design_data, dict):
                data = design_data
            else:
                data = getattr(design_data, "model_dump", lambda: getattr(design_data, "__dict__", {}))()
            director_vision = data.get("director_vision", "")
            cinematic_format = data.get("cinematic_format", "")
            seg_id = data.get("segment_id", 0) or data.get("seg_id", 0)

        if not director_vision or not cinematic_format:
            return True  # Already handled by fallback logic

        warnings = []

        # Check 1: cinematic_format must contain EXT. or INT.
        if "EXT." not in cinematic_format and "INT." not in cinematic_format:
            warnings.append("cinematic_format missing EXT./INT. location marker")

        # Check 2: cinematic_format must contain a time of day
        time_markers = ["DAWN", "MORNING", "NOON", "AFTERNOON", "GOLDEN HOUR", "SUNSET", "DUSK", "NIGHT", "MIDNIGHT"]
        if not any(t in cinematic_format.upper() for t in time_markers):
            warnings.append("cinematic_format missing time-of-day marker")

        # Check 3: cinematic_format must contain a focal length or lens reference
        if "mm" not in cinematic_format.lower() and "LENS" not in cinematic_format.upper():
            warnings.append("cinematic_format missing focal length (e.g., 24mm, 35mm)")

        # Check 4: cinematic_format must contain a Kelvin or color temperature value
        if "K" not in cinematic_format and "KELVIN" not in cinematic_format.upper():
            # Check for common color temperature shorthand like 3500K, 6500K
            import re
            if not re.search(r'\d{3,4}K', cinematic_format):
                warnings.append("cinematic_format missing color temperature (Kelvin value)")

        # Check 5: cinematic_format must contain an aperture or depth reference
        depth_markers = ["f/", "DEPTH", "DOF", "SHALLOW", "DEEP", "MODERATE"]
        if not any(d in cinematic_format.upper() for d in depth_markers):
            warnings.append("cinematic_format missing depth of field / aperture reference")

        # Check 6: image_prompt should contain key terms from cinematic_format (not just director_vision)
        image_prompt = design_data.get("image_prompt", "") if isinstance(design_data, dict) else ""
        if image_prompt and cinematic_format:
            # Extract shot type from cinematic_format
            shot_types = ["WIDE SHOT", "CLOSE UP", "MEDIUM SHOT", "EXTREME CLOSE", "FULL SHOT", "ESTABLISHING"]
            found_shot_type = any(st in cinematic_format.upper() for st in shot_types)
            if found_shot_type:
                # Check if image_prompt also references the shot type or framing
                prompt_has_framing = any(
                    term in image_prompt.lower()
                    for term in ["wide shot", "close up", "medium shot", "extreme close", "full shot", "establishing"]
                )
                if not prompt_has_framing:
                    warnings.append("image_prompt may be missing framing info from cinematic_format")

        # Check 7: director_vision should NOT contain technical terms (it should be pure visual description)
        banned_terms = ["85mm", "f/1.4", "f/2.8", "f/5.6", "f/8", "f/11", "low-key", "high-key", "chiaroscuro", "rembrandt"]
        for term in banned_terms:
            if term.lower() in director_vision.lower():
                warnings.append(f"director_vision contains technical term '{term}' — should be in cinematic_format only")
                break  # One warning is enough

        # Log all warnings
        if warnings:
            logger.warning(
                f"[PromptDirector] Shot {seg_id} three-layer consistency issues: {warnings}"
            )
            # Record in metadata for downstream debugging
            if isinstance(design_data, dict):
                design_data["_three_layer_warnings"] = warnings
            return False
        return True

    def _estimate_duration(self, text: str, config: NarrascapeConfig) -> float:
        speed = config.tts.speed if config.tts else 0.9
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        english_words = max(0, len(text.split()) - chinese_chars)
        if chinese_chars > 0:
            duration = chinese_chars / (3.0 * speed)
        else:
            duration = english_words / (5.0 * speed)
        return max(duration, 3.0)

    def _parse_movement(self, value: str) -> MovementType | None:
        try:
            return MovementType(value.lower().strip().replace(" ", "_"))
        except ValueError:
            return MovementType.STILL

    def _derive_size(self, shot_type_str: str) -> str | None:
        from narrascape.motion.factory import derive_size
        try:
            st = ShotType(shot_type_str.lower().strip().replace(" ", "_"))
            return derive_size(st, manual_size=None)
        except Exception:
            return None

    def _format_storyboard_for_segment(self, frames: list[Any]) -> str:
        """Format storyboard frames as guidance text for the director.

        This text is injected into the segment text to guide shot design.
        """
        if not frames:
            return ""
        lines = ["Based on the storyboard for this segment, the visual plan is:"]
        for f in frames:
            lines.append(f"""
- Frame {f.frame_index + 1}: {f.shot_type or 'medium shot'}
  Composition: {f.description[:200]}
  Camera: {f.camera_angle or 'eye-level'} angle, {f.camera_movement or 'static'}
  Characters: {', '.join(f.character_positions) if f.character_positions else 'none'}
  Emotion: {f.emotion or 'neutral'}
  Duration: {f.duration_hint:.1f}s
  Notes: {f.notes[:100] if f.notes else 'none'}
""")
        lines.append("\nWhen designing this shot, follow the storyboard frame descriptions closely. Match the composition, camera angle, and character positions.")
        return "\n".join(lines)
