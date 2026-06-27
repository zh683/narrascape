# Take Select Stage Director

## Inputs

- `assets/videos/vid_<segment>_take_<take>.mp4`
- Optional `pipeline/<project>/video_gen_state.json`
- Optional `pipeline/<project>/render_report.yaml`

## Outputs

- `pipeline/<project>/take_selection.yaml`

## Procedure

1. Discover multi-take generated-video candidates.
2. Ignore candidates not marked done when `video_gen_state.json` has a done list.
3. Score takes with deterministic QA proxy data.
4. If an LLM client is configured, ask the LLM judge to choose from the QA-scored candidates.
5. Write candidates, selected take, selected path, and judge process.
6. Let `film_timeline` consume the selected take on the next timeline build.

## Do Not

- Do not call `generate_video` from this stage.
- Do not delete losing takes.
- Do not bypass QA or human review for critical shots.
- Do not require an API key to select existing takes.
