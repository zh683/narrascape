# Generate Images Stage Director

## Inputs

- `image_prompts.yaml`
- `image_map.yaml`
- `assets/references/` when references are used
- image provider configuration
- `ARK_API_KEY` for Seedream or `AGNES_API_KEY` for Agnes

## Outputs

- `assets/images/img_*.png`
- `pipeline/<project>/image_gen_state.json`

## Procedure

1. Read each prompt entry and preserve image ids.
2. Preserve reference image ordering.
3. Confirm `negative_prompt` is present for LLM-designed prompts.
4. Select the image provider through `ProviderSelector` before execution.
5. For Agnes Image 2.1 Flash, send `extra_body.response_format: url` and place image-to-image references under `extra_body.image`.
6. Use local provider only for offline verification.
7. Record `provider_selection` in stage metadata and `image_gen_state.json`.
8. After generation, verify every mapped image id exists.

## Do Not

- Do not overwrite production images without review.
- Do not drop `reference_images` or `seedream_sample_strength`.
- Do not silently switch from creative provider output to local placeholders.
- Do not put Agnes `response_format` at the top level; the provider expects it under `extra_body`.
