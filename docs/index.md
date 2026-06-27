# Narrascape Documentation

Narrascape is a staged video-production pipeline for narration-driven documentary and explainer videos.

## Read This First

- [Quick Start](quickstart.md): create a project and build a video.
- [Complete Feature Map](features.md): what is implemented and which providers each part uses.
- [System Design](design.md): how the whole workflow is connected.
- [Architecture](architecture.md): code-level stage graph and runtime behavior.
- [AI Director](ai-director.md): how PromptDirector uses LLM output and when it falls back to local templates.
- [Bridge / AI Assistant Mode](BRIDGE_MODE.md): file-based assistant integration.
- [Configuration Reference](config-reference.md): `config.yaml` and script schema.
- [Provider Governance](provider-governance.md): provider registry, selector scoring, source media, and QA.
- [Film Capability Roadmap](film-capability-roadmap.md): path from video pipeline to AI film studio.
- [Reference Image + Storyboard Workflow](reference-image-storyboard-workflow.md): pre-production assets.
- [Style Consistency](style-consistency.md): reference images and consistency rules.

## Default Build Graph

```text
pre_production -> design -> screenplay_structure -> director_contract
-> generate_images -> generate_tts -> film_timeline
-> film_assemble -> generate_music -> remix_audio -> audio -> subtitles -> qa
-> continuity_bible -> editing_review -> director_review -> rework_plan
-> creative_review -> visual_semantic_qa -> film_supervisor
```

If `scripts/script.yaml` does not exist, the pipeline prepends:

```text
research -> write
```

`humanize` is available as a script-polishing command or explicit stage.
`source_media` and `footage_edit` are optional real-footage documentary stages.
`generate_video` is an optional Seedance stage. Generated clips are consumed by
the next `film_timeline` build:

```text
pre_production -> design -> screenplay_structure -> director_contract
-> generate_images -> generate_video
-> take_select
```

## Stage Outputs

| Stage | Purpose | Main outputs |
| --- | --- | --- |
| `research` | Prepare source material from a topic | `research_report.md` |
| `write` | Generate segmented narration | `scripts/script.yaml` |
| `humanize` | Rewrite narration to reduce AI-like patterns | updated script |
| `pre_production` | Create visual references and storyboard data | `pipeline/<name>/pre_production.yaml`, `assets/references/` |
| `design` | Use AI Director or local fallback to design shots | `design_report.yaml`, `image_prompts.yaml`, `image_map.yaml` |
| `screenplay_structure` | Split story into act, scene, sequence, shot | `pipeline/<name>/screenplay_structure.yaml` |
| `director_contract` | Compile director intent into video prompts and QA assertions | `pipeline/<name>/director_contract.yaml` |
| `generate_images` | Generate Seedream or local images | `assets/images/*.png` |
| `generate_video` | Optional Seedance clips from generated images | `assets/videos/*.mp4` |
| `take_select` | Optional multi-take selection | `pipeline/<name>/take_selection.yaml` |
| `generate_tts` | Generate narration audio and timing | `assets/tts/*.mp3`, `pipeline/<name>/timing.json` |
| `film_timeline` | Build unified film timeline | `film_timeline.yaml` |
| `film_assemble` | Render the film timeline visual track | `pipeline/<name>/film_assembled.mp4`, `pipeline/<name>/timeline_segments/*.mp4` |
| `generate_music` | Generate BGM zones | `assets/music/*.mp3` |
| `remix_audio` | Mix narration and BGM | `pipeline/<name>/mixed_audio.mp3` |
| `kenburns` | Optional legacy animated-image segment renderer | `pipeline/<name>/video_segments/*.mp4` |
| `concat` | Optional legacy silent visual joiner | `pipeline/<name>/final_nosub.mp4` |
| `audio` | Add mixed audio | `output/<name>-clean.mp4` |
| `subtitles` | Burn subtitles | `output/<name>-sub.mp4` |
| `qa` | Validate final render | `pipeline/<name>/render_report.yaml` |
| `continuity_bible` | Preserve character, scene, wardrobe, lighting, and axis state | `pipeline/<name>/continuity_bible.yaml` |
| `editing_review` | Review pacing, repetition, and emotion curve | `pipeline/<name>/editing_review.yaml` |
| `director_review` | Convert QA findings into rework actions | `pipeline/<name>/director_review.yaml` |
| `rework_plan` | Merge director findings into executable rework actions | `pipeline/<name>/rework_plan.yaml` |
| `creative_review` | LLM or fallback creative supervision | `pipeline/<name>/creative_review.yaml` |
| `visual_semantic_qa` | LLM or fallback visual semantic QA | `pipeline/<name>/visual_semantic_report.yaml` |
| `film_supervisor` | Decide the next production stages | `pipeline/<name>/film_supervisor.yaml` |
| `rework_execute` | Explicitly execute rework queues and quarantine invalid generated media | `pipeline/<name>/rework_execution.yaml`, rework queue YAML files |
| `source_media` | Discover local clips/images and plan footage cuts | `asset_manifest.yaml`, `footage_timeline.yaml` |
| `footage_edit` | Render a source-media rough cut | `pipeline/<name>/footage_roughcut.mp4` |

## Verification

The main local verification command is:

```powershell
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m pytest -q --tb=short --no-cov
```

For a no-network pipeline smoke test, configure:

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
