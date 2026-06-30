# Rework Execute Stage Director

## Inputs

- `pipeline/<project>/rework_plan.yaml`
- Optional `pipeline/<project>/video_gen_state.json`
- Optional `pipeline/<project>/state.json`

## Outputs

- `pipeline/<project>/rework_execution.yaml`
- `pipeline/<project>/director_contract_rewrite_queue.yaml`
- `pipeline/<project>/video_regen_queue.yaml`
- `pipeline/<project>/recut_queue.yaml`
- `pipeline/<project>/source_media_replacement_queue.yaml`
- `pipeline/<project>/rework_quarantine/`

## Procedure

1. Read executable actions from `rework_plan.yaml`.
2. For `rewrite_director_contract`, write a contract rewrite queue and mark `director_contract`, `reference_plate`, `animatic`, `generate_video`, `take_select`, and `film_timeline` pending.
3. For `regenerate_video`, move matching generated clips into `rework_quarantine/videos/`.
4. Remove invalidated video ids from `video_gen_state.json`.
5. Write a video regeneration queue.
6. Write recut and source-media replacement queues.
7. Mark affected stages pending in `state.json`.
8. Write `rework_execution.yaml` with every operation performed.
9. Downstream stages consume these queues on rerun:
   - `director_contract` preserves non-queued shots and rewrites only `director_contract_rewrite_queue.yaml` segment ids.
   - `generate_video` restricts provider calls to `video_regen_queue.yaml` segment ids when the queue is non-empty.

## Do Not

- Do not permanently delete generated media.
- Do not execute provider calls directly.
- Do not edit source footage.
- Do not call generation or rendering providers from inside this stage; the pipeline reruns the requested stages after this stage writes queues and resets state.
