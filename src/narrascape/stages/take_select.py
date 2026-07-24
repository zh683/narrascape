from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from narrascape.artifacts import write_artifact
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.stages.take_select_mcts import PairwiseUCTSelector, fallback_trace
from narrascape.utils.video_quality import analyze_take

logger = logging.getLogger(__name__)


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
        expected_durations = self._expected_durations(
            self._load_yaml(config.pipeline_dir / "director_contract.yaml")
        )
        candidates = self._collect_candidates(config.project_dir / "assets" / "videos", video_state)
        strategy = config.take_select.selection_strategy
        if strategy == "mcts" and not self.llm_client:
            logger.warning(
                "take_select: selection_strategy=mcts requires an LLM client; "
                "falling back to deterministic quality-score selection for all segments"
            )
        selections: list[dict[str, Any]] = []
        llm_used = False
        llm_errors: list[str] = []
        fallback_segments: list[int] = []
        mcts_segments: list[int] = []
        mcts_fallback_segments: list[int] = []
        with tempfile.TemporaryDirectory(prefix="take_select_frames_") as work_dir:
            for segment_id, takes in candidates.items():
                selection, used_llm, error, scoring = self._select_for_segment(
                    segment_id,
                    takes,
                    qa_report,
                    context,
                    expected_duration=expected_durations.get(segment_id),
                    work_dir=Path(work_dir),
                )
                selections.append(selection)
                llm_used = llm_used or used_llm
                if error:
                    llm_errors.append(error)
                if scoring == "bytes_fallback":
                    fallback_segments.append(segment_id)
                mcts_info = selection.get("mcts")
                if isinstance(mcts_info, dict):
                    if mcts_info.get("status") == "fallback_no_llm":
                        mcts_fallback_segments.append(segment_id)
                    else:
                        mcts_segments.append(segment_id)
        selection_process: dict[str, Any] = {
            "judges": ["qa", "llm"],
            "mode": "qa_plus_llm" if llm_used else "deterministic_quality_score",
            "llm_status": self._llm_status(llm_used, llm_errors),
            "llm_errors": llm_errors,
            "quality_signals": ["sharpness", "brightness", "duration", "stability"],
            "bytes_fallback_segments": fallback_segments,
            "selection_strategy": strategy,
        }
        if strategy == "mcts":
            selection_process["mcts"] = {
                "budget": config.take_select.mcts_budget,
                "exploration": config.take_select.mcts_exploration,
                "segments": mcts_segments,
                "fallback_segments": mcts_fallback_segments,
            }
        selection = {
            "schema_version": "take_selection.v1",
            "project": {
                "name": config.project.name,
                "title": config.project.title,
            },
            "selection_process": selection_process,
            "selections": selections,
        }
        write_artifact("take_selection", output, selection)
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
        *,
        expected_duration: float | None = None,
        work_dir: Path,
    ) -> tuple[dict[str, Any], bool, str | None, str]:
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

        # Frame-analysis scoring; a single failed take drops the WHOLE segment
        # back to byte-size scoring so scores stay on one comparable scale.
        qualities: dict[str, dict[str, Any]] = {}
        scoring = "frame_analysis"
        for take in takes:
            try:
                qualities[take["id"]] = analyze_take(
                    take["path"],
                    expected_duration=expected_duration,
                    work_dir=work_dir,
                )
            except Exception as exc:
                scoring = "bytes_fallback"
                logger.warning(
                    "take_select: quality analysis failed for %s (%s); "
                    "segment %s falls back to byte-size scoring",
                    take["id"],
                    exc,
                    segment_id,
                )
                break

        for take in takes:
            if scoring == "frame_analysis":
                score = float(qualities[take["id"]]["composite"])
            else:
                score = float(take["bytes"])
            if segment_id in risky_segments:
                score -= 1.0
            scored.append(
                {
                    **take,
                    "score": round(score, 3),
                    "quality": qualities.get(take["id"]) or {"status": "unavailable"},
                }
            )
        scored.sort(key=lambda item: (item["score"], item["take_number"]), reverse=True)
        selected = scored[0]
        llm_error = None
        llm_used = False
        mcts_trace: dict[str, Any] | None = None
        strategy = context.config.take_select.selection_strategy
        if self.llm_client:
            if strategy == "mcts":
                segment = context.script.get_segment(segment_id)
                outcome = PairwiseUCTSelector(
                    self.llm_client,
                    budget=context.config.take_select.mcts_budget,
                    exploration=context.config.take_select.mcts_exploration,
                ).select(
                    segment_id=segment_id,
                    narration=segment.text if segment else "",
                    candidates=scored,
                    qa_checks=(qa_report or {}).get("checks", {}),
                )
                mcts_selected = next(
                    (item for item in scored if item["id"] == outcome.selected_take), None
                )
                if mcts_selected:
                    selected = mcts_selected
                mcts_trace = outcome.trace
                llm_used = outcome.evaluations_used > 0
                reason = outcome.reason
                if outcome.errors:
                    llm_error = f"segment {segment_id}: {'; '.join(outcome.errors)}"
            else:
                try:
                    llm_choice = self._ask_llm(segment_id, scored, qa_report, context)
                    selected_id = llm_choice.get("selected_take")
                    llm_selected = next(
                        (item for item in scored if item["id"] == selected_id), None
                    )
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
            if strategy == "mcts":
                mcts_trace = fallback_trace(
                    budget=context.config.take_select.mcts_budget,
                    exploration=context.config.take_select.mcts_exploration,
                    candidates=scored,
                )
                reason = (
                    "highest QA proxy score; MCTS requested but no LLM client configured "
                    "(see mcts trace)"
                )

        selection_entry: dict[str, Any] = {
            "segment_id": segment_id,
            "selected_take": selected["id"],
            "selected_path": f"assets/videos/{selected['id']}.mp4",
            "reason": reason,
            "scoring": scoring,
            "candidates": [
                {
                    "take": item["id"],
                    "path": f"assets/videos/{item['id']}.mp4",
                    "score": item["score"],
                    "bytes": item["bytes"],
                    "quality": item["quality"],
                }
                for item in scored
            ],
        }
        if mcts_trace is not None:
            selection_entry["mcts"] = mcts_trace

        return (
            selection_entry,
            llm_used,
            llm_error,
            scoring,
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

    def _expected_durations(self, director_contract: dict[str, Any]) -> dict[int, float]:
        """Segment id -> expected clip seconds from director_contract generation.duration."""
        expected: dict[int, float] = {}
        for shot in director_contract.get("shots", []) or []:
            if not isinstance(shot, dict):
                continue
            generation = shot.get("generation")
            if not isinstance(generation, dict):
                continue
            raw_segment = shot.get("segment_id")
            raw_duration = generation.get("duration")
            if raw_segment is None or raw_duration is None:
                continue
            try:
                segment_id = int(str(raw_segment))
                duration = float(str(raw_duration))
            except (TypeError, ValueError):
                continue
            if duration > 0:
                expected[segment_id] = duration
        return expected

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        return super()._load_yaml(path)

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
