from __future__ import annotations

from pathlib import Path
from typing import Any

CORE_ARTIFACT_TEMPLATES: dict[str, str] = {
    "script": "scripts/script.yaml",
    "pre_production": "pipeline/{name}/pre_production.yaml",
    "design_report": "pipeline/{name}/design_report.yaml",
    "screenplay_structure": "pipeline/{name}/screenplay_structure.yaml",
    "director_contract": "pipeline/{name}/director_contract.yaml",
    "reference_plates": "pipeline/{name}/reference_plates.yaml",
    "storyboard_sheet": "pipeline/{name}/storyboard_sheet.yaml",
    "animatic": "pipeline/{name}/animatic.yaml",
    "production_readiness": "pipeline/{name}/production_readiness.yaml",
    "video_prompt_quality": "pipeline/{name}/video_prompt_quality.yaml",
    "take_selection": "pipeline/{name}/take_selection.yaml",
    "film_timeline": "film_timeline.yaml",
    "render_report": "pipeline/{name}/render_report.yaml",
    "continuity_bible": "pipeline/{name}/continuity_bible.yaml",
    "editing_review": "pipeline/{name}/editing_review.yaml",
    "director_review": "pipeline/{name}/director_review.yaml",
    "rework_plan": "pipeline/{name}/rework_plan.yaml",
    "creative_review": "pipeline/{name}/creative_review.yaml",
    "visual_semantic_report": "pipeline/{name}/visual_semantic_report.yaml",
    "film_supervisor": "pipeline/{name}/film_supervisor.yaml",
    "cost_report": "pipeline/{name}/cost_report.yaml",
    "assistant_handoff": "pipeline/{name}/assistant_handoff.yaml",
    "rework_execution": "pipeline/{name}/rework_execution.yaml",
}

STAGE_DOC_PATHS: dict[str, str] = {
    "animatic": "docs/agent-stages/animatic.md",
    "assistant_handoff": "docs/agent-stages/assistant_handoff.md",
    "continuity_bible": "docs/agent-stages/continuity_bible.md",
    "creative_review": "docs/agent-stages/creative_review.md",
    "design": "docs/agent-stages/design.md",
    "director_contract": "docs/agent-stages/director_contract.md",
    "director_review": "docs/agent-stages/director_review.md",
    "editing_review": "docs/agent-stages/editing_review.md",
    "film_assemble": "docs/agent-stages/film_assemble.md",
    "film_supervisor": "docs/agent-stages/film_supervisor.md",
    "film_timeline": "docs/agent-stages/film_timeline.md",
    "footage_edit": "docs/agent-stages/footage_edit.md",
    "generate_images": "docs/agent-stages/generate_images.md",
    "generate_video": "docs/agent-stages/generate_video.md",
    "production_readiness": "docs/agent-stages/production_readiness.md",
    "qa": "docs/agent-stages/qa.md",
    "reference_plate": "docs/agent-stages/reference_plate.md",
    "remotion_preview": "docs/agent-stages/remotion_preview.md",
    "rework_execute": "docs/agent-stages/rework_execute.md",
    "rework_plan": "docs/agent-stages/rework_plan.md",
    "screenplay_structure": "docs/agent-stages/screenplay_structure.md",
    "source_media": "docs/agent-stages/source_media.md",
    "storyboard_sheet": "docs/agent-stages/storyboard_sheet.md",
    "take_select": "docs/agent-stages/take_select.md",
    "visual_semantic_qa": "docs/agent-stages/visual_semantic_qa.md",
}

# ───────────────────────────────────────────
# Rework chains (single source of truth)
# ───────────────────────────────────────────
#
# Consumed by BOTH film_supervisor._next_stages (decision: what the supervisor
# asks the pipeline to rerun) and rework_execute._stages_to_rerun (execution:
# which stages are marked pending). The two must never drift again — extend
# these constants, do not fork the lists.

# Rework action type -> upstream chain to rerun for that action.
REWORK_ACTION_CHAINS: dict[str, list[str]] = {
    "rewrite_director_contract": [
        "director_contract",
        "reference_plate",
        "generate_images",
        "animatic",
        "generate_video",
        "take_select",
        "film_timeline",
    ],
    "regenerate_video": ["generate_video", "take_select", "film_timeline"],
    "replace_source_media": ["source_media", "film_timeline"],
    "recut": ["film_timeline", "remotion_preview", "film_assemble"],
}

# Tail appended whenever any rework reruns: re-render, re-review, re-decide,
# and refresh the assistant takeover packet. assistant_handoff is part of the
# chain (the film_supervisor decision is authoritative): after any rework the
# handoff packet must reflect the reworked state.
REWORK_TAIL_STAGES: list[str] = [
    "remotion_preview",
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
    "assistant_handoff",
]

STAGE_INTENTS: dict[str, str] = {
    "rework_execute": "apply queued regeneration, recut, or media replacement actions",
    "director_contract": "rewrite executable shot contracts",
    "reference_plate": "refresh per-shot reference handoff",
    "generate_images": "regenerate still references or fallback images",
    "storyboard_sheet": "refresh the storyboard review sheet",
    "animatic": "refresh storyboard timing preview",
    "production_readiness": "verify preparation before generated-video production",
    "generate_video": "regenerate queued AI video clips",
    "take_select": "choose the best generated-video take",
    "film_timeline": "rebuild editorial spine",
    "remotion_preview": "refresh inspectable timeline preview",
    "film_assemble": "assemble the film timeline into video",
    "audio": "attach mixed audio to assembled film",
    "subtitles": "burn or generate subtitles",
    "qa": "validate final render and film-quality risks",
    "continuity_bible": "refresh continuity state",
    "editing_review": "review rhythm, repetition, and pacing",
    "director_review": "convert QA failures into shot-level rework",
    "rework_plan": "group rework actions",
    "creative_review": "judge story and cinematic quality",
    "visual_semantic_qa": "check visual semantics against the director contract",
    "film_supervisor": "decide the next production cycle",
    "assistant_handoff": "refresh the AI assistant takeover packet",
}


def core_artifact_templates() -> dict[str, str]:
    return dict(CORE_ARTIFACT_TEMPLATES)


def stage_doc_path(stage_name: str) -> str:
    return STAGE_DOC_PATHS.get(stage_name, "")


def stage_doc_paths(stage_names: list[str]) -> list[str]:
    paths: list[str] = []
    seen = set()
    for stage_name in stage_names:
        path = stage_doc_path(stage_name)
        if path and path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


def stage_intent(stage_name: str) -> str:
    return STAGE_INTENTS.get(stage_name, f"run {stage_name}")


# ───────────────────────────────────────────
# Clean targets (single source of truth)
# ───────────────────────────────────────────
#
# Consumed by Pipeline.clean — the per-stage deletion set is derived here,
# not hand-maintained next to the executor. Two layers:
#
#   STAGE_CLEAN_ARTIFACTS — stage -> keys of CORE_ARTIFACT_TEMPLATES. The
#       resolved path comes from the template itself, so a template change
#       moves the clean set with it (no drift).
#   STAGE_CLEAN_EXTRAS — targets that are not catalog artifacts: directories
#       (trailing "/" = recursive removal), glob patterns ("*"), stage-local
#       state files, and rendered outputs under output/.
#
# All templates are project-dir-relative; "{name}" is the project name
# (pipeline dir and output file prefixes).

STAGE_CLEAN_ARTIFACTS: dict[str, list[str]] = {
    "pre_production": ["pre_production"],
    "screenplay_structure": ["screenplay_structure"],
    "director_contract": ["director_contract"],
    "reference_plate": ["reference_plates"],
    "storyboard_sheet": ["storyboard_sheet"],
    "production_readiness": ["production_readiness"],
    "animatic": ["animatic"],
    "generate_video": ["video_prompt_quality"],
    "take_select": ["take_selection"],
    "film_timeline": ["film_timeline"],
    "qa": ["render_report"],
    "continuity_bible": ["continuity_bible"],
    "editing_review": ["editing_review"],
    "director_review": ["director_review"],
    "rework_plan": ["rework_plan"],
    "creative_review": ["creative_review"],
    "visual_semantic_qa": ["visual_semantic_report"],
    "film_supervisor": ["film_supervisor"],
    "assistant_handoff": ["assistant_handoff"],
    "rework_execute": ["rework_execution"],
}

STAGE_CLEAN_EXTRAS: dict[str, list[str]] = {
    "kenburns": ["pipeline/{name}/video_segments/"],
    "concat": [
        "pipeline/{name}/gaps/",
        "pipeline/{name}/body_concat.mp4",
        "pipeline/{name}/final_nosub.mp4",
    ],
    "audio": [
        "pipeline/{name}/mixed_audio*.mp3",
        "pipeline/{name}/narration_*.mp3",
        "output/{name}-clean.mp4",
    ],
    "subtitles": ["output/{name}-sub.mp4"],
    "pre_production": ["assets/references/*.png", "assets/storyboard/*.png"],
    "generate_images": ["assets/images/*.png", "pipeline/{name}/image_gen_state.json"],
    "generate_video": [
        "pipeline/{name}/video_gen_state.json",
        "pipeline/{name}/video_tasks.json",
        "assets/videos/vid_*.mp4",
    ],
    "generate_tts": [
        "assets/tts/*.mp3",
        "pipeline/{name}/timing.json",
        "pipeline/{name}/tts_state.json",
    ],
    "remotion_preview": [
        "pipeline/{name}/remotion_preview.yaml",
        "pipeline/{name}/remotion_preview/",
    ],
    "film_assemble": [
        "pipeline/{name}/timeline_segments/",
        "pipeline/{name}/film_assemble.txt",
        "pipeline/{name}/film_assembled.mp4",
    ],
    "generate_music": ["assets/music/*.mp3", "pipeline/{name}/bgm_state.json"],
    "remix_audio": ["pipeline/{name}/mixed_audio*.mp3", "pipeline/{name}/narration_*.mp3"],
    "storyboard_sheet": [
        "pipeline/{name}/storyboard_sheet.png",
        "pipeline/{name}/storyboard_sheet.pdf",
    ],
    "animatic": [
        "pipeline/{name}/animatic.mp4",
        "pipeline/{name}/animatic.txt",
        "pipeline/{name}/animatic_panels/",
    ],
    "assistant_handoff": ["pipeline/{name}/assistant_handoff.md"],
    "rework_execute": [
        "pipeline/{name}/director_contract_rewrite_queue.yaml",
        "pipeline/{name}/video_regen_queue.yaml",
        "pipeline/{name}/recut_queue.yaml",
        "pipeline/{name}/source_media_replacement_queue.yaml",
    ],
}


def stage_clean_targets(stage_name: str) -> list[str]:
    """Project-dir-relative clean-target templates for one stage.

    Catalog-artifact paths are resolved from CORE_ARTIFACT_TEMPLATES at call
    time; extras (directories, globs, state files) are appended verbatim.
    Unknown stages return an empty list — clean still resets their status.
    """
    targets = [CORE_ARTIFACT_TEMPLATES[key] for key in STAGE_CLEAN_ARTIFACTS.get(stage_name, [])]
    targets.extend(STAGE_CLEAN_EXTRAS.get(stage_name, []))
    return targets


def design_report_candidates(config: Any) -> list[Path]:
    """Lookup order for ``design_report.yaml``: pipeline dir first, project dir second.

    The design stage writes the report to ``pipeline/<name>/design_report.yaml``
    (see ``stages/design.py``); a file at the project dir root is a stale copy
    left by older versions. Readers must prefer the pipeline-dir copy — the
    opposite order can silently pick up an outdated design. Keep every reader
    on this single ordering.
    """
    return [
        config.pipeline_dir / "design_report.yaml",
        config.project_dir / "design_report.yaml",
    ]


def repo_relative_doc_label(path: str) -> str:
    return Path(path).stem
