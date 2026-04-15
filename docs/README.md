# Ambient Code — Architecture Overview

Ambient Code is a developer tooling system that **watches, remembers, and reasons about your codebase the way a senior engineer would** — not at commit time, but continuously, as you work.

Instead of a stateless linter that runs on demand, Ambient Code builds a living model of your codebase over time: tracking which files change together, which functions are growing complex, which areas lack test coverage. When a meaningful pattern emerges, it surfaces a finding — inline, in a digest, or as a chat notification.

---

## System Architecture

The system is composed of three independent layers that communicate through well-defined file contracts, so each layer can be developed, tested, and deployed separately.

```
┌──────────────────────────────────────────────────────┐
│  Layer 1 — Collection (VS Code Extension)   ✅ Built  │
│  TypeScript · vscode API · diff                      │
│                                                      │
│  FileWatcher · CursorTracker · EditStream            │
│  GitWatcher  · EventQueue (NDJSON)                   │
└──────────────────────┬───────────────────────────────┘
                       │  ~/.ambient-code/events.ndjson
                       ▼
┌──────────────────────────────────────────────────────┐
│  Layer 2 — Context Engine (Python)          ✅ Built  │
│  Python · tree-sitter 0.25 · SQLite · Pydantic v2   │
│                                                      │
│  Tailer · SymbolIndexer · VelocityTracker · Store    │
└──────────────────────┬───────────────────────────────┘
                       │  ~/.ambient-code/context.db
                       ▼
┌──────────────────────────────────────────────────────┐
│  Layer 3 — Insight Engine             🔜 Planned     │
│  LLM reasoning · Pattern triggers · Finding surface  │
└──────────────────────────────────────────────────────┘
```

---

## Repository Layout

```
ambient-code/
├── extension/                    # Layer 1 — VS Code extension (TypeScript)
│   ├── src/
│   │   ├── extension.ts          # Activation entry point
│   │   ├── types.ts              # Shared event types and interfaces
│   │   ├── collectors/
│   │   │   ├── fileWatcher.ts    # Debounced text-change collector
│   │   │   ├── cursorTracker.ts  # Active-editor switch collector
│   │   │   ├── editStream.ts     # Save-event collector
│   │   │   └── gitWatcher.ts     # Git branch/commit collector
│   │   └── queue/
│   │       └── eventQueue.ts     # NDJSON append-only event log writer
│   ├── package.json
│   └── tsconfig.json
│
├── context-engine/               # Layer 2 — Python context engine
│   ├── ambient/
│   │   ├── __init__.py
│   │   ├── models.py             # Pydantic v2 event models (mirrors TS types)
│   │   ├── tailer.py             # NDJSON tailer with byte-offset cursor
│   │   ├── main.py               # Orchestration loop + graceful shutdown
│   │   ├── db/
│   │   │   └── store.py          # SQLite schema DDL + all queries
│   │   ├── indexer/
│   │   │   └── symbol_index.py   # tree-sitter symbol extractor
│   │   └── velocity/
│   │       └── tracker.py        # Daily churn aggregation
│   ├── smoke_test.py             # End-to-end integration test
│   └── pyproject.toml
│
├── docs/
│   ├── README.md                 # This file
│   ├── layer1.md                 # Layer 1 deep-dive
│   ├── layer2.md                 # Layer 2 deep-dive
│   └── contributing.md           # Development guide
│
└── .gitignore
```

---

## Quick Start

### Layer 1 — VS Code Extension

**Prerequisites:** Node.js ≥ 18, VS Code ≥ 1.85

```bash
cd extension
npm install
npm run compile
```

Press **F5** in VS Code to launch the extension in a new Extension Development Host window. Once active:

```
Ambient Code: collecting → C:\Users\<you>\.ambient-code\events.ndjson
```

**Configuration** (VS Code settings):

| Setting | Default | Description |
|---|---|---|
| `ambientCode.dbPath` | `~/.ambient-code/events.ndjson` | Override the log file path |
| `ambientCode.debounceMs` | `2000` | Edit inactivity window before a `file_change` event fires |
| `ambientCode.flushIntervalMs` | `5000` | Interval between NDJSON flush cycles |

### Layer 2 — Context Engine

**Prerequisites:** Python ≥ 3.11

```bash
cd context-engine
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate # macOS / Linux
pip install -e ".[dev]"
ambient
```

**Environment variables:**

| Variable | Default | Description |
|---|---|---|
| `AMBIENT_LOG_PATH` | `~/.ambient-code/events.ndjson` | Event log from Layer 1 |
| `AMBIENT_DB_PATH` | `~/.ambient-code/context.db` | Output SQLite database |
| `AMBIENT_POLL_MS` | `1000` | Poll interval in ms |
| `AMBIENT_LOG_LEVEL` | `INFO` | Logging verbosity |
| `AMBIENT_RESET_CURSOR` | unset | Set to `1` to replay the entire log |

---

## Data Contract Between Layers

### Layer 1 → Layer 2

File: `~/.ambient-code/events.ndjson` — append-only NDJSON event log.

Each line is a JSON-serialised `CodeEvent`. See [layer1.md](layer1.md#event-schema) for the full schema and example payloads. Layer 2 tracks a byte-offset cursor so it can crash and restart without re-processing events.

### Layer 2 → Layer 3

File: `~/.ambient-code/context.db` — SQLite database (WAL mode).

Three tables: `events` (raw log), `symbols` (tree-sitter symbol index), `velocity` (daily churn per file). Layer 3 will query this database to assemble context windows for LLM calls.

---

## Design Principles

| Principle | Meaning |
|---|---|
| Collect dumbly | Layer 1 emits raw events — no analysis, no scoring, no filtering. |
| Think lazily | Analysis is deferred to Layer 2/3, triggered by accumulated patterns. |
| Fail silently in the IDE | Errors in collection are logged to the extension host output, never surfaced as VS Code notifications. |
| Layers are independently deployable | Each layer communicates only through files. Layer 2 can run on a remote machine reading a synced log. |
| Crash-safe delivery | The byte-offset cursor is committed only after a batch is persisted. Restarts re-deliver the last uncommitted batch. |

---

## Further Reading

- [Layer 1 — Collection Layer](layer1.md)
- [Layer 2 — Context Engine](layer2.md)
- [Layer 3 — Insight Engine](layer2.md) *(planned)*
- [Contributing Guide](contributing.md)
