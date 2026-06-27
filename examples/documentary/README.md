# Documentary Example

This is a small Narrascape project that demonstrates the standard script-to-video workflow.

## Run

From the repository root:

```powershell
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p examples/documentary --approve
```

Or, after installing the package:

```bash
narrascape build -p examples/documentary --approve
```

## Step By Step

```bash
narrascape design -p examples/documentary --auto-approve
narrascape build -p examples/documentary --stage generate_images --approve
narrascape build -p examples/documentary --stage generate_tts --approve
narrascape build -p examples/documentary --stage qa --approve
```

Requesting `qa` automatically resolves the required upstream stages.

## Project Files

```text
examples/documentary/
  config.yaml
  image_map.yaml
  scripts/script.yaml
  assets/
  pipeline/
  output/
```

## Standard Workflow

```text
pre_production -> design -> generate_images -> generate_tts -> generate_music
-> remix_audio -> kenburns -> concat -> audio -> subtitles -> qa
```

## Notes

- Use `llm.mode: none` plus local media providers for no-network verification.
- Use `llm.mode: ai_assistant`, `bridge`, or `api` for real AI Director output.
- `generate_video` is optional and requires Seedance/Ark credentials.

## See Also

- [Documentation index](../../docs/index.md)
- [Quick Start](../../docs/quickstart.md)
- [Feature Map](../../docs/features.md)
- [Configuration Reference](../../docs/config-reference.md)
