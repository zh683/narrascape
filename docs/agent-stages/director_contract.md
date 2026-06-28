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
5. Compile provider-specific prompt variants under `generation.compiled_prompts`, currently including `seedance`, `agnes`, and `generic`, with each provider's prompt style, negative prompt, and reference strategy.
6. Write `storyboard_binding.storyboard_frame_ids`, `character_positions`, `scene_ref`, `wardrobe_lock`, `composition_requirements`, and `reference_image_ids` when storyboard frames are available.
7. Write `qa.must_show` and `qa.must_not_show` so `visual_semantic_qa` can review the same contract that guided generation.

## Do Not

- Do not leave director thinking as prose that no later stage consumes.
- Do not add provider-specific prompt instructions only to docs; they must compile into `generation.compiled_prompts`.
- Do not treat storyboard frames as optional prose once `pre_production.yaml` exists; bind them to the shot contract.
- Do not invent media files or mark shots as rendered.
- Do not bypass `screenplay_structure.yaml`; shot contracts must remain traceable to act, scene, sequence, and shot.
- Do not claim fallback mode is creative LLM direction; it is deterministic contract compilation for offline verification.
