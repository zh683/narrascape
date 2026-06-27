# Narrascape

Narrascape is a staged AI film-production pipeline for narration-driven documentary, explainer, and story videos.

It turns a script into an inspectable production graph: visual pre-production, AI Director shot design, executable director contracts, image/video/source-media assembly, audio, subtitles, QA, and director rework planning.

## Current Status

Narrascape is an early AI film studio prototype with a working CLI pipeline and offline verification path. The local test suite covers the main stage graph, AI assistant bridge batching, provider selection, source-media workflow, film timeline assembly, render QA, director review, rework planning, and the `director_contract` prompt/QA handoff.

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
  -> generate_images / generate_video / source_media
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
```

`film_timeline.yaml` is the default visual spine. Visual priority is:

```text
generated video -> source footage -> generated image fallback
```

## AI Director

The AI Director is not just a prompt template. It now produces durable production artifacts:

- `screenplay_structure.yaml`: act, scene, sequence, and shot hierarchy.
- `director_contract.yaml`: per-shot story intent, film language, continuity constraints, storyboard binding, video prompt, negative prompt, and QA assertions.
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

`generate_video` consumes the compiled `generation.video_prompt`, and `visual_semantic_qa` checks the same contract for scene, wardrobe, character-position, and composition mismatches.

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
- Images: Seedream, local placeholder generation.
- Video: Seedance async image-to-video generation.
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
