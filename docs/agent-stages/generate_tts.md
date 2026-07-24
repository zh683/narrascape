# Generate TTS Stage Director

## Inputs

- `scripts/script.yaml`
- `config.yaml` TTS settings
- TTS provider credentials when a remote provider is selected

## Outputs

- `assets/tts/seg_*.mp3`
- `pipeline/<project>/timing.json`
- `pipeline/<project>/tts_state.json`

## Procedure

1. Preserve script segment ids and narration order.
2. Reserve budget before each consequential provider call.
3. Generate missing narration into temporary data and atomically write the result.
4. Probe or calculate clip duration and update timing by segment id.
5. Persist resumable state after each completed segment.

## Do Not

- Do not log credentials or full provider responses.
- Do not commit budget for failed generation.
- Do not infer timing from text length when a valid audio clip can be probed.
