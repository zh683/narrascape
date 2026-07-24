from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from narrascape.artifacts import write_artifact
from narrascape.catalog import design_report_candidates
from narrascape.contracts import DirectorContract, DirectorShot, FilmTimeline
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import load_json_mapping

logger = logging.getLogger("narrascape.stages.film_timeline")


class FilmTimelineStage(Stage):
    """Build a unified film timeline from script, design, media, and audio assets."""

    name = "film_timeline"
    depends_on = ["design", "generate_images", "generate_tts"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        config = context.config
        if not config.script_path.exists():
            return False, f"Script not found: {config.script_path}"
        design_path = self._first_existing(*design_report_candidates(config))
        if not design_path.exists():
            return False, "design_report.yaml not found"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output_path = config.project_dir / "film_timeline.yaml"
        timing = self._load_json(config.pipeline_dir / "timing.json")
        design = self._load_yaml(self._first_existing(*design_report_candidates(config)))
        image_map = self._load_yaml(config.project_dir / "image_map.yaml")
        footage_timeline = self._load_yaml(config.project_dir / "footage_timeline.yaml")
        asset_manifest = self._load_yaml(config.project_dir / "asset_manifest.yaml")
        director_contract = self._load_yaml(config.pipeline_dir / "director_contract.yaml")
        video_state = self._load_json(config.pipeline_dir / "video_gen_state.json")
        take_selection = self._load_yaml(config.pipeline_dir / "take_selection.yaml")
        self._warn_if_multi_take_without_selection(config)

        script_segments = list(context.script.segments)
        design_by_segment = self._items_by_int_key(design.get("segments", []), "segment_id")
        contract_model = self._parse_contract(director_contract)
        contract_by_segment = (
            {shot.segment_id: shot for shot in contract_model.shots}
            if contract_model is not None
            else self._items_by_int_key(director_contract.get("shots", []), "segment_id")
        )
        image_map_by_segment = self._items_by_int_key(image_map.get("segments", []), "id")
        footage_by_segment = self._items_by_int_key(
            footage_timeline.get("edits", []), "target_segment_id"
        )
        generated_video_by_segment = self._generated_videos_by_segment(
            config, video_state, take_selection
        )
        assets_by_id = {
            item.get("id"): item for item in asset_manifest.get("assets", []) if item.get("id")
        }

        cursor = 0.0
        visual: list[dict[str, Any]] = []
        narration: list[dict[str, Any]] = []
        generated_video_segments: list[int] = []
        source_media_segments: list[int] = []
        generated_image_segments: list[int] = []
        missing_visual_segments: list[int] = []

        for index, segment in enumerate(script_segments):
            segment_id = int(segment.id)
            duration = float(timing.get(str(segment_id), 0.0)) or max(1.0, len(segment.text) / 18.0)
            design_item = design_by_segment.get(segment_id, {})
            contract_item = contract_by_segment.get(segment_id, {})
            semantic_fields = self._semantic_fields(design_item, contract_item)
            footage_item = footage_by_segment.get(segment_id)
            generated_video = generated_video_by_segment.get(segment_id)
            if generated_video:
                generated_video_segments.append(segment_id)
                visual.append(
                    {
                        "id": f"v_{segment_id:03d}",
                        "segment_id": segment_id,
                        "source": "generated_video",
                        "asset_ref": generated_video.stem,
                        "path": generated_video.relative_to(config.project_dir).as_posix(),
                        "start": round(cursor, 3),
                        "duration": round(duration, 3),
                        "role": "ai_generated_video",
                        "transition": "cut",
                        "shot_type": design_item.get("shot_type"),
                        "movement": design_item.get("movement"),
                        "emotion": design_item.get("emotion"),
                        "intensity": design_item.get("intensity"),
                        **semantic_fields,
                    }
                )
            elif footage_item:
                source_media_segments.append(segment_id)
                asset_ref = footage_item.get("asset_id")
                asset = assets_by_id.get(asset_ref, {})
                visual.append(
                    {
                        "id": f"v_{segment_id:03d}",
                        "segment_id": segment_id,
                        "source": "source_media",
                        "asset_ref": asset_ref,
                        "path": footage_item.get("source_path") or asset.get("path"),
                        "start": round(cursor, 3),
                        "duration": float(footage_item.get("duration") or duration),
                        "source_in": float(footage_item.get("source_in") or 0.0),
                        "source_out": float(footage_item.get("source_out") or duration),
                        "role": footage_item.get("role", "documentary_footage"),
                        "transition": footage_item.get("transition", "cut"),
                        "shot_type": design_item.get("shot_type"),
                        "movement": design_item.get("movement"),
                        "emotion": design_item.get("emotion"),
                        "intensity": design_item.get("intensity"),
                        **semantic_fields,
                    }
                )
            else:
                image_entry = image_map_by_segment.get(segment_id, {})
                images = list(image_entry.get("images", []))
                if images:
                    generated_image_segments.append(segment_id)
                    timing_ratios = image_entry.get("timing") or []
                    for image_index, image_id in enumerate(images):
                        ratio = self._ratio_for(timing_ratios, image_index, len(images))
                        clip_duration = duration * ratio
                        visual.append(
                            {
                                "id": f"v_{segment_id:03d}_{image_index + 1:02d}",
                                "segment_id": segment_id,
                                "source": "generated_image",
                                "asset_ref": image_id,
                                "path": f"assets/images/{image_id}.png",
                                "start": round(
                                    cursor
                                    + duration
                                    * sum(
                                        self._ratio_for(timing_ratios, earlier, len(images))
                                        for earlier in range(image_index)
                                    ),
                                    3,
                                ),
                                "duration": round(clip_duration, 3),
                                "role": "generated_visual",
                                "transition": "ken_burns",
                                "shot_type": design_item.get("shot_type"),
                                "movement": design_item.get("movement"),
                                "emotion": design_item.get("emotion"),
                                "intensity": design_item.get("intensity"),
                                **semantic_fields,
                            }
                        )
                else:
                    missing_visual_segments.append(segment_id)

            narration.append(
                {
                    "id": f"n_{segment_id:03d}",
                    "segment_id": segment_id,
                    "asset_ref": f"tts_{segment_id:02d}",
                    "path": f"assets/tts/seg_{segment_id:02d}.mp3",
                    "start": round(cursor, 3),
                    "duration": round(duration, 3),
                    "text": segment.text,
                }
            )
            cursor += duration
            if index < len(script_segments) - 1:
                cursor += config.visual.gap_map.get(segment_id, config.visual.segment_gap)

        if config.ending.enabled:
            visual.append(
                {
                    "id": "v_ending",
                    "segment_id": None,
                    "source": "ending_card",
                    "asset_ref": "ending",
                    "path": "",
                    "start": round(cursor, 3),
                    "duration": round(float(config.ending.duration), 3),
                    "role": "ending_card",
                    "transition": "fade",
                }
            )
            cursor += float(config.ending.duration)

        timeline = {
            "schema_version": "film_timeline.v1",
            "project": {
                "name": config.project.name,
                "title": config.project.title,
            },
            "duration": round(cursor, 3),
            "strategy": {
                "visual_priority": ["generated_video", "source_media", "generated_image"],
                "fallback": "generated_image",
            },
            "coverage": {
                "generated_video_segments": generated_video_segments,
                "source_media_segments": source_media_segments,
                "generated_image_segments": generated_image_segments,
                "missing_visual_segments": missing_visual_segments,
            },
            "tracks": {
                "visual": visual,
                "narration": narration,
                "music": self._music_track(config),
                "subtitles": self._subtitle_track(config),
            },
        }
        # 字段级 schema 门：漂移在写点即 fail-fast（pydantic ValidationError）
        FilmTimeline.model_validate(timeline)
        write_artifact("film_timeline", output_path, timeline)

        return StageResult(
            self.name,
            not missing_visual_segments,
            outputs=[output_path],
            message=(
                "film timeline built"
                if not missing_visual_segments
                else f"missing visuals for segments: {missing_visual_segments}"
            ),
            metadata={"coverage": timeline["coverage"], "timeline": output_path.as_posix()},
        )

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return super()._load_yaml(path)

    def _load_json(self, path: Path) -> dict[str, Any]:
        return load_json_mapping(path, default={})

    def _items_by_int_key(self, items: Any, key: str) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        if not isinstance(items, list):
            return result
        for item in items:
            if not isinstance(item, dict) or item.get(key) is None:
                continue
            try:
                result[int(item[key])] = item
            except (TypeError, ValueError):
                continue
        return result

    def _generated_videos_by_segment(
        self,
        config: Any,
        state: dict[str, Any],
        take_selection: dict[str, Any] | None = None,
    ) -> dict[int, Path]:
        done = set(state.get("done", []))
        videos: dict[int, Path] = {}
        videos_dir = config.project_dir / "assets" / "videos"
        if not videos_dir.exists():
            return videos
        for item in (take_selection or {}).get("selections", []) or []:
            try:
                segment_id = int(item.get("segment_id"))
            except (TypeError, ValueError):
                continue
            selected_path = item.get("selected_path")
            if not selected_path:
                continue
            path = config.project_dir / selected_path
            if path.exists():
                videos[segment_id] = path
        for path in sorted(videos_dir.glob("vid_*.mp4")):
            if done and path.stem not in done:
                continue
            try:
                segment_id = int(path.stem.split("_", 1)[1])
            except (IndexError, ValueError):
                continue
            if segment_id in videos:
                continue
            videos[segment_id] = path
        return videos

    def _warn_if_multi_take_without_selection(self, config: Any) -> None:
        """Advisory warning: multi-take videos exist but take_select never ran.

        film_timeline deliberately does NOT declare a dependency on
        take_select / generate_video: ``depends_on`` would pull those stages
        into execution (including paid video generation) when someone runs
        ``--stage film_timeline`` alone. Reads tolerate the missing artifact,
        but silently ignoring take files can pick the wrong clip, so we
        surface the situation instead of failing.
        """
        if (config.pipeline_dir / "take_selection.yaml").exists():
            return
        videos_dir = config.project_dir / "assets" / "videos"
        if not videos_dir.exists():
            return
        takes = sorted(videos_dir.glob("vid_*_take_*.mp4"))
        if not takes:
            return
        logger.warning(
            f"found {len(takes)} multi-take video(s) in {videos_dir} but "
            f"take_selection.yaml is missing; take files (e.g. {takes[0].name}) "
            f"are ignored by the fallback glob, which only uses base vid_NN.mp4 "
            f"files — run the take_select stage first to choose takes explicitly"
        )

    def _parse_contract(self, director_contract: dict[str, Any]) -> DirectorContract | None:
        """Typed parse of director_contract.yaml; None means "fall back to raw dicts".

        Legacy artifacts that predate the typed schema (or drifted from it)
        keep working through the legacy `.get()` path — reads are advisory,
        only writes are fail-fast.
        """
        if not director_contract:
            return None
        try:
            return DirectorContract.model_validate(director_contract)
        except ValidationError as exc:
            logger.warning(
                f"director_contract.yaml failed typed validation; "
                f"falling back to legacy raw access: {exc}"
            )
            return None

    def _continuity_fields(self, design_item: dict[str, Any]) -> dict[str, Any]:
        metadata = (
            design_item.get("metadata", {}) if isinstance(design_item.get("metadata"), dict) else {}
        )
        return {
            "wardrobe": metadata.get("wardrobe"),
            "lighting_scheme": metadata.get("lighting_scheme"),
            "screen_axis": metadata.get("screen_axis"),
        }

    def _semantic_fields(
        self,
        design_item: dict[str, Any],
        contract_item: Any,
    ) -> dict[str, Any]:
        """Merge design + director-contract semantics for one timeline clip.

        ``contract_item`` is a typed ``DirectorShot`` when the contract
        validated; otherwise the legacy raw-dict path applies (byte-identical
        to the pre-schema behavior).
        """
        if isinstance(contract_item, DirectorShot):
            continuity = contract_item.continuity_constraints
            binding = contract_item.storyboard_binding
            film_language = contract_item.film_language
            c_characters: Any = continuity.characters
            c_location: Any = continuity.location
            c_wardrobe: Any = continuity.wardrobe
            c_lighting: Any = continuity.lighting
            b_scene_ref: Any = binding.scene_ref
            b_wardrobe_lock: Any = binding.wardrobe_lock
            b_comp_reqs: list[Any] = list(binding.composition_requirements)
            b_frame_ids: list[Any] = list(binding.storyboard_frame_ids)
            b_positions: list[Any] = list(binding.character_positions)
            fl_lighting: Any = film_language.lighting
            fl_composition: Any = film_language.composition
        else:
            raw = contract_item if isinstance(contract_item, dict) else {}
            continuity_raw = (
                raw.get("continuity_constraints", {})
                if isinstance(raw.get("continuity_constraints"), dict)
                else {}
            )
            binding_raw = (
                raw.get("storyboard_binding", {})
                if isinstance(raw.get("storyboard_binding"), dict)
                else {}
            )
            film_language_raw = (
                raw.get("film_language", {}) if isinstance(raw.get("film_language"), dict) else {}
            )
            c_characters = continuity_raw.get("characters")
            c_location = continuity_raw.get("location")
            c_wardrobe = continuity_raw.get("wardrobe")
            c_lighting = continuity_raw.get("lighting")
            b_scene_ref = binding_raw.get("scene_ref")
            b_wardrobe_lock = binding_raw.get("wardrobe_lock")
            b_comp_reqs = list(binding_raw.get("composition_requirements") or [])
            b_frame_ids = list(binding_raw.get("storyboard_frame_ids") or [])
            b_positions = list(binding_raw.get("character_positions") or [])
            fl_lighting = film_language_raw.get("lighting")
            fl_composition = film_language_raw.get("composition")

        fields = self._continuity_fields(design_item)
        character_ids = design_item.get("character_ids") or c_characters or []
        return {
            "character_ids": character_ids,
            "location_id": self._first_value(
                design_item.get("location_id"),
                c_location,
                b_scene_ref,
            ),
            "wardrobe": self._first_value(
                fields.get("wardrobe"),
                c_wardrobe,
                b_wardrobe_lock,
            ),
            "lighting_scheme": self._first_value(
                fields.get("lighting_scheme"),
                c_lighting,
                fl_lighting,
            ),
            "screen_axis": fields.get("screen_axis"),
            "storyboard_frame_ids": b_frame_ids,
            "character_positions": b_positions,
            "composition": self._first_value(
                design_item.get("composition"),
                fl_composition,
                b_comp_reqs[0] if b_comp_reqs else None,
            ),
        }

    def _first_value(self, *values: Any) -> Any:
        for value in values:
            if value not in (None, "", []):
                return value
        return None

    def _ratio_for(self, ratios: list[float], index: int, count: int) -> float:
        if ratios and len(ratios) == count:
            return float(ratios[index])
        return 1.0 / max(count, 1)

    def _music_track(self, config: Any) -> list[dict[str, Any]]:
        music = []
        for zone in config.bgm_map.zones:
            path = config.music_dir / f"{zone.id}.mp3"
            music.append(
                {
                    "id": f"music_{zone.id}",
                    "asset_ref": zone.id,
                    "path": path.relative_to(config.project_dir).as_posix(),
                    "covers": list(zone.covers),
                    "label": zone.label,
                }
            )
        return music

    def _subtitle_track(self, config: Any) -> list[dict[str, Any]]:
        srt_path = config.pipeline_dir / "subtitles.srt"
        if not srt_path.exists():
            return []
        return [
            {
                "id": "subtitles_srt",
                "path": srt_path.relative_to(config.project_dir).as_posix(),
                "format": "srt",
            }
        ]

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]
