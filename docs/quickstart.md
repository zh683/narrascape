# Quick Start

This guide builds a complete local video pipeline and explains where to switch from offline verification to real AI providers.

## 1. Run From Source

```powershell
cd C:\Users\32472\.openclaw\workspace\narrascape
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m narrascape.cli version
```

If installed as a package, use `narrascape` instead of `python -m narrascape.cli`.

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
pre_production -> design -> generate_images -> generate_tts -> film_timeline
-> film_assemble -> generate_music -> remix_audio -> audio -> subtitles -> qa
-> director_review
```

Final outputs are written under:

```text
output/<project>-clean.mp4
output/<project>-sub.mp4
pipeline/<project>/film_assembled.mp4
pipeline/<project>/render_report.yaml
pipeline/<project>/director_review.yaml
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

## 7. Optional Seedance Video Clips

The standard final-video path is `film_timeline` driven. To generate native image-to-video clips with Seedance:

```powershell
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p .narrascape/my-video --stage generate_video --approve
```

This requires `ARK_API_KEY` and generated images.

After `generate_video`, run the default build again. `film_timeline` will prefer
`assets/videos/vid_*.mp4`, then source footage, then generated-image fallback.

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
