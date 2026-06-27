# Screenplay Structure Stage Director

## Inputs

- `scripts/script.yaml`
- `design_report.yaml`
- Optional `pipeline/<project>/timing.json`

## Outputs

- `pipeline/<project>/screenplay_structure.yaml`

## Procedure

1. Read script segments in story order.
2. Read shot metadata from the design report.
3. Split the story into act, scene, sequence, and shot layers.
4. Group scene changes primarily by location.
5. Group sequence changes primarily by emotion.
6. Write `shot_index` so any segment can be mapped back to act, scene, sequence, and shot ids.

## Do Not

- Do not skip directly from script segment to shot without act/scene/sequence hierarchy.
- Do not mutate `scripts/script.yaml`.
- Do not generate media assets.
- Do not depend on network access or API keys.
