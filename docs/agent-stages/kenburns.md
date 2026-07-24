# Ken Burns Stage Director

## Inputs

- `assets/images/`
- `image_map.yaml` and `image_prompts.yaml`
- `pipeline/<project>/timing.json`
- visual and encode configuration

## Outputs

- `pipeline/<project>/video_segments/seg_*.mp4`

## Procedure

1. Match each script segment to image ids and narration duration.
2. Split duration across mapped images without losing segment order.
3. Render configured pan, zoom, fade, and supersampling behavior.
4. Validate each temporary segment before atomic promotion.
5. Report failed segment ids and keep successful outputs resumable.

## Do Not

- Do not silently substitute an unrelated image.
- Do not accept a zero-byte or unprobeable segment.
- Do not render indefinitely; use the shared FFmpeg timeout policy.
