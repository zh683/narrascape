# Reference Plate Stage Director

## Inputs

- `pipeline/<project>/director_contract.yaml`
- Optional `pipeline/<project>/pre_production.yaml`
- `pipeline/<project>/design_report.yaml` or `design_report.yaml`
- `assets/references/*`

## Outputs

- `pipeline/<project>/reference_plates.yaml`

## Procedure

1. Read every shot in `director_contract.yaml`.
2. Resolve style, character, scene, storyboard, and design reference ids into concrete files or URLs.
3. Preserve storyboard frame ids, character positions, scene refs, wardrobe locks, composition requirements, compiled provider prompts, provider negative prompts, and QA requirements.
4. Write one plate per shot.
5. Mark the report `blocked` when any required reference id cannot be resolved.
6. Treat missing references as stage-blocking only when
   `pipeline.video_generation: required`; in `auto` or `off` mode, keep the
   findings in the report but allow offline/local fallback verification to
   continue.

## Do Not

- Do not invent or silently ignore missing character or scene references.
- Do not block no-network smoke tests merely because production reference images
  are absent; record the risk and let downstream QA/rework see it.
- Do not upload media in this stage; `generate_video` owns provider execution.
- Do not rewrite director prompts here; consume the compiled prompts from `director_contract`.
- Do not let `generate_video` become the first place missing references are discovered.
