# Architecture

This document describes the current code architecture. For product-level design, see [System Design](design.md).

## Modules

```text
src/narrascape/
  cli.py                 Typer CLI and command wiring
  config.py              Pydantic config and project file models
  pipeline.py            Stage graph, dependency resolution, state handling
  pipeline_approval.py   Human review gates
  cache.py               Content-hash artifact cache
  agent/                 AI Director models and PromptDirector
  llm/                   LLM clients, bridge transport, prompt templates, validators
  providers/             Provider registry, selector scoring, execution helpers
  artifacts.py           Lightweight canonical artifact validation
  compose.py             Composition runtime selection surface
  stages/                Pipeline stages
  motion/                Ken Burns and crop/zoom/PIL render engines
  uploader/              Reference image upload helpers
  utils/                 ffmpeg, retry, budget helpers
```

## Stage Registry

`pipeline.py` registers stages in this order:

```text
research
write
humanize
source_media
footage_edit
pre_production
design
screenplay_structure
director_contract
reference_plate
storyboard_sheet
generate_images
animatic
generate_video
take_select
generate_tts
film_timeline
film_assemble
generate_music
remix_audio
kenburns
concat
audio
subtitles
qa
continuity_bible
editing_review
director_review
rework_plan
creative_review
visual_semantic_qa
film_supervisor
rework_execute
```

The default full build intentionally excludes `research`, `write`, `humanize`,
`source_media`, and `footage_edit` unless needed or requested. Generated video is
controlled by `pipeline.video_generation`: `auto` includes `generate_video` and
`take_select` but skips them when credentials or multi-take clips are missing;
`required` makes generated-video coverage blocking; `off` omits those stages.

Default full build:

```text
pre_production -> design -> screenplay_structure -> director_contract -> reference_plate
-> generate_images -> animatic -> generate_video -> take_select -> generate_tts -> film_timeline
-> remotion_preview
-> film_assemble -> generate_music -> remix_audio -> audio -> subtitles -> qa
-> continuity_bible -> editing_review -> director_review -> rework_plan
-> creative_review -> visual_semantic_qa -> film_supervisor
-> rework_execute -> supervisor requested rerun stages (when rework is needed)
```

If the script file is missing, `research` and `write` are prepended. If a research report already exists, only `write` is prepended.

`pipeline.auto_rework` defaults to true. When `film_supervisor.yaml` reports
`status: needs_rework`, the default build runs `rework_execute`, then reruns the
supervisor's `next_stages` for up to `pipeline.max_rework_cycles` cycles.

## Dependencies

| Stage | Depends on |
| --- | --- |
| `research` | none |
| `write` | none |
| `humanize` | none |
| `source_media` | none |
| `footage_edit` | `source_media` |
| `pre_production` | none |
| `design` | `pre_production` |
| `screenplay_structure` | `design` |
| `director_contract` | `screenplay_structure` |
| `reference_plate` | `director_contract` |
| `storyboard_sheet` | `reference_plate`, `generate_images` |
| `film_timeline` | `design`, `generate_images`, `generate_tts` |
| `remotion_preview` | `film_timeline` |
| `film_assemble` | `remotion_preview` |
| `generate_images` | `design` |
| `animatic` | `reference_plate`, `generate_images` |
| `generate_video` | `animatic`, `generate_images` |
| `take_select` | `generate_video` |
| `generate_tts` | none |
| `generate_music` | `generate_tts` |
| `remix_audio` | `generate_tts`, `generate_music` |
| `kenburns` | `generate_images`, `generate_tts` |
| `concat` | `kenburns` |
| `audio` | `film_assemble`, `remix_audio` |
| `subtitles` | `audio` |
| `qa` | `subtitles` |
| `continuity_bible` | `screenplay_structure`, `film_timeline` |
| `editing_review` | `qa` |
| `director_review` | `qa` |
| `rework_plan` | `director_review`, `editing_review`, `continuity_bible` |
| `creative_review` | `editing_review`, `continuity_bible` |
| `visual_semantic_qa` | `qa` |
| `film_supervisor` | `rework_plan`, `creative_review`, `visual_semantic_qa` |
| `rework_execute` | `rework_plan` |

`_resolve_dependencies()` expands requested targets with transitive dependencies and performs a topological sort.

## Pipeline Runtime

`Pipeline.run()` does the following:

1. Determines target stages.
2. Adds `research`/`write` if no script exists.
3. Resolves dependencies.
4. Builds a `StageContext`.
5. For each stage:
   - checks existing approval state
   - skips already completed and approved stages unless `--force`
   - runs `can_run()`
   - executes `run()`
   - marks stage completed or failed
   - reloads the script after `write` or `humanize`
   - creates or checks approval state

## State Files

```text
pipeline/<project>/state.json
pipeline/<project>/approvals/
pipeline/<project>/.cache/
pipeline/<project>/budget_state.json
pipeline/<project>/video_gen_state.json
pipeline/<project>/render_report.yaml
```

`state.json` stores stage completion. Approval files store human review state. The cache stores content-addressed rendered artifacts.

## LLM Client

`llm/client.py` exposes a unified `LLMClient`.

Provider paths:

- `openai`, `deepseek`, `volcengine`: OpenAI-compatible chat completions.
- `anthropic`: Anthropic messages API.
- `local`: local HTTP chat endpoint.
- `ai_assistant`, `bridge`: file-based bridge tasks.

`complete(prompt, json_mode=True)` is used by batch bridge analysis and design. `run_template_validated(...)` is used when a stage needs structured prompt construction and output validation.

Bridge-backed providers do not retry automatically because retrying would create duplicate pending task files.

## AI Director

`DesignStage` controls the first LLM/local split:

- It always creates `ScriptAnalyzer(llm_client=...)`.
- If `llm_client` exists, it calls `PromptDirector.design_sequence(...)`.
- If `llm_client` is missing, it calls `_design_locally(...)`.

In bridge-backed modes:

- `ScriptAnalyzer` analyzes all script segments in one task.
- `PromptDirector` designs all shots in one task.

This keeps assistant workflows manageable.

The post-design director layers are implemented as regular stages:

- `ScriptSceneDirectorStage` writes `screenplay_structure.yaml`.
- `DirectorContractStage` writes `director_contract.yaml`.
- `ReferencePlateStage` writes `reference_plates.yaml`.
- `StoryboardSheetStage` writes `storyboard_sheet.yaml`, `storyboard_sheet.png`, and `storyboard_sheet.pdf`.
- `AnimaticStage` writes `animatic.yaml` and `animatic.mp4`.
- `ContinuityBibleStage` writes `continuity_bible.yaml`.
- `EditingReviewStage` writes `editing_review.yaml`.
- `ReworkPlanStage` writes `rework_plan.yaml`.
- `TakeSelectStage` writes `take_selection.yaml`.
- `CreativeReviewStage` writes `creative_review.yaml`.
- `VisualSemanticQAStage` writes `visual_semantic_report.yaml`.
- `FilmSupervisorStage` writes `film_supervisor.yaml`.
- `ReworkExecuteStage` writes `rework_execution.yaml` plus concrete rework queues.

Some layers are deterministic by default, but they consume LLM-authored design
fields when an LLM director was used. `DirectorContractStage`, `take_select`,
`creative_review`, and `visual_semantic_qa` receive the pipeline LLM client when
available and make real LLM calls; without it, they fall back to deterministic
checks.

## Pre-Production

`PreProductionStage` prepares visual context before shot design:

- style anchor
- character references
- environment references
- storyboard data

The exported YAML is loaded by `DesignStage` when available, then used to enrich shot prompts and references.

## Media Stages

`GenerateImagesStage` selects an image provider, reads `image_prompts.yaml`, and writes `assets/images/*.png`.

`GenerateTTSStage` selects a TTS provider, reads script segments, and writes narration audio plus timing data.

`GenerateMusicStage` selects a music provider, reads `bgm_map.zones`, and writes BGM files.

`ReferencePlateStage` turns the director contract and pre-production assets into
per-shot reference plates. Each plate records storyboard frame ids, expected
reference ids, resolved style/character/scene assets, missing references,
compiled provider prompts, provider negative prompts, and QA requirements.

`AnimaticStage` renders a cheap storyboard timing preview from generated stills
and storyboard duration hints. It blocks when a required panel source image is
missing, so expensive generated-video calls do not start before the storyboard
has a reviewable visual rhythm.

`StoryboardSheetStage` renders a product-style storyboard contact sheet and
keeps it inspectable as a review surface. It is not a hard gate by itself, but
it captures the director bindings that feed the next production gate.

`ProductionReadinessStage` is the final pre-video gate. It reads
`reference_plates.yaml`, `storyboard_sheet.yaml`, and `animatic.yaml`, then
blocks `generate_video` unless those prep artifacts are all `status: ready`.
With `pipeline.video_generation: required`, a failed gate fails the stage. With
the default `auto` policy, the report still records `status: blocked`, but the
stage succeeds so the pipeline can skip generated video and continue through
source footage or generated-image fallback.

`GenerateVideoStage` selects the video provider and runs the selected provider
task workflow when requested. When `director_contract.yaml` exists, it prefers
`generation.compiled_prompts.<provider>.prompt` plus the matching negative
prompt; otherwise it falls back to `generation.video_prompt` and then legacy
design-report prompt construction. Contract prompts include storyboard frame
ids, scene reference, wardrobe lock, character positions, and composition
requirements when pre-production storyboard data is available. The stage reads
`reference_plates.yaml` as its resolved reference handoff and runs after the
animatic preview before uploading references to the selected provider. It also
writes `video_prompt_quality.yaml` and blocks provider execution when a compiled
prompt still looks like a template or lacks executable video ingredients such as
subject, action, scene, wardrobe, camera language, composition, lighting, style,
or reference binding. The same report also records overloaded camera-motion
risks so rework can simplify a shot before another provider call.
When `video.takes > 1`, `GenerateVideoStage` writes
`vid_<segment>_take_<take>.mp4` variants and records them in
`video_gen_state.json`. `TakeSelectStage` selects among those variants and writes
the selected take for `FilmTimelineStage`. The pipeline factory injects the LLM
client when available, so take selection can use QA evidence plus an LLM judge;
otherwise it falls back to deterministic QA proxy scoring.

`FilmTimelineStage` writes `film_timeline.yaml`, unifying director shot data,
generated videos, source footage, generated imagery, narration clips, music
references, and subtitle references into one editorial timeline. Visual priority
is `generated_video`, then `source_media`, then `generated_image`. If
`take_selection.yaml` exists, the selected take is used as that segment's
generated video.

`RemotionPreviewStage` reads the same `film_timeline.yaml` and exports
`pipeline/<project>/remotion_preview/`, a minimal Remotion project with copied
timeline assets, `public/timeline.json`, and a React composition. This is the
visual inspection and future web-rendering handoff; it does not replace the
default FFmpeg assembly path yet.

`FilmAssembleStage` reads `film_timeline.yaml`, renders the visual track into
`pipeline/<project>/timeline_segments/`, inserts black timeline gaps when clip
start times require them, and concatenates the track into
`pipeline/<project>/film_assembled.mp4`.

`AudioRemixStage` combines TTS and music.

`KenBurnsStage` renders visual segments from generated images and TTS durations.

`AudioStage` muxes `film_assembled.mp4` with the remixed audio. It can still
fall back to the old `final_nosub.mp4` when explicitly running legacy stages.
`SubtitleStage` burns subtitles into the clean output.

`QAStage` validates the final subtitled video and writes `render_report.yaml`.
It checks media validity, streams, subtitle artifacts, duration drift, silence,
unexpected black frames, repeated shots, placeholder residue, shot coverage,
missing generated-video clips, continuity risk, and pacing risk.

`DirectorReviewStage` reads `render_report.yaml` and writes
`director_review.yaml`. Failed shots are queued for `regenerate_video` or
`recut` actions. QA is allowed to fail and still pass control to
`director_review` so the rework loop has a report to consume.

`ContinuityBibleStage`, `EditingReviewStage`, and `ReworkPlanStage` extend that
loop into film-direction artifacts: continuity state, timeline rhythm review,
prompt-quality repair, and an executable rework plan grouped by action type.

`CreativeReviewStage` and `VisualSemanticQAStage` add LLM-assisted review for
creative coherence and visual semantic match. `VisualSemanticQAStage` includes
`director_contract.yaml` in the LLM payload and checks contract assertions in
fallback mode. Its fallback checks also compare storyboard-bound scene,
wardrobe, character-position, and composition metadata when present.
`FilmSupervisorStage` reads those reports and outputs the next stages to run.
For `rewrite_director_contract` actions, it requests the full creative
regeneration chain from `director_contract` through `film_timeline` before the
downstream QA/review stages.
`ReworkExecuteStage` is an explicit stage that applies a plan by quarantining
failed generated clips, writing `video_regen_queue.yaml`, `recut_queue.yaml`,
`director_contract_rewrite_queue.yaml`, and
`source_media_replacement_queue.yaml`, then marking affected pipeline stages
pending.

`SourceMediaStage` is optional and writes `asset_manifest.yaml` plus
`footage_timeline.yaml` from local files under `source_media/`.

`FootageEditStage` is optional and renders `footage_roughcut.mp4` from the
source-media timeline.

## Provider Governance

`providers/registry.py` describes available provider tools. `providers/selector.py`
scores candidates by task fit, quality, control, reliability, cost efficiency,
latency, and continuity. `providers/execution.py` is the stage-facing helper for
selecting and serializing provider decisions.

The image, TTS, music, and video generation stages call this layer before
execution and persist `provider_selection` in their state files.

## Offline Providers

Offline providers are intentionally deterministic:

- local images: placeholder PNGs
- local TTS: generated MP3 tones
- local music: generated MP3 tones
- no LLM: deterministic shot design

These are used for testability and end-to-end verification.
