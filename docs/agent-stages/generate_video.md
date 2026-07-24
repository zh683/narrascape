# Generate Video Stage Director

## Inputs

- `pipeline/<project>/design_report.yaml` or `design_report.yaml`
- `pipeline/<project>/director_contract.yaml`
- `pipeline/<project>/reference_plates.yaml`
- `pipeline/<project>/animatic.yaml`
- Optional `pipeline/<project>/pre_production.yaml`
- `assets/images/img_*.png`
- Optional `assets/references/*`
- video provider configuration
- `ARK_API_KEY` for Seedance/Volcengine generation

## Outputs

- `assets/videos/vid_*.mp4`
- `assets/videos/vid_<segment>_take_<take>.mp4` when `video.takes > 1`
- `pipeline/<project>/video_prompt_quality.yaml`
- `pipeline/<project>/video_gen_state.json`
- `pipeline/<project>/video_tasks.json` (paid task ledger)

## Procedure

1. Select the video provider through `ProviderSelector`.
2. Read AI Director shot metadata from the design report.
3. Read `director_contract.yaml` and, when a provider is selected, prefer `generation.compiled_prompts.<provider>.prompt`; fall back to `generation.video_prompt` for legacy contracts.
4. Write `video_prompt_quality.yaml` with per-shot ingredient scores for subject identity, action beat, scene lock, wardrobe lock, camera language, composition, lighting/palette, style/quality, and reference binding.
5. Block generation if the prompt is still generic or lacks the executable ingredients needed for controllable video generation.
6. Read the matching provider negative prompt and pass it to Seedance when supported.
7. Require the animatic preview to exist so storyboard timing has been checked before provider execution.
8. Resolve `storyboard_binding.reference_image_ids` to actual style, character, and scene reference images.
9. Use generated images as first-frame references when available. When
   `video.storyboard_conditioning: auto` (default `off`), a physical storyboard
   panel bound via `storyboard_binding.storyboard_frame_ids`
   (`assets/storyboard/<frame_id>.<ext>`, first match wins) outranks the
   generated still as the provider `first_frame`, and reference images whose
   ids appear in `storyboard_binding.reference_image_ids` lead the reference
   list ahead of the auto-derived style/character/scene refs. Missing panels
   or unresolvable ids fall back to the default inputs without blocking; the
   per-shot choice is recorded under
   `reference_inputs.<vid>.storyboard_conditioning` in `video_gen_state.json`,
   and any panel/content switch changes the request fingerprint, so stale
   clips are never silently reused.
10. Resolve explicit `reference_image_chains` with `usage_mode: last_frame` or
    ending/final-frame chain ids into provider last-frame inputs for bookended
    shot continuity.
11. Send resolved style, character, and scene images to the selected provider.
   - Seedance receives multimodal `reference_image` inputs.
12. If `video.takes > 1`, submit one asynchronous task per take using stable
   `vid_<segment>_take_<take>` names.
13. Poll each task until it succeeds or fails, up to `video.max_poll_time`
   seconds per task. Record every created task in `video_tasks.json`
   immediately; on rerun, resume polling unfinished parameter-equivalent
   tasks from the ledger instead of creating duplicate paid tasks, and
   re-download from succeeded records before paying again.
14. Download completed clips to `assets/videos/`.

   When `video.max_concurrency > 1`, steps 12-14 run as a submit-all →
   poll-all pipeline instead: cache decisions (fingerprint skip / free
   re-download / resume) are made serially up front (Phase A), all new tasks
   are created with bounded concurrency (Phase B, ledger-recorded on
   creation; Agnes submits serially to keep its >=65s creation cadence), and
   every in-flight task is polled in one unified loop with concurrent
   downloads (Phase C; `max_poll_time` budgets the slowest task, 429 polls
   back off per Retry-After without counting as errors, unfinished tasks
   stay resumable in the ledger). Exactly-once cost accounting is unchanged:
   success → `try_spend`, terminal failed/expired → `record_actual(failed)`.
15. Record completed clip ids, `provider_selection`, `take_policy`, generated
    take ids, expected reference ids, resolved assets, missing ids, and uploaded
    reference counts in `video_gen_state.json`.
16. Run `film_timeline` after generation so completed clips become first-class timeline visuals.

## Do Not

- Do not leave generated videos as side outputs; they must be consumed by `film_timeline`.
- Do not ignore `director_contract.yaml` when it exists.
- Do not send a generic prompt when a provider-specific compiled prompt exists.
- Do not drop the provider-specific negative prompt.
- Do not leave `storyboard_binding.reference_image_ids` as YAML-only metadata.
- Do not treat ordinary character/style reference chains as last-frame inputs;
  last-frame use must be explicit.
- Do not bypass the animatic preview in the default production chain.
- Do not send under-specified or template-like prompts to paid video providers.
- Do not silently fall back to local placeholders for production video generation.
- Do not skip provider selection metadata.
- Do not generate multiple takes unless `video.takes` requests them.
- Do not overwrite completed clips unless the user requested a rebuild.
