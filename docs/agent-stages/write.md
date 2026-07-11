# Write Stage Director

## Inputs

- `research_report.md` or configured project topic
- project title, ending tone, and segment-count configuration
- configured LLM client

## Outputs

- `scripts/script_raw.yaml`
- `scripts/script.yaml`
- `scripts/script_approved.yaml` when approval is recorded

## Procedure

1. Load existing research or create it through the research engine.
2. Draft narration with stable segment ids and production metadata.
3. Add the configured ending without changing prior segment identity.
4. Preserve a backup before replacing an existing canonical script.
5. Validate and atomically write raw and canonical script artifacts.

## Do Not

- Do not bypass the script artifact schema.
- Do not erase an authored script after an empty or failed LLM response.
- Do not start image, voice, or video generation from this stage.
