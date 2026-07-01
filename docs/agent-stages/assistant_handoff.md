# Assistant Handoff Stage Director

## Inputs

- `pipeline/<project>/film_supervisor.yaml`
- Optional `pipeline/<project>/render_report.yaml`
- Optional `pipeline/<project>/production_readiness.yaml`
- Optional `pipeline/<project>/state.json`

## Outputs

- `pipeline/<project>/assistant_handoff.yaml`
- `pipeline/<project>/assistant_handoff.md`

## Procedure

1. Read the latest supervisor decision.
2. Collect next stages and map each one to its agent-stage doc.
3. Summarize core artifacts, quality gates, blocking findings, and stage state.
4. Write a machine-readable takeover packet for Codex-style assistants.
5. Write a Markdown summary for humans.

## Do Not

- Do not mutate media.
- Do not call providers.
- Do not invent rework actions. Consume `film_supervisor.yaml`,
  `render_report.yaml`, and `production_readiness.yaml`.
- Do not hide missing director artifacts; mark them in the artifact summary.
