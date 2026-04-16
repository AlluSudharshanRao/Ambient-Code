# Ambient Code

> A developer tooling system that watches, remembers, and reasons about your codebase the way a senior engineer would — continuously, as you work.

---

## What Is Ambient Code?

Traditional static analysis tools run on demand and have no memory of how code evolved.  
Ambient Code is different: it **observes every edit, save, and git action in real time**, builds a persistent model of your codebase, and surfaces LLM-generated insights exactly when they become relevant — not when you ask for them.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Developer's Machine                              │
│                                                                         │
│  ┌────────────────────────────────┐                                     │
│  │   VS Code Editor               │                                     │
│  │   ┌──────────────────────────┐ │                                     │
│  │   │  Layer 1 — Collection    │ │  ← TypeScript Extension             │
│  │   │  Sensors (no analysis)   │ │                                     │
│  │   └──────────┬───────────────┘ │                                     │
│  │              │  events.ndjson  │                                     │
│  │   ┌──────────▼───────────────┐ │                                     │
│  │   │  Layer 3 findings watcher│ │  ← surfaces toast/output            │
│  │   └──────────────────────────┘ │                                     │
│  └────────────────────────────────┘                                     │
│              │ events.ndjson (append-only file)                         │
│              ▼                                                           │
│  ┌───────────────────────────────┐                                      │
│  │  Layer 2 — Context Engine     │  ← Python background process         │
│  │  tree-sitter · SQLite · WAL   │                                      │
│  └──────────────┬────────────────┘                                      │
│                 │ context.db (SQLite)                                   │
│                 ▼                                                        │
│  ┌───────────────────────────────┐                                      │
│  │  Layer 3 — Insight Engine     │  ← Python + OpenAI API               │
│  │  Triggers · LLM · Cooldown    │                                      │
│  └──────────────┬────────────────┘                                      │
│                 │ findings.ndjson (append-only file)                    │
│                 └──────────────────────────────────────►  VS Code       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## System Layers

| Layer | Role | Technology | Status |
|---|---|---|---|
| **1 — Collection** | Silent sensor: captures edits, saves, cursor moves, git actions | TypeScript · VS Code API · diff | ✅ Complete |
| **2 — Context Engine** | Builds persistent codebase model: symbol index, velocity, event log | Python · tree-sitter · SQLite · Pydantic | ✅ Complete |
| **3 — Insight Engine** | Detects patterns, calls LLM, surfaces findings to VS Code | Python · OpenAI API · NDJSON | ✅ Complete |

---

## Data Flow

```
┌──────────────┐   file_change / file_save    ┌──────────────────┐
│  VS Code     │   cursor_move / git_event    │  events.ndjson   │
│  Extension   │ ─────────────────────────►  │  (append-only)   │
│  (Layer 1)   │                              └────────┬─────────┘
└──────────────┘                                       │ tail + cursor
                                                       ▼
                                             ┌──────────────────┐
                                             │  Context Engine  │
                                             │  (Layer 2)       │
                                             │                  │
                                             │  SymbolIndexer   │
                                             │  VelocityTracker │
                                             │  Store (SQLite)  │
                                             └────────┬─────────┘
                                                      │ READ-ONLY
                                                      ▼
                                             ┌──────────────────┐
                                             │  Insight Engine  │
                                             │  (Layer 3)       │
                                             │                  │
                                             │  Triggers        │
                                             │  LLM (OpenAI)    │
                                             │  Writer          │
                                             └────────┬─────────┘
                                                      │ findings.ndjson
                                                      ▼
                                             ┌──────────────────┐
                                             │  FindingsWatcher │
                                             │  (Layer 1)       │
                                             │                  │
                                             │  Toast notif.    │
                                             │  Output channel  │
                                             └──────────────────┘
```

---

## File Contracts

All three layers communicate **exclusively through local files**. No sockets, no shared memory, no APIs between layers.

| File | Written by | Read by | Format |
|---|---|---|---|
| `~/.ambient-code/events.ndjson` | Layer 1 | Layer 2 | NDJSON (append-only) |
| `~/.ambient-code/cursor` | Layer 2 | Layer 2 | Plain text (byte offset) |
| `~/.ambient-code/context.db` | Layer 2 | Layer 3 | SQLite (WAL mode) |
| `~/.ambient-code/findings.ndjson` | Layer 3 | Layer 1 | NDJSON (append-only) |

---

## Quick Start

### Prerequisites

| Tool | Version | Required by |
|---|---|---|
| VS Code | ≥ 1.85 | Layer 1 |
| Node.js | ≥ 18 | Layer 1 build |
| Python | ≥ 3.11 | Layer 2 & 3 |
| OpenAI API key | — | Layer 3 |

### Step 1 — Layer 1: VS Code Extension

```bash
cd extension
npm install
npm run compile
# Press F5 in VS Code to launch the Extension Development Host
```

The status bar will show:
```
Ambient Code: collecting → ~/.ambient-code/events.ndjson
```

### Step 2 — Layer 2: Context Engine

```bash
cd context-engine
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
ambient
```

Layer 2 starts tailing `events.ndjson` and writing to `context.db`.

### Step 3 — Layer 3: Insight Engine

```bash
cd insight-engine
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
set OPENAI_API_KEY=sk-...       # Windows
# export OPENAI_API_KEY=sk-...  # macOS / Linux
ambient-insight
```

Layer 3 polls `context.db` every 60 seconds, calls OpenAI when a pattern fires, and writes findings to `findings.ndjson`. VS Code surfaces them automatically.

---

## Repository Layout

```
ambient-code/
│
├── extension/                         # Layer 1 — VS Code extension
│   ├── src/
│   │   ├── extension.ts               # Activation entry point
│   │   ├── types.ts                   # Shared event types
│   │   ├── collectors/
│   │   │   ├── fileWatcher.ts         # Debounced edit collector
│   │   │   ├── cursorTracker.ts       # File-switch collector
│   │   │   ├── editStream.ts          # Save-event collector
│   │   │   └── gitWatcher.ts          # Git HEAD change collector
│   │   ├── findings/
│   │   │   └── findingsWatcher.ts     # Layer 3 findings → VS Code UI
│   │   └── queue/
│   │       └── eventQueue.ts          # NDJSON append-only writer
│   ├── package.json
│   └── tsconfig.json
│
├── context-engine/                    # Layer 2 — Python context engine
│   ├── ambient/
│   │   ├── models.py                  # Pydantic v2 event models
│   │   ├── tailer.py                  # NDJSON tailer + byte-offset cursor
│   │   ├── main.py                    # Poll loop + graceful shutdown
│   │   ├── db/store.py                # SQLite DDL + all queries
│   │   ├── indexer/symbol_index.py    # tree-sitter symbol extractor
│   │   └── velocity/tracker.py        # Daily churn aggregator
│   ├── tests/                         # 120 pytest tests
│   └── pyproject.toml
│
├── insight-engine/                    # Layer 3 — Python insight engine
│   ├── ambient_insight/
│   │   ├── models.py                  # Finding Pydantic model
│   │   ├── reader.py                  # Read-only context.db interface
│   │   ├── writer.py                  # findings.ndjson writer + cooldown
│   │   ├── main.py                    # InsightEngine poll loop
│   │   ├── triggers/                  # Pattern detectors (3 built-in)
│   │   └── llm/                       # OpenAI client + prompt templates
│   ├── tests/                         # 115 pytest tests
│   └── pyproject.toml
│
└── docs/
    ├── README.md                      # Architecture overview (this file's sibling)
    ├── layer1.md                      # Layer 1 deep-dive
    ├── layer2.md                      # Layer 2 deep-dive
    ├── layer3.md                      # Layer 3 deep-dive
    ├── tests.md                       # Full test-suite reference (235 tests)
    └── contributing.md                # Development & contribution guide
```

---

## Test Coverage

| Layer | Tests | Command |
|---|---|---|
| Layer 2 — Context Engine | **120 passing** | `cd context-engine && pytest tests/ -v` |
| Layer 3 — Insight Engine | **115 passing** | `cd insight-engine && pytest tests/ -v` |
| Layer 1 — Extension | TypeScript strict mode + ESLint | `cd extension && npx tsc --noEmit && npm run lint` |

---

## Design Principles

| Principle | Meaning |
|---|---|
| **Collect dumbly** | Layer 1 is a pure sensor — no analysis, no scoring, no filtering. |
| **Think lazily** | Reasoning is deferred to later layers, triggered by accumulated patterns only when thresholds are crossed. |
| **Communicate through files** | Layers are decoupled by well-defined file contracts; each can run on a different machine or process. |
| **Crash-safe delivery** | Byte-offset cursors are committed only after successful batch persistence. Restarts re-deliver the last batch. |
| **Fail silently in the IDE** | Collection errors are logged to the extension host output channel, never surfaced as VS Code notifications. |
| **No remote calls in Layers 1–2** | Only Layer 3 makes outbound network calls (OpenAI). Layers 1 and 2 run entirely offline. |

---

## Privacy

- **Layer 1 & 2:** All data stays on your machine. No network calls.
- **Layer 3:** The only outbound call is to OpenAI. Only code diffs and symbol names are sent — never full file contents, credentials, or personal data. You can audit exactly what is sent in `insight-engine/ambient_insight/llm/prompts.py`.

---

## Documentation

| Document | Description |
|---|---|
| [docs/README.md](docs/README.md) | Full architecture reference with component diagrams |
| [docs/layer1.md](docs/layer1.md) | Layer 1 deep-dive: collectors, event schema, configuration |
| [docs/layer2.md](docs/layer2.md) | Layer 2 deep-dive: tailer, store, symbol indexer, velocity |
| [docs/layer3.md](docs/layer3.md) | Layer 3 deep-dive: triggers, LLM pipeline, findings writer |
| [docs/tests.md](docs/tests.md) | Per-test reference for all 235 tests across Layers 2 & 3 |
| [docs/contributing.md](docs/contributing.md) | Setup, workflow, conventions, PR checklist |
