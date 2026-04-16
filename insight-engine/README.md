# Ambient Code — Layer 3: Insight Engine

The Insight Engine is the intelligence layer of the Ambient Code system.
It reads the Layer 2 context database, evaluates pattern triggers, calls
OpenAI, and appends actionable findings to `findings.ndjson` for the
VS Code extension to surface.

## Quick start

```bash
cd insight-engine
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -e ".[dev]"

export OPENAI_API_KEY=sk-...
ambient-insight
```

## Environment variables

| Variable                          | Default               | Description                      |
|-----------------------------------|-----------------------|----------------------------------|
| `OPENAI_API_KEY`                  | *(required)*          | OpenAI API key                   |
| `OPENAI_MODEL`                    | `gpt-4o-mini`         | Model override                   |
| `AMBIENT_DB_PATH`                 | `~/.ambient-code/context.db` | Layer 2 database          |
| `AMBIENT_FINDINGS_PATH`           | `~/.ambient-code/findings.ndjson` | Output file          |
| `AMBIENT_POLL_MS`                 | `60000`               | Poll interval (ms)               |
| `AMBIENT_VELOCITY_THRESHOLD`      | `5`                   | Saves/day to trigger velocity    |
| `AMBIENT_FUNCTION_LINE_THRESHOLD` | `40`                  | Lines to trigger long-function   |
| `AMBIENT_LOG_LEVEL`               | `INFO`                | Logging verbosity                |

## Triggers

| Trigger                    | Fires when…                                       |
|----------------------------|---------------------------------------------------|
| `HighVelocityTrigger`      | File saved ≥ N times today                        |
| `LongFunctionTrigger`      | Function body spans ≥ N lines in a saved file     |
| `UncoveredHighChurnTrigger`| Heavy edits with no test file saved today         |

## Testing

```bash
pytest tests/ -v   # 115 tests, 0 failures
```

## Full documentation

See [docs/layer3.md](../docs/layer3.md) for complete architecture, data
contracts, and design decisions.
