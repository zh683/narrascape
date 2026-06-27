from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult


class FilmTimelineStage(Stage):
    """Build a unified film timeline from script, design, media, and audio assets."""

    name = "film_timeline"
    depends_on = ["design", "generate_images", "generate_tts"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        config = context.config
        if not config.script_path.exists():
            return False, f"Script not found: {config.script_path}"
        design_path = self._first_existing(
            config.project_dir / "design_report.yaml",
            config.pipeline_dir / "design_report.yaml",
        )
        if not design_path.exists():
            return False, "design_report.yaml not found"
        if not (config.pipeline_dir / "timing.json").exists():
            return False, "timing.json not found. Run generate_tts first."
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output_path = config.project_dir / "film_timeline.yaml"
        timing = self._load_json(config.pipeline_dir / "timing.json")
        design = self._load_yaml(
            self._first_existing(config.project_dir / "design_report.yaml", config.pipeline_dir / "design_report.yaml")
        )
        image_map = self._load_yaml(config.project_dir / "image_map.yaml")
        footage_timeline = self._load_yaml(config.project_dir / "footage_timeline.yaml")
        asset_manifest = self._load_yaml(config.project_dir / "asset_manifest.yaml")
        video_state = self._load_json(config.pipeline_dir / "video_gen_state.json")
        take_selection = self._load_yaml(config.pipeline_dir / "take_selection.yaml")

        script_segments = list(context.script.segments)
        design_by_segment = {
            int(item.get("segment_id")): item
            for item in design.get("segments", [])
            if item.get("segment_id") is not None
        }
        image_map_by_segment = {
            int(item.get("id")): item
            for item in image_map.get("segments", [])
            if item.get("id") is not None
        }
        footage_by_segment = {
            int(item.get("target_segment_id")): item
            for item in footage_timeline.get("edits", [])
            if item.get("target_segment_id") is not None
        }
        generated_video_by_segment = self._generated_videos_by_segment(config, video_state, take_selection)
        assets_by_id = {
            item.get("id"): item
            for item in asset_manifest.get("assets", [])
            if item.get("id")
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
                        "character_ids": design_item.get("character_ids", []),
                        "location_id": design_item.get("location_id"),
                        **self._continuity_fields(design_item),
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
                        "character_ids": design_item.get("character_ids", []),
                        "location_id": design_item.get("location_id"),
                        **self._continuity_fields(design_item),
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
                                "start": round(cursor + duration * sum(
                                    self._ratio_for(timing_ratios, earlier, len(images))
                                    for earlier in range(image_index)
                                ), 3),
                                "duration": round(clip_duration, 3),
                                "role": "generated_visual",
                                "transition": "ken_burns",
                                "shot_type": design_item.get("shot_type"),
                                "movement": design_item.get("movement"),
                                "emotion": design_item.get("emotion"),
                                "intensity": design_item.get("intensity"),
                                "character_ids": design_item.get("character_ids", []),
                                "location_id": design_item.get("location_id"),
                                **self._continuity_fields(design_item),
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
        validate_artifact("film_timeline", timeline)
        output_path.write_text(yaml.safe_dump(timeline, sort_keys=False), encoding="utf-8")

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
        if not path or not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

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

    def _continuity_fields(self, design_item: dict[str, Any]) -> dict[str, Any]:
        metadata = design_item.get("metadata", {}) if isinstance(design_item.get("metadata"), dict) else {}
        return {
            "wardrobe": metadata.get("wardrobe"),
            "lighting_scheme": metadata.get("lighting_scheme"),
            "screen_axis": metadata.get("screen_axis"),
        }

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
