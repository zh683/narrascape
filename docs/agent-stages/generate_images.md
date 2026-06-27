# Generate Images Stage Director

## Inputs

- `image_prompts.yaml`
- `image_map.yaml`
- `assets/references/` when references are used
- image provider configuration

## Outputs

- `assets/images/img_*.png`
- `pipeline/<project>/image_gen_state.json`

## Procedure

1. Read each prompt entry and preserve image ids.
2. Preserve reference image ordering.
3. Confirm `negative_prompt` is present for LLM-designed prompts.
4. Select the image provider through `ProviderSelector` before execution.
5. Use local provider only for offline verification.
6. Record `provider_selection` in stage metadata and `image_gen_state.json`.
7. After generation, verify every mapped image id exists.

## Do Not

- Do not overwrite production images without review.
- Do not drop `reference_images` or `seedream_sample_strength`.
- Do not silently switch from creative provider output to local placeholders.
