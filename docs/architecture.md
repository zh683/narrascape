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
  contracts/             Typed pydantic schemas for the core stage contracts
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
generate_images
storyboard_sheet
animatic
production_readiness
generate_video
take_select
generate_tts
film_timeline
remotion_preview
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
assistant_handoff
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
-> generate_images -> storyboard_sheet -> animatic -> production_readiness
-> generate_video -> take_select -> generate_tts -> film_timeline
-> remotion_preview -> film_assemble -> generate_music -> remix_audio -> audio -> subtitles -> qa
-> continuity_bible -> editing_review -> director_review -> rework_plan
-> creative_review -> visual_semantic_qa -> film_supervisor
-> assistant_handoff
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
| `generate_images` | `design` |
| `animatic` | `reference_plate`, `generate_images` |
| `production_readiness` | `reference_plate`, `storyboard_sheet`, `animatic` |
| `generate_video` | `animatic`, `generate_images`, `production_readiness` |
| `take_select` | `generate_video` |
| `generate_tts` | none |
| `film_timeline` | `design`, `generate_images`, `generate_tts` |
| `remotion_preview` | `film_timeline` |
| `film_assemble` | `remotion_preview` |
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
| `assistant_handoff` | `film_supervisor` |
| `rework_execute` | `rework_plan` |

`_resolve_dependencies()` expands requested targets with transitive dependencies and performs a topological sort.

`_resolve_dependency_levels()` groups the same closure into topological levels
(registry order within a level, deterministic) for the optional layered
parallel scheduler.

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

### Parallel orchestration (opt-in)

When `pipeline.max_workers > 1` (or `--stage-parallel N` is passed), the
scheduler switches to layered parallel execution. The serial loop is untouched
and remains the default. Parallel semantics:

- Stages within one dependency level run concurrently on a thread pool;
  pre-gates (rejected / cached-skip / pending-approval halt / `can_run`) are
  evaluated serially on the main thread before a level is submitted.
- A pre-gate halt stops the run before the level executes; execution halts
  (stage failure, review request) take effect at the level boundary —
  already-submitted stages always run to completion.
- When approval is required, every successful stage of the level gets a review
  request (in execution order) instead of stopping after the first one.
- Results are aggregated in dependency execution order, never completion order.
- The script context is refreshed at level boundaries (after `write` /
  `humanize`), never mid-level.
- `--interactive` forces serial orchestration because approval prompts only
  work on the main thread.
- LLM budget attribution (`_active_stage`) is thread-local, so concurrent
  stages charge the correct stage; state, approval, budget, and provider-health
  files are already guarded by `safe_io` file locks.

### Per-asset concurrency (opt-in)

`generate_tts` supports `tts.max_concurrency > 1` to generate segments
concurrently. Payloads and cache-fingerprint checks are prepared serially; only
paid generation runs on the pool. The per-provider token bucket
(`requests_per_minute`) is thread-safe (lock-guarded check-and-decrement) and
still applies per request. State and fingerprint writes are lock-guarded. On
budget exhaustion, in-flight requests finish before the stage fails.

`generate_video` supports `video.max_concurrency > 1` as a submit-all →
poll-all pipeline (see `docs/agent-stages/generate_video.md`): serial Phase A
cache/fingerprint decisions, bounded-concurrency Phase B task creation
(Agnes serialized to keep its >=65s cadence), and a unified Phase C poll loop
with concurrent downloads, 429 Retry-After backoff exempt from error counts,
and `max_poll_time` budgeting the slowest task. The paid task ledger,
exactly-once accounting, and crash-resume semantics are unchanged; no extra
locks were needed because ledger/budget/state writes are already
file-lock-atomic and all shared-state aggregation stays on the main thread.
Image generation remains serial per asset (its sequential-batch mode produces
N images per request and is not asset-parallelizable).

## State Files

```text
pipeline/<project>/state.json
pipeline/<project>/approvals/
pipeline/<project>/budget_state.json
pipeline/<project>/video_gen_state.json
pipeline/<project>/video_tasks.json
pipeline/<project>/render_report.yaml
```

`state.json` stores stage completion. Approval files store human review state.
Paid generation stages (images, video, TTS, music) skip re-generation only when
the output file exists AND its stored request fingerprint matches the current
request (prompt, model, size/resolution/duration, voice/speed, reference
content). Per-unit fingerprints live in each stage's state file
(`image_gen_state.json`, `tts_state.json`, `bgm_state.json` under a
`fingerprints` key); for video they live in the paid task ledger
(`video_tasks.json`, `request_fingerprint` field) alongside the stable
`prompt_hash` used for in-flight task resume. Legacy state without
fingerprints never matches and is regenerated once.

## Contract Schemas

`contracts/` holds the canonical field-level pydantic models for the three
core stage-to-stage contracts: `director_contract.yaml`
(`DirectorContract`), `film_timeline.yaml` (`FilmTimeline`), and
`film_supervisor.yaml` (`FilmSupervisorReport`). They complement — not
replace — the lightweight top-level key / `schema_version` checks in
`artifacts.py`.

- **Write side (fail-fast):** each producing stage validates its full payload
  through the model immediately before the `artifacts.py` gate and the YAML
  write, so schema drift raises `pydantic.ValidationError` at the write
  point and no broken artifact reaches disk.
- **Read side (advisory):** readers such as `Pipeline._supervisor_next_stages`,
  `FilmTimelineStage._semantic_fields`, and
  `GenerateVideoStage._load_director_contract` validate loaded artifacts for
  typed access or drift detection, but fall back to raw dict access with a
  warning when an older artifact does not match the model.
- **Compatibility policy:** every model uses `extra="allow"`, optional fields
  carry defaults, and `schema_version` stays a required `Literal` anchor, so
  artifacts from older/newer producers keep loading and unknown fields
  round-trip unchanged.

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
- `AssistantHandoffStage` writes `assistant_handoff.yaml` and `assistant_handoff.md`.
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
