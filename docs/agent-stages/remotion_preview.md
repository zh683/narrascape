# Remotion Preview Stage Director

## Inputs

- `film_timeline.yaml`
- visual assets referenced by timeline clips

## Outputs

- `pipeline/<project>/remotion_preview.yaml`
- `pipeline/<project>/remotion_preview/package.json`
- `pipeline/<project>/remotion_preview/public/timeline.json`
- `pipeline/<project>/remotion_preview/public/assets/*`
- `pipeline/<project>/remotion_preview/src/*`

## Procedure

1. Read `film_timeline.yaml`.
2. Sort visual clips by timeline `start`.
3. Copy referenced generated videos, source footage, and generated images into the Remotion `public/assets/` folder.
4. Convert the timeline into `public/timeline.json` and `src/timeline-data.json`.
5. Generate a minimal Remotion composition using `Sequence`, `Img`, `Video`, and `staticFile()`.
6. Write `remotion_preview.yaml` with composition metadata, copied assets, missing assets, and local Remotion commands.
7. Fail the stage when required visual assets are missing instead of producing a misleading preview.

## Do Not

- Do not replace `film_assemble` as the final render path until the Remotion renderer is explicitly promoted.
- Do not mutate `film_timeline.yaml`.
- Do not install Node packages or run network commands during the stage.
- Do not silently drop timeline clips that have missing media.
