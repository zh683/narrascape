# Film Capability Roadmap

Narrascape's long-term target is an AI film studio: a system that can develop a
script, direct scenes, choose or generate media, cut a timeline, review the
result, and iterate toward a finished film.

## Current Foundation

Implemented now:

- AI Director shot design through `design`.
- Source-media discovery through `source_media`.
- Source-media rough cuts through `footage_edit`.
- Provider-selected generation for images, TTS, music, and Seedance video.
- Unified editorial contract through `film_timeline.yaml`.
- Timeline assembly through `film_assemble`, including generated video,
  source footage, generated-image fallback, ending cards, and gaps.
- Final render QA with subtitle, duration, silence, black-frame, repeated-shot,
  placeholder, shot coverage, missing clip, continuity, and pacing checks.
- Director rework reports through `director_review`.
- Multi-take video generation, QA/LLM take ranking, and timeline selection through
  `generate_video` and `take_select`.
- Automated rework execution through `rework_execute`, including quarantine,
  regeneration/recut/replacement queues, and bounded supervisor rerun cycles.
- A continuity bible that persists character, wardrobe, location, lighting, and
  screen-axis state and feeds review and rework.

## Film Spine

`film_timeline.yaml` is the center of the film workflow. New film-level
stages should read it, update it, or write derived reports rather than creating
isolated handoffs.

The current schema records:

- project identity
- visual clips from generated video, source media, or generated images
- narration clips
- music references
- subtitle references
- source-media/generated/missing visual coverage

## Remaining Capability Layers

1. Scene-model depth:
   Extend the implemented act, scene, sequence, shot, take, and timeline edit
   artifacts with richer blocking, lens, color, and cross-scene state.

2. Sound design:
   Add ambience, foley, effects, music cues, and mix notes as timeline tracks.

3. Finishing:
   Add color pass, titles, credits, delivery presets, and QC reports.

## Non-Goals

- Do not make another one-off renderer that ignores `film_timeline.yaml`.
- Do not treat local placeholders as production creative output.
- Do not make provider choice invisible; every generation should remain
  traceable.
