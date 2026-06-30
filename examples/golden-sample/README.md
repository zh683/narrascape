# Golden Sample

This project is the fixed Narrascape quality benchmark: a short psychological
AI-film scene from *Crime and Punishment*.

It is designed to answer one question after every optimization:

> Did the pipeline produce better controllable film material, or did it only run?

Recommended production run:

```powershell
narrascape build -p examples/golden-sample --production --approve
```

Expected production behavior:

- Seedream image generation.
- Seedance video generation.
- Oil-painting visual style.
- Strict director mode.
- Production readiness gates.
- Three takes per shot.
- Film timeline assembly.
- QA, supervisor review, and automatic rework cycle.

This example should stay small. Do not commit generated images, videos, audio, or
pipeline output from this project.
