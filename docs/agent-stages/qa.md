# QA Stage Director

## Inputs

- `output/<project>-sub.mp4`
- `pipeline/<project>/subtitles.srt`
- `pipeline/<project>/timing.json`
- `pipeline/<project>/state.json`
- optional `film_timeline.yaml`
- optional `asset_manifest.yaml`

## Outputs

- `pipeline/<project>/render_report.yaml`

## Procedure

1. Confirm the final subtitled video exists and is non-empty.
2. Run ffprobe validation.
3. Check video stream, audio stream, duration, and resolution.
4. Check subtitles, expected duration tolerance, silence, black frames, repeated shots, and local placeholder residue.
5. Check film-level coverage from `film_timeline.yaml`: missing visual segments, missing generated-video clips, missing timeline video files, continuity risk, and pacing risk.
6. Treat QA errors as release blockers and warnings as review items.
7. Allow `director_review` to consume the report even when QA fails.
8. Report exact failed checks to the user.

## Do Not

- Do not claim the video is complete if QA fails.
- Do not ignore missing audio or missing subtitles.
- Do not replace QA with a simple file-exists check.
- Do not treat configured black gaps or ending cards as unexpected black-frame failures.
- Do not ignore `timeline_segments/` when checking repeated shots.
