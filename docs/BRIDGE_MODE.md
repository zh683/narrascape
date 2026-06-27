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

## Batching

Bridge-backed modes intentionally batch large creative calls:

| Component | Bridge behavior |
| --- | --- |
| `ScriptAnalyzer` | one task for all segments |
| `PromptDirector` | one task for all shot designs |

Retries are disabled for bridge calls so a timeout does not create duplicate task files.

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

Then rerun the command.

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
