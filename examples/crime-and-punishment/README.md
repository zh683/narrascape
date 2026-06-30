# 罪与罚 / Crime and Punishment

`crime-and-punishment` is a rebuilt Narrascape AI-film starter project based on Fyodor Dostoevsky's 1866 public-domain novel. This version replaces the failed first run's loose prompt set with a stricter production package: locked character bible, locked scene bible, storyboard intent, curated shot prompts, reference-aware director contracts, and separate preview/production configs.

The project uses original Chinese narration and original prompts. It does not copy modern translations.

## What Changed In This Rebuild

- Re-authored the film brief as a psychological drama, not a crime-trailer summary.
- Rewrote all 12 narration segments in clean UTF-8 Chinese.
- Rebuilt `director_notes.md` with explicit character, wardrobe, scene, storyboard, and QA locks.
- Rewrote all 12 image prompts with concrete action, camera language, lighting, continuity, and stronger negative prompts.
- Added explicit bans for exposed axe imagery in segment 2 and platform artifacts such as `AI生成`, `即梦AI`, watermarks, logos, subtitles, and readable text.
- Split local preview from production:
  - `config.yaml` is a safe local preview config with generated-video disabled.
  - `config.production.yaml` is the strict Seedream/Seedance production config with generated video required, three takes per shot, and strict director mode enabled.

## Project Shape

```text
examples/crime-and-punishment/
  config.yaml              # local preview config; no paid/external generation required
  config.production.yaml   # strict Seedream/Seedance production config
  film_brief.md            # story, source boundary, production goals
  director_notes.md        # character/scene bible, storyboard intent, QA locks
  image_prompts.yaml       # curated executable shot prompts
  image_map.yaml           # segment-to-image map
  scripts/script.yaml      # original Chinese narration
```

Generated media, pipeline artifacts, and old trial renders are intentionally ignored by Git. They should be regenerated from the source files above.

## Local Preview

Use this only to verify pipeline wiring, subtitles, audio timing, film timeline, QA reports, and rework loop. Local preview uses placeholders; it is not an image-quality test.

```powershell
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p examples/crime-and-punishment --approve --force
```

## Seedream/Seedance Production Run

Use the production config when you want real Seedream image generation and Seedance video generation.

```powershell
Copy-Item examples/crime-and-punishment/config.production.yaml examples/crime-and-punishment/config.yaml -Force
$env:ARK_API_KEY = "your_ark_key"
$env:PYTHONPATH = "src"
.\.venv_test\Scripts\python.exe -m narrascape.cli build -p examples/crime-and-punishment --approve --force
```

Production mode is intentionally strict:

- `pipeline.video_generation: required`
- `pipeline.strict_director: true`
- `video.takes: 3`
- `pipeline.max_rework_cycles: 2`

If a key AI director stage falls back to `not_configured` or `fallback_after_error`, the build should fail rather than hiding a weak director pass inside the finished film.

## Creative Rule

The film should feel like a conscience closing in. Keep the visual pressure in rooms, faces, hands, thresholds, keys, candlelight, rain-dark stone, official paper, and cold dawn. Do not allow modern props, platform text, visible watermarks, glossy fantasy lighting, handsome fashion-model casting, or exposed weapon imagery to dominate the film.
