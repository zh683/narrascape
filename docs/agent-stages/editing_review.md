# Editing Review Stage Director

## Inputs

- `film_timeline.yaml`
- Optional `pipeline/<project>/render_report.yaml`

## Outputs

- `pipeline/<project>/editing_review.yaml`

## Procedure

1. Read visual clips from the film timeline.
2. Compute shot durations and pacing-risk segments.
3. Detect repeated visual assets or repeated shot risk from QA.
4. Build an emotion curve from timeline emotion and intensity metadata.
5. Recommend `recut` actions for pacing problems.
6. Recommend `replace_source_media` actions for repeated visual assets.

## Do Not

- Do not assemble or render media.
- Do not change `film_timeline.yaml` directly.
- Do not ignore QA warnings when `render_report.yaml` exists.
- Do not mark a timeline as final when recommendations are non-empty.
