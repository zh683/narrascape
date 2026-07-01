# Narrascape Documentation

Narrascape is a staged AI film-production pipeline. It turns a script into
inspectable production artifacts: pre-production references, AI Director
contracts, generated/source media, a film timeline, final assembly, QA reports,
and rework queues.

## Start Here

| Need | Read |
| --- | --- |
| Understand the product in Chinese and English | [Product Introduction / 产品介绍](product-introduction.md) |
| Run the project locally | [Quick Start](quickstart.md) |
| See what is implemented today | [Complete Feature Map](features.md) |
| Understand the whole workflow | [System Design](design.md) |
| Understand the code architecture | [Architecture](architecture.md) |
| Understand AI Director behavior and boundaries | [AI Director](ai-director.md) |
| Let Codex or another AI assistant take over a project | [Assistant Handoff Protocol](assistant-handoff.md) |
| Configure a project | [Configuration Reference](config-reference.md) |
| Understand provider selection | [Provider Governance](provider-governance.md) |
| Use reference images and storyboard bindings | [Reference Image + Storyboard Workflow](reference-image-storyboard-workflow.md) |
| Track long-term film capability | [Film Capability Roadmap](film-capability-roadmap.md) |

## Recommended Paths

For a first local run:

1. Read [Quick Start](quickstart.md).
2. Run an offline local-provider build.
3. Inspect `film_timeline.yaml`, `director_contract.yaml`, and
   `pipeline/<project>/render_report.yaml`.

For AI-film production work:

1. Read [Product Introduction / 产品介绍](product-introduction.md).
2. Run [examples/golden-sample](../examples/golden-sample/README.md) with
   `--production`.
3. Review [AI Director](ai-director.md), [production_readiness](agent-stages/production_readiness.md),
   [generate_video](agent-stages/generate_video.md), and
   [visual_semantic_qa](agent-stages/visual_semantic_qa.md).

For provider integration:

1. Read [Provider Governance](provider-governance.md).
2. Review `src/narrascape/providers/`.
3. Review the relevant stage docs under [Agent Stage Docs](#agent-stage-docs).

## Default Build Graph

```text
pre_production -> design -> screenplay_structure -> director_contract -> reference_plate
-> generate_images -> storyboard_sheet -> animatic -> production_readiness
-> generate_video -> take_select -> generate_tts -> film_timeline
-> remotion_preview -> film_assemble -> generate_music -> remix_audio
-> audio -> subtitles -> qa -> continuity_bible -> editing_review
-> director_review -> rework_plan -> creative_review -> visual_semantic_qa
-> film_supervisor -> assistant_handoff
-> rework_execute + rerun requested stages when needed
```

If `scripts/script.yaml` does not exist, the pipeline prepends:

```text
research -> write
```

`source_media` and `footage_edit` are optional real-footage documentary stages.
`humanize` is available as a script-polishing command or explicit stage.

`generate_video` is controlled by `pipeline.video_generation`:

- `auto`: include generated-video stages and skip them when credentials are unavailable.
- `required`: generated video is a blocking production requirement.
- `off`: omit generated-video stages.

## Core Artifacts

| Artifact | Role |
| --- | --- |
| `pre_production.yaml` | character, scene, style, and storyboard preparation |
| `design_report.yaml` | shot design and image prompt plan |
| `screenplay_structure.yaml` | act, scene, sequence, and shot hierarchy |
| `director_contract.yaml` | executable per-shot director contract |
| `reference_plates.yaml` | resolved style, character, scene, and storyboard references |
| `storyboard_sheet.yaml/png/pdf` | reviewable storyboard contact sheet |
| `animatic.yaml/mp4` | low-cost timing preview before video generation |
| `production_readiness.yaml` | pre-video quality gate |
| `video_prompt_quality.yaml` | prompt ingredient audit before provider calls |
| `take_selection.yaml` | selected generated-video takes |
| `film_timeline.yaml` | default editorial spine |
| `render_report.yaml` | final render QA report |
| `rework_plan.yaml` | grouped regeneration, recut, and replacement actions |
| `film_supervisor.yaml` | next-stage production decision |
| `assistant_handoff.yaml/md` | Codex-readable takeover packet |

## Agent Stage Docs

These docs are written for AI assistants and developers implementing or
debugging one stage at a time:

- [animatic](agent-stages/animatic.md)
- [assistant_handoff](agent-stages/assistant_handoff.md)
- [continuity_bible](agent-stages/continuity_bible.md)
- [creative_review](agent-stages/creative_review.md)
- [design](agent-stages/design.md)
- [director_contract](agent-stages/director_contract.md)
- [director_review](agent-stages/director_review.md)
- [editing_review](agent-stages/editing_review.md)
- [film_assemble](agent-stages/film_assemble.md)
- [film_supervisor](agent-stages/film_supervisor.md)
- [film_timeline](agent-stages/film_timeline.md)
- [footage_edit](agent-stages/footage_edit.md)
- [generate_images](agent-stages/generate_images.md)
- [generate_video](agent-stages/generate_video.md)
- [production_readiness](agent-stages/production_readiness.md)
- [qa](agent-stages/qa.md)
- [reference_plate](agent-stages/reference_plate.md)
- [remotion_preview](agent-stages/remotion_preview.md)
- [rework_execute](agent-stages/rework_execute.md)
- [rework_plan](agent-stages/rework_plan.md)
- [screenplay_structure](agent-stages/screenplay_structure.md)
- [source_media](agent-stages/source_media.md)
- [storyboard_sheet](agent-stages/storyboard_sheet.md)
- [take_select](agent-stages/take_select.md)
- [visual_semantic_qa](agent-stages/visual_semantic_qa.md)

## Verification

```powershell
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m pytest -q --tb=short --no-cov
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
