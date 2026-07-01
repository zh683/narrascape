# Quick Start

This guide builds a complete local video pipeline and shows where to switch from
offline verification to real AI providers.

## 1. Run From Source

```powershell
cd C:\Users\32472\.openclaw\workspace\narrascape
python -m pip install -r requirements-dev.txt
narrascape version
```

For import-only checks in an uninstalled checkout, setting `PYTHONPATH=src` is
enough. The CLI needs the package dependencies installed.

To use the Streamlit dashboard, install the optional UI extra:

```powershell
pip install -e ".[dashboard]"
```

## 2. Create A Project

```powershell
.\.venv_test\Scripts\python.exe -m narrascape.cli init .narrascape/my-video
```

The generated project contains `config.yaml`, `scripts/script.yaml`, asset directories, and pipeline state directories.

## 3. Choose A Mode

For offline end-to-end verification:

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

For AI-assisted creative design without external LLM API keys:

```yaml
llm:
  mode: ai_assistant
  timeout: 300
```

For external API mode:

```yaml
llm:
  mode: api
  provider: openai
  model: gpt-4o
  api_key: "${OPENAI_API_KEY}"
```

## 4. Build The Video

```powershell
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p .narrascape/my-video --approve
```

The default build graph is:

```text
pre_production -> design -> screenplay_structure -> director_contract
-> reference_plate -> generate_images -> storyboard_sheet -> animatic
-> production_readiness -> generate_video -> take_select -> generate_tts
-> film_timeline -> remotion_preview -> film_assemble
-> generate_music -> remix_audio -> audio -> subtitles -> qa
-> continuity_bible -> editing_review -> director_review -> rework_plan
-> creative_review -> visual_semantic_qa -> film_supervisor
-> assistant_handoff -> rework_execute + rerun requested stages when needed
```

With the default `pipeline.video_generation: auto`, missing Seedance/Ark
credentials skip `generate_video` and continue with source footage or
generated-image fallback. Use `pipeline.video_generation: required` when every
shot must become generated video.

For the stricter AI-film profile, run the included golden sample:

```powershell
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p examples/golden-sample --production --approve
```

`--production` applies Seedream images, Seedance video, oil-painting style,
required generated video, strict director mode, production readiness quality
gates, three takes per shot, and the automatic rework loop.

Use `--production` when weak pre-production, missing AI Director output, or
missing generated-video clips should fail early instead of falling back.

Final outputs are written under:

```text
output/<project>-clean.mp4
output/<project>-sub.mp4
pipeline/<project>/film_assembled.mp4
pipeline/<project>/remotion_preview.yaml
pipeline/<project>/remotion_preview/
pipeline/<project>/render_report.yaml
pipeline/<project>/director_review.yaml
pipeline/<project>/assistant_handoff.yaml
film_timeline.yaml
```

## 5. Run One Stage

Dependencies are resolved automatically:

```powershell
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p .narrascape/my-video --stage qa --approve
```

This pulls in the required upstream stages before `qa`.

## 6. Run AI Director Only

```powershell
.\.venv_test\Scripts\python.exe -m narrascape.cli design -p .narrascape/my-video --auto-approve
```

Outputs:

```text
design_report.yaml
image_prompts.yaml
image_map.yaml
```

In `ai_assistant` or `bridge` mode, this may create task files under `.narrascape/bridge/pending/`. Process those tasks with the assistant, then rerun the command or let the waiting command continue.

## 7. Seedance Video Clips

The standard final-video path is `film_timeline` driven. The default build
includes `generate_video` in `auto` mode. To run only the native image-to-video
stage with Seedance:

```powershell
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p .narrascape/my-video --stage generate_video --approve
```

This requires `ARK_API_KEY` and generated images.
It also pulls in `reference_plate`, `storyboard_sheet`, and `animatic`, so missing storyboard
references or panel images are caught before provider execution.

`film_timeline` prefers `assets/videos/vid_*.mp4`, then source footage, then
generated-image fallback.

The build also writes `pipeline/<project>/remotion_preview/`. To inspect the
timeline as a Remotion composition, install dependencies in that directory and
run `npx remotion studio`.

## 8. Approval Modes

```powershell
# Automatic, useful for tests and CI
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p .narrascape/my-video --approve

# Interactive review after each stage
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p .narrascape/my-video --interactive

# Manual approvals
.\.venv_test\Scripts\python.exe -m narrascape.cli approve -p .narrascape/my-video -s design
.\.venv_test\Scripts\python.exe -m narrascape.cli reject -p .narrascape/my-video -s design --notes "Revise style"
.\.venv_test\Scripts\python.exe -m narrascape.cli status -p .narrascape/my-video
```

## 9. Verify The Codebase

```powershell
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m pytest -q --tb=short --no-cov
```
