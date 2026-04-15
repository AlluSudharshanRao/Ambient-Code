# Ambient Code — Architecture Overview

Ambient Code is a developer tooling system that **watches, remembers, and reasons about your codebase the way a senior engineer would** — not at commit time, but continuously, as you work.

Instead of a stateless linter that runs on demand, Ambient Code builds a living model of your codebase over time: tracking which files change together, which functions are growing complex, which areas lack test coverage. When a meaningful pattern emerges, it surfaces a finding — inline, in a digest, or as a chat notification.

---

## System Architecture

The system is composed of three independent layers that communicate through well-defined file contracts, so each layer can be developed, tested, and deployed separately.

```
┌──────────────────────────────────────────────────────┐
│  Layer 1 — Collection (VS Code Extension)            │
│  TypeScript · vscode API · diff                      │
│                                                      │
│  FileWatcher · CursorTracker · EditStream            │
│  GitWatcher  · EventQueue (NDJSON)                   │
└──────────────────────┬───────────────────────────────┘
                       │  ~/.ambient-code/events.ndjson
                       ▼
┌──────────────────────────────────────────────────────┐
│  Layer 2 — Context Engine (Python background process)│
│  Python · tree-sitter · SQLite · Pydantic            │
│                                                      │
│  Tailer · SymbolIndex · VelocityTracker · Store      │
└──────────────────────┬───────────────────────────────┘
                       │  ~/.ambient-code/context.db
                       ▼
┌──────────────────────────────────────────────────────┐
│  Layer 3 — Insight Engine  (planned)                 │
│  LLM reasoning · Pattern triggers · Finding surface  │
└──────────────────────────────────────────────────────┘
```

---

## Repository Layout

```
ambient-code/
├── extension/                  # Layer 1 — VS Code extension (TypeScript)
│   ├── src/
│   │   ├── extension.ts        # Activation entry point
│   │   ├── types.ts            # Shared event types and interfaces
│   │   ├── collectors/
│   │   │   ├── fileWatcher.ts  # Debounced text-change collector
│   │   │   ├── cursorTracker.ts# Active-editor switch collector
│   │   │   ├── editStream.ts   # Save-event collector
│   │   │   └── gitWatcher.ts   # Git branch/commit collector
│   │   └── queue/
│   │       └── eventQueue.ts   # NDJSON append-only event log writer
│   ├── package.json
│   └── tsconfig.json
│
├── context-engine/             # Layer 2 — Python context engine (planned)
│
├── docs/
│   ├── README.md               # This file
│   ├── layer1.md               # Layer 1 deep-dive
│   ├── layer2.md               # Layer 2 spec (planned)
│   └── contributing.md         # Development guide
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

Press **F5** in VS Code to launch the extension in a new Extension Development Host window. Once active, the extension writes a status bar message:

```
Ambient Code: collecting → C:\Users\<you>\.ambient-code\events.ndjson
```

All editor events are now streaming to that file.

**Configuration** (VS Code settings):

| Setting | Default | Description |
|---|---|---|
| `ambientCode.dbPath` | `~/.ambient-code/events.ndjson` | Override the log file path |
| `ambientCode.debounceMs` | `2000` | Edit inactivity window before a `file_change` event fires |
| `ambientCode.flushIntervalMs` | `5000` | Interval between NDJSON flush cycles |

### Layer 2 — Context Engine

See [layer2.md](layer2.md) — not yet built.

---

## Data Contract Between Layers

The only coupling between layers is the NDJSON file at `~/.ambient-code/events.ndjson`.

Each line is a JSON-serialised `CodeEvent` object. See [layer1.md](layer1.md#event-schema) for the full schema and example payloads.

Layer 2 reads this file by maintaining a byte-offset cursor, processing new lines as they appear. Because the file is append-only, Layer 2 can crash and restart without losing events — it picks up from the last committed offset.

---

## Design Principles

| Principle | Meaning |
|---|---|
| Collect dumbly | Layer 1 emits raw events. It never analyses, scores, or filters. |
| Think lazily | Analysis is deferred to Layer 2/3, triggered by accumulated patterns. |
| Fail silently in the IDE | Errors in collection are logged to the extension host output but never shown as VS Code notifications. |
| Layers are independently deployable | Each layer communicates only through files. Layer 2 can run on a remote machine reading a synced log. |

---

## Further Reading

- [Layer 1 — Collection Layer](layer1.md)
- [Layer 2 — Context Engine](layer2.md) *(planned)*
- [Contributing Guide](contributing.md)
