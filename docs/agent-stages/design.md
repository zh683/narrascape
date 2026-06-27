# Design Stage Director

## Inputs

- `scripts/script.yaml`
- `pipeline/<project>/pre_production.yaml` when available
- `config.yaml`
- LLM mode from `llm.mode`

## Outputs

- `design_report.yaml`
- `image_prompts.yaml`
- `image_map.yaml`

## Procedure

1. Confirm the script exists and has ordered segments.
2. If LLM mode is `ai_assistant` or `bridge`, process pending bridge tasks exactly as written.
3. Inspect `design_report.yaml` after generation.
4. Verify every segment has a shot design, image prompt, and mapping entry.
5. For production work, reject `llm.mode: none` unless the user explicitly wants offline verification.

## Do Not

- Do not hand-write `image_prompts.yaml` when the user asked for AI Director output.
- Do not treat local deterministic fallback as creative LLM output.
- Do not skip `pre_production` when reference consistency matters.
