# Take Select Stage Director

## Inputs

- `assets/videos/vid_<segment>_take_<take>.mp4`
- `assets/videos/vid_<segment>_shot_<shot>_take_<take>.mp4`
- Optional `pipeline/<project>/video_gen_state.json`
- Optional `pipeline/<project>/render_report.yaml`
- Optional `pipeline/<project>/director_contract.yaml` (expected clip durations)

## Outputs

- `pipeline/<project>/take_selection.yaml`

## Procedure

1. Discover multi-take generated-video candidates created by `generate_video` when `video.takes > 1`, grouping director coverage independently by `(segment_id, shot_order)`.
2. Ignore candidates not marked done when `video_gen_state.json` has a done list.
3. Score takes with deterministic frame analysis (`utils/video_quality.py`):
   ffprobe duration + 3 evenly spaced sampled frames per take, combined into a
   0-100 composite of **sharpness** (Laplacian variance, weight 0.35),
   **brightness** (mean luminance, 0.25), **duration** (deviation from the
   director-contract `generation.duration`, 0.25), and **stability**
   (average-hash agreement across sampled frames — frozen-video detection, 0.15).
   Risk segments from `render_report.yaml` keep their -1.0 penalty on top.
   If analysis fails for any take (ffmpeg missing, extraction error), the whole
   segment falls back to legacy byte-size scoring with a warning, so scores on
   one segment always share one scale.
4. If an LLM client is configured, ask the LLM judge to choose from the QA-scored candidates; the LLM choice still overrides the deterministic score.
   With `take_select.selection_strategy: mcts` (opt-in), the single-pass judge is
   replaced by an MCTS-style UCT search — see "MCTS selection strategy" below.
5. Write candidates (with per-take `quality` audit blocks and per-segment `scoring` mode), selected take, selected path, and judge process.
6. Let `film_timeline` consume the selected take on the next timeline build.

## MCTS selection strategy (opt-in, AniMaker-inspired)

Off by default (`selection_strategy: auto` keeps the single-pass judge — zero
behavior change). With `selection_strategy: mcts`:

1. The segment's candidate takes form a shallow search tree: a root with one
   leaf per take; evaluation edges are LLM **pairwise duels** (more stable
   than absolute scoring and naturally tree-shaped).
2. Each iteration picks the next duel pair by UCT
   (`win_rate + c*sqrt(ln(total)/visits)`, `c = take_select.mcts_exploration`),
   balancing the current duel leader (exploit) against rarely-compared takes
   (explore; unvisited takes have infinite UCT and duel first). The
   deterministic quality score is the Bayesian prior for unvisited leaves and
   breaks all ties — a zero-information search degrades exactly to the legacy
   deterministic ranking.
3. `take_select.mcts_budget` (default 5) is a **hard cap** on LLM duel
   attempts per segment; errored attempts also count (they may have cost
   money) but add no visits. LLM token usage still flows into the project
   BudgetTracker via the pipeline `on_usage` hook, like any other LLM call.
4. Given identical LLM responses the search is fully deterministic — UCT is
   closed-form and ties break by (prior, take_number); no RNG is involved.
5. Fallbacks: no LLM client → deterministic ranking + one warning, with a
   `fallback_no_llm` trace block; all duels failing → prior favorite with
   `llm_status: fallback_after_error`; an unparseable verdict counts as an
   honest tie (0.5/0.5) and stays visible in the trace.

### Decision trace (auditability first)

Every segment selected under `mcts` gains an `mcts` block in
`take_selection.yaml` (legacy fields unchanged; downstream consumers are
unaffected):

- `tree`: root id, leaf take ids, evaluation-edge count
- `evaluations[]`: per-duel `index`, `pair`, `winner` (or `tie` / `error`),
  `reason` — the complete "why not the other take" record
- `candidates[]`: per-take `prior`, `visits`, `wins`, `win_rate`, `final_uct`
- `budget` / `evaluations_used` / `evaluation_errors` / `exploration`
- `summary`: human-readable verdict, also mirrored into the selection `reason`

`selection_process` gains `selection_strategy` and (under mcts) an `mcts`
summary block with per-segment `segments` / `fallback_segments` lists.

## Do Not

- Do not call `generate_video` from this stage.
- Do not delete losing takes.
- Do not bypass QA or human review for critical shots.
- Do not require an API key to select existing takes.
- Do not mix scoring scales within one segment (quality composites and byte sizes are not comparable).
- Do not exceed `take_select.mcts_budget` LLM evaluations per segment under the mcts strategy — the budget is a hard cost cap.
