# Animatic Stage Director

## Inputs

- `pipeline/<project>/reference_plates.yaml`
- `pipeline/<project>/pre_production.yaml`
- `pipeline/<project>/timing.json`
- `assets/images/img_*.png`

## Outputs

- `pipeline/<project>/animatic.yaml`
- `pipeline/<project>/animatic.mp4`
- `pipeline/<project>/animatic_panels/*.mp4`

## Procedure

1. Read storyboard frames and per-shot reference plates.
2. Convert each storyboard frame into a timed panel.
3. Use generated still images as the visual source for each segment.
4. Preserve storyboard frame ids, reference plate ids, scene refs, character positions, composition requirements, and duration hints in `animatic.yaml`.
5. Render one still-image panel clip per storyboard frame, then concatenate them into `animatic.mp4`.
6. Mark the report `blocked` if any required panel image is missing.

## Do Not

- Do not call video generation providers from this stage.
- Do not treat the animatic as final footage.
- Do not silently skip missing panel images.
- Do not rewrite director intent; consume `reference_plates.yaml` and storyboard data.
