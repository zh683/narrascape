# Bridge / AI Assistant Mode

Bridge mode lets an AI assistant act as Narrascape's LLM backend through project-local files. It is useful when you want Codex, Kimi, Claude, Copilot, or another assistant to perform creative tasks without configuring an external LLM API key.

`llm.mode: ai_assistant` and `llm.mode: bridge` both use this file-based exchange.

## Flow

```text
Narrascape command
-> writes .narrascape/bridge/pending/task_<id>.md
-> assistant reads the task and creates a response
-> assistant writes .narrascape/bridge/completed/response_<id>.json
-> Narrascape reads the response and continues
```

The task id is stable for identical prompts. If a command times out, process the pending task and rerun the command; Narrascape can reuse the completed response.

## Enable It

In `config.yaml`:

```yaml
llm:
  mode: ai_assistant
  timeout: 300
```

Or:

```yaml
llm:
  mode: bridge
  timeout: 300
```

You can also use an environment override:

```powershell
$env:NARRASCAPE_LLM_MODE = "ai_assistant"
$env:NARRASCAPE_BRIDGE_TIMEOUT = "600"
```

## Wait Modes

`llm.bridge_wait` controls what happens while a task is unanswered:

| Value | Behavior | Best for |
| --- | --- | --- |
| `block` (default) | Poll until the response arrives or `timeout` expires | a human/assistant watching the terminal live |
| `exit_on_pending` | Pause the build immediately with an `awaiting_bridge` status; the stage stays `pending` (not `failed`) and rerunning the command resumes once the response exists | turn-based assistants (Kimi Work, Codex) that process tasks between runs |

```yaml
llm:
  mode: ai_assistant
  bridge_wait: exit_on_pending
  timeout: 1800
```

With `exit_on_pending`, a build that reaches an unanswered task prints the
task/response paths and stops without marking anything failed. Process the
task, then rerun the same command: the stable task id lets the bridge pick up
the completed response and continue. Environment override:
`NARRASCAPE_BRIDGE_WAIT=exit_on_pending`.

An explicitly configured `llm.bridge_wait` or `llm.timeout` takes precedence
over its environment variable. When the project omits the field,
`NARRASCAPE_BRIDGE_WAIT` or `NARRASCAPE_BRIDGE_TIMEOUT` supplies the runtime
default.

`llm.bridge_batch` controls task granularity:

| Value | Behavior |
| --- | --- |
| `true` (default) | One batched task per stage (all shots in a single JSON payload) |
| `false` | One smaller task per shot/segment in `design` and `director_contract` — easier for assistants to answer reliably, and each shot resumes independently |

## Task File

Narrascape writes:

```text
.narrascape/bridge/pending/task_<id>.md
```

The file includes:

- the assistant role
- the full prompt
- whether JSON is required
- where to write the response

## Response File

The assistant writes:

```text
.narrascape/bridge/completed/response_<id>.json
```

**Write it atomically**: write a temporary file first, then rename (move) it
over the response path. Narrascape polls the response path while waiting; a
partially written (unparseable) response file is treated as still-in-progress
and the wait continues until timeout instead of failing on the partial read.
A parseable response whose `content` field is missing or not a string is a
semantic error and fails immediately.

Format:

```json
{
  "content": "the response text or JSON string requested by the task",
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0
  }
}
```

When the task asks for JSON, put the JSON payload inside the `content` string. Narrascape parses `content`.

`content` may also be a directly embedded JSON object or array, which avoids
double-encoding a large payload inside a JSON string:

```json
{
  "content": {"shots": [{"segment_id": 1}]},
  "usage": {}
}
```

## Error Feedback

Validated prompts retry through the bridge: when a response cannot be parsed
or fails schema validation, Narrascape issues a follow-up task whose text
contains the exact parse/validation error (look for "Your previous response
was not valid JSON" or "had validation errors"). Answer the follow-up task
with the corrected payload; each follow-up is a new task id, so the loop also
resumes correctly across reruns in `exit_on_pending` mode.

## Discovery

The `assistant_handoff` stage lists unanswered bridge tasks under
`pending_bridge_tasks` in `assistant_handoff.yaml` (and a `## Pending Bridge
Tasks` section in the `.md`), so takeover flows do not depend on watching
console output.

## Batching

Bridge-backed modes intentionally batch large creative calls by default:

| Component | `bridge_batch: true` (default) | `bridge_batch: false` |
| --- | --- | --- |
| `ScriptAnalyzer` | one task for all segments | one task for all segments |
| `PromptDirector` (design) | one task for all shot designs | one task per shot |
| `director_contract` | one task for all shot contracts | one task per shot |

Plain bridge calls do not retry, so a timeout never creates duplicate task
files (the pending task keeps a stable id and is reused). Validated prompts
are the exception: parse/validation failures issue a follow-up task carrying
the exact error — see [Error Feedback](#error-feedback).

## Common Tasks

| Task type | Expected content |
| --- | --- |
| Script analysis | JSON array of segment analysis objects |
| Shot design | JSON array of shot design objects |
| Character extraction | JSON object with characters and scenes |
| Storyboard | JSON array or object matching the requested schema |

Always follow the exact schema in the task file.

## Troubleshooting

### Bridge timeout

Check:

- The response file path matches the task id.
- The response JSON is valid.
- The response has a `content` field.
- `content` contains valid JSON if the task requested JSON.

The timeout error reports the task id, the wait duration, the response file
path, and whether an incomplete (still-being-written) response file was
observed — use that to distinguish "assistant never responded" from
"assistant wrote the file non-atomically".

Then rerun the command. With `llm.bridge_wait: exit_on_pending`, an
unanswered task pauses the build instead of raising a timeout — process the
task and rerun to resume.

### Bridge lock timeout

The bridge serializes task/response file exchanges with a `.bridge.lock`
file in the bridge directory. If a narrascape process crashes while holding
it, the leftover lock self-recovers after 60 seconds (stale-lock reclaim) —
just rerun the command. To recover immediately, delete
`.narrascape/bridge/.bridge.lock` manually. A *fresh* lock means another
narrascape process is actively running; let it finish instead of deleting.

### Expected JSON array/object

The assistant probably wrapped the answer in prose or Markdown. Rewrite the response so `content` contains only the requested JSON payload.

### Too many pending tasks

Current analysis and design are batched, but different stages still create separate tasks. Process the oldest pending task first unless the command output points to a specific task id.

## Bridge Vs API Vs None

| Mode | LLM source | Best for |
| --- | --- | --- |
| `ai_assistant` | local task files processed by an assistant | collaborative creative work |
| `bridge` | same file bridge, explicit integration mode | advanced/manual bridge workflows |
| `api` | external provider API | automated production runs |
| `none` | no LLM; deterministic fallback | offline testing and pipeline verification |
