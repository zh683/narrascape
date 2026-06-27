# Director Review Stage Director

## Inputs

- `pipeline/<project>/render_report.yaml`
- Film QA checks written by `qa`

## Outputs

- `pipeline/<project>/director_review.yaml`

## Procedure

1. Read `render_report.yaml`.
2. Mark missing visual segments for `regenerate_video`.
3. Mark missing generated-video segments for `regenerate_video`.
4. Mark missing timeline video files for `regenerate_video`.
5. Mark continuity-risk segments for regeneration review.
6. Mark pacing-risk segments for `recut`.
7. Deduplicate identical segment/action/reason entries.
8. Write `status: needs_rework` when the queue or QA errors are present.

## Do Not

- Do not hide QA failures behind an approved status.
- Do not mutate `film_timeline.yaml` directly from this stage.
- Do not discard failed segment ids.
- Do not claim the render is final when the rework queue is non-empty.
