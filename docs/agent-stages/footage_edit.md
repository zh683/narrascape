# Footage Edit Stage Director

## Inputs

- `asset_manifest.yaml`
- `footage_timeline.yaml`
- `source_media/`

## Outputs

- `pipeline/<project>/source_media_segments/*.mp4`
- `pipeline/<project>/footage_roughcut.mp4`

## Procedure

1. Read `footage_timeline.yaml`.
2. Confirm each edit source file still exists.
3. Render each edit to the project resolution and frame rate.
4. Preserve the requested source in/out and duration.
5. Concatenate rendered edits into `footage_roughcut.mp4`.
6. Report failed edit ids instead of silently dropping them.

## Do Not

- Do not replace missing footage with generated placeholders.
- Do not mutate the user-provided source files.
- Do not ignore failed edit renders.
- Do not assume source clips already match the delivery resolution.
