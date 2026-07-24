# Director Contract Stage Director

## Inputs

- `scripts/script.yaml`
- `design_report.yaml` or `pipeline/<project>/design_report.yaml`
- `pipeline/<project>/screenplay_structure.yaml`
- Optional `pipeline/<project>/pre_production.yaml`
- Optional `pipeline/<project>/continuity_bible.yaml`
- Optional LLM client

## Outputs

- `pipeline/<project>/director_contract.yaml`

## Procedure

1. Read the screenplay structure, design report, script segments, storyboard frames, and any available continuity bible.
2. If an LLM client is configured, ask it to act as a top-tier film director and prompt compiler.
3. For every shot, compile story purpose, emotional target, film language, continuity constraints, storyboard binding, generation instructions, and QA assertions.
4. Write `generation.video_prompt`, `generation.negative_prompt`, `generation.duration`, and `generation.motion` as the portable execution contract.
5. Compile provider-specific prompt variants under `generation.compiled_prompts`, especially `seedance` plus a `generic` fallback, with the provider prompt style, negative prompt, and reference strategy.
6. Write `storyboard_binding.storyboard_frame_ids`, `character_positions`, `scene_ref`, `wardrobe_lock`, `composition_requirements`, and `reference_image_ids` when storyboard frames are available.
7. Write `qa.must_show` and `qa.must_not_show` so `visual_semantic_qa` can review the same contract that guided generation.
8. Tag every QA assertion with a stable dimension from `narrascape.contracts.qa_taxonomy.QA_DIMENSIONS` and write the tagged checklist to `qa.assertions` (and `prompt_blueprint.qa_assertions.assertions`). The LLM path is instructed to tag assertions itself; the deterministic fallback emits a default checklist covering all six dimensions per shot. Legacy contracts without `assertions` stay valid — readers bucket them as `uncategorized`.

## QA Assertion Dimensions

`qa.assertions` entries are `{id, dimension, check}`. The dimension taxonomy (Stable-cinemetrics-inspired) is fixed:

| Dimension | Review intent |
|---|---|
| `identity_continuity` | Correct character identity: face, age, body, wardrobe locked to references |
| `dialogue_attribution` | The right character says/acts the right narration beat |
| `camera_language` | Shot type, camera motion, lighting, composition execute the film-language plan |
| `motion_plausibility` | Subject action and camera movement are physically plausible |
| `scene_consistency` | Location, geography, props, time-of-day coherent with continuity locks |
| `technical_quality` | No readable text, watermark, flicker, artifacts, low-quality frames |

Anything outside these ids (legacy contracts, malformed LLM output) is tolerated and bucketed as `uncategorized`; the flat `must_show` / `must_not_show` planes always stay populated alongside the tagged checklist.

## Do Not

- Do not leave director thinking as prose that no later stage consumes.
- Do not add provider-specific prompt instructions only to docs; they must compile into `generation.compiled_prompts`.
- Do not treat storyboard frames as optional prose once `pre_production.yaml` exists; bind them to the shot contract.
- Do not invent media files or mark shots as rendered.
- Do not bypass `screenplay_structure.yaml`; shot contracts must remain traceable to act, scene, sequence, and shot.
- Do not claim fallback mode is creative LLM direction; it is deterministic contract compilation for offline verification.
