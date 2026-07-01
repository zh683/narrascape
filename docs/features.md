# Complete Feature Map

This page describes the implemented product surface as it exists in the codebase.

## Content Pipeline

- Project scaffolding with `narrascape init`.
- Topic research stage that can use an LLM or a deterministic fallback.
- Script writing stage that creates `scripts/script.yaml`.
- Humanization stage that rewrites or scores narration.
- Stage dependency resolution, so a requested target stage runs its prerequisites first.
- Persistent stage state in `pipeline/<name>/state.json`.
- Stage approval gates with `approve`, `reject`, `skip`, `status`, `--interactive`, and `--approve`.
- Default builds write a unified `film_timeline.yaml`.
- Default visual assembly is driven by `film_timeline.yaml`, not the legacy Ken Burns/concat path.
- Optional local source-media discovery and footage edit planning through `source_media`.
- Optional source-media rough-cut rendering through `footage_edit`.
- Final render QA through `qa`.
- Director rework queue through `director_review`.
- Multi-layer director workflow:
  - `screenplay_structure` splits act, scene, sequence, and shot.
  - `director_contract` compiles story intent into executable video prompts, negative prompts, continuity constraints, and QA assertions.
  - `continuity_bible` maintains character, location, wardrobe, lighting, and screen-axis continuity.
  - `storyboard_sheet` renders a product-style contact sheet for storyboard frames and director bindings.
  - `editing_review` evaluates `film_timeline.yaml` for pacing, repetition, and emotional curve.
  - `rework_plan` turns director findings into regeneration, recut, or source-media replacement actions.
  - `take_select` selects the best generated-video take when multi-take clips exist.
- Supervising director workflow:
  - `creative_review` uses an LLM when configured to review story clarity, cinematic intent, pacing, emotion, and continuity.
  - `visual_semantic_qa` uses an LLM when configured to check whether visuals match script, character, costume, scene, and shot intent.
  - `film_supervisor` reads director reports and decides the next pipeline stages.
  - `assistant_handoff` writes a Codex-readable takeover packet with required reading, artifacts, quality gates, commands, and next actions.
  - `rework_execute` applies a rework plan by quarantining failed generated clips, writing rework queues, marking affected stages pending, and feeding the automatic rerun loop.

## AI Director

- `ScriptAnalyzer` creates semantic and visual analysis for each script segment.
- `PromptDirector` designs shots when an LLM client is configured.
- Bridge-backed assistant modes batch script analysis and shot design to avoid task-file explosions.
- Offline mode uses `_design_locally()` for deterministic verification.
- Required generated-video projects cannot use `llm.mode: none`; config validation and pipeline startup fail before deterministic fallbacks can silently replace the AI Director.
- Design exports:
  - `design_report.yaml`
  - `image_prompts.yaml`
  - `image_map.yaml`
- Director-layer exports:
  - `pipeline/<project>/screenplay_structure.yaml`
  - `pipeline/<project>/director_contract.yaml`
  - `pipeline/<project>/continuity_bible.yaml`
  - `pipeline/<project>/reference_plates.yaml`
  - `pipeline/<project>/storyboard_sheet.yaml`
  - `pipeline/<project>/storyboard_sheet.png`
  - `pipeline/<project>/storyboard_sheet.pdf`
  - `pipeline/<project>/animatic.yaml`
  - `pipeline/<project>/production_readiness.yaml`
  - `pipeline/<project>/editing_review.yaml`
  - `pipeline/<project>/rework_plan.yaml`
  - `pipeline/<project>/take_selection.yaml`
  - `pipeline/<project>/creative_review.yaml`
  - `pipeline/<project>/visual_semantic_report.yaml`
  - `pipeline/<project>/film_supervisor.yaml`
  - `pipeline/<project>/assistant_handoff.yaml`
  - `pipeline/<project>/assistant_handoff.md`
  - `pipeline/<project>/rework_execution.yaml`
- Each LLM shot design carries:
  - `director_vision`
  - `cinematic_format`
  - `image_prompt`
  - `negative_prompt`
  - shot type, movement, emotion, intensity, and metadata.

## Pre-Production

- Character and environment extraction from the script.
- Style anchor generation.
- Character reference sheet structure.
- Environment reference structure.
- Storyboard model for per-segment visual guidance.
- Export to `pipeline/<name>/pre_production.yaml`.
- Design stage loads pre-production data when available.

## Image Generation

- Seedream provider path with prompt metadata and reference-image fields.
- Local provider that creates deterministic PNG placeholders for offline end-to-end tests.
- Provider selector is executed before generation and records the selected provider in `image_gen_state.json`.
- Per-prompt fields:
  - `shot_type`
  - `movement`
  - `size`
  - `description`
  - `reference_image_url`
  - `reference_images`
  - `seedream_model`
  - `seedream_sample_strength`
  - `negative_prompt`
- Image map supports single-image and multi-image segment mappings.

## Video Generation

- Configurable Seedance async task workflow through `pipeline.video_generation` and `video.provider`.
- Uses generated images as first frames when available.
- Uses `pipeline/<project>/director_contract.yaml` prompts when available, so director intent reaches the video provider instead of remaining review-only metadata.
- Writes `video_prompt_quality.yaml` with per-shot ingredient scores for subject, action, scene, wardrobe, camera language, composition, lighting, style, and reference binding.
- Blocks provider calls when prompts are still generic or missing the executable ingredients needed for controllable video generation.
- Supports model mapping from internal names to Volcengine Ark IDs.
- Persists video generation state for resumability.
- Provider selector is executed before generation and records the selected video provider and requirements.
- `video.takes` can ask `generate_video` to create multiple `vid_<segment>_take_<take>.mp4` candidates per shot.
- `take_select` chooses among those candidates, using an LLM judge when configured and deterministic QA proxy scoring otherwise.
- The default `pipeline.video_generation: auto` path includes `generate_video` and `take_select`; missing credentials or missing multi-take clips are skipped so the build can continue through fallback visuals. `required` makes generated video blocking, and `off` removes those stages.

## Source Media

- `SourceMediaStage` scans `source_media/`.
- It writes a canonical `asset_manifest.yaml`.
- It writes `footage_timeline.yaml` with edit decisions for footage-first documentary cuts.
- Local media entries include id, path, type, provider, source, license, and metadata.
- Video metadata is probed when ffprobe is available.
- The timeline maps each asset to a target segment, source in/out, edit duration, role, and transition.
- `FootageEditStage` reads the timeline, renders normalized source-media segments, and concatenates `footage_roughcut.mp4`.

## Film Timeline

- `FilmTimelineStage` writes `film_timeline.yaml` in the default build.
- The timeline combines script segments, AI Director metadata, generated video clips, source footage, generated images, narration clips, music references, and subtitles.
- Visual selection priority is generated video, source media, then generated-image fallback.
- When `pipeline/<project>/take_selection.yaml` exists, selected multi-take clips override the base generated-video clip for that segment.
- Coverage metadata records generated-video segments, source-media segments, generated-image segments, and missing visual segments.
- `RemotionPreviewStage` exports `pipeline/<project>/remotion_preview/` from the same timeline for visual inspection and future web rendering.
- `FilmAssembleStage` renders the timeline into `pipeline/<project>/film_assembled.mp4`.
- Timeline assembly handles generated videos, source footage, generated-image fallback, ending cards, and explicit time gaps.
- This artifact is the center for smart editing, director review, sound design, and color workflows.

## Audio

- TTS stage creates per-segment narration files and timing metadata.
- Local TTS provider creates deterministic MP3 tones for offline tests.
- TTS provider selection is recorded in `tts_state.json`.
- Music stage creates configured BGM zones.
- Local music provider creates deterministic BGM audio.
- Music provider selection is recorded in `bgm_state.json`.
- Remix stage combines narration and BGM with sidechain and loudness settings.
- Audio stage attaches the mixed audio to `film_assembled.mp4`, with a legacy fallback to `final_nosub.mp4`.

## Motion And Final Render

- Default film timeline rendering through `film_assemble`, with `remotion_preview` generated first as an inspectable timeline handoff.
- Optional Ken Burns rendering from generated still images.
- Shot type and movement mapping.
- Three motion engines:
  - ffmpeg zoompan
  - ffmpeg crop/pan
  - PIL float-pixel rendering for hard-edge images
- Auto hard-edge detection.
- Segment rendering cache.
- Optional concat stage for legacy Ken Burns visual segments.
- Subtitle stage generates and burns subtitles.
- QA stage validates the final subtitled video and writes `render_report.yaml`.
- QA checks include file validity, streams, subtitles, duration drift, silence, black-frame risk, repeated shots, placeholder residue, shot coverage, missing generated-video clips, missing timeline video files, continuity risk, and pacing risk.
- Director review writes `director_review.yaml` and marks failed shots for regeneration or recut.
- `continuity_bible`, `editing_review`, and `rework_plan` complete the director loop after QA by preserving continuity context, diagnosing edit rhythm, and grouping executable rework actions.
- `creative_review` and `visual_semantic_qa` add LLM-assisted creative and semantic review when an LLM client is configured, with deterministic metadata fallback for offline verification.
- `film_supervisor` is the default supervising report: it reads the director artifacts and returns the next stages to run.
- `assistant_handoff` turns the supervisor decision into a project takeover packet for AI assistants such as Codex.
- In the default build, `pipeline.auto_rework: true` lets `film_supervisor` trigger `rework_execute` automatically when it reports `needs_rework`.
- `rework_execute` safely moves invalid generated videos to `pipeline/<project>/rework_quarantine/`, writes `video_regen_queue.yaml`, `recut_queue.yaml`, and `source_media_replacement_queue.yaml`, resets affected stage state, and lets the pipeline rerun the requested stages up to `pipeline.max_rework_cycles`. `director_contract` and `generate_video` consume their queues so rewrites and provider calls are limited to queued segments.

## Production AI-Film Profile

- `narrascape build --production` applies the `seedream-seedance-oil-painting` runtime profile.
- The profile selects Seedream for images, Seedance for video, oil-painting visual style, required video generation, strict director mode, production quality gates, at least three video takes, and two automatic rework cycles.
- `pipeline.production_quality_gates: true` makes `production_readiness` check script density, pre-production character/scene/storyboard coverage, storyboard bindings, director-contract continuity locks, prompt blueprints, compiled prompts, and QA assertions before generated video starts.
- `generation.prompt_blueprint` is written into each director-contract shot and copied into `reference_plates.yaml`, giving future visual QA a structured contract instead of only a natural-language prompt.
- `examples/golden-sample` is the fixed quality benchmark for this profile.

## Product Dashboard

- Streamlit dashboard includes a Timeline page for `film_timeline.yaml`.
- The page shows clip count, duration, generated-video coverage, source mix, missing media, and Remotion preview status.
- It exposes the generated Remotion Studio, still-check, and render commands from `remotion_preview.yaml`.
- Install dashboard dependencies with `pip install -e ".[dashboard]"` or `pip install -e ".[dev]"`.

## Provider Governance

- Provider registry reports configured and local providers.
- Provider selector scores candidates by task fit, quality, control, reliability, cost efficiency, latency, and continuity.
- Provider selector is wired into `generate_images`, `generate_tts`, `generate_music`, and `generate_video`.
- Canonical artifact validation exists for `asset_manifest`, `assistant_handoff`, `design_report`, `film_timeline`, `remotion_preview`, `render_report`, `screenplay_structure`, `director_contract`, `continuity_bible`, `editing_review`, `rework_plan`, `take_selection`, `creative_review`, `visual_semantic_report`, `film_supervisor`, `rework_execution`, and `storyboard_sheet`.
- Composition runtime registry exposes `ffmpeg` now and reserves a Remotion integration surface.

## Cache And Rebuilds

- Content-hash cache under `pipeline/<name>/.cache`.
- Stage state tracking.
- `--force` bypasses cached stage completion.
- `clean` can remove stage artifacts or all pipeline outputs.

## Dashboard

- `narrascape dashboard` launches a local control panel for project inspection and command execution.

## Provider Matrix

| Area | Implemented paths |
| --- | --- |
| LLM | AI assistant bridge, file bridge, OpenAI-compatible APIs, Anthropic, DeepSeek, Volcengine, local HTTP chat |
| Images | Seedream, local placeholder |
| Video | Seedance async task API |
| TTS | MiniMax, local tone provider |
| Music | MiniMax, local tone provider |
| Rendering | ffmpeg, PIL |
| Source media | local media library, footage timeline, rough-cut render |
| QA | ffprobe-backed render and quality validation |

## Intentional Offline Fallbacks

Offline fallbacks are not production creativity features. They exist so the whole pipeline can be verified without network access or API keys:

- `llm.mode: none`
- `images.provider: local`
- `tts.provider: local`
- `audio.music.provider: local`

Use LLM and media providers for real creative output.
