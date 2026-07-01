# Narrascape Agent Guide

This repository is an AI film-production pipeline. When a coding assistant such
as Codex takes over a Narrascape project, use the pipeline artifacts as the
source of truth instead of improvising one-off scripts.

## First Read

1. `README.md`
2. `docs/ai-director.md`
3. `docs/assistant-handoff.md`
4. `pipeline/<project>/assistant_handoff.yaml` when it exists
5. The relevant `docs/agent-stages/<stage>.md` file before touching a stage

## Rule Zero

All production work goes through stages. Do not bypass the pipeline to call
image, video, voice, music, or render providers directly unless the user is
explicitly asking to add or debug provider code.

## Production Boundaries

- Treat `director_contract.yaml` and `reference_plates.yaml` as the executable
  visual contract.
- Treat `film_timeline.yaml` as the editorial spine.
- Treat `render_report.yaml`, `visual_semantic_report.yaml`,
  `rework_plan.yaml`, and `film_supervisor.yaml` as the review and rework loop.
- For production video, do not accept `llm.mode: none`,
  `llm_status: not_configured`, or `fallback_after_error` director artifacts.
- Before paid or consequential provider calls, state the provider, model,
  target stage, reason, and whether the run is a sample or batch.

## Standard Takeover Flow

```text
narrascape status -p <project>
narrascape build -p <project> --stage assistant_handoff --approve
read pipeline/<project>/assistant_handoff.yaml
read the listed stage docs
run the next requested stage through narrascape build
run tests or QA
refresh assistant_handoff
```

## Verification

For repository changes, prefer:

```bash
ruff check src tests
black --check src tests
mypy
pytest -q --tb=short --no-cov
```

For project-output changes, run the relevant stage plus `qa` and refresh
`assistant_handoff`.
