# Ambient Code — Context Engine (Layer 2)

> Python background process that tails the VS Code extension's event log and builds a living model of your codebase.

## What it does

The context engine reads events from `~/.ambient-code/events.ndjson` (written by the Layer 1 VS Code extension) and:

1. **Persists raw events** into a queryable SQLite database (`~/.ambient-code/context.db`)
2. **Indexes symbols** — on every file save, runs tree-sitter on the saved file and extracts functions, classes, methods, interfaces, type aliases, and enums
3. **Tracks change velocity** — counts how many times each file is saved per day, accumulating a churn signal that Layer 3 uses to prioritise which files to reason about

## Quick start

**Prerequisites:** Python ≥ 3.11, pip

```bash
cd context-engine
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -e ".[dev]"
```

**Run:**

```bash
ambient
# or
python -m ambient.main
```

The engine logs to stdout and runs until `Ctrl+C`.

## Supported languages (symbol indexing)

| Language | VS Code ID | Symbols extracted |
|---|---|---|
| Python | `python` | functions, classes |
| JavaScript | `javascript` | functions, classes, methods |
| TypeScript | `typescript` | functions, classes, methods, interfaces, type aliases, enums |
| TSX | `typescriptreact` | same as TypeScript |

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `AMBIENT_LOG_PATH` | `~/.ambient-code/events.ndjson` | Event log from Layer 1 |
| `AMBIENT_DB_PATH` | `~/.ambient-code/context.db` | Output SQLite database |
| `AMBIENT_POLL_MS` | `1000` | Poll interval in ms |
| `AMBIENT_LOG_LEVEL` | `INFO` | Logging verbosity |
| `AMBIENT_RESET_CURSOR` | unset | Set to `1` to replay entire log |

## Architecture

See [docs/layer2.md](../docs/layer2.md) for the full component breakdown, SQLite schema, and data flow diagram.
