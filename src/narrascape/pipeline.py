from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from narrascape.config import (
    DEFAULT_VISUAL_STYLE,
    ImageProvider,
    NarrascapeConfig,
    Script,
    load_script,
)
from narrascape.contracts import FilmSupervisorReport
from narrascape.pipeline_approval import PipelineApproval
from narrascape.stages.animatic import AnimaticStage
from narrascape.stages.assistant_handoff import AssistantHandoffStage
from narrascape.stages.audio import AudioRemixStage, AudioStage
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.stages.concat import ConcatStage
from narrascape.stages.continuity_bible import ContinuityBibleStage
from narrascape.stages.creative_review import CreativeReviewStage
from narrascape.stages.design import DesignStage
from narrascape.stages.director_contract import DirectorContractStage
from narrascape.stages.director_review import DirectorReviewStage
from narrascape.stages.editing_review import EditingReviewStage
from narrascape.stages.film_assemble import FilmAssembleStage
from narrascape.stages.film_supervisor import FilmSupervisorStage
from narrascape.stages.film_timeline import FilmTimelineStage
from narrascape.stages.footage_edit import FootageEditStage
from narrascape.stages.generate_images import GenerateImagesStage
from narrascape.stages.generate_music import GenerateMusicStage
from narrascape.stages.generate_tts import GenerateTTSStage
from narrascape.stages.generate_video import GenerateVideoStage
from narrascape.stages.humanize import HumanizeStage
from narrascape.stages.kenburns import KenBurnsStage
from narrascape.stages.pre_production import PreProductionStage
from narrascape.stages.production_readiness import ProductionReadinessStage
from narrascape.stages.qa import QAStage
from narrascape.stages.reference_plate import ReferencePlateStage
from narrascape.stages.remotion_preview import RemotionPreviewStage
from narrascape.stages.research import ResearchStage
from narrascape.stages.rework_execute import ReworkExecuteStage
from narrascape.stages.rework_plan import ReworkPlanStage
from narrascape.stages.screenplay_structure import ScriptSceneDirectorStage
from narrascape.stages.source_media import SourceMediaStage
from narrascape.stages.storyboard_sheet import StoryboardSheetStage
from narrascape.stages.subtitles import SubtitleStage
from narrascape.stages.take_select import TakeSelectStage
from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage
from narrascape.stages.write import WriteStage
from narrascape.utils.budget import BudgetTracker, estimate_llm_cost
from narrascape.utils.safe_io import (
    atomic_write_json,
    load_json_mapping,
    load_yaml_mapping,
    update_json_mapping,
)

logger = logging.getLogger("narrascape.pipeline")

STRICT_DIRECTOR_BLOCKED_STATUSES = {"fallback_after_error", "not_configured"}

STRICT_DIRECTOR_ARTIFACTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pre_production": ("pre_production.yaml", ("director_process",)),
    "design": ("design_report.yaml", ("director_process",)),
    "director_contract": ("director_contract.yaml", ("compile_process",)),
    "take_select": ("take_selection.yaml", ("selection_process",)),
    "creative_review": ("creative_review.yaml", ("review_process",)),
    "visual_semantic_qa": ("visual_semantic_report.yaml", ("review_process",)),
}


# ═══════════════════════════════════════════
# Stage Registry
# ═══════════════════════════════════════════

ALL_STAGES: list[type[Stage]] = [
    ResearchStage,
    WriteStage,
    HumanizeStage,
    SourceMediaStage,
    FootageEditStage,
    PreProductionStage,
    DesignStage,
    ScriptSceneDirectorStage,
    DirectorContractStage,
    ReferencePlateStage,
    GenerateImagesStage,
    StoryboardSheetStage,
    AnimaticStage,
    ProductionReadinessStage,
    GenerateVideoStage,
    TakeSelectStage,
    GenerateTTSStage,
    FilmTimelineStage,
    RemotionPreviewStage,
    FilmAssembleStage,
    GenerateMusicStage,
    AudioRemixStage,
    KenBurnsStage,
    ConcatStage,
    AudioStage,
    SubtitleStage,
    QAStage,
    ContinuityBibleStage,
    EditingReviewStage,
    DirectorReviewStage,
    ReworkPlanStage,
    CreativeReviewStage,
    VisualSemanticQAStage,
    FilmSupervisorStage,
    AssistantHandoffStage,
    ReworkExecuteStage,
]

STAGE_MAP: dict[str, type[Stage]] | None = None


def get_stage_map() -> dict[str, type[Stage]]:
    """Lazy-load stage name → class mapping.

    Avoids instantiating all stages at module import time.
    """
    global STAGE_MAP
    if STAGE_MAP is None:
        STAGE_MAP = {_stage_class_name(cls): cls for cls in ALL_STAGES}
    return STAGE_MAP


def _stage_class_name(stage_cls: type[Stage]) -> str:
    name = stage_cls.__dict__.get("name")
    if isinstance(name, str):
        return name
    return stage_cls().name


def _stage_class_depends_on(stage_cls: type[Stage]) -> list[str]:
    depends_on = stage_cls.__dict__.get("depends_on")
    if isinstance(depends_on, list):
        return [str(item) for item in depends_on]
    return list(stage_cls().depends_on)


def _resolve_dependencies(
    target_stages: list[str],
    available: dict[str, type[Stage]],
) -> list[str]:
    """Topological sort of stage dependencies.

    Returns stages in execution order (dependencies first).
    """
    # Build dependency graph
    deps: dict[str, set[str]] = {}
    for name, cls in available.items():
        deps[name] = set(_stage_class_depends_on(cls))

    # Collect all required stages (target + transitive deps)
    required = set()
    queue = list(target_stages)
    while queue:
        name = queue.pop(0)
        if name in required:
            continue
        required.add(name)
        for dep in deps.get(name, set()):
            if dep not in required:
                queue.append(dep)

    # Kahn's algorithm for topological sort
    in_degree = dict.fromkeys(required, 0)
    for name in required:
        for dep in deps.get(name, set()):
            if dep in required:
                in_degree[name] += 1

    stage_order = {name: idx for idx, name in enumerate(available)}

    result = []
    queue = [name for name in required if in_degree[name] == 0]
    while queue:
        queue.sort(key=lambda item: stage_order.get(item, len(stage_order)))
        name = queue.pop(0)
        result.append(name)
        for other in required:
            if name in deps.get(other, set()):
                in_degree[other] -= 1
                if in_degree[other] == 0:
                    queue.append(other)

    if len(result) != len(required):
        raise RuntimeError("Circular dependency detected in stages")

    return result


def _resolve_dependency_levels(
    target_stages: list[str],
    available: dict[str, type[Stage]],
) -> list[list[str]]:
    """Group stages into topological levels for layered parallel execution.

    Every stage in a level depends only on stages in earlier levels, so all
    stages within one level may run concurrently. Level order and within-level
    order are deterministic (registry order), matching the serial topological
    order produced by ``_resolve_dependencies``.
    """
    deps: dict[str, set[str]] = {}
    for name, cls in available.items():
        deps[name] = set(_stage_class_depends_on(cls))

    required = set()
    queue = list(target_stages)
    while queue:
        name = queue.pop(0)
        if name in required:
            continue
        required.add(name)
        for dep in deps.get(name, set()):
            if dep not in required:
                queue.append(dep)

    stage_order = {name: idx for idx, name in enumerate(available)}

    levels: list[list[str]] = []
    assigned: set[str] = set()
    remaining = set(required)
    while remaining:
        ready = [
            name
            for name in remaining
            if all(dep in assigned or dep not in required for dep in deps.get(name, set()))
        ]
        if not ready:
            raise RuntimeError("Circular dependency detected in stages")
        ready.sort(key=lambda item: stage_order.get(item, len(stage_order)))
        levels.append(ready)
        assigned.update(ready)
        remaining -= set(ready)

    return levels


# ═══════════════════════════════════════════
# Pipeline State
# ═══════════════════════════════════════════


class PipelineState:
    """Persistent pipeline execution state."""

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        return load_json_mapping(
            self.state_path,
            default={"version": "2.0", "stages": {}, "segments": {}, "stage_outputs": {}},
        )

    def save(self) -> None:
        atomic_write_json(self.state_path, self.data)

    def get_stage_status(self, name: str) -> str:
        return str(self.data.get("stages", {}).get(name, "pending"))

    def set_stage_status(self, name: str, status: str) -> None:
        def update(data: dict[str, Any]) -> None:
            data.setdefault("version", "2.0")
            data.setdefault("segments", {})
            data.setdefault("stage_outputs", {})
            data.setdefault("stages", {})[name] = status

        self.data = update_json_mapping(
            self.state_path,
            update,
            default={"version": "2.0", "stages": {}, "segments": {}, "stage_outputs": {}},
        )

    def set_stage_outputs(self, name: str, outputs: list[str]) -> None:
        def update(data: dict[str, Any]) -> None:
            data.setdefault("version", "2.0")
            data.setdefault("stages", {})
            data.setdefault("segments", {})
            data.setdefault("stage_outputs", {})[name] = outputs

        self.data = update_json_mapping(
            self.state_path,
            update,
            default={"version": "2.0", "stages": {}, "segments": {}, "stage_outputs": {}},
        )

    def clear_stage_outputs(self, name: str) -> None:
        def update(data: dict[str, Any]) -> None:
            data.setdefault("version", "2.0")
            data.setdefault("stages", {})
            data.setdefault("segments", {})
            data.setdefault("stage_outputs", {}).pop(name, None)

        self.data = update_json_mapping(
            self.state_path,
            update,
            default={"version": "2.0", "stages": {}, "segments": {}, "stage_outputs": {}},
        )

    def get_stage_outputs(self, name: str) -> list[str]:
        outputs = self.data.get("stage_outputs", {}).get(name, [])
        return [str(path) for path in outputs] if isinstance(outputs, list) else []

    def is_completed(self, name: str) -> bool:
        return self.get_stage_status(name) == "completed"


# ═══════════════════════════════════════════
# Pipeline Executor
# ═══════════════════════════════════════════


class Pipeline:
    """Main pipeline executor with dependency graph, incremental builds, and optional stage approval."""

    def __init__(
        self,
        config: NarrascapeConfig,
        dry_run: bool = False,
        force: bool = False,
        interactive: bool = False,
        auto_approve: bool = False,
        console: Any = None,
        llm_client: Any = None,
        image_api_key: str | None = None,
        minimax_api_key: str | None = None,
        max_workers: int | None = None,
    ):
        self.config = config
        self.dry_run = dry_run
        self.force = force
        self.interactive = interactive
        self.auto_approve = auto_approve
        self.console = console
        self.llm_client = llm_client
        workers = max_workers if max_workers is not None else config.pipeline.max_workers
        workers = max(1, min(16, int(workers)))
        if workers > 1 and interactive:
            # 审批交互只能在主线程进行：interactive 模式强制串行
            logger.warning("--interactive requires serial orchestration; max_workers forced to 1")
            workers = 1
        self.max_workers = workers
        if self.config.pipeline.video_generation == "required" and self.llm_client is None:
            raise RuntimeError(
                "pipeline.video_generation=required requires an LLM client. "
                "Use llm.mode=ai_assistant, bridge, api, or auto before running an AI-film build."
            )
        self.image_api_key = image_api_key
        self.minimax_api_key = minimax_api_key
        # Script may not exist yet (research/write stages create it)
        self.script = self._load_script()
        self.state = PipelineState(config.pipeline_dir / "state.json")
        self.approval = PipelineApproval(config.pipeline_dir)
        # Project-level budget tracker shared by LLM usage accounting.
        self.budget_tracker = BudgetTracker(
            config.budget, config.pipeline_dir / "budget_state.json"
        )
        self._active_stage: str | None = None
        self._stage_local = threading.local()
        if self.llm_client is not None and hasattr(self.llm_client, "on_usage"):
            self.llm_client.on_usage = self._record_llm_usage

    def _set_active_stage(self, name: str | None) -> None:
        """Mark the stage currently running *in this thread*.

        Thread-local so LLM usage attribution stays correct when orchestration
        runs same-layer stages concurrently; the ``_active_stage`` attribute is
        kept as the main-thread mirror for backward compatibility.
        """
        self._stage_local.active = name
        if threading.current_thread() is threading.main_thread():
            self._active_stage = name

    def _record_llm_usage(self, usage: dict[str, int], model: str, estimated: bool) -> None:
        """Budget-track one completed LLM call (invoked via LLMClient.on_usage).

        Free providers (local / bridge / ai_assistant) are recorded as
        zero-cost entries so the cost report still shows their token volume.
        """
        provider = str(getattr(self.llm_client.config, "provider", "") or "")
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        if provider in ("local", "bridge", "ai_assistant"):
            cost = 0.0
        else:
            cost = estimate_llm_cost(
                self.config.budget.llm_rates,
                self.config.budget.llm_default_rate,
                model,
                prompt_tokens,
                completion_tokens,
            )
        self.budget_tracker.record_actual(
            cost,
            kind="llm",
            stage=self._current_active_stage(),
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated=estimated,
        )

    def _current_active_stage(self) -> str:
        """Stage running in the calling thread (empty string when unknown)."""
        return str(getattr(self._stage_local, "active", None) or self._active_stage or "")

    def _load_script(self) -> Script:
        """Load script if it exists, otherwise return empty placeholder."""
        if self.config.script_path.exists():
            return load_script(self.config.script_path)
        # Return an internal placeholder for early stages that create the script.
        from narrascape.config import Script

        return Script.model_construct(segments=[])

    def _create_stage(self, stage_cls: type[Stage]) -> Stage:
        """Create a stage instance with appropriate constructor arguments.

        Pulls configuration values from self.config and passes API keys
        and LLM clients where needed.
        """
        from narrascape.stages.creative_review import CreativeReviewStage
        from narrascape.stages.design import DesignStage
        from narrascape.stages.director_contract import DirectorContractStage
        from narrascape.stages.generate_images import GenerateImagesStage
        from narrascape.stages.generate_music import GenerateMusicStage
        from narrascape.stages.generate_tts import GenerateTTSStage
        from narrascape.stages.generate_video import GenerateVideoStage
        from narrascape.stages.humanize import HumanizeStage
        from narrascape.stages.pre_production import PreProductionStage
        from narrascape.stages.reference_plate import ReferencePlateStage
        from narrascape.stages.research import ResearchStage
        from narrascape.stages.take_select import TakeSelectStage
        from narrascape.stages.visual_semantic_qa import VisualSemanticQAStage
        from narrascape.stages.write import WriteStage

        style = self.config.images.style if self.config.images else DEFAULT_VISUAL_STYLE
        image_provider = self.config.images.provider if self.config.images else None
        lean_reference_pass = image_provider == ImageProvider.AGNES

        if stage_cls == PreProductionStage:
            return PreProductionStage(
                llm_client=self.llm_client,
                style_template=style,
                generate_turns=not lean_reference_pass,
                generate_expressions=not lean_reference_pass,
                image_api_key=self.image_api_key,
            )
        elif stage_cls == DesignStage:
            return DesignStage(
                llm_client=self.llm_client,
                style_template=style,
            )
        elif stage_cls == DirectorContractStage:
            return DirectorContractStage(llm_client=self.llm_client)
        elif stage_cls == ReferencePlateStage:
            return ReferencePlateStage()
        elif stage_cls == AnimaticStage:
            return AnimaticStage()
        elif stage_cls == GenerateImagesStage:
            return GenerateImagesStage(api_key=self.image_api_key)
        elif stage_cls == GenerateVideoStage:
            return GenerateVideoStage(api_key=self.image_api_key)
        elif stage_cls == GenerateTTSStage:
            return GenerateTTSStage(api_key=self.minimax_api_key)
        elif stage_cls == GenerateMusicStage:
            return GenerateMusicStage(api_key=self.minimax_api_key)
        elif stage_cls == TakeSelectStage:
            return TakeSelectStage(llm_client=self.llm_client)
        elif stage_cls == CreativeReviewStage:
            return CreativeReviewStage(llm_client=self.llm_client)
        elif stage_cls == VisualSemanticQAStage:
            return VisualSemanticQAStage(llm_client=self.llm_client)
        elif stage_cls == ResearchStage:
            return ResearchStage(llm_client=self.llm_client, topic=self.config.project.title)
        elif stage_cls == WriteStage:
            return WriteStage(
                llm_client=self.llm_client,
                topic=self.config.project.title,
                segment_count=self.config.project.segment_count or 12,
                style=self.config.project.style or "documentary",
            )
        elif stage_cls == HumanizeStage:
            return HumanizeStage(llm_client=self.llm_client)
        else:
            return stage_cls()

    def _default_stages(self) -> list[str]:
        stages = [
            "pre_production",
            "design",
            "screenplay_structure",
            "director_contract",
            "reference_plate",
            "generate_images",
            "storyboard_sheet",
            "animatic",
            "production_readiness",
            "generate_tts",
        ]
        video_policy = self.config.pipeline.video_generation
        if video_policy != "off":
            stages.extend(["generate_video", "take_select"])
        stages.extend(
            [
                "film_timeline",
                "remotion_preview",
                "film_assemble",
                "generate_music",
                "remix_audio",
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
                "assistant_handoff",
            ]
        )
        return stages

    def run(self, stages: list[str] | None = None) -> dict[str, StageResult]:
        """Execute the pipeline with optional stage-by-stage approval.

        Args:
            stages: Specific stages to run (default: all). Dependencies are auto-resolved.

        Returns:
            Dictionary of stage name -> result
        """
        default_run = stages is None
        if stages is None:
            stages = self._default_stages()

        # Add research/write to the default pipeline if no script exists
        if not self.config.script_path.exists():
            # No script — check if research_report exists
            research_report = self.config.project_dir / "research_report.md"
            if (
                research_report.exists()
                and not self.config.project_dir.joinpath("scripts", "script_approved.yaml").exists()
            ):
                stages = ["write"] + stages
            else:
                stages = ["research", "write"] + stages

        if default_run:
            return self._run_with_auto_rework(stages)
        return self._run_once(stages)

    def _run_with_auto_rework(self, stages: list[str]) -> dict[str, StageResult]:
        results = self._run_once(stages, allow_optional_skips=True)
        if not self.config.pipeline.auto_rework or self.config.pipeline.max_rework_cycles <= 0:
            return results
        if not self._stage_succeeded(results, "film_supervisor"):
            return results

        for cycle_index in range(1, self.config.pipeline.max_rework_cycles + 1):
            next_stages = self._supervisor_next_stages()
            if not next_stages:
                break

            rework_result = self._run_once(
                ["rework_execute"],
                force_stages={"rework_execute"},
            )
            self._merge_cycle_results(results, rework_result, cycle_index)
            if not self._stage_succeeded(rework_result, "rework_execute"):
                break

            rerun_stages = [
                stage
                for stage in next_stages
                if stage != "rework_execute" and stage in get_stage_map()
            ]
            rerun_stages = self._filter_rerun_stages(rerun_stages)
            if not rerun_stages:
                break

            cycle_results = self._run_once(
                rerun_stages,
                allow_optional_skips=True,
                force_stages=set(rerun_stages),
            )
            self._merge_cycle_results(results, cycle_results, cycle_index)
            if not self._stage_succeeded(cycle_results, "film_supervisor"):
                break
        return results

    def _run_once(
        self,
        stages: list[str],
        *,
        allow_optional_skips: bool = False,
        force_stages: set[str] | None = None,
    ) -> dict[str, StageResult]:
        if self.max_workers > 1:
            return self._run_once_parallel(
                stages,
                allow_optional_skips=allow_optional_skips,
                force_stages=force_stages,
            )
        # Resolve dependencies
        stage_map = get_stage_map()
        execution_order = _resolve_dependencies(stages, stage_map)
        logger.info(f"Pipeline execution order: {execution_order}")

        # Build context
        context = StageContext(
            config=self.config,
            script=self.script,
            state={},
            dry_run=self.dry_run,
        )

        results: dict[str, StageResult] = {}
        force_stages = force_stages or set()

        for stage_name in execution_order:
            stage_cls = stage_map[stage_name]
            stage = self._create_stage(stage_cls)

            # ── Check approval gate ──
            approval_status = self.approval.get_status(stage_name)
            if approval_status == "rejected":
                logger.error(
                    f"[{stage_name}] Previously rejected. Fix and retry, or run: narrascape approve -p . -s {stage_name}"
                )
                results[stage_name] = StageResult(
                    stage_name,
                    False,
                    message=f"Stage rejected. Run 'narrascape approve -p . -s {stage_name}' to continue.",
                )
                break

            # Check if already completed (incremental) AND approved
            if (
                stage_name not in force_stages
                and not self.force
                and self.state.is_completed(stage_name)
                and approval_status in ("approved", "skipped")
            ):
                if not self._completed_outputs_present(stage_name, stage):
                    logger.warning(
                        f"[{stage_name}] Completed state ignored because recorded outputs are missing"
                    )
                    self.state.set_stage_status(stage_name, "pending")
                    self.approval._clear_status_files(stage_name)
                else:
                    logger.info(
                        f"[{stage_name}] Already completed and approved (skip with --force to rebuild)"
                    )
                    strict_ok, strict_reason = self._strict_director_check(stage_name)
                    if not strict_ok:
                        result = StageResult(
                            stage_name,
                            False,
                            message=strict_reason,
                            metadata={
                                "strict_director": True,
                                "strict_director_reason": strict_reason,
                                "cached_artifact": True,
                            },
                        )
                        results[stage_name] = result
                        self.state.set_stage_status(stage_name, "failed")
                        logger.error(f"[{stage_name}] Failed: {result.message}")
                        self._mark_remaining_pending(execution_order, stage_name)
                        break
                    results[stage_name] = StageResult(
                        stage_name, True, message="skipped (cached + approved)"
                    )
                    continue

            # Completed but still awaiting human approval: halt without re-running.
            # Re-running here would silently repeat LLM/paid API calls. Interactive
            # and --approve (auto_approve) modes keep their existing rerun semantics.
            if (
                stage_name not in force_stages
                and not self.force
                and not self.interactive
                and not self.auto_approve
                and self.state.is_completed(stage_name)
                and approval_status == "pending"
            ):
                if not self._completed_outputs_present(stage_name, stage):
                    logger.warning(
                        f"[{stage_name}] Completed state ignored because recorded outputs are missing"
                    )
                    self.state.set_stage_status(stage_name, "pending")
                    self.approval._clear_status_files(stage_name)
                else:
                    approve_cmd = f"narrascape approve -p . -s {stage_name}"
                    logger.info(
                        f"[{stage_name}] Completed but awaiting approval; stopping here. "
                        f"Run '{approve_cmd}' (or build with --approve) to continue."
                    )
                    results[stage_name] = StageResult(
                        stage_name,
                        True,
                        message=(
                            f"Awaiting approval; run '{approve_cmd}' "
                            "or build with --approve to continue."
                        ),
                        metadata={"awaiting_approval": True},
                    )
                    break

            # Check prerequisites
            can_run, reason = stage.can_run(context)
            if not can_run:
                if allow_optional_skips and self._can_skip_optional_stage(stage_name, reason):
                    logger.warning(f"[{stage_name}] Optional stage skipped: {reason}")
                    result = StageResult(
                        stage_name,
                        True,
                        message=f"skipped optional stage: {reason}",
                        metadata={"optional_skipped": True, "reason": reason},
                    )
                    results[stage_name] = result
                    self.state.set_stage_status(stage_name, "skipped")
                    if self.auto_approve:
                        self.approval.skip(stage_name, reviewer="auto", notes=reason)
                    continue
                logger.error(f"[{stage_name}] Prerequisites not met: {reason}")
                results[stage_name] = StageResult(stage_name, False, message=reason)
                break

            # Execute
            self.state.set_stage_status(stage_name, "running")
            start = time.monotonic()

            try:
                self._set_active_stage(stage_name)
                result = stage.run(context)
                result.duration_seconds = time.monotonic() - start
            except Exception as e:
                logger.exception(f"[{stage_name}] Execution failed")
                result = StageResult(
                    stage_name,
                    False,
                    message=f"Exception: {e}",
                    duration_seconds=time.monotonic() - start,
                )
            finally:
                self._set_active_stage(None)

            if result.success:
                strict_ok, strict_reason = self._strict_director_check(stage_name)
                if not strict_ok:
                    result = StageResult(
                        stage_name,
                        False,
                        outputs=result.outputs,
                        message=strict_reason,
                        duration_seconds=result.duration_seconds,
                        metadata={
                            **result.metadata,
                            "strict_director": True,
                            "strict_director_reason": strict_reason,
                        },
                    )

            results[stage_name] = result

            if result.success:
                self.state.set_stage_status(stage_name, "completed")
                self.state.set_stage_outputs(stage_name, self._recordable_outputs(result))
                logger.info(f"[{stage_name}] Completed in {result.duration_seconds:.1f}s")
                if stage_name in ("write", "humanize") and self.config.script_path.exists():
                    self.script = self._load_script()
                    context.script = self.script

                # ── Approval gate ──
                if self.interactive and self.console:
                    # Interactive mode: pause for user approval
                    # Use a loop to handle retry multiple times
                    while True:
                        action = self.approval.prompt_interactive(stage_name, result, self.console)
                        if action == "rejected":
                            break
                        elif action == "approved" or action == "skipped":
                            break  # Continue to next stage
                        elif action == "retry":
                            # Remove approval files and retry this stage
                            self.approval._clear_status_files(stage_name)
                            self.state.set_stage_status(stage_name, "pending")
                            # Retry: create a new stage instance and re-run
                            logger.info(f"[{stage_name}] Retrying...")
                            stage = self._create_stage(stage_cls)
                            retry_start = time.monotonic()
                            try:
                                self._set_active_stage(stage_name)
                                result = stage.run(context)
                                result.duration_seconds = time.monotonic() - retry_start
                            except Exception as e:
                                logger.exception(f"[{stage_name}] Retry failed")
                                result = StageResult(
                                    stage_name,
                                    False,
                                    message=f"Retry exception: {e}",
                                    duration_seconds=time.monotonic() - retry_start,
                                )
                            finally:
                                self._set_active_stage(None)
                            results[stage_name] = result
                            if not result.success:
                                self.state.set_stage_status(stage_name, "failed")
                                break  # Retry failed, stop
                            self.state.set_stage_status(stage_name, "completed")
                            logger.info(
                                f"[{stage_name}] Retry completed in {result.duration_seconds:.1f}s"
                            )
                            # Loop again to prompt for the retry result
                            continue
                    if action == "rejected":
                        self.state.set_stage_status(stage_name, "pending")
                        break  # Stop pipeline
                    # If action is approved/skipped, continue to next stage
                elif not self.auto_approve:
                    # Non-interactive, no auto-approve: create review request and stop
                    self.approval.request_review(stage_name, result)
                    logger.info(
                        f"[{stage_name}] Review required. Run: narrascape approve -p . -s {stage_name}"
                    )
                    break
                else:
                    # Auto-approve mode
                    self.approval.approve(stage_name, reviewer="auto")
                    logger.info(f"[{stage_name}] Auto-approved")
            else:
                self.state.set_stage_status(stage_name, "failed")
                logger.error(f"[{stage_name}] Failed: {result.message}")
                if not getattr(stage, "continue_on_failure", False):
                    self._mark_remaining_pending(execution_order, stage_name)
                    break

        return results

    def _run_once_parallel(
        self,
        stages: list[str],
        *,
        allow_optional_skips: bool = False,
        force_stages: set[str] | None = None,
    ) -> dict[str, StageResult]:
        """Layered parallel execution used when ``max_workers > 1``.

        Stages are grouped into dependency levels; stages within one level run
        concurrently on a thread pool. Semantics intentionally mirror the serial
        scheduler with these precisely defined differences:

        - Pre-gates (rejected / cached-skip / pending-halt / can_run) are
          evaluated serially on the main thread before a level is submitted.
          A pre-gate halt stops the whole run immediately (already-gated
          runnable stages of the same level are NOT executed).
        - Execution halts (failure, review request) take effect at the level
          boundary: already-submitted stages of the current level always run
          to completion before the pipeline stops.
        - When approval is required, every successful stage of the level gets
          a review request (in execution order) instead of stopping after the
          first one.
        - ``results`` are keyed by stage name; consumers iterate them in
          dependency execution order, never in completion order.
        - The script context is refreshed at level boundaries (after a
          successful write / humanize), never mid-level.
        - Interactive mode never reaches this path (max_workers forced to 1).
        """
        stage_map = get_stage_map()
        levels = _resolve_dependency_levels(stages, stage_map)
        execution_order = [name for level in levels for name in level]
        logger.info(f"Pipeline execution levels (max_workers={self.max_workers}): {levels}")

        context = StageContext(
            config=self.config,
            script=self.script,
            state={},
            dry_run=self.dry_run,
        )

        results: dict[str, StageResult] = {}
        force = force_stages or set()
        halt = False
        with ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="narrascape-stage"
        ) as pool:
            for level in levels:
                if halt:
                    break
                runnable: list[tuple[str, Stage]] = []
                for stage_name in level:
                    if self._parallel_pre_gate(
                        stage_name,
                        stage_map[stage_name],
                        context,
                        results,
                        execution_order,
                        force,
                        allow_optional_skips,
                        runnable,
                    ):
                        halt = True
                        break
                if halt:
                    break
                futures = {
                    pool.submit(self._parallel_execute, stage_name, stage, context): stage_name
                    for stage_name, stage in runnable
                }
                for future in as_completed(futures):
                    stage_name = futures[future]
                    try:
                        results[stage_name] = future.result()
                    except Exception as exc:  # pragma: no cover - defensive guard
                        logger.exception(f"[{stage_name}] Execution failed")
                        results[stage_name] = StageResult(
                            stage_name, False, message=f"Exception: {exc}"
                        )
                if self._parallel_post_gates(runnable, results, execution_order, context):
                    halt = True
        # Aggregate in dependency execution order, never completion order.
        return {name: results[name] for name in execution_order if name in results}

    def _parallel_pre_gate(
        self,
        stage_name: str,
        stage_cls: type[Stage],
        context: StageContext,
        results: dict[str, StageResult],
        execution_order: list[str],
        force_stages: set[str],
        allow_optional_skips: bool,
        runnable: list[tuple[str, Stage]],
    ) -> bool:
        """Evaluate serial pre-gates for one stage (main thread).

        Mirrors the pre-execution gates of the serial scheduler exactly.
        Returns True when the run must halt before executing this level.
        """
        stage = self._create_stage(stage_cls)

        # ── Check approval gate ──
        approval_status = self.approval.get_status(stage_name)
        if approval_status == "rejected":
            logger.error(
                f"[{stage_name}] Previously rejected. Fix and retry, or run: narrascape approve -p . -s {stage_name}"
            )
            results[stage_name] = StageResult(
                stage_name,
                False,
                message=f"Stage rejected. Run 'narrascape approve -p . -s {stage_name}' to continue.",
            )
            return True

        # Check if already completed (incremental) AND approved
        if (
            stage_name not in force_stages
            and not self.force
            and self.state.is_completed(stage_name)
            and approval_status in ("approved", "skipped")
        ):
            if not self._completed_outputs_present(stage_name, stage):
                logger.warning(
                    f"[{stage_name}] Completed state ignored because recorded outputs are missing"
                )
                self.state.set_stage_status(stage_name, "pending")
                self.approval._clear_status_files(stage_name)
            else:
                logger.info(
                    f"[{stage_name}] Already completed and approved (skip with --force to rebuild)"
                )
                strict_ok, strict_reason = self._strict_director_check(stage_name)
                if not strict_ok:
                    result = StageResult(
                        stage_name,
                        False,
                        message=strict_reason,
                        metadata={
                            "strict_director": True,
                            "strict_director_reason": strict_reason,
                            "cached_artifact": True,
                        },
                    )
                    results[stage_name] = result
                    self.state.set_stage_status(stage_name, "failed")
                    logger.error(f"[{stage_name}] Failed: {result.message}")
                    self._mark_remaining_pending(execution_order, stage_name)
                    return True
                results[stage_name] = StageResult(
                    stage_name, True, message="skipped (cached + approved)"
                )
                return False

        # Completed but still awaiting human approval: halt without re-running.
        if (
            stage_name not in force_stages
            and not self.force
            and not self.interactive
            and not self.auto_approve
            and self.state.is_completed(stage_name)
            and approval_status == "pending"
        ):
            if not self._completed_outputs_present(stage_name, stage):
                logger.warning(
                    f"[{stage_name}] Completed state ignored because recorded outputs are missing"
                )
                self.state.set_stage_status(stage_name, "pending")
                self.approval._clear_status_files(stage_name)
            else:
                approve_cmd = f"narrascape approve -p . -s {stage_name}"
                logger.info(
                    f"[{stage_name}] Completed but awaiting approval; stopping here. "
                    f"Run '{approve_cmd}' (or build with --approve) to continue."
                )
                results[stage_name] = StageResult(
                    stage_name,
                    True,
                    message=(
                        f"Awaiting approval; run '{approve_cmd}' "
                        "or build with --approve to continue."
                    ),
                    metadata={"awaiting_approval": True},
                )
                return True

        # Check prerequisites
        can_run, reason = stage.can_run(context)
        if not can_run:
            if allow_optional_skips and self._can_skip_optional_stage(stage_name, reason):
                logger.warning(f"[{stage_name}] Optional stage skipped: {reason}")
                results[stage_name] = StageResult(
                    stage_name,
                    True,
                    message=f"skipped optional stage: {reason}",
                    metadata={"optional_skipped": True, "reason": reason},
                )
                self.state.set_stage_status(stage_name, "skipped")
                if self.auto_approve:
                    self.approval.skip(stage_name, reviewer="auto", notes=reason)
                return False
            logger.error(f"[{stage_name}] Prerequisites not met: {reason}")
            results[stage_name] = StageResult(stage_name, False, message=reason)
            return True

        runnable.append((stage_name, stage))
        return False

    def _parallel_execute(
        self, stage_name: str, stage: Stage, context: StageContext
    ) -> StageResult:
        """Run one stage on a worker thread (called via ThreadPoolExecutor)."""
        self.state.set_stage_status(stage_name, "running")
        start = time.monotonic()
        try:
            self._set_active_stage(stage_name)
            result = stage.run(context)
            result.duration_seconds = time.monotonic() - start
        except Exception as exc:
            logger.exception(f"[{stage_name}] Execution failed")
            result = StageResult(
                stage_name,
                False,
                message=f"Exception: {exc}",
                duration_seconds=time.monotonic() - start,
            )
        finally:
            self._set_active_stage(None)

        if result.success:
            strict_ok, strict_reason = self._strict_director_check(stage_name)
            if not strict_ok:
                result = StageResult(
                    stage_name,
                    False,
                    outputs=result.outputs,
                    message=strict_reason,
                    duration_seconds=result.duration_seconds,
                    metadata={
                        **result.metadata,
                        "strict_director": True,
                        "strict_director_reason": strict_reason,
                    },
                )
        return result

    def _parallel_post_gates(
        self,
        runnable: list[tuple[str, Stage]],
        results: dict[str, StageResult],
        execution_order: list[str],
        context: StageContext,
    ) -> bool:
        """Apply post-execution bookkeeping in execution order. Returns True to halt.

        Unlike the serial scheduler (which stops at the first review request),
        every successful stage of the level gets a review request before the
        run halts, so no completed stage is left unreviewed.
        """
        halt = False
        for stage_name, stage in runnable:
            result = results[stage_name]
            if result.success:
                self.state.set_stage_status(stage_name, "completed")
                self.state.set_stage_outputs(stage_name, self._recordable_outputs(result))
                logger.info(f"[{stage_name}] Completed in {result.duration_seconds:.1f}s")
                if not self.auto_approve:
                    self.approval.request_review(stage_name, result)
                    logger.info(
                        f"[{stage_name}] Review required. Run: narrascape approve -p . -s {stage_name}"
                    )
                    halt = True
                else:
                    self.approval.approve(stage_name, reviewer="auto")
                    logger.info(f"[{stage_name}] Auto-approved")
            else:
                self.state.set_stage_status(stage_name, "failed")
                logger.error(f"[{stage_name}] Failed: {result.message}")
                if not getattr(stage, "continue_on_failure", False) and not halt:
                    self._mark_remaining_pending(execution_order, stage_name)
                    halt = True

        # Refresh the script context at the level boundary so later levels see
        # write/humanize output (serial does this immediately after the stage).
        if any(
            name in ("write", "humanize")
            and results[name].success
            and self.config.script_path.exists()
            for name, _ in runnable
        ):
            self.script = self._load_script()
            context.script = self.script
        return halt

    def _can_skip_optional_stage(self, stage_name: str, reason: str) -> bool:
        if self.config.pipeline.video_generation == "required":
            return False
        if stage_name == "generate_video" and self.config.pipeline.video_generation in {
            "auto",
            "off",
        }:
            return True
        if stage_name == "take_select":
            return True
        return stage_name in {"source_media", "footage_edit"}

    def _strict_director_check(self, stage_name: str) -> tuple[bool, str]:
        if not getattr(self.config.pipeline, "strict_director", False):
            return True, ""
        spec = STRICT_DIRECTOR_ARTIFACTS.get(stage_name)
        if not spec:
            return True, ""
        artifact_name, process_paths = spec
        path = self.config.pipeline_dir / artifact_name
        if not path.exists():
            return False, (
                "Strict director mode rejected "
                f"{stage_name}: missing director artifact {path.as_posix()}"
            )
        try:
            artifact = load_yaml_mapping(path)
        except Exception as exc:
            return False, (
                "Strict director mode rejected "
                f"{stage_name}: could not read {artifact_name}: {exc}"
            )

        statuses = self._director_llm_statuses(artifact, process_paths)
        blocked = [
            status for status in statuses if status.lower() in STRICT_DIRECTOR_BLOCKED_STATUSES
        ]
        if blocked:
            return False, (
                "Strict director mode rejected "
                f"{stage_name}: artifact {artifact_name} contains blocked LLM status "
                f"{', '.join(blocked)}"
            )
        if not statuses:
            return False, (
                "Strict director mode rejected "
                f"{stage_name}: artifact {artifact_name} does not expose llm_status"
            )
        return True, ""

    def _director_llm_statuses(
        self,
        artifact: dict[str, Any],
        process_paths: tuple[str, ...],
    ) -> list[str]:
        statuses: list[str] = []
        for path in process_paths:
            value: Any = artifact
            for part in path.split("."):
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(part)
            self._collect_llm_statuses(value, statuses)
        return statuses

    def _collect_llm_statuses(self, value: Any, statuses: list[str]) -> None:
        if isinstance(value, dict):
            status = value.get("llm_status")
            if status:
                statuses.append(str(status))
            for item in value.values():
                self._collect_llm_statuses(item, statuses)
        elif isinstance(value, list):
            for item in value:
                self._collect_llm_statuses(item, statuses)

    def _supervisor_next_stages(self) -> list[str]:
        path = self.config.pipeline_dir / "film_supervisor.yaml"
        if not path.exists():
            return []

        try:
            data = load_yaml_mapping(path)
        except Exception as exc:
            logger.warning(f"Could not read film_supervisor.yaml: {exc}")
            return []
        try:
            report = FilmSupervisorReport.model_validate(data)
        except ValidationError:
            # 读取侧是 advisory：老 artifact 落回裸 dict 访问
            logger.warning("film_supervisor.yaml failed typed validation; using raw access")
            if data.get("status") != "needs_rework":
                return []
            return [str(stage) for stage in data.get("next_stages", []) or []]
        if report.status != "needs_rework":
            return []
        return [str(stage) for stage in report.next_stages]

    def _recordable_outputs(self, result: StageResult) -> list[str]:
        paths: list[str] = []
        for item in self._flatten_output_values(result.outputs):
            text = str(item)
            if not text:
                continue
            path = Path(text)
            if not path.is_absolute():
                path = self.config.project_dir / path
            paths.append(str(path))
        return paths

    def _flatten_output_values(self, value: Any) -> list[str | Path]:
        if value is None:
            return []
        if isinstance(value, (str, Path)):
            return [value]
        if isinstance(value, dict):
            flattened: list[str | Path] = []
            for item in value.values():
                flattened.extend(self._flatten_output_values(item))
            return flattened
        if isinstance(value, (list, tuple, set)):
            sequence_values: list[str | Path] = []
            for item in value:
                sequence_values.extend(self._flatten_output_values(item))
            return sequence_values
        return []

    def _completed_outputs_present(self, stage_name: str, stage: Stage) -> bool:
        recorded = self.state.get_stage_outputs(stage_name)
        if recorded:
            return all(Path(path).exists() for path in recorded)
        expected = self._expected_stage_outputs(stage)
        if expected:
            return all(path.exists() for path in expected)
        return True

    def _expected_stage_outputs(self, stage: Stage) -> list[Path]:
        result: list[Path] = []
        for item in getattr(stage, "outputs", []) or []:
            text = str(item)
            if not text or text.endswith("/"):
                continue
            path = Path(text.format(name=self.config.project.name))
            if not path.is_absolute():
                path = self.config.project_dir / path
            result.append(path)
        return result

    def _filter_rerun_stages(self, stages: list[str]) -> list[str]:
        result: list[str] = []
        for stage in stages:
            if stage == "generate_video" and self.config.pipeline.video_generation == "off":
                continue
            if stage not in result:
                result.append(stage)
        return result

    def _stage_succeeded(self, results: dict[str, StageResult], stage_name: str) -> bool:
        result = results.get(stage_name)
        return bool(result and result.success)

    def _merge_cycle_results(
        self,
        results: dict[str, StageResult],
        cycle_results: dict[str, StageResult],
        cycle_index: int,
    ) -> None:
        for stage_name, result in cycle_results.items():
            key = f"cycle_{cycle_index}.{stage_name}"
            results[key] = result

    def _mark_remaining_pending(self, execution_order: list[str], failed_stage: str) -> None:
        if failed_stage not in execution_order:
            return
        failed_index = execution_order.index(failed_stage)
        for stage_name in execution_order[failed_index + 1 :]:
            self.state.set_stage_status(stage_name, "pending")
            self.state.clear_stage_outputs(stage_name)

    def status(self) -> dict[str, Any]:
        """Get current pipeline status including approval states."""
        stage_map = get_stage_map()
        approvals = self.approval.list_all()
        return {
            "project": self.config.project.name,
            "state_file": str(self.state.state_path),
            "stages": {
                name: {
                    "status": self.state.get_stage_status(name),
                    "depends_on": cls().depends_on,
                    "approval": approvals.get(name, "unknown"),
                }
                for name, cls in stage_map.items()
            },
            "segments": self.state.data.get("segments", {}),
            "approvals": approvals,
        }

    def clean(self, stages: list[str] | None = None) -> None:
        """Remove intermediate artifacts for given stages."""
        stage_map = get_stage_map()
        dirs_to_clean = []
        if stages is None or "kenburns" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "video_segments")
        if stages is None or "concat" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "gaps",
                    self.config.pipeline_dir / "body_concat.mp4",
                    self.config.pipeline_dir / "final_nosub.mp4",
                ]
            )
        if stages is None or "audio" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "mixed_audio*.mp3",
                    self.config.pipeline_dir / "narration_*.mp3",
                    self.config.output_dir / f"{self.config.project.name}-clean.mp4",
                ]
            )
        if stages is None or "subtitles" in stages:
            dirs_to_clean.append(self.config.output_dir / f"{self.config.project.name}-sub.mp4")
        if stages is None or "pre_production" in stages:
            dirs_to_clean.extend(
                [
                    self.config.project_dir / "assets" / "references" / "*.png",
                    self.config.project_dir / "assets" / "storyboard" / "*.png",
                    self.config.pipeline_dir / "pre_production.yaml",
                ]
            )
        if stages is None or "generate_images" in stages:
            dirs_to_clean.extend(
                [
                    self.config.images_dir / "*.png",
                    self.config.pipeline_dir / "image_gen_state.json",
                ]
            )
        if stages is None or "generate_video" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "video_gen_state.json",
                    self.config.pipeline_dir / "video_tasks.json",
                    self.config.pipeline_dir / "video_prompt_quality.yaml",
                    self.config.project_dir / "assets" / "videos" / "vid_*.mp4",
                ]
            )
        if stages is None or "generate_tts" in stages:
            dirs_to_clean.extend(
                [
                    self.config.tts_dir / "*.mp3",
                    self.config.pipeline_dir / "timing.json",
                    self.config.pipeline_dir / "tts_state.json",
                ]
            )
        if stages is None or "film_timeline" in stages:
            dirs_to_clean.append(self.config.project_dir / "film_timeline.yaml")
        if stages is None or "remotion_preview" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "remotion_preview.yaml",
                    self.config.pipeline_dir / "remotion_preview",
                ]
            )
        if stages is None or "film_assemble" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "timeline_segments",
                    self.config.pipeline_dir / "film_assemble.txt",
                    self.config.pipeline_dir / "film_assembled.mp4",
                ]
            )
        if stages is None or "generate_music" in stages:
            dirs_to_clean.extend(
                [
                    self.config.music_dir / "*.mp3",
                    self.config.pipeline_dir / "bgm_state.json",
                ]
            )
        if stages is None or "remix_audio" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "mixed_audio*.mp3",
                    self.config.pipeline_dir / "narration_*.mp3",
                ]
            )
        if stages is None or "qa" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "render_report.yaml")
        if stages is None or "screenplay_structure" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "screenplay_structure.yaml")
        if stages is None or "director_contract" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "director_contract.yaml")
        if stages is None or "reference_plate" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "reference_plates.yaml")
        if stages is None or "storyboard_sheet" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "storyboard_sheet.yaml",
                    self.config.pipeline_dir / "storyboard_sheet.png",
                    self.config.pipeline_dir / "storyboard_sheet.pdf",
                ]
            )
        if stages is None or "production_readiness" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "production_readiness.yaml")
        if stages is None or "animatic" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "animatic.yaml",
                    self.config.pipeline_dir / "animatic.mp4",
                    self.config.pipeline_dir / "animatic.txt",
                    self.config.pipeline_dir / "animatic_panels",
                ]
            )
        if stages is None or "continuity_bible" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "continuity_bible.yaml")
        if stages is None or "editing_review" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "editing_review.yaml")
        if stages is None or "director_review" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "director_review.yaml")
        if stages is None or "rework_plan" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "rework_plan.yaml")
        if stages is None or "creative_review" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "creative_review.yaml")
        if stages is None or "visual_semantic_qa" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "visual_semantic_report.yaml")
        if stages is None or "film_supervisor" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "film_supervisor.yaml")
        if stages is None or "assistant_handoff" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "assistant_handoff.yaml",
                    self.config.pipeline_dir / "assistant_handoff.md",
                ]
            )
        if stages is None or "rework_execute" in stages:
            dirs_to_clean.extend(
                [
                    self.config.pipeline_dir / "rework_execution.yaml",
                    self.config.pipeline_dir / "director_contract_rewrite_queue.yaml",
                    self.config.pipeline_dir / "video_regen_queue.yaml",
                    self.config.pipeline_dir / "recut_queue.yaml",
                    self.config.pipeline_dir / "source_media_replacement_queue.yaml",
                ]
            )
        if stages is None or "take_select" in stages:
            dirs_to_clean.append(self.config.pipeline_dir / "take_selection.yaml")

        for path in dirs_to_clean:
            if isinstance(path, str) and "*" in path:
                import glob

                for p in glob.glob(path):
                    Path(p).unlink(missing_ok=True)
            elif isinstance(path, Path) and "*" in str(path):
                import glob

                for p in glob.glob(str(path)):
                    Path(p).unlink(missing_ok=True)
            elif path.is_dir():
                import shutil

                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink(missing_ok=True)

        # Reset state and approvals
        for stage in stages or list(stage_map.keys()):
            self.state.set_stage_status(stage, "pending")
            self.approval._clear_status_files(stage)

        logger.info(f"Cleaned: {stages or 'all stages'}")
