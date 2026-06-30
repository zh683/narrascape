# Provider Governance

Narrascape borrows a small, code-backed slice of OpenMontage's provider governance model.

## Provider Registry

`narrascape.providers.registry` defines provider tools with:

- name
- capability
- provider
- status
- quality
- control
- reliability
- cost efficiency
- latency
- continuity
- task-fit hints
- requirements

Use:

```python
from narrascape.providers import build_default_registry

registry = build_default_registry(config)
envelope = registry.support_envelope()
```

## Provider Selector

`ProviderSelector` scores available providers with weighted criteria:

| Criterion | Weight |
| --- | --- |
| task fit | 0.30 |
| quality | 0.20 |
| control | 0.15 |
| reliability | 0.15 |
| cost efficiency | 0.10 |
| latency | 0.05 |
| continuity | 0.05 |

`generate_images`, `generate_tts`, `generate_music`, and `generate_video` call
the selector before execution. Each stage writes `provider_selection` into
`StageResult.metadata` and its persistent state file. The selected provider is
the branch that executes.

Configured media providers include:

| Capability | Provider options | Credential |
| --- | --- | --- |
| image_generation | `seedream`, `local` | `ARK_API_KEY` |
| video_generation | `seedance` | `ARK_API_KEY` |
| tts | `minimax`, `local` | `MINIMAX_API_KEY` |
| music | `minimax`, `local` | `MINIMAX_API_KEY` |

Seedream and Seedance are the canonical production media providers for new
projects. The registry still contains Agnes compatibility entries for older
configs, but the supported production route is `seedream -> seedance` with
`ARK_API_KEY`.

## Canonical Artifacts

`narrascape.artifacts` validates lightweight canonical artifacts:

- `asset_manifest`
- `design_report`
- `film_timeline`
- `render_report`

This prevents malformed handoffs such as missing `assets` in a source-media manifest.

## Source Media

`source_media` scans:

```text
source_media/
```

and writes:

```text
asset_manifest.yaml
footage_timeline.yaml
```

`asset_manifest.yaml` catalogs local clips and stills. `footage_timeline.yaml`
turns those assets into ordered edit decisions with source path, target segment,
duration, in/out points, role, and transition. This gives the project a real-footage
documentary workflow alongside generated-video and generated-image fallback paths.

The optional `footage_edit` stage consumes `footage_timeline.yaml` and renders:

```text
pipeline/<project>/footage_roughcut.mp4
```

## Render QA

`qa` validates the final subtitled output and writes:

```text
pipeline/<project>/render_report.yaml
```

Checks include:

- file exists
- non-empty file
- ffprobe validity
- video stream
- audio stream
- duration
- resolution
- subtitle source and final subtitled output
- expected-vs-actual duration tolerance
- silence risk
- black-frame risk with configured intentional black sections allowed
- repeated shot risk
- local placeholder imagery residue
- shot coverage ratio
- missing timeline video clip files
- generated-video coverage gaps
- character/location continuity risk
- narrative pacing risk

## Director Review

`director_review` consumes `render_report.yaml` and writes:

```text
pipeline/<project>/director_review.yaml
```

It converts QA findings into a rework queue. Missing visuals, missing generated
video coverage, and missing timeline video files are marked for
`regenerate_video`; pacing risks are marked for `recut`; continuity risks are
marked for regeneration review. QA can fail and still hand control to this stage
so failed shots are not lost.

## Agent Stage Docs

AI assistants should read:

```text
docs/agent-stages/design.md
docs/agent-stages/source_media.md
docs/agent-stages/footage_edit.md
docs/agent-stages/film_timeline.md
docs/agent-stages/remotion_preview.md
docs/agent-stages/film_assemble.md
docs/agent-stages/generate_images.md
docs/agent-stages/generate_video.md
docs/agent-stages/qa.md
docs/agent-stages/director_review.md
```

These files define stage inputs, outputs, procedure, and "do not" rules.
