# production_readiness

## Purpose

`production_readiness` is the final gate before generated video begins. It makes
sure the project is not spending video-generation attempts on weak preparation.

## Inputs

- `reference_plates.yaml`
- `storyboard_sheet.yaml`
- `animatic.yaml`
- `pre_production.yaml` when `pipeline.production_quality_gates: true`
- `director_contract.yaml` when `pipeline.production_quality_gates: true`
- `scripts/script.yaml`

## Outputs

- `pipeline/<project>/production_readiness.yaml`

## Default Checks

- Reference plates are `ready`.
- Storyboard sheet is `ready`.
- Animatic is `ready`.
- In `pipeline.video_generation: required`, any blocked gate fails the stage.
- In `pipeline.video_generation: auto`, blocked gates are recorded without
  pretending generated video is production-ready.

## Production Quality Gates

When `pipeline.production_quality_gates: true`, the stage also checks:

- Script segments are present and dense enough to direct.
- `pre_production.yaml` has character references.
- `pre_production.yaml` has scene/environment references.
- Every script segment has storyboard coverage.
- Storyboard frames include reference image ids, scene refs, and character positions.
- `director_contract.yaml` has one shot per script segment.
- Each shot has storyboard frame ids, reference image ids, wardrobe lock,
  characters, location, compiled prompts, prompt blueprint, and QA `must_show`
  assertions.

## Failure Meaning

A failure here means the project should go back to script, visual pre-production,
storyboard, or director-contract work before calling image/video providers again.
It is not a rendering failure; it is a preparation failure.
