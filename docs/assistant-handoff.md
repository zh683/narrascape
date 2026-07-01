# Assistant Handoff Protocol

Narrascape is designed so an AI coding assistant can take over a project without
guessing the current production state. The `assistant_handoff` stage writes:

- `pipeline/<project>/assistant_handoff.yaml`
- `pipeline/<project>/assistant_handoff.md`

The YAML file is the machine-readable takeover packet. The Markdown file is the
human-readable version.

## What It Solves

Before this stage, an assistant could inspect many files, but it had to infer:

- which director reports mattered now
- which stage docs to read
- which stage to run next
- whether generated video was blocked by QA, readiness gates, or rework queues
- whether the run was production-safe or only an offline fallback

`assistant_handoff` turns those assumptions into one explicit artifact.

## Borrowed Lessons From Related Projects

- [OpenMontage](https://github.com/calesthio/OpenMontage) puts a strong rule
  around agent-driven production: the coding assistant must select a pipeline,
  read stage director instructions, run preflight, communicate decisions, and
  avoid ad-hoc provider calls. Narrascape adopts that idea through
  `AGENTS.md`, agent-stage docs, and the generated handoff packet.
- [ViMax](https://github.com/HKUDS/ViMax) emphasizes agentic video generation,
  reference-image management, storyboarding, and consistency checks. Narrascape
  already has `reference_plates.yaml`, `storyboard_sheet`, `animatic`, and
  `visual_semantic_qa`; the handoff packet exposes those artifacts to Codex as
  required context.
- StoryAgent-style multi-agent work separates story design, storyboard,
  generation, coordination, and evaluation. Narrascape maps those concerns to
  explicit stages and uses `film_supervisor` plus `assistant_handoff` as the
  coordination layer.

## Handoff Contents

| Field | Purpose |
| --- | --- |
| `status` | current takeover state: approved, needs rework, blocked by QA, or blocked before generation |
| `director_decision` | `film_supervisor.yaml` status and next stages |
| `assistant_contract` | rules the assistant must follow before acting |
| `required_reading` | README, AI Director docs, takeover docs, and next-stage docs |
| `artifacts` | key project artifacts and whether they exist |
| `quality_gates` | production-safety checks such as LLM mode, strict director mode, readiness, QA errors, and missing generated video |
| `next_actions` | stage-by-stage commands and intent |
| `blocking_items` | QA errors or production-readiness findings |
| `state_summary` | compact stage-state counts |
| `commands` | status, build, production build, and refresh commands |

## Standard AI Assistant Flow

```text
1. Run or read assistant_handoff.
2. Read every file listed in required_reading.
3. Treat director_contract.yaml and reference_plates.yaml as the visual contract.
4. Treat film_timeline.yaml as the editorial spine.
5. Run the next stage through narrascape build, not an ad-hoc script.
6. Run QA or tests.
7. Refresh assistant_handoff so the next takeover starts from current state.
```

## Production Rules

- Production video work should use `llm.mode: ai_assistant`, `bridge`, `api`, or
  `auto`, not `none`.
- `pipeline.strict_director: true` rejects fallback director artifacts.
- `pipeline.production_quality_gates: true` blocks generated-video work when
  script density, storyboard bindings, prompt blueprints, compiled prompts,
  continuity locks, or QA assertions are missing.
- Missing generated video should be handled through `rework_plan.yaml`,
  `rework_execute`, and queued reruns.

## Run It

```powershell
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p .narrascape/my-video --stage assistant_handoff --approve
```

or, after installation:

```bash
narrascape build -p my-video --stage assistant_handoff --approve
```
