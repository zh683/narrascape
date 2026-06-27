# System Design

Narrascape separates creative decisions, media generation, motion rendering, and assembly into explicit stages. Each stage reads typed project data, writes durable artifacts, and records status for resumable builds.

## Goals

- Build long narration-driven videos from script segments.
- Keep every intermediate artifact inspectable and editable.
- Let an LLM act as a creative director when configured.
- Keep an offline path for deterministic tests and local verification.
- Rebuild only what changed where practical.
- Make human approval a first-class part of the pipeline.

## Runtime Data Flow

```text
config.yaml
scripts/script.yaml
        |
        v
source_media -> asset_manifest.yaml + footage_timeline.yaml
        |
        v
footage_edit -> pipeline/<project>/footage_roughcut.mp4
        |
        v
pre_production -> design -> image_prompts.yaml + image_map.yaml
        |             |
        |             v
        |        screenplay_structure -> screenplay_structure.yaml
        |             |
        |             v
        |        director_contract -> director_contract.yaml
        |             |
        |             v
        |        generate_images -> assets/images/*.png
        |             |
        |             v
        |        generate_video -> assets/videos/*.mp4
        |             |
        |             v
        |        take_select -> take_selection.yaml
        |
generate_tts -> assets/tts/*.mp3 + pipeline/<project>/timing.json
        |
film_timeline -> film_timeline.yaml
        |
film_assemble -> pipeline/<project>/film_assembled.mp4
        |
generate_music -> assets/music/*.mp3
        |
remix_audio -> pipeline/<project>/mixed_audio.mp3
        |
audio -> output/*-clean.mp4
        |
subtitles -> output/*-sub.mp4
        |
        v
qa -> render_report.yaml
        |
continuity_bible -> continuity_bible.yaml
        |
editing_review -> editing_review.yaml
        |
director_review -> director_review.yaml
        |
rework_plan -> rework_plan.yaml
        |
creative_review -> creative_review.yaml
        |
visual_semantic_qa -> visual_semantic_report.yaml
        |
film_supervisor -> film_supervisor.yaml
        |
rework_execute -> rework queues + quarantined failed media + rerun plan
```

`kenburns` and `concat` remain explicit legacy stages for animated still-image
experiments:

```text
design -> generate_images -> kenburns -> concat
```

## Stage Contract

Every stage follows the same base contract:

- `name`: stable stage identifier.
- `depends_on`: upstream stage list.
- `can_run(context)`: prerequisite validation.
- `run(context)`: performs work and returns `StageResult`.

The pipeline creates stage instances with the right shared clients:

- LLM client for research, write, humanize, pre-production, and design.
- Image API key for image and optional video generation.
- MiniMax API key for TTS and music.

## Dependency Resolution

Requested stages are expanded with transitive dependencies and sorted topologically. For example:

```text
subtitles
-> pre_production, design, generate_images, generate_tts, film_timeline,
   film_assemble, generate_music, remix_audio, audio, subtitles
```

This prevents users from needing to memorize the whole graph.

## Provider Governance

Narrascape now has a provider registry and selector layer inspired by OpenMontage:

- `ProviderRegistry` reports capabilities and availability.
- `ProviderSelector` chooses among available tools with weighted scoring.
- The score includes task fit, quality, control, reliability, cost efficiency, latency, and continuity.

The selector is wired into execution for `generate_images`, `generate_tts`,
`generate_music`, and `generate_video`. Each of those stages writes the selected
provider into its return metadata and state file, then executes the selected
branch.

## Canonical Artifacts

Canonical artifacts can be validated before they flow downstream:

- `asset_manifest`
- `continuity_bible`
- `creative_review`
- `design_report`
- `director_contract`
- `editing_review`
- `film_supervisor`
- `film_timeline`
- `render_report`
- `rework_execution`
- `rework_plan`
- `screenplay_structure`
- `take_selection`
- `visual_semantic_report`

The schema layer is intentionally lightweight in the first version and can grow into JSON Schema files later.

## Director Layers

The AI Director is no longer only a shot-prompt stage. It now has durable
director layers:

- `screenplay_structure` reads the script and design report, then writes
  `screenplay_structure.yaml` with act, scene, sequence, and shot hierarchy.
- `director_contract` reads the screenplay structure and design report, then
  writes `director_contract.yaml` with story intent, film language, executable
  video prompts, negative prompts, continuity constraints, storyboard binding,
  and QA assertions.
- `continuity_bible` reads `film_timeline.yaml` and the screenplay structure,
  then writes `continuity_bible.yaml` with character appearances, locations,
  wardrobe, lighting, screen axis, and continuity risks.
- `editing_review` reads `film_timeline.yaml` plus `render_report.yaml`, then
  writes `editing_review.yaml` with pacing, repeated shots, emotion curve, and
  edit recommendations.
- `rework_plan` reads `director_review.yaml`, `editing_review.yaml`, and
  `continuity_bible.yaml`, then writes `rework_plan.yaml` grouped by
  `regenerate_video`, `recut`, and `replace_source_media`.
- `take_select` reads generated multi-take clips and QA context, then writes
  `take_selection.yaml`. `film_timeline` consumes that file when present, so
  selected takes enter the assembly path.
- `creative_review` reads the film timeline, editing review, continuity bible,
  and QA report. When an LLM client is configured, it asks the LLM for story and
  cinematic review; otherwise it creates deterministic findings from existing
  director artifacts.
- `visual_semantic_qa` reads visual clip paths, design intent, script, and QA
  context. With an LLM client, it asks for semantic visual findings; offline, it
  flags metadata mismatches such as scene or wardrobe drift.
- `film_supervisor` reads all director reports and writes `film_supervisor.yaml`
  with the next stages that should run.
- `rework_execute` executes `rework_plan.yaml` safely by quarantining failed
  generated video clips, writing concrete queues, and resetting affected stage
  state. In the default auto-rework path, the pipeline runs it after a
  `film_supervisor` `needs_rework` decision and then reruns the requested
  stages.

## Film Timeline

`film_timeline` is the movie-production spine in Narrascape. It writes
`film_timeline.yaml`, a unified editorial timeline that gathers:

- script segment ids and narration text
- AI Director shot metadata and director contract prompts
- generated-video clips when available
- source-media clips when available
- generated-image fallback clips
- narration audio clips
- music zone references
- subtitle references

The timeline uses `generated_video -> source_media -> generated_image` visual
priority and records coverage: generated-video segments, real-footage segments,
generated-image fallback segments, and missing visual segments. Smart re-cut,
sound-design, color, continuity, and future generated-video providers should
read and write against this timeline instead of inventing separate handoffs.
Selected multi-take clips from `take_selection.yaml` are treated as the
generated-video asset for their segment.

`film_assemble` reads that timeline, renders generated video clips, source
footage, generated-image fallback clips, ending cards, and timeline gaps into
normalized segments, then concatenates `pipeline/<project>/film_assembled.mp4`.
This is now the default visual input to the audio stage.

`generate_video` consumes `director_contract.yaml` when it is present. That
makes the contract the handoff between director thinking and AI video
generation: the model's creative choices become the exact prompt, negative
prompt, motion, continuity, storyboard frame binding, and QA expectations for
each shot.

## Source Media

`source_media` is an optional stage. It scans `source_media/`, writes
`asset_manifest.yaml`, and builds `footage_timeline.yaml`.

The manifest records local clips and stills with provider, source, license, byte
size, and available ffprobe metadata. The footage timeline converts those assets
into ordered edit decisions: asset id, source path, target script segment,
source in/out, edit duration, role, and transition. This gives the project a
footage-first documentary path instead of relying only on generated still images.

`footage_edit` reads `footage_timeline.yaml`, renders normalized rough-cut
segments under `pipeline/<project>/source_media_segments/`, and concatenates
them into `pipeline/<project>/footage_roughcut.mp4`.

## Composition Runtime Surface

`CompositionRuntimeRegistry` exposes runtime selection separately from the current FFmpeg stages. `ffmpeg` is available by default; Remotion is represented as an unavailable runtime until fully wired.

## Render QA

`qa` runs after `subtitles` in the default build. It verifies the final file with
ffprobe, checks video/audio streams, records duration and resolution, and writes
`pipeline/<project>/render_report.yaml`.

The report also checks subtitle source/output presence, expected-vs-actual
duration tolerance, silent audio risk, black-frame risk, repeated shots, local
placeholder image residue, shot coverage, missing generated-video clips, missing
timeline video files, character/location continuity risk, and narrative pacing
risk. Configured gaps and ending cards are treated as intentional black sections
so the detector flags unexpected black frames rather than designed pauses.

`director_review` runs after QA. It reads failed film checks and writes
`director_review.yaml` with a rework queue. Missing shots, missing generated
video coverage, and missing timeline video files are marked for
`regenerate_video`; pacing risks are marked for `recut`; continuity risks are
marked for regeneration review.

`rework_plan` completes that loop by merging QA-driven director review,
timeline-level editing review, and continuity-bible risks into a single action
plan. This gives downstream automation one file to decide whether a segment
should be regenerated, recut, or replaced with source media.

`creative_review`, `visual_semantic_qa`, and `film_supervisor` extend the loop
from individual reports to production supervision. `visual_semantic_qa` also
reads `director_contract.yaml` so semantic review checks the same contract that
guided video generation, including storyboard frame ids, scene references,
wardrobe locks, character positions, and composition requirements.
`film_supervisor` does not mutate media; it decides the next stage list.
`rework_execute` performs the mutation. Default builds run it automatically when
`pipeline.auto_rework` is true; set `auto_rework: false` to inspect the plan
before moving generated clips into quarantine.

## State And Approvals

Pipeline state is stored at:

```text
pipeline/<project>/state.json
```

Approval files live at:

```text
pipeline/<project>/approvals/
```

Approval states:

- `.pending`: stage finished and needs review.
- `.approved`: stage can be skipped or used by later stages.
- `.rejected`: pipeline stops until the issue is fixed or manually approved.
- `.skipped`: treated as approved.

`--approve` is intended for CI, automated tests, and trusted local builds. `--interactive` is intended for creative review.

## LLM Boundary

The project deliberately separates two concepts:

- Prompt templates: structured instructions that tell a model what JSON to return.
- Local templates: deterministic fallback logic used when no LLM client exists.

In LLM modes, creative fields come from model responses. In `llm.mode: none`, the design stage uses local deterministic logic.

## Bridge Boundary

Bridge-backed modes are file based:

```text
LLMClient.complete()
-> .narrascape/bridge/pending/task_<id>.md
-> assistant writes .narrascape/bridge/completed/response_<id>.json
-> pipeline parses response content
```

Retries are disabled for bridge-backed LLM calls so a timeout does not create duplicated tasks.

## Offline Verification Path

The offline path is intentionally boring but complete:

- `llm.mode: none` creates deterministic design data.
- `images.provider: local` writes placeholder PNG images.
- `tts.provider: local` writes MP3 tones and timing data.
- `audio.music.provider: local` writes BGM tones.
- ffmpeg stages assemble the real final video files.

This proves the workflow is wired end to end without pretending that local placeholders are production-quality creative output.

## Extension Points

- Add a provider by implementing the provider path inside the relevant stage or client.
- Add a stage by subclassing `Stage`, registering it in `ALL_STAGES`, and declaring `depends_on`.
- Add new output fields through Pydantic models first, then export them to YAML.
- Add human review rules through `PipelineApproval`.
