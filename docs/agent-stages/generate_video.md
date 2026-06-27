# Generate Video Stage Director

## Inputs

- `pipeline/<project>/design_report.yaml` or `design_report.yaml`
- `pipeline/<project>/director_contract.yaml`
- `assets/images/img_*.png`
- video provider configuration
- `ARK_API_KEY` for Seedance/Volcengine generation

## Outputs

- `assets/videos/vid_*.mp4`
- `pipeline/<project>/video_gen_state.json`

## Procedure

1. Select the video provider through `ProviderSelector`.
2. Read AI Director shot metadata from the design report.
3. Read `director_contract.yaml` and prefer each shot's `generation.video_prompt` when present.
4. Use generated images as first-frame references when available.
5. Submit asynchronous video generation tasks.
6. Poll each task until it succeeds or fails.
7. Download completed clips to `assets/videos/vid_*.mp4`.
8. Record completed clip ids and `provider_selection` in `video_gen_state.json`.
9. Run `film_timeline` after generation so completed clips become first-class timeline visuals.

## Do Not

- Do not leave generated videos as side outputs; they must be consumed by `film_timeline`.
- Do not ignore `director_contract.yaml` when it exists.
- Do not silently fall back to local placeholders for production video generation.
- Do not skip provider selection metadata.
- Do not overwrite completed clips unless the user requested a rebuild.
