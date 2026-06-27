# Visual Semantic QA Stage Director

## Inputs

- `film_timeline.yaml`
- `design_report.yaml`
- Optional `pipeline/<project>/continuity_bible.yaml`
- Optional `pipeline/<project>/render_report.yaml`
- Optional `pipeline/<project>/director_contract.yaml`
- Optional LLM client

## Outputs

- `pipeline/<project>/visual_semantic_report.yaml`

## Procedure

1. Read visual clips and their file paths from `film_timeline.yaml`.
2. Read expected character, location, wardrobe, and shot intent from `design_report.yaml`.
3. Read `director_contract.yaml` when present, including `qa.must_show`, `qa.must_not_show`, and `storyboard_binding`.
4. If an LLM client is configured, ask it to judge visual match against the script, director intent, and director contract.
5. If no LLM is configured, flag metadata mismatches such as scene or wardrobe drift, contract assertion mismatches, and storyboard scene, wardrobe, character-position, or composition mismatches against timeline metadata.
6. Write findings with segment id, risk type, severity, and evidence.

## Do Not

- Do not claim pixel-level semantic certainty in fallback mode.
- Do not ignore contract assertions when `director_contract.yaml` exists.
- Do not ignore `storyboard_binding` when it exists.
- Do not mutate `film_timeline.yaml`.
- Do not delete or quarantine media files.
- Do not treat file validity checks as semantic checks; those belong to `qa`.
