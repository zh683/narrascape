# Generate Video Stage Director

## Inputs

- `pipeline/<project>/design_report.yaml` or `design_report.yaml`
- `pipeline/<project>/director_contract.yaml`
- `pipeline/<project>/reference_plates.yaml`
- `pipeline/<project>/animatic.yaml`
- Optional `pipeline/<project>/pre_production.yaml`
- `assets/images/img_*.png`
- Optional `assets/references/*`
- video provider configuration
- `ARK_API_KEY` for Seedance/Volcengine generation

## Outputs

- `assets/videos/vid_*.mp4`
- `assets/videos/vid_<segment>_take_<take>.mp4` when `video.takes > 1`
- `pipeline/<project>/video_prompt_quality.yaml`
- `pipeline/<project>/video_gen_state.json`

## Procedure

1. Select the video provider through `ProviderSelector`.
2. Read AI Director shot metadata from the design report.
3. Read `director_contract.yaml` and, when a provider is selected, prefer `generation.compiled_prompts.<provider>.prompt`; fall back to `generation.video_prompt` for legacy contracts.
4. Write `video_prompt_quality.yaml` with per-shot ingredient scores for subject identity, action beat, scene lock, wardrobe lock, camera language, composition, lighting/palette, style/quality, and reference binding.
5. Block generation if the prompt is still generic or lacks the executable ingredients needed for controllable video generation.
6. Read the matching provider negative prompt and pass it to Seedance when supported.
7. Require the animatic preview to exist so storyboard timing has been checked before provider execution.
8. Resolve `storyboard_binding.reference_image_ids` to actual style, character, and scene reference images.
9. Use generated images as first-frame references when available.
10. Resolve explicit `reference_image_chains` with `usage_mode: last_frame` or
    ending/final-frame chain ids into provider last-frame inputs for bookended
    shot continuity.
11. Send resolved style, character, and scene images to the selected provider.
   - Seedance receives multimodal `reference_image` inputs.
12. If `video.takes > 1`, submit one asynchronous task per take using stable
   `vid_<segment>_take_<take>` names.
13. Poll each task until it succeeds or fails.
14. Download completed clips to `assets/videos/`.
15. Record completed clip ids, `provider_selection`, `take_policy`, generated
    take ids, expected reference ids, resolved assets, missing ids, and uploaded
    reference counts in `video_gen_state.json`.
16. Run `film_timeline` after generation so completed clips become first-class timeline visuals.

## Do Not

- Do not leave generated videos as side outputs; they must be consumed by `film_timeline`.
- Do not ignore `director_contract.yaml` when it exists.
- Do not send a generic prompt when a provider-specific compiled prompt exists.
- Do not drop the provider-specific negative prompt.
- Do not leave `storyboard_binding.reference_image_ids` as YAML-only metadata.
- Do not treat ordinary character/style reference chains as last-frame inputs;
  last-frame use must be explicit.
- Do not bypass the animatic preview in the default production chain.
- Do not send under-specified or template-like prompts to paid video providers.
- Do not silently fall back to local placeholders for production video generation.
- Do not skip provider selection metadata.
- Do not generate multiple takes unless `video.takes` requests them.
- Do not overwrite completed clips unless the user requested a rebuild.
