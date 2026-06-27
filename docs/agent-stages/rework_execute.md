# Rework Execute Stage Director

## Inputs

- `pipeline/<project>/rework_plan.yaml`
- Optional `pipeline/<project>/video_gen_state.json`
- Optional `pipeline/<project>/state.json`

## Outputs

- `pipeline/<project>/rework_execution.yaml`
- `pipeline/<project>/video_regen_queue.yaml`
- `pipeline/<project>/recut_queue.yaml`
- `pipeline/<project>/source_media_replacement_queue.yaml`
- `pipeline/<project>/rework_quarantine/`

## Procedure

1. Read executable actions from `rework_plan.yaml`.
2. For `regenerate_video`, move matching generated clips into `rework_quarantine/videos/`.
3. Remove invalidated video ids from `video_gen_state.json`.
4. Write a video regeneration queue.
5. Write recut and source-media replacement queues.
6. Mark affected stages pending in `state.json`.
7. Write `rework_execution.yaml` with every operation performed.

## Do Not

- Do not permanently delete generated media.
- Do not execute provider calls directly.
- Do not edit source footage.
- Do not call generation or rendering providers from inside this stage; the pipeline reruns the requested stages after this stage writes queues and resets state.
