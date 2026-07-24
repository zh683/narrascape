# Pre-Production Stage Director

## Inputs

- `scripts/script.yaml`
- image provider configuration (`ARK_API_KEY` for Seedream reference generation; `images.provider: local` needs no key)
- Optional LLM client for character/scene notes extraction

## Outputs

- `pipeline/<project>/pre_production.yaml`
- `assets/references/` (style anchor, character, and scene reference images)
- `assets/storyboard/` (storyboard panel images, when storyboard generation is enabled)
- `pipeline/<project>/prompt_safety.yaml` (sanitize audit, only when a prompt was rewritten)

## Procedure

1. Extract characters and scenes from the script (LLM-assisted notes extraction when a client is configured, deterministic extraction otherwise), capped by `max_characters` / `max_scenes`.
2. Build character reference sheets (turnarounds and expressions when enabled) and environment reference images through the selected image provider.
3. Generate the style anchor and per-segment storyboard frames when storyboard generation is enabled.
4. With `images.provider: local`, write metadata-only references so offline verification needs no network or API key.
5. Sanitize provider-bound prompts and persist any rewrite to the shared `pipeline/<project>/prompt_safety.yaml` audit.
6. Write `pre_production.yaml` with `director_process` metadata; `design` loads it to enrich shot prompts, and downstream stages bind storyboard frames and reference ids from it.

## Do Not

- Do not treat local-provider metadata-only references as production visual assets.
- Do not invent characters or scenes the script does not support.
- Do not skip the prompt-safety audit when a provider-bound prompt is rewritten.
- Do not leave storyboard frames as unbound images; `director_contract` and `reference_plate` must be able to bind them by id.
