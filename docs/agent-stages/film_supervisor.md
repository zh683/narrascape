# Film Supervisor Stage Director

## Inputs

- `pipeline/<project>/rework_plan.yaml`
- `pipeline/<project>/creative_review.yaml`
- `pipeline/<project>/visual_semantic_report.yaml`
- Optional `pipeline/<project>/render_report.yaml`

## Outputs

- `pipeline/<project>/film_supervisor.yaml`

## Procedure

1. Read all director and QA reports.
2. Count rework actions, creative recommendations, visual findings, and blocking render errors.
3. Decide whether the film is approved or needs rework.
4. Write the next stage list for the next production cycle.
5. Include `rework_execute` when actions need to be applied.

## Do Not

- Do not mutate media files.
- Do not run the stages it recommends.
- Do not hide unresolved rework actions.
- Do not automatically execute `rework_execute`; that remains an explicit stage.
