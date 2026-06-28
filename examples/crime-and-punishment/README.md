# 罪与罚 / Crime and Punishment

`crime-and-punishment` is Narrascape's first public-domain AI-film starter project: a compact cinematic adaptation prototype based on Fyodor Dostoevsky's 1866 novel.

The project uses original Chinese narration and newly written image/video prompts. It does not copy any modern translation. The goal is not to compress the whole novel into a summary, but to test whether Narrascape can carry a serious dramatic arc through AI direction, reference-aware generation, film timeline assembly, QA, and rework.

## What This Project Tests

- Script-to-film continuity: `scripts/script.yaml` is the narrative spine.
- AI director supervision: character locks, wardrobe locks, location references, moral tension, and storyboard intent are defined in `director_notes.md`.
- Curated shot prompts: `pipeline.design_overwrite: false` preserves the authored `image_prompts.yaml` and `image_map.yaml` while still writing a fresh `design_report.yaml`.
- Film timeline path: the default pipeline prefers generated video, then source footage, then generated-image fallback.
- QA and rework loop: default config keeps `pipeline.auto_rework: true` and `max_rework_cycles: 1`.
- Safe local preview: default `config.yaml` uses local image/TTS/music providers so the pipeline can be tested without using external service requests.
- Agnes production mode: `config.agnes.yaml` switches image and video generation to Agnes with zero-dollar estimated cost and normal request-limit handling.

## Project Shape

```text
examples/crime-and-punishment/
  config.yaml              # local preview config
  config.agnes.yaml        # Agnes image/video production config
  film_brief.md            # story, tone, public-domain boundary
  director_notes.md        # continuity bible and storyboard intent
  image_prompts.yaml       # curated seed prompts for the first visual pass
  image_map.yaml           # segment-to-image seed map
  scripts/script.yaml      # Chinese narration script
```

## Local Preview

From the repository root:

```powershell
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p examples/crime-and-punishment --approve
```

This produces a local verification render using placeholders and local audio. It proves the film timeline, assembly, subtitles, QA, director reports, and rework loop can run before real Agnes generation.

## Agnes Production Run

The CLI reads `config.yaml`, so use the Agnes config as the active config when you want real image/video generation.

```powershell
Copy-Item examples/crime-and-punishment/config.agnes.yaml examples/crime-and-punishment/config.yaml -Force
$env:AGNES_API_KEY = "your_agnes_key"
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p examples/crime-and-punishment --approve --force
```

In Agnes mode, `generate_images` creates visual anchors and shot images, `generate_video` turns selected shots into clips, `film_timeline.yaml` assembles the story order, and QA/rework decides whether shots need regeneration or recutting.

Agnes currently presents its core image/video capabilities as free, but real API runs can still hit request-per-minute limits, quota pools, temporary capacity limits, or availability issues. Narrascape treats Agnes production mode as zero-dollar estimated cost while still using retry, QA, and rework controls.

## Creative Rule

The film should be a severe, psychological, 19th-century drama. Keep the moral pressure close to faces, rooms, stairwells, hands, doorways, icons, letters, and city weather. Avoid spectacle, modern props, generic crime-thriller style, and any text copied from copyrighted translations.
