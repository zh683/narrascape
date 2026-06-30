# Storyboard Sheet Stage Director

## Inputs

- `pipeline/<project>/pre_production.yaml`
- `pipeline/<project>/director_contract.yaml`
- `pipeline/<project>/reference_plates.yaml`
- Optional `design_report.yaml`
- Optional `image_map.yaml`

## Outputs

- `pipeline/<project>/storyboard_sheet.yaml`
- `pipeline/<project>/storyboard_sheet.png`
- `pipeline/<project>/storyboard_sheet.pdf`

## Procedure

1. Read storyboard frames from `pre_production.yaml`.
2. If storyboard frames are missing, synthesize cards from director contract shots.
3. Bind each card to director contract storyboard frame ids, positions, scene refs, wardrobe locks, composition requirements, and reference image ids.
4. Prefer generated images when present, then resolved reference assets, then placeholder cards.
5. Render a 12-up product-style review board with one card per frame.
6. Write a YAML report so downstream QA and documentation can inspect the sheet without parsing the image.

## Do Not

- Do not treat this as the creative source of truth; it is a review surface.
- Do not fail the whole pipeline just because a preview image is missing.
- Do not ignore storyboard bindings when they exist.
