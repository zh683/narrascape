# Pre-Production Stage Director

## Inputs

- `scripts/script.yaml`
- optional `director_notes.md`
- visual style and image provider configuration
- configured LLM client for production direction

## Outputs

- `pipeline/<project>/pre_production.yaml`
- `assets/references/` character, environment, and style references
- `assets/storyboard/` authored storyboard frames when generated

## Procedure

1. Read the script and extract characters, environments, visual rules, and storyboard intent.
2. Use the LLM director path for production work; label deterministic output as offline fallback.
3. Build character turnarounds, expressions, scene references, and storyboard descriptions.
4. Reserve provider budget before reference generation and record provider tasks.
5. Validate references and atomically write the canonical pre-production artifact.

## Do Not

- Do not bypass `director_notes.md` or existing visual constraints.
- Do not accept `llm_status: not_configured` for production video work.
- Do not overwrite curated references after a failed provider call.
