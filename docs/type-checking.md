# Type Checking

Narrascape now runs a full-source mypy gate.

Run the enforced check:

```bash
mypy
```

`pyproject.toml` sets `files = ["src"]`, so the default command checks the entire
`src/narrascape` package under strict mode. CI runs the same command and treats it
as a required check.

## Policy

- Fix real type errors in production code instead of narrowing the checked file list.
- Keep dynamic UI or provider boundaries explicit with typed helper functions and
  concrete `dict[str, Any]` / `list[...]` annotations.
- When a stage accepts partially trusted YAML, JSON, API, or Streamlit state data,
  normalize it before using it in pipeline logic.
- Do not add module-level ignores for new code without documenting the reason and a
  removal path.
