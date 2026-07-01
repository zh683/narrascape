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
6. When an action is `rewrite_director_contract`, include the full creative
   regeneration chain: `director_contract`, `reference_plate`,
   `generate_images`, `animatic`, `generate_video`, `take_select`, and
   `film_timeline`.
7. Keep downstream validation stages in the next cycle so regenerated shots are
   assembled, QA checked, reviewed, replanned, and supervised again.
8. Include `assistant_handoff` after supervision so Codex-style assistants can
   read a fresh takeover packet before the next intervention.

## Do Not

- Do not mutate media files.
- Do not run provider calls or mutate assets from this stage.
- Do not hide unresolved rework actions.
- Do not mark a film approved while `next_stages` still contains unresolved rework. The pipeline executor may automatically run `rework_execute` after this stage when `pipeline.auto_rework` is enabled.
