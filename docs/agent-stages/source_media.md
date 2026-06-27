# Source Media Stage Director

## Inputs

- `source_media/`
- `scripts/script.yaml`

## Outputs

- `asset_manifest.yaml`
- `footage_timeline.yaml`

## Procedure

1. Scan supported local clips and stills under `source_media/`.
2. Write each asset with id, path, media type, provider, source, license, and metadata.
3. Probe video duration and resolution when ffprobe is available.
4. Build `footage_timeline.yaml` with ordered edit decisions.
5. Map footage edits to script segment ids where possible.
6. Preserve user-provided media paths and licensing notes.

## Do Not

- Do not treat generated images as source footage.
- Do not delete or move user media.
- Do not invent external licensing for local files.
- Do not collapse the footage timeline back into a flat file list.
