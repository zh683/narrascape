# Generate Images Stage Director

## Inputs

- `image_prompts.yaml`
- `image_map.yaml`
- `assets/references/` when references are used
- image provider configuration
- `ARK_API_KEY` for Seedream

## Outputs

- `assets/images/img_*.png`
- `pipeline/<project>/image_gen_state.json`
- `pipeline/<project>/prompt_safety.yaml` (sanitize audit, only when a prompt was rewritten)

## Procedure

1. Read each prompt entry and preserve image ids.
2. Preserve reference image ordering.
3. Confirm `negative_prompt` is present for LLM-designed prompts.
4. Select the image provider through `ProviderSelector` before execution.
5. Skip regeneration only when the output image exists AND its stored request fingerprint (prompt, model, size, reference content, under the `fingerprints` key in `image_gen_state.json`) matches the current request.
6. Send Seedream text-to-image or image-to-image requests with resolved reference images.
7. Use local provider only for offline verification.
8. Record `provider_selection` in stage metadata and `image_gen_state.json`.
9. After generation, verify every mapped image id exists.

## Do Not

- Do not overwrite production images without review.
- Do not drop `reference_images` or `seedream_sample_strength`.
- Do not silently switch from creative provider output to local placeholders.
