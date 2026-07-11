# Concat Stage Director

## Inputs

- `pipeline/<project>/video_segments/`
- visual gap and ending configuration

## Outputs

- `pipeline/<project>/body_concat.mp4`
- `pipeline/<project>/final_nosub.mp4`

## Procedure

1. Order rendered segments by script segment id.
2. Generate configured black gaps between segments.
3. Write an FFmpeg concat manifest using resolved local paths.
4. Append the ending card when enabled.
5. Validate and atomically promote the final unsubtitled video.

## Do Not

- Do not reorder segments by filesystem discovery order.
- Do not reuse stale gap or ending media without validation.
- Do not write directly to the final output during rendering.
