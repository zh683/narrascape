# Narrascape

Narrascape is an open-source AI film-production pipeline for narration-driven
films, documentaries, explainers, and story videos.

It is not a single prompt-to-video button. Narrascape turns a script into an
inspectable production graph: visual pre-production, AI Director shot design,
storyboard-bound director contracts, image/video/source-media generation,
film-timeline assembly, audio, subtitles, QA, and automated rework.

## Why It Exists

Most AI video workflows fail when a project needs continuity: the same
character, the same wardrobe, the same room, the same emotional arc, and clips
that actually cut together. Narrascape treats those requirements as production
artifacts instead of hidden prompt text.

The central idea is:

```text
creative direction -> executable contracts -> generated/source media -> film timeline -> QA -> rework
```

Every major stage writes files that can be inspected, edited, tested, and rerun.

## Current Status

Narrascape is an early AI film studio prototype. The pipeline is real and
covered by CI across Ubuntu and Windows with Python 3.10, 3.11, and 3.12, but
final creative quality still depends on the configured LLM, media providers,
source material, and human review.

Production-oriented features already implemented:

- AI Director stages for screenplay structure, director contract, continuity,
  editing review, creative review, visual semantic QA, and film supervision.
- `director_contract.yaml` with per-shot story intent, film language,
  continuity locks, storyboard bindings, prompt blueprint, provider prompts,
  negative prompts, and QA assertions.
- `film_timeline.yaml` as the default editorial spine.
- Visual priority: generated video, then source footage, then generated-image
  fallback.
- Seedream image generation and Seedance video generation through provider
  selection.
- Multi-take video generation and `take_select`.
- Production readiness gates before expensive video generation.
- Render QA for validity, audio, subtitles, duration drift, black frames,
  repeated shots, missing clips, placeholder residue, continuity risk, and
  pacing risk.
- `rework_execute` that consumes rework plans, quarantines failed generated
  clips, writes regeneration/recut/replacement queues, and triggers reruns.
- `assistant_handoff` that writes a Codex-readable takeover packet with stage
  docs, next actions, quality gates, artifacts, and commands.
- Offline deterministic providers for end-to-end tests.

## Production Flow

```text
script
  -> pre_production
  -> design
  -> screenplay_structure
  -> director_contract
  -> reference_plate
  -> generate_images
  -> storyboard_sheet
  -> animatic
  -> production_readiness
  -> generate_video
  -> take_select
  -> generate_tts
  -> film_timeline
  -> remotion_preview
  -> film_assemble
  -> generate_music + remix_audio
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
  -> assistant_handoff
  -> rework_execute + rerun requested stages
```

The film timeline is the default visual spine:

```text
generated video -> source footage -> generated image fallback
```

## Quick Start

Install from a source checkout:

```bash
pip install -e ".[dev]"
narrascape init my-video
narrascape build -p my-video --approve
```

Run a no-network smoke test by using local providers:

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

Offline mode proves the pipeline is wired end to end. It does not produce
film-grade creative output.

## Production Profile

Narrascape includes a stricter AI-film runtime profile:

```bash
narrascape build -p examples/golden-sample --production --approve
```

`--production` applies the `seedream-seedance-oil-painting` profile:

- Seedream image generation.
- Seedance video generation.
- Oil-painting visual style.
- `pipeline.video_generation: required`.
- `pipeline.strict_director: true`.
- `pipeline.production_quality_gates: true`.
- At least three generated-video takes per shot.
- Two automatic rework cycles.

Use this profile when you want missing AI Director output, weak pre-production,
or missing generated video to fail early instead of quietly falling back.

## Golden Sample

[examples/golden-sample](examples/golden-sample/README.md) is the fixed quality
benchmark: a short *Crime and Punishment* chamber scene with one room, a small
cast, clear wardrobe locks, storyboard intent, and six shots.

It exists to answer one question after every optimization:

> Did the pipeline produce better controllable film material, or did it only run?

## AI Director Boundary

Narrascape separates three layers:

- Prompt templates: instructions that ask an LLM for structured output.
- LLM creative output: model-authored shot design, director judgment, creative
  review, take selection, and semantic QA.
- Offline fallback: deterministic local logic used for tests and no-network
  verification.

For production builds, use `llm.mode: ai_assistant`, `bridge`, `api`, or `auto`.
`llm.mode: none` is intentionally not allowed with
`pipeline.video_generation: required`.

## Common Commands

```bash
narrascape init my-video
narrascape workbench -p my-video --port 8765
narrascape dashboard -p my-video --port 8501
narrascape research -p my-video --topic "Notre Dame"
narrascape write -p my-video
narrascape humanize -p my-video
narrascape pre_production -p my-video
narrascape design -p my-video
narrascape build -p my-video --approve
narrascape build -p my-video --production --approve
narrascape build -p my-video --stage generate_video --approve
narrascape build -p my-video --stage qa --approve
narrascape status -p my-video
narrascape approve -p my-video -s design
narrascape reject -p my-video -s design --notes "revise faces"
narrascape clean -p my-video --all
```

`workbench` 启动 React/Vite 原生制作控制面，可直接运行阶段、审批、查看时间线、
取消或恢复持久作业。`dashboard` 保留为 Streamlit 诊断台，用于检查底层状态和产物。

Dashboard dependencies are optional:

```bash
pip install -e ".[dashboard]"
narrascape dashboard -p my-video --port 8501
```

The dashboard includes an artifact-first Workbench page for production takeover:
current stage, supervisor queue, director/review artifacts, rework loop status,
and the exact `narrascape build` commands to continue the next stage.

## Provider Matrix

| Area | Implemented paths |
| --- | --- |
| LLM | AI assistant bridge, file bridge, OpenAI-compatible APIs, Anthropic, DeepSeek, Volcengine, local HTTP chat |
| Images | Seedream, local placeholder |
| Video | Seedance async image-to-video |
| TTS | MiniMax, local tone provider |
| Music | MiniMax, local tone provider |
| Source media | local media library, footage timeline, rough-cut render |
| Preview/render | Remotion timeline handoff, FFmpeg assembly |
| QA | ffprobe-backed render and quality validation |

## Documentation

- [Product Introduction / 产品介绍](docs/product-introduction.md)
- [Quick Start](docs/quickstart.md)
- [Complete Feature Map](docs/features.md)
- [System Design](docs/design.md)
- [Architecture](docs/architecture.md)
- [AI Director](docs/ai-director.md)
- [Assistant Handoff Protocol](docs/assistant-handoff.md)
- [Configuration Reference](docs/config-reference.md)
- [Provider Governance](docs/provider-governance.md)
- [Reference Image + Storyboard Workflow](docs/reference-image-storyboard-workflow.md)
- [Film Capability Roadmap](docs/film-capability-roadmap.md)
- [Agent Stage Docs](docs/index.md#agent-stage-docs)

## Development

```bash
python -m pip install -r requirements-dev.txt
ruff check src tests
black --check src tests
mypy
pytest -q --tb=short --no-cov
```

`requirements-dev.txt` is a thin wrapper around `pip install -e ".[dev]"`.
Use it when bootstrapping a fresh checkout so CLI dependencies such as Typer and
test tools such as pytest are installed before running `python -m narrascape.cli`.

## License

Narrascape is released under the GNU Affero General Public License v3.0. See
[LICENSE](LICENSE).
