# Reference Image And Storyboard Workflow

This document describes how pre-production data is meant to support consistent visual design.

## Purpose

The pre-production stage creates visual context before shot design:

- a style anchor
- character reference data
- environment reference data
- storyboard frames

The design stage can then consume that context instead of designing every shot in isolation.

## Current Flow

```text
scripts/script.yaml
        |
        v
PreProductionStage
        |
        v
pipeline/<project>/pre_production.yaml
        |
        v
DesignStage
        |
        v
design_report.yaml
image_prompts.yaml
image_map.yaml
        |
        v
director_contract.yaml
        |
        v
reference_plates.yaml
        |
        v
animatic.yaml + animatic.mp4
        |
        v
generate_video -> video_gen_state.json
        |
        v
visual_semantic_qa
```

Generated reference assets are stored under:

```text
assets/references/
```

## Pre-Production Data

The report can include:

- characters
- environments
- storyboard
- style anchor path

These structures are represented in `src/narrascape/agent/models.py` and exported as YAML for later stages.

## Character References

Character references are used to keep identity stable across shots.

The intended reference sheet includes:

- anchor image
- turn images
- expression images
- primary reference path
- identity block

The most important field for downstream generation is the primary reference path. Design and image generation can attach this path to image prompts through `reference_image_url` or `reference_images`.

## Environment References

Environment references describe locations, lighting, mood, and visual world rules.

They can be used by the AI Director as scene guidance and by image generation as reference inputs.

## Storyboard Frames

Storyboard frames give segment-level composition guidance:

- segment id
- frame description
- shot type
- camera movement
- camera angle
- character positions
- emotion
- duration hint
- character reference ids
- scene reference id

The storyboard is not a separate video asset by default. It is structured
guidance for design and an execution contract input for later director stages.

## Interaction With AI Director

`DesignStage` loads `pre_production.yaml` when available and passes storyboard information into `PromptDirector.design_sequence(...)`.

In LLM mode, this lets the model design shots with awareness of:

- already extracted characters
- scene style
- reference image paths
- planned storyboard composition

`DirectorContractStage` also reads the storyboard frames and binds them to each
shot as `storyboard_binding`:

- `storyboard_frame_ids`
- `character_positions`
- `scene_ref`
- `wardrobe_lock`
- `composition_requirements`
- `reference_image_ids`

`ReferencePlateStage` receives those bindings and writes one reviewable plate per
shot. A plate contains:

- `generation.video_prompt` carries the director's text instructions.
- `generation.compiled_prompts.<provider>.prompt` carries the selected
  provider's execution prompt when available.
- `storyboard_binding.reference_image_ids` resolves to actual style, character,
  and scene images under `assets/references/` or paths recorded in
  `pre_production.yaml`.
- missing reference ids, if a storyboard or continuity lock points to an asset
  that cannot be resolved.
- `qa_requirements`, so visual QA sees the same must-show and must-not-show
  constraints as generation.

`GenerateVideoStage` reads `reference_plates.yaml`, sends resolved images to
Seedance as `reference_image` inputs or to Agnes as image/keyframe payload
inputs, passes provider-specific negative prompts when supported, and records
the execution handoff in `video_gen_state.json`.

`AnimaticStage` runs between `generate_images` and `generate_video`. It turns
storyboard frames plus generated stills into `animatic.mp4`, preserving frame
ids, panel durations, scene refs, composition requirements, and reference plate
ids in `animatic.yaml`. Missing panel images block the stage before paid video
generation begins.

`VisualSemanticQAStage` then checks the same binding against timeline metadata,
reference-image execution records, and extracted clip frames. In LLM mode, the
QA prompt includes the extracted frames and reference image paths so a vision
capable reviewer can judge identity, wardrobe, scene, style, and composition
drift.

In offline mode, the stage still produces deterministic prompts, but does not make creative LLM decisions.

## Interaction With Image Generation

`image_prompts.yaml` may contain:

```yaml
reference_image_url: assets/references/char_001_anchor.png
reference_images:
  - assets/references/style_anchor.png
  - assets/references/char_001_anchor.png
seedream_sample_strength: 0.7
```

`GenerateImagesStage` uses these fields when invoking the configured image provider.

## Interaction With Video Generation

`director_contract.yaml` may contain:

```yaml
storyboard_binding:
  reference_image_ids:
    - char_001_anchor
    - scene_lab_mood
```

`ReferencePlateStage` resolves those ids using:

- `pre_production.yaml` character sheets
- `pre_production.yaml` environment references
- `pre_production.yaml` `style_anchor_path`
- files in `assets/references/`
- design report reference chains

The stage always tries to include the style anchor when it is available, then
adds storyboard, character, and scene references. Missing references make
`reference_plates.yaml` `status: blocked`. In
`pipeline.video_generation: required` mode this blocks the stage, preventing
production video generation
from quietly running without the intended character or scene locks. In `auto` or
`off` mode, the finding is preserved while offline/local fallback verification
continues.
Resolved references are then sent as video generation reference images and
persisted in `video_gen_state.json`.

For bookended video generation, the design report may also define
`reference_image_chains` whose `usage_mode` is `last_frame`. A shot can list that
chain in `reference_chain_ids`; `GenerateVideoStage` resolves the chain's
`generated_images`, `reference_urls`, or `reference_local_paths` into the
provider `last_frame` input. Ordinary character, scene, and style reference
chains are not used as last frames unless they are explicitly marked for that
purpose.

## Production Review Checklist

Before final image generation, review:

- Does each recurring character have a stable reference path?
- Are references ordered consistently when multiple images are used?
- Does the prompt explicitly describe how each reference should be used?
- Does `seedream_sample_strength` match the task?
- Do storyboard cues match the narration pacing?
- Is `reference_plates.yaml` `status: ready`, with no missing references?
- Does `animatic.mp4` make the storyboard timing and shot order reviewable
  before video generation?
- Does `video_gen_state.json` show the expected reference ids were uploaded for
  each generated video?
- Does `visual_semantic_report.yaml` contain extracted frame evidence for
  reference-critical clips?

## Non-Goals

- It does not replace human review of generated images.
- It does not guarantee model quality; it supplies structure and references.
