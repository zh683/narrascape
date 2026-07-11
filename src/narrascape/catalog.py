from __future__ import annotations

from pathlib import Path

CORE_ARTIFACT_TEMPLATES: dict[str, str] = {
    "script": "scripts/script.yaml",
    "pre_production": "pipeline/{name}/pre_production.yaml",
    "design_report": "design_report.yaml",
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
    "assistant_handoff": "pipeline/{name}/assistant_handoff.yaml",
    "rework_execution": "pipeline/{name}/rework_execution.yaml",
}

STAGE_DOC_PATHS: dict[str, str] = {
    "animatic": "docs/agent-stages/animatic.md",
    "assistant_handoff": "docs/agent-stages/assistant_handoff.md",
    "audio": "docs/agent-stages/audio.md",
    "concat": "docs/agent-stages/concat.md",
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
    "generate_music": "docs/agent-stages/generate_music.md",
    "generate_tts": "docs/agent-stages/generate_tts.md",
    "generate_video": "docs/agent-stages/generate_video.md",
    "humanize": "docs/agent-stages/humanize.md",
    "kenburns": "docs/agent-stages/kenburns.md",
    "pre_production": "docs/agent-stages/pre_production.md",
    "production_readiness": "docs/agent-stages/production_readiness.md",
    "qa": "docs/agent-stages/qa.md",
    "reference_plate": "docs/agent-stages/reference_plate.md",
    "remix_audio": "docs/agent-stages/remix_audio.md",
    "remotion_preview": "docs/agent-stages/remotion_preview.md",
    "research": "docs/agent-stages/research.md",
    "rework_execute": "docs/agent-stages/rework_execute.md",
    "rework_plan": "docs/agent-stages/rework_plan.md",
    "screenplay_structure": "docs/agent-stages/screenplay_structure.md",
    "source_media": "docs/agent-stages/source_media.md",
    "storyboard_sheet": "docs/agent-stages/storyboard_sheet.md",
    "subtitles": "docs/agent-stages/subtitles.md",
    "take_select": "docs/agent-stages/take_select.md",
    "visual_semantic_qa": "docs/agent-stages/visual_semantic_qa.md",
    "write": "docs/agent-stages/write.md",
}

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


def repo_relative_doc_label(path: str) -> str:
    return Path(path).stem
