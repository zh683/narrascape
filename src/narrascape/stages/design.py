"""Design stage — AI director generates visual design from script.

This stage can be run standalone (before kenburns) to produce:
- image_prompts.yaml
- image_map.yaml
- BGM zone suggestions

Or it can be integrated into the pipeline as a pre-production step.
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from narrascape.agent import PromptDirector
from narrascape.agent.analyzer import ScriptAnalyzer
from narrascape.agent.models import BGMZoneSuggestion, DesignReport, SegmentAnalysis, ShotDesign
from narrascape.artifacts import write_artifact
from narrascape.config import (
    DEFAULT_VISUAL_STYLE,
    NarrascapeConfig,
    Script,
    ShotType,
    load_image_map,
    load_image_prompts,
    load_script,
)
from narrascape.motion.factory import SHOT_SIZE_MAP
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import atomic_write_yaml

logger = logging.getLogger("narrascape.stages.design")


class DesignStage(Stage):
    """AI director stage that designs shots from narration script.

    Outputs:
    - image_prompts.yaml  (in project dir)
    - image_map.yaml      (in project dir)
    - design_report.yaml  (in pipeline dir, for inspection)
    """

    name = "design"
    depends_on = ["pre_production"]
    outputs = ["image_prompts.yaml", "image_map.yaml", "design_report.yaml"]

    def __init__(
        self, llm_client: Any = None, style_template: str = "", auto_movement: bool = True
    ):
        self.llm_client = llm_client
        self.style_template = style_template
        self.auto_movement = auto_movement

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        script = load_script(config.script_path)

        logger.info(f"[design] Running AI director for project: {config.project.name}")

        # ══ Load pre-production references if available ══
        pre_production = self._load_pre_production(config)
        if pre_production:
            logger.info(
                f"[design] Loaded pre-production: {len(pre_production.get('characters', []))} characters, {len(pre_production.get('environments', []))} scenes, {pre_production.get('storyboard', {}).get('total_frames', 0)} storyboard frames"
            )

        storyboard_obj = None
        if pre_production:
            sb_data = pre_production.get("storyboard", {})
            if sb_data and sb_data.get("frames"):
                from narrascape.agent.models import Storyboard, StoryboardFrame

                storyboard_obj = Storyboard(
                    project_title=sb_data.get("project_title", config.project.title),
                    total_frames=sb_data.get("total_frames", 0),
                    total_segments=sb_data.get("total_segments", 0),
                    frames=[
                        StoryboardFrame(
                            frame_id=f.get("frame_id", ""),
                            segment_id=f.get("segment_id", 0),
                            frame_index=f.get("frame_index", 0),
                            description=f.get("description", ""),
                            shot_type=f.get("shot_type", ""),
                            camera_movement=f.get("camera_movement", ""),
                            camera_angle=f.get("camera_angle", ""),
                            character_positions=f.get("character_positions", []),
                            emotion=f.get("emotion", ""),
                            duration_hint=f.get("duration_hint", 3.0),
                            character_refs=f.get("character_refs", []),
                            scene_ref=f.get("scene_ref", ""),
                            reference_image_ids=f.get("reference_image_ids", []),
                            notes=f.get("notes", ""),
                        )
                        for f in sb_data.get("frames", [])
                    ],
                )
                logger.info(f"[design] Loaded storyboard with {storyboard_obj.total_frames} frames")

        # First, analyze the script with LLM
        analyzer = ScriptAnalyzer(llm_client=self.llm_client)
        analysis_list = analyzer.analyze(script)
        director_steps: dict[str, dict[str, Any]] = {
            "script_analysis": {
                "mode": "llm_script_analysis" if self.llm_client else "rule_based_analysis",
                "llm_status": getattr(
                    analyzer,
                    "last_llm_status",
                    "used" if self.llm_client else "not_configured",
                ),
            }
        }
        analyzer_errors = getattr(analyzer, "last_errors", [])
        if analyzer_errors:
            director_steps["script_analysis"]["errors"] = analyzer_errors

        if self.llm_client:
            logger.info("[design] Using PromptDirector")
            director = PromptDirector(llm_client=self.llm_client)
            try:
                shot_designs = director.design_sequence(
                    segments=script.segments,
                    analysis_list=analysis_list,
                    config=config,
                    storyboard=storyboard_obj,
                )
                director_steps["shot_design"] = {
                    "mode": "prompt_director",
                    "llm_status": "used",
                    "shot_count": len(shot_designs),
                }
            except Exception as exc:
                director_steps["shot_design"] = {
                    "mode": "prompt_director",
                    "llm_status": "fallback_after_error",
                    "errors": [str(exc)],
                }
                raise
        else:
            logger.info("[design] No LLM client configured; using local deterministic design")
            director = None
            shot_designs = self._design_locally(script, analysis_list, config)
            director_steps["shot_design"] = {
                "mode": "local_deterministic_design",
                "llm_status": "not_configured",
                "shot_count": len(shot_designs),
            }

        # CRITICAL: Inject style anchor reference into all shot prompts
        style_anchor_path = ""
        if pre_production:
            style_anchor_path = pre_production.get("style_anchor_path", "")

        if style_anchor_path:
            logger.info(f"[design] Injecting style anchor reference into {len(shot_designs)} shots")
            for shot in shot_designs:
                if "参考图" not in shot.image_prompt:
                    shot.image_prompt = f"参考图1的风格和色调，{shot.image_prompt}"
                if shot.character_refs:
                    shot.metadata["seedream_sample_strength"] = 0.65
                else:
                    shot.metadata["seedream_sample_strength"] = 0.35
                shot.metadata["style_anchor_path"] = style_anchor_path

        # BGM zones from analysis
        bgm_zones = self._derive_bgm_zones(analysis_list)

        from narrascape.agent.models import CharacterProfile, ReferenceImageChain, SceneStyle

        anchor = director.get_consistency_anchor() if director else {}

        # Build CharacterProfile objects from anchor
        pre_prod_char_refs = {}
        if pre_production:
            for char in pre_production.get("characters", []):
                pre_prod_char_refs[char.get("char_id", "")] = char.get("primary_reference_path", "")

        characters = []
        for c in anchor.get("characters", []):
            char_ref = pre_prod_char_refs.get(c["char_id"], c.get("reference_image_url", ""))
            characters.append(
                CharacterProfile(
                    char_id=c["char_id"],
                    name=c.get("name", ""),
                    identity_block=c.get("identity_block", ""),
                    face_description=c.get("face_description", ""),
                    hair_description=c.get("hair_description", ""),
                    body_description=c.get("body_description", ""),
                    default_outfit=c.get("default_outfit", ""),
                    signature_accessories=c.get("signature_accessories", []),
                    negative_anchors=c.get("negative_anchors", []),
                    reference_image_url=char_ref,
                )
            )

        # Build SceneStyle from anchor
        scene_style = None
        s = anchor.get("scene_style")
        if s:
            scene_style = SceneStyle(
                style_id=s.get("style_id", "default"),
                style_name=s.get("style_name", ""),
                base_color_temperature=s.get("base_color_temperature", ""),
                color_palette=s.get("color_palette", ""),
                lighting_signature=s.get("lighting_signature", ""),
                texture_palette=s.get("texture_palette", ""),
                atmosphere_signature=s.get("atmosphere_signature", ""),
                depth_signature=s.get("depth_signature", ""),
                lens_signature=s.get("lens_signature", ""),
                style_references=s.get("style_references", []),
                world_rules=s.get("world_rules", []),
                consistency_notes=s.get("consistency_notes", ""),
            )

        # Build ReferenceImageChain objects from anchor
        reference_image_chains = []
        for r in anchor.get("reference_image_chains", []):
            reference_image_chains.append(
                ReferenceImageChain(
                    chain_id=r["chain_id"],
                    chain_type=r.get("chain_type", "character"),
                    reference_urls=r.get("reference_urls", []),
                    reference_local_paths=r.get("reference_local_paths", []),
                    target_model=r.get("target_model", ""),
                    usage_mode=r.get("usage_mode", "reference"),
                    sample_strength=r.get("sample_strength", 0.5),
                    consistency_target=r.get("consistency_target", "face"),
                    description=r.get("description", ""),
                    generated_images=r.get("generated_images", []),
                )
            )

        # Get style_anchor_path from pre_production
        style_anchor_path = ""
        if pre_production:
            style_anchor_path = pre_production.get("style_anchor_path", "")
            if style_anchor_path:
                logger.info(f"[design] Using style anchor from pre-production: {style_anchor_path}")

        report = DesignReport(
            project_title=config.project.title,
            style_template=self.style_template or config.images.style,
            segments=shot_designs,
            analysis=analysis_list,
            bgm_zones=bgm_zones,
            characters=characters,
            scene_style=scene_style,
            reference_image_chains=reference_image_chains,
            style_anchor_path=style_anchor_path,
        )
        # Export files
        project_dir = config.project_dir
        prompts_path = project_dir / "image_prompts.yaml"
        map_path = project_dir / "image_map.yaml"
        report_path = config.pipeline_dir / "design_report.yaml"

        wrote_prompts = True
        wrote_map = True

        # Write image_prompts.yaml (rich format with metadata), unless the
        # project intentionally keeps curated prompt files as its execution source.
        prompts_data = report.to_image_prompts()
        if config.pipeline.design_overwrite or not prompts_path.exists():
            atomic_write_yaml(prompts_path, prompts_data)
            logger.info(f"[design] Wrote {prompts_path}")
        else:
            load_image_prompts(prompts_path)
            wrote_prompts = False
            logger.info(f"[design] Preserved curated {prompts_path}")

        # Write image_map.yaml
        map_data = report.to_image_map()
        if config.pipeline.design_overwrite or not map_path.exists():
            atomic_write_yaml(map_path, map_data)
            logger.info(f"[design] Wrote {map_path}")
        else:
            load_image_map(map_path)
            wrote_map = False
            logger.info(f"[design] Preserved curated {map_path}")

        # Write design report (full director metadata for human review)
        report_dict = (
            report.to_design_report()
            if hasattr(report, "to_design_report")
            else report.model_dump()
        )
        director_process = self._director_process(
            director_steps,
            "prompt_director" if self.llm_client else "local_deterministic_design",
        )
        report_dict["director_process"] = director_process
        write_artifact("design_report", report_path, report_dict)
        logger.info(f"[design] Wrote {report_path}")

        # Validate design quality
        issues = self._validate_design(report, config)
        if issues:
            logger.warning(f"[design] {len(issues)} quality issues detected:")
            for issue in issues:
                logger.warning(f"  - {issue}")
        else:
            logger.info("[design] All quality checks passed")

        # Print summary
        self._print_summary(report, llm_mode=bool(self.llm_client), issues=issues)

        return StageResult(
            stage_name=self.name,
            success=True,
            outputs={
                "image_prompts": str(prompts_path),
                "image_map": str(map_path),
                "design_report": str(report_path),
            },
            metadata={
                "segment_count": len(report.segments),
                "bgm_zones": len(report.bgm_zones),
                "style_template": report.style_template,
                "director_mode": "prompt_director",
                "design_overwrite": config.pipeline.design_overwrite,
                "wrote_image_prompts": wrote_prompts,
                "wrote_image_map": wrote_map,
                "director_process": director_process,
            },
        )

    def _design_locally(
        self, script: Script, analysis_list: list[SegmentAnalysis], config: NarrascapeConfig
    ) -> list[ShotDesign]:
        """Create deterministic shot designs for offline/local pipeline runs."""
        designs: list[ShotDesign] = []
        for index, seg in enumerate(script.segments):
            analysis = analysis_list[index] if index < len(analysis_list) else None
            shot_type = seg.shot_type or self._shot_type_from_analysis(
                analysis, index, len(script.segments)
            )
            movement = None
            if self.auto_movement:
                from narrascape.motion.factory import derive_movement

                movement = derive_movement(shot_type, 3.0, None)
            size = SHOT_SIZE_MAP.get(shot_type)
            text = seg.text.replace("\n", " ").strip()
            style = self.style_template or config.images.style or DEFAULT_VISUAL_STYLE
            prompt = (
                f"{style}, {shot_type.value} shot, cinematic composition, "
                f"visualizing: {text[:220]}, detailed lighting, coherent painterly oil-painted frame, no text"
            )
            designs.append(
                ShotDesign(
                    segment_id=seg.id,
                    shot_type=shot_type,
                    movement=movement,
                    size=size,
                    director_vision=f"Visualize the narration as a clear {shot_type.value} oil-painted cinematic frame.",
                    cinematic_format=f"SHOT {seg.id}: {shot_type.value.upper()} / eye-level / natural light",
                    image_prompt=prompt,
                    reasoning="Local deterministic design for offline pipeline verification.",
                    style_prefix=style,
                    emotion=getattr(analysis, "emotion", "calm"),
                    intensity=getattr(analysis, "intensity", 0.3),
                    metadata={
                        "negative_prompt": "text, watermark, logo, distorted anatomy, low quality",
                        "focal_length": "35mm",
                        "camera_angle": "eye-level",
                        "lighting_scheme": "soft natural key light",
                        "composition": "balanced painterly cinematic composition",
                        "color_palette": "natural contrast",
                    },
                )
            )
        return designs

    def _director_process(
        self,
        steps: dict[str, dict[str, Any]],
        mode: str,
    ) -> dict[str, Any]:
        statuses = [
            str(step.get("llm_status", "")) for step in steps.values() if step.get("llm_status")
        ]
        if any(status == "fallback_after_error" for status in statuses):
            llm_status = "fallback_after_error"
        elif any(status == "not_configured" for status in statuses) or not statuses:
            llm_status = "not_configured"
        else:
            llm_status = "used"

        errors: list[str] = []
        for step in steps.values():
            step_errors = step.get("errors") or []
            if isinstance(step_errors, list):
                errors.extend(str(item) for item in step_errors)
            elif step_errors:
                errors.append(str(step_errors))

        process: dict[str, Any] = {
            "mode": mode,
            "llm_status": llm_status,
            "steps": steps,
        }
        if errors:
            process["errors"] = errors
        return process

    def _shot_type_from_analysis(self, analysis: Any, index: int, total: int) -> ShotType:
        if index == 0:
            return ShotType.ESTABLISHING
        if index == total - 1:
            return ShotType.DETAIL
        scene_type = getattr(analysis, "scene_type", "") if analysis else ""
        if scene_type in ("landscape", "outdoor"):
            return ShotType.WIDE_ENV
        if scene_type == "portrait":
            return ShotType.CLOSE_UP
        return ShotType.MEDIUM

    def _derive_bgm_zones(self, analysis_list: list[SegmentAnalysis]) -> list[BGMZoneSuggestion]:
        """Derive BGM zones from analysis (simplified when using PromptDirector)."""
        if not analysis_list:
            return []

        zones: list[BGMZoneSuggestion] = []
        current_zone = [analysis_list[0]]

        for i in range(1, len(analysis_list)):
            prev = analysis_list[i - 1]
            curr = analysis_list[i]
            emotion_change = prev.emotion != curr.emotion
            intensity_shift = abs(prev.intensity - curr.intensity) > 0.4
            if emotion_change or intensity_shift:
                if current_zone:
                    emotions = [a.emotion for a in current_zone]
                    dominant = max(set(emotions), key=emotions.count)
                    emotion_bgm = {
                        "calm": "Solo piano, gentle flowing, 60 BPM, major key",
                        "tense": "String tremolo, low drones, building tension, 80 BPM, minor key",
                        "sad": "Solo cello, mournful sparse, 48 BPM, minor key",
                        "hopeful": "Warm strings, rising melody, 72 BPM, major key",
                        "dramatic": "Orchestral brass percussion, epic, 90 BPM, minor key",
                        "nostalgic": "Acoustic guitar, soft melody, 55 BPM, major key",
                        "awe": "Choir strings, vast transcendent, 60 BPM, major key",
                        "mysterious": "Sparse piano, ambient pads, 50 BPM, atonal",
                        "urgent": "Fast percussion, driving rhythm, 120 BPM, minor key",
                    }
                    prompt = emotion_bgm.get(dominant, "Ambient strings, neutral, 60 BPM")
                    zones.append(
                        BGMZoneSuggestion(
                            covers=[a.segment_id for a in current_zone],
                            label=dominant.capitalize(),
                            prompt=prompt,
                            emotion=dominant,
                        )
                    )
                current_zone = [curr]
            else:
                current_zone.append(curr)

        if current_zone:
            emotions = [a.emotion for a in current_zone]
            dominant = max(set(emotions), key=emotions.count)
            emotion_bgm = {
                "calm": "Solo piano, gentle flowing, 60 BPM, major key",
                "tense": "String tremolo, low drones, building tension, 80 BPM, minor key",
                "sad": "Solo cello, mournful sparse, 48 BPM, minor key",
                "hopeful": "Warm strings, rising melody, 72 BPM, major key",
                "dramatic": "Orchestral brass percussion, epic, 90 BPM, minor key",
                "nostalgic": "Acoustic guitar, soft melody, 55 BPM, major key",
                "awe": "Choir strings, vast transcendent, 60 BPM, major key",
                "mysterious": "Sparse piano, ambient pads, 50 BPM, atonal",
                "urgent": "Fast percussion, driving rhythm, 120 BPM, minor key",
            }
            prompt = emotion_bgm.get(dominant, "Ambient strings, neutral, 60 BPM")
            zones.append(
                BGMZoneSuggestion(
                    covers=[a.segment_id for a in current_zone],
                    label=dominant.capitalize(),
                    prompt=prompt,
                    emotion=dominant,
                )
            )

        return zones

    def _validate_design(self, report: DesignReport, config: NarrascapeConfig) -> list[str]:
        """Run quality checks on the design report. Returns list of issue strings."""
        issues: list[str] = []
        segments = report.segments

        # 1. Check prompt word count (80-150 recommended)
        for shot in segments:
            word_count = len(shot.image_prompt.split())
            if word_count < 50:
                issues.append(
                    f"Seg {shot.segment_id}: prompt too short ({word_count} words, recommend 80-150)"
                )
            elif word_count > 200:
                issues.append(
                    f"Seg {shot.segment_id}: prompt very long ({word_count} words, may cause quality issues)"
                )

        # 2. Check oil-painting style lock.
        style_lower = (report.style_template or "").lower()
        if "realism" in style_lower or "painting" in style_lower or "oil" in style_lower:
            for shot in segments:
                prompt_lower = shot.image_prompt.lower()
                oil_terms = ("oil painting", "painterly", "brush", "canvas", "pigment")
                if not any(term in prompt_lower for term in oil_terms):
                    issues.append(f"Seg {shot.segment_id}: missing oil-painting style anchor")

        # 3. Check resolution matches shot_type
        for shot in segments:
            expected_size = SHOT_SIZE_MAP.get(shot.shot_type)
            if shot.size and expected_size and shot.size != expected_size:
                issues.append(
                    f"Seg {shot.segment_id}: size mismatch {shot.size} vs expected {expected_size} for {shot.shot_type.value}"
                )

        # 4. Check for adjacent shot_type repetition (no more than 3 in a row)
        if len(segments) >= 3:
            current_type = segments[0].shot_type
            streak = 1
            for shot in segments[1:]:
                if shot.shot_type == current_type:
                    streak += 1
                    if streak > 3:
                        issues.append(
                            f"Seg {shot.segment_id}: {current_type.value} repeats {streak} times — consider varying shot types for visual rhythm"
                        )
                else:
                    current_type = shot.shot_type
                    streak = 1

        # 5. Check negative_prompt exists (LLM mode)
        if self.llm_client:
            for shot in segments:
                if not shot.metadata or not shot.metadata.get("negative_prompt"):
                    issues.append(
                        f"Seg {shot.segment_id}: missing negative_prompt (important for AI artifact prevention)"
                    )

        # 6. Check first and last shot guidelines
        if segments:
            first = segments[0]
            if first.shot_type not in (
                ShotType.WIDE_ENV,
                ShotType.WIDE_ANGLE,
                ShotType.ESTABLISHING,
                ShotType.AERIAL,
                ShotType.MEDIUM,
            ):
                issues.append(
                    f"Seg 1: first shot is {first.shot_type.value} — consider opening with wide/establishing shot"
                )

            last = segments[-1]
            if last.shot_type not in (
                ShotType.WIDE_ENV,
                ShotType.WIDE_ANGLE,
                ShotType.ESTABLISHING,
                ShotType.DETAIL,
                ShotType.BLACK,
            ):
                issues.append(
                    f"Seg {last.segment_id}: last shot is {last.shot_type.value} — consider ending with wide/env or detail for closure"
                )

        return issues

    def _print_summary(
        self, report: DesignReport, llm_mode: bool = False, issues: list[str] | None = None
    ) -> None:
        """Print a human-readable summary of the design."""
        import sys

        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console(emoji=False if sys.platform == "win32" else True)
        console.print()

        mode_text = "[bold cyan]PromptDirector (LLM Autonomous)[/]"
        if not llm_mode:
            mode_text = "[bold yellow]Template-Based Design (No LLM)[/]"
        console.print(
            Panel(f"{mode_text}\nDesign Report: {report.project_title}", border_style="green")
        )
        console.print(f"Style: {report.style_template or 'default'}")
        console.print()

        table = Table(title="Shot Designs")
        table.add_column("Seg", justify="right", style="cyan")
        table.add_column("Shot Type", style="magenta")
        table.add_column("Movement", style="yellow")
        table.add_column("Lens", style="blue")
        table.add_column("Lighting", style="green")
        table.add_column("Reasoning", style="white")

        for shot in report.segments:
            mv = shot.movement.value if shot.movement else "still"
            lens = shot.metadata.get("focal_length", "") if shot.metadata else ""
            lighting = shot.metadata.get("lighting_scheme", "") if shot.metadata else ""
            table.add_row(
                str(shot.segment_id),
                shot.shot_type.value,
                mv,
                lens[:20] + "..." if len(lens) > 20 else lens,
                lighting[:20] + "..." if len(lighting) > 20 else lighting,
                shot.reasoning[:40] + "..." if len(shot.reasoning) > 40 else shot.reasoning,
            )

        console.print(table)

        # Show quality issues
        if issues:
            console.print()
            console.print(f"[bold yellow]WARNING: {len(issues)} Quality Issues:[/]")
            for issue in issues:
                console.print(f"  [yellow]-[/] {issue}")
        else:
            console.print()
            console.print("[bold green]All quality checks passed[/]")

        # Show metadata-rich fields if in LLM mode
        if llm_mode and report.segments:
            console.print()
            console.print("[bold dim]Example full prompt (Seg 1):[/]")
            first = report.segments[0]
            console.print(f"[dim]Prompt:[/] {first.image_prompt[:200]}...")
            if first.metadata and first.metadata.get("negative_prompt"):
                console.print(f"[dim]Negative:[/] {first.metadata['negative_prompt'][:150]}...")

        if report.bgm_zones:
            console.print()
            console.print("[bold]Suggested BGM Zones:[/]")
            for zone in report.bgm_zones:
                console.print(f"  - Segments {zone.covers}: {zone.label} - {zone.prompt}")

        console.print()

    def _load_pre_production(self, config: NarrascapeConfig) -> dict[str, Any] | None:
        """Load pre_production.yaml if available.

        Returns the pre-production report dict, or None if not found.
        """
        pre_prod_path = config.pipeline_dir / "pre_production.yaml"
        if not pre_prod_path.exists():
            return None
        try:
            with open(pre_prod_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else None
        except Exception as e:
            logger.warning(f"[design] Failed to load pre_production.yaml: {e}")
            return None
