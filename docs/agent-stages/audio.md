# Audio Stage Director

## Inputs

- `pipeline/<project>/film_assembled.mp4`
- `pipeline/<project>/mixed_audio.mp3`
- ending and encode configuration

## Outputs

- `output/<project>-clean.mp4`
- optional `pipeline/<project>/mixed_audio_aligned.mp3`

## Procedure

1. Validate the assembled film and mixed soundtrack.
2. Align soundtrack duration with the film and configured ending.
3. Mux video and audio through a temporary validated media file.
4. Atomically promote the clean master only after FFmpeg validation succeeds.

## Do Not

- Do not mutate the assembled film or mixed soundtrack.
- Do not publish a partial or unvalidated mux.
- Do not bypass the configured FFmpeg timeout.
