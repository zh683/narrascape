from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import (
    atomic_write_yaml,
    load_yaml_mapping,
    update_json_mapping,
)


class ReworkExecuteStage(Stage):
    """Execute a rework plan by invalidating assets and writing concrete queues."""

    name = "rework_execute"
    depends_on = ["rework_plan"]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        plan = context.config.pipeline_dir / "rework_plan.yaml"
        if not plan.exists():
            return False, f"rework_plan.yaml not found: {plan}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "rework_execution.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        plan = self._load_yaml(config.pipeline_dir / "rework_plan.yaml")
        actions = list(plan.get("actions", []) or [])
        executed: list[dict[str, Any]] = []

        regen_queue: list[dict[str, Any]] = []
        contract_rewrite_queue: list[dict[str, Any]] = []
        recut_queue: list[dict[str, Any]] = []
        replacement_queue: list[dict[str, Any]] = []

        for action in actions:
            action_type = action.get("action")
            if action_type == "rewrite_director_contract":
                contract_rewrite_queue.append(action)
                executed.append(
                    {
                        "segment_id": int(action["segment_id"]),
                        "operation": "queue_director_contract_rewrite",
                        "reason": action.get("reason"),
                    }
                )
            elif action_type == "regenerate_video":
                executed.append(self._invalidate_generated_video(context, action))
                regen_queue.append(action)
            elif action_type == "recut":
                recut_queue.append(action)
                executed.append(
                    {
                        "segment_id": int(action["segment_id"]),
                        "operation": "queue_recut",
                        "reason": action.get("reason"),
                    }
                )
            elif action_type == "replace_source_media":
                replacement_queue.append(action)
                executed.append(
                    {
                        "segment_id": int(action["segment_id"]),
                        "operation": "queue_source_media_replacement",
                        "reason": action.get("reason"),
                    }
                )

        queues = {
            "director_contract_rewrite_queue": self._write_queue(
                config.pipeline_dir / "director_contract_rewrite_queue.yaml",
                contract_rewrite_queue,
            ),
            "video_regen_queue": self._write_queue(
                config.pipeline_dir / "video_regen_queue.yaml", regen_queue
            ),
            "recut_queue": self._write_queue(config.pipeline_dir / "recut_queue.yaml", recut_queue),
            "source_media_replacement_queue": self._write_queue(
                config.pipeline_dir / "source_media_replacement_queue.yaml",
                replacement_queue,
            ),
        }
        self._mark_stages_pending(
            config.pipeline_dir / "state.json",
            self._stages_to_rerun(
                contract_rewrite_queue,
                regen_queue,
                recut_queue,
                replacement_queue,
            ),
        )
        execution = {
            "schema_version": "rework_execution.v1",
            "project": {"name": config.project.name, "title": config.project.title},
            "status": "executed" if executed else "no_actions",
            "source_plan": (config.pipeline_dir / "rework_plan.yaml").as_posix(),
            "executed_actions": executed,
            "queues": queues,
        }
        validate_artifact("rework_execution", execution)
        atomic_write_yaml(output, execution)
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(executed)} rework operation(s) executed",
            metadata={"executed_count": len(executed), "queues": queues},
        )

    def _invalidate_generated_video(
        self, context: StageContext, action: dict[str, Any]
    ) -> dict[str, Any]:
        segment_id = int(action["segment_id"])
        video_id = f"vid_{segment_id:02d}"
        videos_dir = context.config.project_dir / "assets" / "videos"
        candidates = list(videos_dir.glob(f"{video_id}.mp4")) + list(
            videos_dir.glob(f"{video_id}_take_*.mp4")
        )
        quarantined: list[str] = []
        quarantine_dir = context.config.pipeline_dir / "rework_quarantine" / "videos"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        for path in candidates:
            if not path.exists():
                continue
            target = quarantine_dir / path.name
            if target.exists():
                target.unlink()
            shutil.move(str(path), str(target))
            quarantined.append(target.as_posix())
        self._remove_done_ids(
            context.config.pipeline_dir / "video_gen_state.json",
            [path.stem for path in candidates] + [video_id],
        )
        return {
            "segment_id": segment_id,
            "operation": "invalidate_generated_video",
            "reason": action.get("reason"),
            "quarantined": quarantined,
        }

    def _remove_done_ids(self, state_path: Path, ids: list[str]) -> None:
        if not state_path.exists():
            return
        remove = set(ids)

        def update(state: dict[str, Any]) -> None:
            state["done"] = [item for item in state.get("done", []) if item not in remove]

        update_json_mapping(state_path, update, default={"done": [], "errors": [], "task_map": {}})

    def _write_queue(self, path: Path, actions: list[dict[str, Any]]) -> str:
        data = {"actions": actions}
        atomic_write_yaml(path, data)
        return path.as_posix()

    def _stages_to_rerun(
        self,
        contract_rewrite_queue: list[dict[str, Any]],
        regen_queue: list[dict[str, Any]],
        recut_queue: list[dict[str, Any]],
        replacement_queue: list[dict[str, Any]],
    ) -> list[str]:
        stages: list[str] = []
        if contract_rewrite_queue:
            stages.extend(
                [
                    "director_contract",
                    "reference_plate",
                    "generate_images",
                    "animatic",
                    "generate_video",
                    "take_select",
                    "film_timeline",
                ]
            )
        if regen_queue:
            stages.extend(["generate_video", "take_select", "film_timeline"])
        if replacement_queue:
            stages.extend(["source_media", "film_timeline"])
        if recut_queue:
            stages.extend(["film_timeline", "film_assemble"])
        if stages:
            stages.extend(
                [
                    "film_assemble",
                    "audio",
                    "subtitles",
                    "qa",
                    "continuity_bible",
                    "editing_review",
                    "director_review",
                    "rework_plan",
                    "creative_review",
                    "visual_semantic_qa",
                    "film_supervisor",
                ]
            )
        return self._dedupe(stages)

    def _mark_stages_pending(self, state_path: Path, stages: list[str]) -> None:
        if not stages:
            return

        def update(state: dict[str, Any]) -> None:
            state.setdefault("version", "2.0")
            state.setdefault("segments", {})
            state.setdefault("stage_outputs", {})
            state.setdefault("stages", {})
            for stage in stages:
                state["stages"][stage] = "pending"
                state["stage_outputs"].pop(stage, None)

        update_json_mapping(
            state_path,
            update,
            default={"version": "2.0", "stages": {}, "segments": {}, "stage_outputs": {}},
        )

    def _dedupe(self, stages: list[str]) -> list[str]:
        result: list[str] = []
        seen = set()
        for stage in stages:
            if stage in seen:
                continue
            seen.add(stage)
            result.append(stage)
        return result

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return load_yaml_mapping(path)
