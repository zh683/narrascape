# Generate Music Stage Director

## Inputs

- `config.yaml` audio music and `bgm_map` sections
- `pipeline/<project>/timing.json`
- music provider credentials when a remote provider is selected

## Outputs

- `assets/music/<zone>.mp3`
- `pipeline/<project>/bgm_state.json`
- budget and provider task records

## Procedure

1. Calculate each music-zone duration from narration timing and gaps.
2. Select the configured provider and reserve budget before remote calls.
3. Reuse only completed, valid zone outputs.
4. Generate each missing zone, validate it, then commit budget and task state.
5. Persist bounded progress after each zone so the stage can resume.

## Do Not

- Do not call a paid provider without a successful budget reservation.
- Do not mark failed or empty audio as complete.
- Do not replace authored zone boundaries with an implicit full-length track.
