# AI Director Design

The AI Director starts with `ScriptAnalyzer`, `PromptDirector`, and
`DesignStage`, then continues through film-direction stages that produce
screenplay structure, continuity, editing review, rework planning, multi-take
selection, creative review, visual semantic QA, and supervising control artifacts.

## What It Does

The design stage reads `scripts/script.yaml` and produces:

```text
design_report.yaml
image_prompts.yaml
image_map.yaml
```

The director stack also writes:

```text
pipeline/<project>/screenplay_structure.yaml
pipeline/<project>/director_contract.yaml
pipeline/<project>/continuity_bible.yaml
pipeline/<project>/editing_review.yaml
pipeline/<project>/director_review.yaml
pipeline/<project>/rework_plan.yaml
pipeline/<project>/take_selection.yaml
pipeline/<project>/creative_review.yaml
pipeline/<project>/visual_semantic_report.yaml
pipeline/<project>/film_supervisor.yaml
pipeline/<project>/rework_execution.yaml
```

In LLM modes, the AI Director asks a model to make creative shot decisions:

- emotional analysis
- scene type
- key visual entities
- shot type
- camera movement
- director vision
- cinematic format
- image generation prompt
- negative prompt
- reasoning and metadata

## LLM Path

`DesignStage` always starts by constructing:

```python
ScriptAnalyzer(llm_client=self.llm_client)
```

If `self.llm_client` exists, it then calls:

```python
PromptDirector(llm_client=self.llm_client).design_sequence(...)
```

For assistant-backed modes, `PromptDirector` batches all shot design into one LLM task. The batch prompt explicitly asks the model to act as an AI Director and return a JSON array of creative shot designs.

For API-backed modes, the director can build character profiles, scene style, and individual shot designs through structured LLM prompts.

## Bridge Path

In `ai_assistant` and `bridge` mode:

```text
PromptDirector -> LLMClient.complete(...)
-> BridgeLLMClient writes task_<id>.md
-> assistant writes response_<id>.json
-> response content is parsed as JSON
```

If the assistant does not write a response before timeout, the command fails. It does not silently generate a fake AI Director result.

## Offline Path

If there is no LLM client, `DesignStage` calls `_design_locally(...)`.

That path is deterministic:

- picks shot types from simple script and analysis hints
- builds a prompt from style, shot type, and narration text
- records reasoning as local deterministic design

This is useful for tests and offline end-to-end verification. It is not the creative AI Director path.

## Director Layers

### Script And Scene Director

`screenplay_structure` reads the script and design report, then splits the work
in this order:

```text
act -> scene -> sequence -> shot
```

It writes a `shot_index` so each script segment can be traced back to its act,
scene, sequence, and shot.

### Director Contract / Prompt Compiler

`director_contract` reads `screenplay_structure.yaml`, the design report, and
any available continuity bible. It turns director judgment into a per-shot
execution contract:

- why the shot exists in the story
- emotional target
- film language: shot type, camera motion, lighting, and composition
- continuity constraints: characters, location, wardrobe, and light
- storyboard binding: frame ids, character positions, scene reference, wardrobe
  lock, composition requirements, and reference image ids
- generation instructions: video prompt, negative prompt, duration, and motion
- QA assertions: `must_show` and `must_not_show`

When an LLM client is configured, this stage asks the model to act as a
top-tier film director and prompt compiler. Without an LLM, it creates a
deterministic contract from existing design fields. The important boundary is
that artistic ideas do not remain vague advice: every idea must compile into
prompt text, continuity constraints, or QA checks consumed by later stages.

### Continuity Director

`continuity_bible` reads `film_timeline.yaml`, `screenplay_structure.yaml`, and
the design report. It maintains:

- characters
- locations
- wardrobe
- lighting
- screen axis
- continuity risks

The current deterministic checks flag wardrobe jumps and screen-axis flips.

### Editing Director

`editing_review` reads `film_timeline.yaml` and QA data. It evaluates:

- pacing
- repeated visual assets
- emotion curve
- edit recommendations

It does not render media. It writes recommendations for later action.

### Rework Director

`rework_plan` reads:

- `director_review.yaml`
- `editing_review.yaml`
- `continuity_bible.yaml`

It merges findings into executable actions grouped as:

- `regenerate_video`
- `recut`
- `replace_source_media`

### Multi-Take Director

`take_select` reads existing `vid_<segment>_take_<take>.mp4` files and writes
`take_selection.yaml`. When an LLM client is configured, the stage calls the LLM
as a take judge with QA evidence and candidate metadata. Without an LLM, it uses
a deterministic QA proxy score. When the file exists, `film_timeline` uses the
selected take as the generated-video clip for that segment.

### Creative Review Director

`creative_review` reads the timeline, editing review, continuity bible, QA
report, and script. With an LLM client, it asks the model to judge story
clarity, cinematic intent, pacing, emotional arc, and continuity. Without an
LLM, it creates findings from existing director reports.

### Visual Semantic QA Director

`visual_semantic_qa` reads visual clip paths, design intent, continuity context,
the director contract, and QA checks. With an LLM client, it asks the model
whether visuals match the script, character identity, costume, location, shot
intent, and the contract's `must_show` / `must_not_show` assertions. Without an
LLM, it flags metadata mismatches such as scene or wardrobe drift, checks
contract assertions against timeline metadata, and compares storyboard scene,
wardrobe, character-position, and composition bindings when those fields are
available.

### Supervising Director

`film_supervisor` reads `rework_plan.yaml`, `creative_review.yaml`,
`visual_semantic_report.yaml`, and QA output. It writes `film_supervisor.yaml`
with the next stages to run. It does not mutate media.

In the default build, `pipeline.auto_rework: true` lets the supervisor trigger
`rework_execute` automatically when it reports `needs_rework`. `rework_execute`
reads `rework_plan.yaml`, quarantines invalid generated videos, writes concrete
regeneration/recut/source-media replacement queues, and marks affected stages
pending. The pipeline then reruns the supervisor's requested stages, such as
`generate_video -> take_select -> film_timeline -> qa -> film_supervisor`, up to
`pipeline.max_rework_cycles`.

## Prompt Template Vs Local Template

The LLM path uses prompt templates, but that does not mean the image prompts are hard-coded.

Prompt templates define:

- the model role
- required output JSON schema
- fields that must be returned
- validation expectations

The model still supplies the creative content inside `director_vision`, `cinematic_format`, `image_prompt`, and `reasoning`.

Local template fallback is different: the program itself constructs the creative-looking prompt without asking a model. That only happens when no LLM client is configured.

Several later director layers are deterministic by default, but they preserve
and consume LLM-authored design fields when the LLM path was used.
`director_contract`, `take_select`, `creative_review`, and
`visual_semantic_qa` have real LLM judge or prompt-compiler paths. These are
execution-layer directors: their job is to keep the film workflow coherent, not
to fake model creativity when no LLM is configured.

## Quality Boundaries

The code can verify wiring, schema, and required fields. It cannot guarantee that a model's creative taste is good. Real production review should inspect:

- `design_report.yaml`
- `image_prompts.yaml`
- generated reference images
- generated final images
- rendered motion segments

For strict production mode, configure an LLM mode and avoid `llm.mode: none`.
