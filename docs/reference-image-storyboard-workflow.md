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

`GenerateVideoStage` receives those bindings in two ways:

- `generation.video_prompt` carries the director's text instructions.
- `storyboard_binding.reference_image_ids` resolves to actual style, character,
  and scene images under `assets/references/` or paths recorded in
  `pre_production.yaml`.

The video stage sends those resolved images to Seedance as `reference_image`
inputs and records the execution handoff in `video_gen_state.json`.

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

`GenerateVideoStage` resolves those ids using:

- `pre_production.yaml` character sheets
- `pre_production.yaml` environment references
- `pre_production.yaml` `style_anchor_path`
- files in `assets/references/`
- design report reference chains

The stage always tries to include the style anchor when it is available, then
adds storyboard, character, and scene references. The resolved references are
sent as video generation reference images and persisted in
`video_gen_state.json`.

## Production Review Checklist

Before final image generation, review:

- Does each recurring character have a stable reference path?
- Are references ordered consistently when multiple images are used?
- Does the prompt explicitly describe how each reference should be used?
- Does `seedream_sample_strength` match the task?
- Do storyboard cues match the narration pacing?
- Does `video_gen_state.json` show the expected reference ids were uploaded for
  each generated video?
- Does `visual_semantic_report.yaml` contain extracted frame evidence for
  reference-critical clips?

## Non-Goals

- It does not replace human review of generated images.
- It does not guarantee model quality; it supplies structure and references.
