# Subtitles Stage Director

## Inputs

- `output/<project>-clean.mp4`
- `scripts/script.yaml`
- `pipeline/<project>/timing.json`
- subtitle style configuration

## Outputs

- `pipeline/<project>/subtitles.srt`
- `output/<project>-sub.mp4`

## Procedure

1. Build subtitle cues from canonical script text and narration timing.
2. Preserve segment order and configured gap offsets.
3. Write the SRT artifact atomically.
4. Burn subtitles into a temporary video using escaped platform-safe paths.
5. Validate and atomically promote the subtitled master.

## Do Not

- Do not derive cue order from filenames.
- Do not mutate the clean master.
- Do not publish a partial subtitle render.
