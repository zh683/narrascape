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

## Film Spine

`film_timeline.yaml` is the center of the future film workflow. New film-level
stages should read it, update it, or write derived reports rather than creating
isolated handoffs.

The current schema records:

- project identity
- visual clips from generated video, source media, or generated images
- narration clips
- music references
- subtitle references
- source-media/generated/missing visual coverage

## Next Capability Layers

1. Scene model:
   Add `act`, `scene`, `shot`, `take`, and `edit` concepts above script
   segments.

2. Multi-take generated-video integration:
   Support several generated takes per shot, rank them by QA and director
   preference, then keep the selected take in `film_timeline.yaml`.

3. Automated rework execution:
   Turn `director_review.yaml` queues into repeatable regenerate/recut runs,
   with human approval before replacing timeline clips.

4. Continuity bible:
   Persist character, wardrobe, location, lighting, lens, color, and style rules
   across scenes and generated media.

5. Sound design:
   Add ambience, foley, effects, music cues, and mix notes as timeline tracks.

6. Finishing:
   Add color pass, titles, credits, delivery presets, and QC reports.

## Non-Goals

- Do not make another one-off renderer that ignores `film_timeline.yaml`.
- Do not treat local placeholders as production creative output.
- Do not make provider choice invisible; every generation should remain
  traceable.
