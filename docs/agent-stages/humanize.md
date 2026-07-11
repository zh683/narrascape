# Humanize Stage Director

## Inputs

- `scripts/script.yaml`
- configured LLM mode or deterministic humanizer

## Outputs

- updated `scripts/script.yaml`
- timestamped script backup when content changes

## Procedure

1. Load and validate the canonical script artifact.
2. Humanize narration while preserving segment ids and structural fields.
3. Keep a backup before replacing existing authored text.
4. Validate and atomically write the updated script artifact.

## Do Not

- Do not change segment ids or remove production metadata.
- Do not overwrite the script without a recoverable backup.
- Do not present deterministic offline rewriting as LLM-authored work.
