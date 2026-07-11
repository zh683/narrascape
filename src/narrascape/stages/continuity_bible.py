from __future__ import annotations

from pathlib import Path
from typing import Any

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import atomic_write_yaml


class ContinuityBibleStage(Stage):
    """Maintain character, location, wardrobe, lighting, and screen-axis continuity."""

    name = "continuity_bible"
    depends_on = ["screenplay_structure", "film_timeline"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        timeline = context.config.project_dir / "film_timeline.yaml"
        if not timeline.exists():
            return False, f"film_timeline.yaml not found: {timeline}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "continuity_bible.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        timeline = self._load_yaml(config.project_dir / "film_timeline.yaml")
        design = self._load_yaml(
            self._first_existing(
                config.project_dir / "design_report.yaml",
                config.pipeline_dir / "design_report.yaml",
            )
        )
        structure = self._load_yaml(config.pipeline_dir / "screenplay_structure.yaml")
        design_by_segment = {
            int(item.get("segment_id")): item
            for item in design.get("segments", [])
            if item.get("segment_id") is not None
        }

        characters: dict[str, dict[str, Any]] = {}
        locations: dict[str, dict[str, Any]] = {}
        risks: list[dict[str, Any]] = []
        previous_by_character: dict[str, dict[str, Any]] = {}

        for clip in self._story_clips(timeline):
            segment_id = int(clip["segment_id"])
            design_item = design_by_segment.get(segment_id, {})
            record = self._continuity_record(clip, design_item)
            location_id = record["location_id"]
            locations.setdefault(
                location_id,
                {
                    "id": location_id,
                    "appearances": [],
                    "lighting": [],
                    "screen_axis": [],
                },
            )
            locations[location_id]["appearances"].append(segment_id)
            self._append_unique(locations[location_id]["lighting"], record["lighting_scheme"])
            self._append_unique(locations[location_id]["screen_axis"], record["screen_axis"])

            for character_id in record["character_ids"]:
                character = characters.setdefault(
                    character_id,
                    {
                        "id": character_id,
                        "appearances": [],
                        "wardrobe": [],
                        "screen_axis": [],
                    },
                )
                character["appearances"].append(
                    {
                        "segment_id": segment_id,
                        "location_id": location_id,
                        "wardrobe": record["wardrobe"],
                        "lighting_scheme": record["lighting_scheme"],
                        "screen_axis": record["screen_axis"],
                    }
                )
                self._append_unique(character["wardrobe"], record["wardrobe"])
                self._append_unique(character["screen_axis"], record["screen_axis"])

                previous = previous_by_character.get(character_id)
                if previous:
                    risks.extend(self._compare_records(character_id, previous, record))
                previous_by_character[character_id] = record

        bible = {
            "schema_version": "continuity_bible.v1",
            "project": {
                "name": config.project.name,
                "title": config.project.title,
            },
            "source_structure": (
                (config.pipeline_dir / "screenplay_structure.yaml").as_posix() if structure else ""
            ),
            "characters": characters,
            "locations": locations,
            "continuity_risks": self._dedupe_risks(risks),
        }
        validate_artifact("continuity_bible", bible)
        atomic_write_yaml(output, bible)
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(bible['continuity_risks'])} continuity risk(s)",
            metadata={"risk_count": len(bible["continuity_risks"]), "bible": output.as_posix()},
        )

    def _story_clips(self, timeline: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            clip
            for clip in sorted(
                timeline.get("tracks", {}).get("visual", []),
                key=lambda item: float(item.get("start", 0.0)),
            )
            if clip.get("segment_id") is not None
        ]

    def _continuity_record(
        self, clip: dict[str, Any], design_item: dict[str, Any]
    ) -> dict[str, Any]:
        metadata = (
            design_item.get("metadata", {}) if isinstance(design_item.get("metadata"), dict) else {}
        )
        return {
            "segment_id": int(clip["segment_id"]),
            "character_ids": list(
                clip.get("character_ids") or design_item.get("character_ids") or []
            ),
            "location_id": clip.get("location_id")
            or design_item.get("location_id")
            or "unspecified_location",
            "wardrobe": clip.get("wardrobe") or metadata.get("wardrobe") or "unspecified_wardrobe",
            "lighting_scheme": clip.get("lighting_scheme")
            or metadata.get("lighting_scheme")
            or "unspecified_lighting",
            "screen_axis": clip.get("screen_axis")
            or metadata.get("screen_axis")
            or "unspecified_axis",
        }

    def _compare_records(
        self,
        character_id: str,
        previous: dict[str, Any],
        current: dict[str, Any],
    ) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        same_location = previous["location_id"] == current["location_id"]
        if same_location and previous["wardrobe"] != current["wardrobe"]:
            risks.append(
                {
                    "segment_id": current["segment_id"],
                    "character_id": character_id,
                    "risk_type": "wardrobe_jump",
                    "previous_segment_id": previous["segment_id"],
                    "detail": f"{previous['wardrobe']} -> {current['wardrobe']}",
                }
            )
        if same_location and previous["screen_axis"] != current["screen_axis"]:
            risks.append(
                {
                    "segment_id": current["segment_id"],
                    "character_id": character_id,
                    "risk_type": "screen_axis_flip",
                    "previous_segment_id": previous["segment_id"],
                    "detail": f"{previous['screen_axis']} -> {current['screen_axis']}",
                }
            )
        return risks

    def _append_unique(self, values: list[Any], value: Any) -> None:
        if value and value not in values:
            values.append(value)

    def _dedupe_risks(self, risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen = set()
        for risk in risks:
            key = (
                risk.get("segment_id"),
                risk.get("character_id"),
                risk.get("risk_type"),
                risk.get("previous_segment_id"),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(risk)
        return deduped

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return super()._load_yaml(path)

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]
