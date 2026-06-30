from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from narrascape.artifacts import validate_artifact
from narrascape.stages.base import Stage, StageContext, StageResult


class TakeSelectStage(Stage):
    """Select the best take for each generated video shot."""

    name = "take_select"
    depends_on = ["generate_video"]

    TAKE_RE = re.compile(r"^vid_(?P<segment>\d+)_take_(?P<take>\d+)$")

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        videos_dir = context.config.project_dir / "assets" / "videos"
        if not videos_dir.exists():
            return False, f"videos directory not found: {videos_dir}"
        if not any(self.TAKE_RE.match(path.stem) for path in videos_dir.glob("vid_*_take_*.mp4")):
            return False, "No multi-take generated videos found"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "take_selection.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        qa_report = self._load_yaml(config.pipeline_dir / "render_report.yaml")
        video_state = self._load_json(config.pipeline_dir / "video_gen_state.json")
        candidates = self._collect_candidates(config.project_dir / "assets" / "videos", video_state)
        selections: list[dict[str, Any]] = []
        llm_used = False
        llm_errors: list[str] = []
        for segment_id, takes in candidates.items():
            selection, used_llm, error = self._select_for_segment(
                segment_id, takes, qa_report, context
            )
            selections.append(selection)
            llm_used = llm_used or used_llm
            if error:
                llm_errors.append(error)
        selection = {
            "schema_version": "take_selection.v1",
            "project": {
                "name": config.project.name,
                "title": config.project.title,
            },
            "selection_process": {
                "judges": ["qa", "llm"],
                "mode": "qa_plus_llm" if llm_used else "deterministic_quality_score",
                "llm_status": self._llm_status(llm_used, llm_errors),
                "llm_errors": llm_errors,
            },
            "selections": selections,
        }
        validate_artifact("take_selection", selection)
        output.write_text(yaml.safe_dump(selection, sort_keys=False), encoding="utf-8")
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(selections)} multi-take shot(s) selected",
            metadata={"selection_count": len(selections), "selection": output.as_posix()},
        )

    def _collect_candidates(
        self,
        videos_dir: Path,
        video_state: dict[str, Any],
    ) -> dict[int, list[dict[str, Any]]]:
        done = set(video_state.get("done", []) or [])
        candidates: dict[int, list[dict[str, Any]]] = {}
        for path in sorted(videos_dir.glob("vid_*_take_*.mp4")):
            match = self.TAKE_RE.match(path.stem)
            if not match:
                continue
            if done and path.stem not in done:
                continue
            segment_id = int(match.group("segment"))
            take_id = int(match.group("take"))
            candidates.setdefault(segment_id, []).append(
                {
                    "id": path.stem,
                    "take_number": take_id,
                    "path": path,
                    "bytes": path.stat().st_size,
                }
            )
        return candidates

    def _select_for_segment(
        self,
        segment_id: int,
        takes: list[dict[str, Any]],
        qa_report: dict[str, Any],
        context: StageContext,
    ) -> tuple[dict[str, Any], bool, str | None]:
        scored: list[dict[str, Any]] = []
        risky_segments: set[int] = set()
        checks = qa_report.get("checks", {}) if isinstance(qa_report, dict) else {}
        for key in (
            "missing_video_clips",
            "continuity_risk_segments",
            "pacing_risk_segments",
            "missing_generated_video_segments",
        ):
            for item in checks.get(key, []) or []:
                try:
                    risky_segments.add(int(item))
                except (TypeError, ValueError):
                    continue
        for take in takes:
            score = float(take["bytes"])
            if segment_id in risky_segments:
                score -= 1.0
            scored.append({**take, "score": round(score, 3)})
        scored.sort(key=lambda item: (item["score"], item["take_number"]), reverse=True)
        selected = scored[0]
        llm_error = None
        llm_used = False
        if self.llm_client:
            try:
                llm_choice = self._ask_llm(segment_id, scored, qa_report, context)
                selected_id = llm_choice.get("selected_take")
                llm_selected = next((item for item in scored if item["id"] == selected_id), None)
                if llm_selected:
                    selected = llm_selected
                    llm_used = True
                    reason = str(llm_choice.get("reason") or "LLM director selected this take.")
                else:
                    reason = "highest QA proxy score; LLM returned an unknown take"
                    llm_error = f"segment {segment_id}: unknown LLM take {selected_id!r}"
            except Exception as exc:
                reason = "highest QA proxy score; LLM judge unavailable"
                llm_error = f"segment {segment_id}: {exc}"
        else:
            reason = "highest QA proxy score; ready for LLM judge override"

        return (
            {
                "segment_id": segment_id,
                "selected_take": selected["id"],
                "selected_path": f"assets/videos/{selected['id']}.mp4",
                "reason": reason,
                "candidates": [
                    {
                        "take": item["id"],
                        "path": f"assets/videos/{item['id']}.mp4",
                        "score": item["score"],
                        "bytes": item["bytes"],
                    }
                    for item in scored
                ],
            },
            llm_used,
            llm_error,
        )

    def _ask_llm(
        self,
        segment_id: int,
        scored: list[dict[str, Any]],
        qa_report: dict[str, Any],
        context: StageContext,
    ) -> dict[str, Any]:
        segment = context.script.get_segment(segment_id)
        candidate_payload = [
            {
                "take": item["id"],
                "score": item["score"],
                "bytes": item["bytes"],
            }
            for item in scored
        ]
        prompt = (
            "You are the multi-take director for a film timeline. "
            "Choose exactly one generated-video take for the segment. "
            "Use QA score as evidence, but prefer story clarity and continuity when the choice is close.\n\n"
            f"Segment id: {segment_id}\n"
            f"Narration: {segment.text if segment else ''}\n"
            f"Candidates: {json.dumps(candidate_payload, ensure_ascii=False)}\n"
            f"QA checks: {json.dumps((qa_report or {}).get('checks', {}), ensure_ascii=False)}\n\n"
            'Return JSON only: {"selected_take": "vid_01_take_01", "reason": "short reason"}.'
        )
        response = self.llm_client.complete(prompt, json_mode=True)
        if hasattr(response, "extract_json_safe"):
            data = response.extract_json_safe(default={})
        else:
            data = json.loads(getattr(response, "content", "{}"))
        if not isinstance(data, dict):
            raise ValueError("LLM returned non-object JSON")
        return data

    def _llm_status(self, used: bool, errors: list[str]) -> str:
        if used and not errors:
            return "used"
        if used and errors:
            return "partial"
        if errors:
            return "fallback_after_error"
        return "not_configured"

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
