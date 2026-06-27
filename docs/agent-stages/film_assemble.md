# Film Assemble Stage Director

## Inputs

- `film_timeline.yaml`
- `assets/videos/vid_*.mp4` when generated video clips exist
- `source_media/` clips referenced by the timeline
- `assets/images/img_*.png` for generated-image fallback

## Outputs

- `pipeline/<project>/timeline_segments/*.mp4`
- `pipeline/<project>/film_assemble.txt`
- `pipeline/<project>/film_assembled.mp4`

## Procedure

1. Read `film_timeline.yaml`.
2. Sort visual clips by timeline `start`.
3. Render generated-video and source-media clips with source in/out and duration.
4. Render generated-image fallback clips as still video segments.
5. Insert black timeline gaps when clip start times leave holes.
6. Render ending cards when the timeline includes them.
7. Concatenate rendered segments into `film_assembled.mp4`.
8. Report failed clip ids instead of silently dropping them.

## Do Not

- Do not bypass `film_timeline.yaml` and rebuild an implicit order from filenames.
- Do not replace missing generated video with a still image inside this stage; fallback belongs in `film_timeline`.
- Do not mutate user source footage or generated source assets.
- Do not ignore timeline `start`, `duration`, or `source_in`.
