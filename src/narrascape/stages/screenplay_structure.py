from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult


class ScriptSceneDirectorStage(Stage):
    """Build the act -> scene -> sequence -> shot hierarchy for a film project."""

    name = "screenplay_structure"
    depends_on = ["design"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        if not context.config.script_path.exists():
            return False, f"Script not found: {context.config.script_path}"
        design_path = self._first_existing(
            context.config.project_dir / "design_report.yaml",
            context.config.pipeline_dir / "design_report.yaml",
        )
        if not design_path.exists():
            return False, "design_report.yaml not found"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "screenplay_structure.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)

        design = self._load_yaml(
            self._first_existing(config.project_dir / "design_report.yaml", config.pipeline_dir / "design_report.yaml")
        )
        timing = self._load_json(config.pipeline_dir / "timing.json")
        design_by_segment = {
            int(item.get("segment_id")): item
            for item in design.get("segments", [])
            if item.get("segment_id") is not None
        }

        segments = list(context.script.segments)
        acts: list[dict[str, Any]] = []
        shot_index: dict[str, dict[str, str]] = {}
        act_buckets: list[list[Any]] = [[], [], []]
        for index, segment in enumerate(segments):
            act_buckets[self._act_index(index, len(segments))].append(segment)

        for act_idx, act_segments in enumerate(act_buckets, start=1):
            act_id = f"act_{act_idx:02d}"
            scenes = self._build_scenes(act_id, act_segments, design_by_segment, timing, shot_index)
            acts.append(
                {
                    "id": act_id,
                    "label": self._act_label(act_idx),
                    "dramatic_function": self._act_function(act_idx),
                    "segment_ids": [int(segment.id) for segment in act_segments],
                    "scenes": scenes,
                }
            )

        structure = {
            "schema_version": "screenplay_structure.v1",
            "project": {
                "name": config.project.name,
                "title": config.project.title,
            },
            "grain_order": ["act", "scene", "sequence", "shot"],
            "method": "deterministic_scene_director",
            "acts": acts,
            "shot_index": shot_index,
        }
        validate_artifact("screenplay_structure", structure)
        output.write_text(yaml.safe_dump(structure, sort_keys=False), encoding="utf-8")
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(segments)} shot(s) organized into screenplay hierarchy",
            metadata={"shot_count": len(segments), "structure": output.as_posix()},
        )

    def _build_scenes(
        self,
        act_id: str,
        segments: list[Any],
        design_by_segment: dict[int, dict[str, Any]],
        timing: dict[str, Any],
        shot_index: dict[str, dict[str, str]],
    ) -> list[dict[str, Any]]:
        scenes: list[dict[str, Any]] = []
        scene_groups: list[list[Any]] = []
        current: list[Any] = []
        current_location: str | None = None
        for segment in segments:
            design = design_by_segment.get(int(segment.id), {})
            location = design.get("location_id") or "unspecified_location"
            if current and location != current_location:
                scene_groups.append(current)
                current = []
            current.append(segment)
            current_location = location
        if current:
            scene_groups.append(current)

        for scene_index, scene_segments in enumerate(scene_groups, start=1):
            scene_id = f"{act_id}_scene_{scene_index:02d}"
            first_design = design_by_segment.get(int(scene_segments[0].id), {}) if scene_segments else {}
            sequences = self._build_sequences(
                act_id,
                scene_id,
                scene_segments,
                design_by_segment,
                timing,
                shot_index,
            )
            scenes.append(
                {
                    "id": scene_id,
                    "location_id": first_design.get("location_id", "unspecified_location"),
                    "emotion": first_design.get("emotion", "neutral"),
                    "segment_ids": [int(segment.id) for segment in scene_segments],
                    "sequences": sequences,
                }
            )
        return scenes

    def _build_sequences(
        self,
        act_id: str,
        scene_id: str,
        segments: list[Any],
        design_by_segment: dict[int, dict[str, Any]],
        timing: dict[str, Any],
        shot_index: dict[str, dict[str, str]],
    ) -> list[dict[str, Any]]:
        sequences: list[dict[str, Any]] = []
        sequence_groups: list[list[Any]] = []
        current: list[Any] = []
        current_emotion: str | None = None
        for segment in segments:
            design = design_by_segment.get(int(segment.id), {})
            emotion = design.get("emotion") or "neutral"
            if current and emotion != current_emotion:
                sequence_groups.append(current)
                current = []
            current.append(segment)
            current_emotion = emotion
        if current:
            sequence_groups.append(current)

        for sequence_index, sequence_segments in enumerate(sequence_groups, start=1):
            first_segment_id = int(sequence_segments[0].id) if sequence_segments else sequence_index
            sequence_id = f"seq_{first_segment_id:03d}"
            shots: list[dict[str, Any]] = []
            for segment in sequence_segments:
                segment_id = int(segment.id)
                design = design_by_segment.get(segment_id, {})
                shot_id = f"shot_{segment_id:03d}"
                shots.append(
                    {
                        "id": shot_id,
                        "segment_id": segment_id,
                        "text": segment.text,
                        "shot_type": design.get("shot_type", "medium"),
                        "movement": design.get("movement", "still"),
                        "duration": self._duration_for(timing, segment_id, segment.text),
                        "director_intent": design.get("director_vision") or design.get("image_prompt", ""),
                    }
                )
                shot_index[str(segment_id)] = {
                    "act_id": act_id,
                    "scene_id": scene_id,
                    "sequence_id": sequence_id,
                    "shot_id": shot_id,
                }
            sequences.append(
                {
                    "id": sequence_id,
                    "emotion": self._dominant_emotion(sequence_segments, design_by_segment),
                    "segment_ids": [int(segment.id) for segment in sequence_segments],
                    "shots": shots,
                }
            )
        return sequences

    def _act_index(self, index: int, total: int) -> int:
        if total <= 1:
            return 0
        position = index / max(total - 1, 1)
        if position < 0.34:
            return 0
        if position < 0.67:
            return 1
        return 2

    def _act_label(self, act_index: int) -> str:
        return {1: "Setup", 2: "Confrontation", 3: "Resolution"}[act_index]

    def _act_function(self, act_index: int) -> str:
        return {
            1: "establish world, character, and premise",
            2: "escalate conflict and discovery",
            3: "resolve the emotional and narrative question",
        }[act_index]

    def _duration_for(self, timing: dict[str, Any], segment_id: int, text: str) -> float:
        try:
            return round(float(timing.get(str(segment_id))), 3)
        except (TypeError, ValueError):
            return round(max(1.0, len(text) / 18.0), 3)

    def _dominant_emotion(
        self,
        segments: list[Any],
        design_by_segment: dict[int, dict[str, Any]],
    ) -> str:
        emotions = [
            design_by_segment.get(int(segment.id), {}).get("emotion", "neutral")
            for segment in segments
        ]
        return max(set(emotions), key=emotions.count) if emotions else "neutral"

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]
