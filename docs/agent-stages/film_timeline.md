# Film Timeline Stage Director

## Inputs

- `scripts/script.yaml`
- `pipeline/<project>/design_report.yaml`
- `image_map.yaml`
- optional `pipeline/<project>/video_gen_state.json`
- optional `pipeline/<project>/take_selection.yaml`
- optional `assets/videos/vid_*.mp4`
- optional `asset_manifest.yaml`
- optional `footage_timeline.yaml`
- `pipeline/<project>/timing.json`
- optional `pipeline/<project>/subtitles.srt`

## Outputs

- `film_timeline.yaml`

## Procedure

1. Read script segments and narration timing.
2. Load AI Director shot metadata from the design report.
3. When `take_selection.yaml` exists, use the selected take as that segment's generated video; the base `vid_NN.mp4` glob only fills segments without a selection.
4. Emit an advisory (non-blocking) warning when multi-take files (`vid_*_take_*.mp4`) exist but `take_selection.yaml` is missing, because take files are invisible to the fallback glob.
5. Prefer generated video clips when `assets/videos/vid_*.mp4` exists and generation state allows them.
6. Prefer source-media edits when generated video is unavailable for the segment.
7. Use generated image clips as fallback visual coverage.
8. Add narration clip references for every script segment.
9. Add music zone references and subtitle references when present.
10. Record coverage for generated-video, source-media, generated-image, and missing-visual segments.
11. Leave visual preview and final rendering to downstream `remotion_preview` and `film_assemble`.

## Do Not

- Do not invent visual coverage when both source media and generated assets are missing.
- Do not treat `film_timeline.yaml` as a render output; it is the editorial contract.
- Do not bypass this timeline for future director review, re-cut, generated-video, sound-design, or color stages.
- Do not mutate source assets while building the timeline.
