# Research Stage Director

## Inputs

- project title or an explicitly supplied research topic
- configured research engine and LLM client

## Outputs

- `research_report.md`

## Procedure

1. Resolve the requested topic without changing project identity.
2. Run the research engine through the configured LLM boundary.
3. Preserve source and confidence information returned by the engine.
4. Atomically write the report for the writing stage.

## Do Not

- Do not fabricate citations or claim unverified sources.
- Do not trigger media generation from research.
- Do not overwrite an authored report with an empty result.
