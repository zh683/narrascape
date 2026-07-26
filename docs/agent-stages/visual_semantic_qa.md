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
3. Read `director_contract.yaml` when present, including `qa.must_show`, `qa.must_not_show`, the dimension-tagged `qa.assertions` checklist, and `storyboard_binding`.
4. Resolve expected reference images from `storyboard_binding.reference_image_ids`, character ids, scene refs, style anchors, and pre-production assets.
5. Read `video_gen_state.json` and verify generated videos actually recorded the expected reference-image execution handoff.
6. Extract `visual_semantic_qa.frames_per_clip` representative frames from each generated video and source clip into `pipeline/<project>/visual_semantic_frames/`, using shot-safe filenames.
7. If a multimodal LLM client is configured, attach the actual extracted frame and local reference-image bytes to the request. OpenAI-compatible clients receive image blocks, Anthropic receives base64 image sources, and bridge assistants receive workspace-local paths they can open. Organize review by QA dimension and require every finding to carry both its segment and shot identity when available.
8. If no LLM is configured, flag metadata mismatches and reference execution failures, but do not claim true face or scene understanding.
9. Write findings with segment id, risk type, severity, evidence, and a stable QA `dimension` (valid LLM label > `risk_type` mapping > `uncategorized`); write `dimension_summary` with per-dimension assertions/passed/failed/unevaluated counts. Record `review_process.pixel_evidence_reviewed` and `multimodal_image_count`; only the multimodal path may set the former true.

## QA Dimensions

Every finding is attributed to one dimension from `narrascape.contracts.qa_taxonomy.QA_DIMENSIONS` (`identity_continuity`, `dialogue_attribution`, `camera_language`, `motion_plausibility`, `scene_consistency`, `technical_quality`) or the `uncategorized` bucket. `dimension_summary` answers "which dimension failed" at a glance: `assertions` counts tagged checklist items across shots, `failed` counts findings, `passed = max(assertions - failed, 0)`, and `unevaluated` counts shots whose checklist has no assertion in that dimension (legacy contracts mark every dimension unevaluated). Findings keep all legacy keys; the `dimension` key is purely additive.

## Do Not

- Do not claim pixel-level semantic certainty in fallback mode.
- Do not treat file paths alone as pixel evidence.
- Do not ignore contract assertions when `director_contract.yaml` exists.
- Do not ignore `storyboard_binding` when it exists.
- Do not ignore missing or unexecuted reference-image ids.
- Do not mutate `film_timeline.yaml`.
- Do not delete or quarantine media files.
- Do not treat file validity checks as semantic checks; those belong to `qa`.
