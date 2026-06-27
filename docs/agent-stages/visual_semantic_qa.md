# Visual Semantic QA Stage Director

## Inputs

- `film_timeline.yaml`
- `design_report.yaml`
- Optional `pipeline/<project>/continuity_bible.yaml`
- Optional `pipeline/<project>/render_report.yaml`
- Optional `pipeline/<project>/director_contract.yaml`
- Optional `pipeline/<project>/pre_production.yaml`
- Optional `pipeline/<project>/video_gen_state.json`
- Optional LLM client

## Outputs

- `pipeline/<project>/visual_semantic_report.yaml`

## Procedure

1. Read visual clips and their file paths from `film_timeline.yaml`.
2. Read expected character, location, wardrobe, and shot intent from `design_report.yaml`.
3. Read `director_contract.yaml` when present, including `qa.must_show`, `qa.must_not_show`, and `storyboard_binding`.
4. Resolve expected reference images from `storyboard_binding.reference_image_ids`, character ids, scene refs, style anchors, and pre-production assets.
5. Read `video_gen_state.json` and verify generated videos actually recorded the expected reference-image execution handoff.
6. Extract representative frames from generated video and source footage clips into `pipeline/<project>/visual_semantic_frames/`.
7. If an LLM client is configured, ask it to judge visual match against the script, director intent, director contract, extracted frames, and reference image paths.
8. If no LLM is configured, flag metadata mismatches and reference execution failures, but do not claim true face or scene understanding.
9. Write findings with segment id, risk type, severity, and evidence.

## Do Not

- Do not claim pixel-level semantic certainty in fallback mode.
- Do not ignore contract assertions when `director_contract.yaml` exists.
- Do not ignore `storyboard_binding` when it exists.
- Do not ignore missing or unexecuted reference-image ids.
- Do not mutate `film_timeline.yaml`.
- Do not delete or quarantine media files.
- Do not treat file validity checks as semantic checks; those belong to `qa`.
