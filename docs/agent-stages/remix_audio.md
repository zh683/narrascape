# Remix Audio Stage Director

## Inputs

- `assets/tts/seg_*.mp3`
- `assets/music/*.mp3`
- `pipeline/<project>/timing.json`
- `bgm_map`, gap, ducking, and fade configuration

## Outputs

- `pipeline/<project>/mixed_audio.mp3`
- intermediate narration and music concat manifests

## Procedure

1. Assemble narration clips using canonical timing and configured gaps.
2. Resolve music zones and fail when required zone media is missing.
3. Apply fades, crossfades, level control, and narration ducking.
4. Render to a temporary mix, validate it, and atomically promote it.

## Do Not

- Do not change editorial timing to hide missing audio.
- Do not ignore missing configured music zones.
- Do not publish a mix that FFmpeg cannot probe.
