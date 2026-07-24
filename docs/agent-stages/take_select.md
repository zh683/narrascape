# Take Select Stage Director

## Inputs

- `assets/videos/vid_<segment>_take_<take>.mp4`
- Optional `pipeline/<project>/video_gen_state.json`
- Optional `pipeline/<project>/render_report.yaml`
- Optional `pipeline/<project>/director_contract.yaml` (expected clip durations)

## Outputs

- `pipeline/<project>/take_selection.yaml`

## Procedure

1. Discover multi-take generated-video candidates created by `generate_video` when `video.takes > 1`.
2. Ignore candidates not marked done when `video_gen_state.json` has a done list.
3. Score takes with deterministic frame analysis (`utils/video_quality.py`):
   ffprobe duration + 3 evenly spaced sampled frames per take, combined into a
   0-100 composite of **sharpness** (Laplacian variance, weight 0.35),
   **brightness** (mean luminance, 0.25), **duration** (deviation from the
   director-contract `generation.duration`, 0.25), and **stability**
   (average-hash agreement across sampled frames — frozen-video detection, 0.15).
   Risk segments from `render_report.yaml` keep their -1.0 penalty on top.
   If analysis fails for any take (ffmpeg missing, extraction error), the whole
   segment falls back to legacy byte-size scoring with a warning, so scores on
   one segment always share one scale.
4. If an LLM client is configured, ask the LLM judge to choose from the QA-scored candidates; the LLM choice still overrides the deterministic score.
5. Write candidates (with per-take `quality` audit blocks and per-segment `scoring` mode), selected take, selected path, and judge process.
6. Let `film_timeline` consume the selected take on the next timeline build.

## Do Not

- Do not call `generate_video` from this stage.
- Do not delete losing takes.
- Do not bypass QA or human review for critical shots.
- Do not require an API key to select existing takes.
- Do not mix scoring scales within one segment (quality composites and byte sizes are not comparable).
