# Style Consistency

Style consistency is handled by combining global style text, style anchor references, character references, scene references, and reviewable design reports.

## Consistency Layers

```text
config.images.style
        |
        v
PreProductionStage style anchor
        |
        v
character / scene references
        |
        v
DesignStage prompt enrichment
        |
        v
GenerateImagesStage reference image fields
```

## Style Anchor

A style anchor is a reference image intended to carry palette, lighting, texture, and visual treatment. It should avoid important story content so the model does not copy the wrong subject into later shots.

Good style anchor traits:

- simple still-life or neutral scene
- no main characters
- no highly specific story event
- clear lighting and palette
- close to the desired final visual style

## Reference Ordering

When multiple reference images are passed, keep their meaning stable:

```text
reference_images[0] = style anchor
reference_images[1] = character reference
reference_images[2] = scene or mood reference
```

Prompts should describe that order explicitly, for example:

```text
Use reference image 1 for visual style and color palette.
Use reference image 2 for the character identity.
Use reference image 3 for scene mood.
```

## Sample Strength

Use lower strength when the reference should guide style only. Use higher strength when identity matters.

| Use case | Typical strength |
| --- | --- |
| Style-only scene guidance | 0.2-0.4 |
| Balanced style and subject guidance | 0.5-0.6 |
| Character identity preservation | 0.6-0.8 |
| Strict identity-critical shot | 0.8-1.0 |

These are practical defaults, not hard rules.

## AI Director Responsibilities

In LLM mode, the AI Director should:

- keep character identity terms stable
- keep lighting and palette consistent across adjacent shots
- vary shot sizes and movement without changing the world style
- include negative prompts that prevent identity drift and artifacts
- carry reference image ids into `image_prompts.yaml`

In offline mode, the local fallback can preserve a style string but does not provide true creative consistency reasoning.

## Image Generation Responsibilities

Image generation should:

- pass the selected reference images to the provider
- preserve the reference order
- include negative prompts
- save generated files using stable ids such as `img_01.png`
- avoid overwriting existing production images without review

## Review Checklist

Before moving from `generate_images` to rendering:

- Faces match across recurring character shots.
- Clothing and accessories do not drift.
- Lighting direction is plausible across adjacent shots.
- Palette matches `config.images.style` and the style anchor.
- Reference prompts do not accidentally copy the style-anchor subject.
- No text, watermark, logo, extra limbs, or malformed anatomy appears.

## Troubleshooting

If style drifts:

- Check that `reference_images[0]` is the style anchor.
- Make the prompt explicitly state how to use each reference.
- Lower strength for scene references that copy too much content.
- Raise strength for character close-ups that lose identity.
- Regenerate only the affected image ids when possible.
