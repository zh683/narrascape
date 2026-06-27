# Continuity Bible Stage Director

## Inputs

- `film_timeline.yaml`
- `pipeline/<project>/screenplay_structure.yaml`
- `design_report.yaml`

## Outputs

- `pipeline/<project>/continuity_bible.yaml`

## Procedure

1. Read story clips from the film timeline.
2. Extract character ids, location ids, wardrobe, lighting scheme, and screen axis.
3. Build per-character appearances.
4. Build per-location appearances and lighting/axis notes.
5. Compare adjacent appearances for wardrobe jumps and screen-axis flips.
6. Write continuity risks with segment ids and previous segment ids.

## Do Not

- Do not hide continuity risks because the render exists.
- Do not rewrite the timeline directly.
- Do not invent character ids when neither timeline nor design report supplies them.
- Do not treat this artifact as final human approval.
