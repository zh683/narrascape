# Configuration Reference

This reference follows the current `NarrascapeConfig` model in `src/narrascape/config.py`.

## Minimal Config

```yaml
project:
  name: my-video
  title: My Video
  script_file: scripts/script.yaml
```

All other sections have defaults.

## Project

```yaml
project:
  name: my-video
  title: My Video
  subtitle: Optional subtitle
  author: Optional author
  year: 2026
  series: Optional series
  episode: 1
  script_file: scripts/script.yaml
  segment_count: 12
  style: documentary
```

`project.name` controls the pipeline directory and output filenames.

## Pipeline

```yaml
pipeline:
  name: animated-explainer
  category: null
  version: "2.0"
  design_overwrite: true
  video_generation: auto   # auto | required | off
  strict_director: false
  production_quality_gates: false
  auto_rework: true
  max_rework_cycles: 1
```

| Field | Behavior |
| --- | --- |
| `video_generation: auto` | Include `generate_video` and `take_select`, but skip video generation when required credentials or multi-take clips are unavailable. |
| `video_generation: required` | Treat missing generated video as a blocking production issue and queue regeneration. |
| `video_generation: off` | Omit generated-video stages and rely on source footage or generated-image fallback. |
| `strict_director` | When true, fail key AI Director stages if their artifacts expose `llm_status: not_configured` or `fallback_after_error`. |
| `production_quality_gates` | When true, make `production_readiness` check script density, pre-production coverage, storyboard bindings, director-contract prompt blueprints, compiled prompts, continuity locks, and QA assertions before generated video starts. |
| `design_overwrite` | When true, `design` rewrites root `image_prompts.yaml` and `image_map.yaml`. Set false for hand-curated projects that should preserve authored prompt files while still writing `pipeline/<name>/design_report.yaml`. |
| `auto_rework` | When true, the default build executes `rework_execute` after a `film_supervisor` `needs_rework` decision. |
| `max_rework_cycles` | Maximum automatic supervisor/rework/rerun cycles after the first build pass. |

`video_generation: required` is an AI-film production policy. It rejects `llm.mode: none` during config validation because required generated-video workflows need an AI Director client for script breakdown, director contract, take selection, semantic QA, and rework decisions.

Use `strict_director: true` when a production run must prove that the director
chain used configured LLM paths instead of local templates. The pipeline checks
`pre_production.yaml`, `design_report.yaml`, `director_contract.yaml`,
`take_selection.yaml`, `creative_review.yaml`, and
`visual_semantic_report.yaml`; a blocked status fails the stage before
downstream assembly can consume the fallback artifact.

Use `production_quality_gates: true` when you want the build to fail before
video generation if preparation is incomplete. This is enabled automatically by
`narrascape build --production`.

## LLM

```yaml
llm:
  mode: auto
  timeout: 300
  provider: ""
  model: ""
  api_key: ""
  base_url: ""
  temperature: 0.7
  max_tokens: 2000
```

| Mode | Behavior |
| --- | --- |
| `auto` | Use configured project mode, environment, API keys, or assistant bridge fallback. |
| `ai_assistant` | Use project-local bridge task files for an assistant. |
| `bridge` | Same bridge transport, explicit file-integration mode. |
| `api` | Use the configured external API provider. |
| `none` | Disable LLM calls and use deterministic local fallbacks. |

`none` is useful for offline tests. It is not a creative production mode.

`llm.mode: none` is only valid with `pipeline.video_generation: auto` or `off`. A project with `pipeline.video_generation: required` must use `auto`, `ai_assistant`, `bridge`, or `api`, and the pipeline also refuses to start if no LLM client is supplied.

## TTS

```yaml
tts:
  provider: minimax        # minimax | openai | elevenlabs | piper | local
  engine: null
  model: speech-2.8-hd
  voice_id: male-qn-jingying
  speed: 0.9
  pitch: 0
  vol: 1.0
  sample_rate: 32000
  continuous_sound: true
  text_normalization: true
  language_boost: Chinese
  add_pauses: false
  pronunciation_dict: []
```

`provider: local` creates deterministic MP3 tones for verification.

## Images

```yaml
images:
  provider: seedream       # production default; use local only for offline preview
  engine: null
  model: doubao-seedream-5-0-260128
  style: "Oil painting style, painterly cinematic frames, visible brush texture, layered pigments, canvas grain, rich chiaroscuro lighting, cohesive color palette; not photorealistic photography, not anime, not cartoon, no readable text, no watermark."
  aspect_ratio: "16:9"
  width: 2560
  height: 1440
  count: null
```

`provider: local` creates deterministic placeholder PNG files.
Seedream is the canonical production image provider for new projects. Legacy
Agnes image support remains in code for older projects, but new production
configs should use `provider: seedream` with `ARK_API_KEY`.

## Video

```yaml
video:
  provider: seedance       # production default
  model: jimeng-video-seedance-2.0
  resolution: 720p
  ratio: "16:9"
  duration: 5
  frame_rate: 24
  takes: 1
```

Set `takes` above `1` to ask `generate_video` for multiple candidate clips per
shot. Single-take output keeps the legacy `assets/videos/vid_01.mp4` naming.
Multi-take output writes `assets/videos/vid_01_take_01.mp4`,
`assets/videos/vid_01_take_02.mp4`, and so on, then `take_select` chooses the
clip that enters `film_timeline.yaml`.

Seedance is the canonical production video provider for new projects.
Narrascape sends generated stills, storyboard-bound reference plates, and
director-contract prompts into Seedance, then writes completed clips for
`take_select`, `film_timeline`, QA, and rework stages. Legacy Agnes video
support remains only for older configs.

## Visual Rendering

```yaml
visual:
  type: ken_burns
  zoom_rate: 0.001
  zoom_cap: 1.20
  vignette: null
  fade_in_duration: 3.0
  supersample: auto       # normal | extreme | auto
  segment_gap: 1.5
  gap_map:
    1: 2.5
```

`gap_map` controls the pause after a segment id.

## Subtitles

```yaml
subtitles:
  engine: srt
  font: Microsoft YaHei
  font_size: 24
  max_chars_per_line: 18
  strip_punctuation: true
  alignment: 2
  primary_color: "&H00FFFFFF"
  outline_color: "&H00000000"
  outline: 2
  shadow: 1
  margin_v: 60
```

## Audio

```yaml
audio:
  narration:
    provider: null
    format: mp3
    sample_rate: 32000
  music:
    provider: minimax     # minimax | suno | elevenlabs | local
    model: music-2.6-free
    sample_rate: 44100
    bitrate: 256000
    volume: 0.25
    music_boost_db: 2.0
    sidechain_threshold: 0.05
    sidechain_ratio: 3
    sidechain_attack: 20
    sidechain_release: 600
    narration_lufs: -16
    target_lufs: -14
    fade_out_seconds: 5
```

## BGM Map

```yaml
bgm_map:
  zone_crossfade: 1.5
  zones:
    - id: bgm_opening
      covers: [1, 4]
      label: Opening
      prompt: Solo piano, sparse, 60 BPM
      min_duration: 120
```

If there are no zones, local/offline music generation skips cleanly.

## Encode

```yaml
encode:
  width: 1920
  height: 1080
  fps: 25
  crf: 18
  preset: medium
  codec: libx264
  audio_codec: aac
  audio_bitrate: 192k
```

## Ending

```yaml
ending:
  enabled: true
  duration: 15.0
  template: null
  lines:
    - text: Produced by Narrascape
      size: 36
  quote: null
  quote_size: 28
```

## Budget

```yaml
budget:
  total_usd: 10.0
  tts_estimated: null
  images_estimated: null
  music_estimated: null
  video_estimated: null
  total_estimated: null
  mode: warn              # observe | warn | cap
  per_action_threshold: 0.5
```

Set any `*_estimated` value to `0.0` for providers that are free but still rate-limited. `null` means Narrascape uses its conservative default estimate.

## Script File

```yaml
segments:
  - id: 1
    text: "Narration for the first segment."
    shot_type: establishing
    pause_markers:
      - after: "first beat"
        seconds: 1.0
    pronunciation: []
```

`shot_type` is optional. When present, it overrides AI Director shot-type selection for that segment.

## Image Prompts

`image_prompts.yaml` is generated by `design`, but can be edited manually:

```yaml
prompts:
  - id: img_01
    shot_type: establishing
    movement: pan_left
    size: 4704x2016
    description: "Wide cinematic establishing frame..."
    reference_image_url: assets/references/style_anchor.png
    reference_images:
      - assets/references/style_anchor.png
    seedream_model: doubao-seedream-5-0-260128
    seedream_sample_strength: 0.7
    negative_prompt: "text, watermark, low quality"
```

## Image Map

```yaml
segments:
  - id: 1
    images: [img_01]
  - id: 2
    images: [img_02, img_03]
    timing: [0.4, 0.6]
```

For multi-image segments, `timing` must match image count and sum to `1.0`.

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `NARRASCAPE_LLM_MODE` | Override LLM mode. |
| `NARRASCAPE_BRIDGE_DIR` | Override bridge task directory. |
| `NARRASCAPE_BRIDGE_TIMEOUT` | Override bridge timeout seconds. |
| `OPENAI_API_KEY` | OpenAI-compatible provider. |
| `ANTHROPIC_API_KEY` | Anthropic provider. |
| `DEEPSEEK_API_KEY` | DeepSeek provider. |
| `ARK_API_KEY` | Volcengine Seedream/Seedance. |
| `MINIMAX_API_KEY` | MiniMax TTS/music. |
| `NARRASCAPE_UPLOAD_ENDPOINT` | HTTP uploader endpoint for reference images. |
