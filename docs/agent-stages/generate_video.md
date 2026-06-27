# Generate Video Stage Director

## Inputs

- `pipeline/<project>/design_report.yaml` or `design_report.yaml`
- `pipeline/<project>/director_contract.yaml`
- Optional `pipeline/<project>/pre_production.yaml`
- `assets/images/img_*.png`
- Optional `assets/references/*`
- video provider configuration
- `ARK_API_KEY` for Seedance/Volcengine generation

## Outputs

- `assets/videos/vid_*.mp4`
- `pipeline/<project>/video_gen_state.json`

## Procedure

1. Select the video provider through `ProviderSelector`.
2. Read AI Director shot metadata from the design report.
3. Read `director_contract.yaml` and prefer each shot's `generation.video_prompt` when present.
4. Resolve `storyboard_binding.reference_image_ids` to actual style, character, and scene reference images.
5. Use generated images as first-frame references when available.
6. Send resolved style, character, and scene images as Seedance `reference_image` inputs.
7. Submit asynchronous video generation tasks.
8. Poll each task until it succeeds or fails.
9. Download completed clips to `assets/videos/vid_*.mp4`.
10. Record completed clip ids, `provider_selection`, expected reference ids, resolved assets, missing ids, and uploaded reference counts in `video_gen_state.json`.
11. Run `film_timeline` after generation so completed clips become first-class timeline visuals.

## Do Not

- Do not leave generated videos as side outputs; they must be consumed by `film_timeline`.
- Do not ignore `director_contract.yaml` when it exists.
- Do not leave `storyboard_binding.reference_image_ids` as YAML-only metadata.
- Do not silently fall back to local placeholders for production video generation.
- Do not skip provider selection metadata.
- Do not overwrite completed clips unless the user requested a rebuild.
