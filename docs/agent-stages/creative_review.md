# Creative Review Stage Director

## Inputs

- `film_timeline.yaml`
- `pipeline/<project>/editing_review.yaml`
- `pipeline/<project>/continuity_bible.yaml`
- Optional `pipeline/<project>/render_report.yaml`
- Optional LLM client

## Outputs

- `pipeline/<project>/creative_review.yaml`

## Procedure

1. Read the timeline, editing review, continuity bible, QA report, and script.
2. If an LLM client is configured, ask it to review story clarity, cinematic intent, pacing, emotion, and continuity.
3. If no LLM is configured, convert existing director findings into deterministic creative findings.
4. Write findings and recommendations.
5. Mark status `needs_rework` when recommendations exist.

## Do Not

- Do not fabricate LLM creativity when no LLM client is configured.
- Do not mutate media files.
- Do not replace `rework_plan.yaml`; this stage only contributes recommendations.
- Do not approve a film with unresolved high-severity findings.
