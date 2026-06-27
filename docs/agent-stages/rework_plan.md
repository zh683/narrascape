# Rework Plan Stage Director

## Inputs

- `pipeline/<project>/director_review.yaml`
- `pipeline/<project>/editing_review.yaml`
- `pipeline/<project>/continuity_bible.yaml`

## Outputs

- `pipeline/<project>/rework_plan.yaml`

## Procedure

1. Read QA-derived director rework actions.
2. Read timeline editing recommendations.
3. Read continuity-bible risks.
4. Convert findings into executable actions.
5. Deduplicate by segment, action, and reason.
6. Group actions by `regenerate_video`, `recut`, and `replace_source_media`.
7. Mark the plan `needs_rework` when any action remains.

## Do Not

- Do not discard lower-level director findings.
- Do not silently approve a project with queued actions.
- Do not perform the regeneration or recut in this stage.
- Do not mutate source media, generated media, or the final render.
