# Narrascape

Narrascape is a staged AI film-production pipeline for narration-driven documentary, explainer, and story videos.

It turns a script into an inspectable production graph: visual pre-production, AI Director shot design, executable director contracts, image/video/source-media assembly, audio, subtitles, QA, and director rework planning.

## Current Status

Narrascape is an early AI film studio prototype with a working CLI pipeline and offline verification path. The local test suite covers the main stage graph, AI assistant bridge batching, provider selection, source-media workflow, film timeline assembly, render QA, director review, rework planning, automated rework execution, and the `director_contract` prompt/QA handoff.

AI Director behavior depends on the configured LLM mode:

- `llm.mode: ai_assistant`, `bridge`, `api`, or `auto`: creative analysis, shot design, review, and contract compilation can use a large language model.
- `llm.mode: none`: deterministic fallbacks keep the pipeline testable offline, but they are not a substitute for creative model output.

## What It Builds

```text
script
  -> pre_production
  -> design
  -> screenplay_structure
  -> director_contract
  -> reference_plate
  -> generate_images
  -> animatic
  -> generate_video
  -> take_select
  -> film_timeline
  -> film_assemble
  -> generate_tts + generate_music + remix_audio
  -> audio
  -> subtitles
  -> qa
  -> continuity_bible
  -> editing_review
  -> director_review
  -> rework_plan
  -> creative_review
  -> visual_semantic_qa
  -> film_supervisor
  -> rework_execute + rerun when supervisor requests rework
```

`film_timeline.yaml` is the default visual spine. Visual priority is:

```text
generated video -> source footage -> generated image fallback
```

By default, `pipeline.video_generation: auto` tries the generated-video path when it can run. If the configured video provider credentials are missing, the video stage is skipped and the timeline continues through source footage or generated-image fallback. Use `pipeline.video_generation: required` to make missing generated video a blocking production issue, or `off` to omit video generation stages.

`pipeline.video_generation: required` is treated as an AI-film production mode, so it cannot run with `llm.mode: none`. Required-video projects must use `llm.mode: ai_assistant`, `bridge`, `api`, or `auto`; otherwise configuration loading or pipeline startup fails before deterministic templates can silently take over.

The default build also has `pipeline.auto_rework: true` and `pipeline.max_rework_cycles: 1`. After `film_supervisor`, a `needs_rework` decision automatically executes `rework_execute`, then reruns the supervisor's requested stages such as `generate_video -> take_select -> film_timeline -> qa -> film_supervisor`.

## AI Director

The AI Director is not just a prompt template. It now produces durable production artifacts:

- `screenplay_structure.yaml`: act, scene, sequence, and shot hierarchy.
- `director_contract.yaml`: per-shot story intent, film language, continuity constraints, storyboard binding, portable video prompt, provider-compiled prompts, negative prompts, and QA assertions.
- `reference_plates.yaml`: per-shot resolved style, character, scene, and storyboard reference handoff.
- `animatic.yaml` plus `animatic.mp4`: low-cost storyboard timing preview before expensive video generation.
- `continuity_bible.yaml`: character, location, wardrobe, lighting, and screen-axis state.
- `editing_review.yaml`: pacing, repetition, and emotional rhythm review.
- `director_review.yaml`: QA-driven shot rework queue.
- `rework_plan.yaml`: grouped regeneration, recut, and source-media replacement actions.
- `creative_review.yaml`: LLM-assisted or fallback creative supervision.
- `visual_semantic_report.yaml`: semantic visual QA against script, design intent, director contract, and storyboard binding.
- `film_supervisor.yaml`: next-stage supervision decision.

`director_contract` is the execution handoff. When storyboard frames exist, each shot is bound to:

- `storyboard_frame_ids`
- `character_positions`
- `scene_ref`
- `wardrobe_lock`
- `composition_requirements`
- `reference_image_ids`

`generate_video` consumes `generation.compiled_prompts.<provider>.prompt` when available, passes the matching negative prompt into the provider request, and falls back to `generation.video_prompt` for legacy contracts. It writes `video_prompt_quality.yaml`, scores each prompt for executable video ingredients such as subject, action, scene, wardrobe, camera language, composition, lighting, style, and reference binding, then blocks generic or under-specified prompts before provider execution. `visual_semantic_qa` checks the same contract for scene, wardrobe, character-position, and composition mismatches.

## Quick Start

From a source checkout:

```powershell
$env:PYTHONPATH = "src"
python -m narrascape.cli init .narrascape/my-video
python -m narrascape.cli build -p .narrascape/my-video --approve
```

For an editable install:

```bash
pip install -e ".[dev]"
narrascape init my-video
narrascape build -p my-video --approve
```

For a no-network smoke test, configure local providers:

```yaml
llm:
  mode: none
images:
  provider: local
tts:
  provider: local
audio:
  music:
    provider: local
```

For Agnes image and video generation, set `AGNES_API_KEY` in your environment or `.env`, then configure:

```yaml
llm:
  mode: ai_assistant
pipeline:
  video_generation: required
images:
  provider: agnes
  model: agnes-image-2.1-flash
video:
  provider: agnes
  model: agnes-video-v2.0
  resolution: 720p
  duration: 5
  frame_rate: 24
  takes: 1
```

Agnes image generation supports text-to-image and image-to-image through the existing `reference_images` fields. Agnes video generation writes the same generated-video contract as Seedance, so `take_select`, `film_timeline`, QA, and rework loops continue unchanged. Set `video.takes` above `1` to generate multiple candidates per shot for `take_select`. For image-to-video or multi-image video, Agnes expects publicly reachable image URLs; use an HTTP/object-storage upload backend for production reference images.

## First Film Project

The current starter film is [罪与罚 / Crime and Punishment](examples/crime-and-punishment/README.md), a public-domain AI-film prototype based on Fyodor Dostoevsky's 1866 novel.

It includes a 12-segment Chinese narration script, director notes, character and wardrobe locks, scene continuity rules, Agnes-ready image/video prompts, and local-preview config:

```powershell
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p examples/crime-and-punishment --approve
```

## Common Commands

```bash
narrascape init my-video
narrascape dashboard -p my-video
narrascape research -p my-video --topic "Notre Dame"
narrascape write -p my-video
narrascape humanize -p my-video
narrascape pre_production -p my-video
narrascape design -p my-video
narrascape build -p my-video --approve
narrascape build -p my-video --stage generate_video
narrascape build -p my-video --stage source_media
narrascape build -p my-video --stage film_assemble
narrascape build -p my-video --stage qa
narrascape build -p my-video --stage rework_execute
narrascape status -p my-video
narrascape approve -p my-video -s design
narrascape reject -p my-video -s design --notes "revise faces"
narrascape clean -p my-video --all
```

## Provider Families

- LLM: AI assistant bridge, file bridge, OpenAI-compatible APIs, Anthropic, DeepSeek, Volcengine, local HTTP chat.
- Images: Seedream, Agnes Image 2.1 Flash, local placeholder generation.
- Video: Seedance async image-to-video generation, Agnes Video V2.0 async text/image/multi-image generation.
- TTS: MiniMax, local tone generation.
- Music: MiniMax, local tone generation.
- Source media: local media discovery and footage timeline planning.
- Rendering and QA: FFmpeg timeline assembly, final render validation, and director rework actions.

Provider selection is wired into image, TTS, music, and video generation stages. Each selected provider is recorded in the stage state file.

## Project Layout

```text
my-video/
  config.yaml
  scripts/script.yaml
  image_prompts.yaml
  image_map.yaml
  design_report.yaml
  film_timeline.yaml
  assets/
    images/
    references/
    storyboard/
    tts/
    music/
    videos/
  pipeline/<project-name>/
    state.json
    approvals/
    pre_production.yaml
    screenplay_structure.yaml
    director_contract.yaml
    reference_plates.yaml
    animatic.yaml
    animatic.mp4
    render_report.yaml
    continuity_bible.yaml
    editing_review.yaml
    director_review.yaml
    rework_plan.yaml
    visual_semantic_report.yaml
    film_supervisor.yaml
    film_assembled.mp4
  output/
    <project>-clean.mp4
    <project>-sub.mp4
```

Generated project outputs are intentionally ignored by git.

## Documentation

- [Product Introduction / 产品介绍](docs/product-introduction.md)
- [Quick Start](docs/quickstart.md)
- [Complete Feature Map](docs/features.md)
- [System Design](docs/design.md)
- [Architecture](docs/architecture.md)
- [AI Director](docs/ai-director.md)
- [Bridge / AI Assistant Mode](docs/BRIDGE_MODE.md)
- [Configuration Reference](docs/config-reference.md)
- [Provider Governance](docs/provider-governance.md)
- [Reference Image + Storyboard Workflow](docs/reference-image-storyboard-workflow.md)
- [Film Capability Roadmap](docs/film-capability-roadmap.md)

## Development

```powershell
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m pytest -q --tb=short --no-cov
```

Or:

```bash
pip install -e ".[dev]"
pytest
```

## License

Narrascape is released under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
