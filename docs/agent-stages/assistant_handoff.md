# Assistant Handoff Stage Director

## Inputs

- `pipeline/<project>/film_supervisor.yaml`
- Optional `pipeline/<project>/render_report.yaml`
- Optional `pipeline/<project>/production_readiness.yaml`
- Optional `pipeline/<project>/state.json`
- Optional `.narrascape/bridge/pending/` (unanswered assistant bridge tasks)

## Outputs

- `pipeline/<project>/assistant_handoff.yaml`
- `pipeline/<project>/assistant_handoff.md`
- `pipeline/<project>/cost_report.yaml` (aggregated from `budget_state.json`)

## Procedure

1. Read the latest supervisor decision.
2. Collect next stages and map each one to its agent-stage doc.
3. Summarize core artifacts, quality gates, blocking findings, and stage state.
4. List unanswered bridge task files as `pending_bridge_tasks` (task id, task
   path, expected response path) so the takeover assistant knows what to
   answer first.
5. Write a machine-readable takeover packet for Codex-style assistants.
6. Write a Markdown summary for humans.

## Do Not

- Do not mutate media.
- Do not call providers.
- Do not invent rework actions. Consume `film_supervisor.yaml`,
  `render_report.yaml`, and `production_readiness.yaml`.
- Do not hide missing director artifacts; mark them in the artifact summary.
