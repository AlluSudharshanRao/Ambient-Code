# Ambient Code — Architecture Reference

> Full system design: components, data contracts, sequence flows, and design rationale.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Low-Level Component Map](#3-low-level-component-map)
4. [Data Contracts](#4-data-contracts)
5. [Sequence Flows](#5-sequence-flows)
6. [Design Principles](#6-design-principles)
7. [Layer Summaries](#7-layer-summaries)
8. [Further Reading](#8-further-reading)

---

## 1. System Overview

Ambient Code is a three-layer developer tooling system. Each layer has a single responsibility and communicates with adjacent layers only through local files on disk.

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — COLLECTION (VS Code Extension / TypeScript)          │
│  Role: Observe and stream. Zero analysis. Zero network calls.   │
└───────────────────────────┬─────────────────────────────────────┘
                            │  ~/.ambient-code/events.ndjson
                            │  (append-only NDJSON event log)
┌───────────────────────────▼─────────────────────────────────────┐
│  LAYER 2 — CONTEXT ENGINE (Python background process)           │
│  Role: Index, aggregate, persist. Zero network calls.           │
└───────────────────────────┬─────────────────────────────────────┘
                            │  ~/.ambient-code/context.db
                            │  (SQLite, WAL mode, read-only for L3)
┌───────────────────────────▼─────────────────────────────────────┐
│  LAYER 3 — INSIGHT ENGINE (Python background process)           │
│  Role: Detect patterns, reason with LLM, surface findings.      │
└───────────────────────────┬─────────────────────────────────────┘
                            │  ~/.ambient-code/findings.ndjson
                            │  (append-only findings log)
┌───────────────────────────▼─────────────────────────────────────┐
│  LAYER 1 — FINDINGS WATCHER (VS Code Extension / TypeScript)    │
│  Role: Tail findings file, route to VS Code UI surfaces.        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. High-Level Architecture

```
╔══════════════════════════════════════════════════════════════════════╗
║                     Developer's Workstation                          ║
║                                                                      ║
║  ┌──────────────────────────────────────────────────────────────┐   ║
║  │                  VS Code Process                             │   ║
║  │                                                              │   ║
║  │  ┌─────────────────────────────────────────────────────┐    │   ║
║  │  │             Layer 1 — Collection                    │    │   ║
║  │  │                                                     │    │   ║
║  │  │  FileWatcher    ──► file_change event               │    │   ║
║  │  │  EditStream     ──► file_save event                 │    │   ║
║  │  │  CursorTracker  ──► cursor_move event               │    │   ║
║  │  │  GitWatcher     ──► git_event                       │    │   ║
║  │  │                         │                           │    │   ║
║  │  │                   EventQueue ──► events.ndjson      │    │   ║
║  │  │                                                     │    │   ║
║  │  │  FindingsWatcher ◄── findings.ndjson                │    │   ║
║  │  │       │                                             │    │   ║
║  │  │       ├──► showInformationMessage (warning)         │    │   ║
║  │  │       ├──► showWarningMessage (critical)            │    │   ║
║  │  │       └──► Output Channel (info, always)            │    │   ║
║  │  └─────────────────────────────────────────────────────┘    │   ║
║  └──────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
║  ┌──────────────────────┐      ┌───────────────────────────────┐    ║
║  │ Layer 2              │      │ Layer 3                       │    ║
║  │ Context Engine       │      │ Insight Engine                │    ║
║  │ (Python process)     │      │ (Python process)              │    ║
║  │                      │      │                               │    ║
║  │ Tailer               │      │ ContextReader (read-only)     │    ║
║  │ SymbolIndexer        │      │ HighVelocityTrigger           │    ║
║  │ VelocityTracker      │      │ LongFunctionTrigger           │    ║
║  │ Store (SQLite)       │      │ UncoveredChurnTrigger         │    ║
║  │        │             │      │ LLM Client (OpenAI)           │    ║
║  │        ▼             │      │ FindingsWriter                │    ║
║  │   context.db ────────┼─────►│        │                      │    ║
║  │                      │      │        ▼                      │    ║
║  └──────────────────────┘      │  findings.ndjson              │    ║
║          ▲                     └───────────────────────────────┘    ║
║          │                                        ▲                  ║
║    events.ndjson                                  │ HTTP             ║
║          ▲                               ┌────────┴──────┐          ║
║          │                               │  OpenAI API   │          ║
║    (VS Code writes)                      │  (gpt-4o-mini)│          ║
║                                          └───────────────┘          ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 3. Low-Level Component Map

### Layer 1 Components

```
extension/src/
│
├── extension.ts              ← Activation entry point
│     activate()
│       ├── new EventQueue(logPath)
│       ├── new FileWatcher(queue, workspace, debounceMs)
│       ├── new CursorTracker(queue, workspace)
│       ├── new EditStream(queue, workspace)
│       ├── new GitWatcher(queue, workspace)
│       └── new FindingsWatcher()   ← NEW in Layer 3 integration
│
├── types.ts                  ← Shared TypeScript interfaces
│     CodeEvent, EventType
│     FileChangeMetadata, CursorMoveMetadata, GitEventMetadata
│
├── collectors/
│   ├── fileWatcher.ts        ← onDidChangeTextDocument → debounce → file_change
│   ├── cursorTracker.ts      ← onDidChangeActiveTextEditor → cursor_move
│   ├── editStream.ts         ← onDidSaveTextDocument → file_save
│   └── gitWatcher.ts         ← vscode.git API → git_event
│
├── findings/
│   └── findingsWatcher.ts    ← polls findings.ndjson (3s) → VS Code UI
│
└── queue/
    └── eventQueue.ts         ← in-memory buffer → 5s flush → NDJSON append
```

### Layer 2 Components

```
context-engine/ambient/
│
├── main.py                   ← ContextEngine orchestrator
│     run()
│       ├── Tailer.read_new_events()
│       ├── Store.bulk_insert_events()
│       ├── SymbolIndexer.index(event)      [file_save only]
│       ├── VelocityTracker.record(event)   [file_save only]
│       └── Tailer.commit()
│
├── tailer.py                 ← NDJSON tail + byte-offset cursor
│     read_new_events() → list[CodeEvent]
│     commit()           → persists offset atomically
│
├── models.py                 ← Pydantic v2 mirrors of TypeScript types
│     CodeEvent, EventType, Symbol
│     FileChangeMetadata, CursorMoveMetadata, GitEventMetadata
│
├── db/
│   └── store.py              ← SQLite persistence (WAL mode)
│         Schema: events | symbols | velocity
│         bulk_insert_events() | upsert_symbols() | increment_velocity()
│         get_hot_files()     | get_velocity_for_file()
│
├── indexer/
│   └── symbol_index.py       ← tree-sitter symbol extractor
│         Grammars: python | javascript | typescript | tsx
│         Kinds:    function | class | method | interface | type_alias | enum
│
└── velocity/
    └── tracker.py            ← daily churn aggregation
          record()     → increment (file_path, date) row
          hot_files()  → top-N files by edit count
          file_trend() → day-by-day churn for one file
```

### Layer 3 Components

```
insight-engine/ambient_insight/
│
├── main.py                   ← InsightEngine orchestrator
│     run()
│       loop (every POLL_MS):
│         ContextReader.get_all_workspaces()
│         for workspace:
│           for trigger in [HighVelocity, LongFunction, UncoveredChurn]:
│             results = trigger.evaluate(reader, workspace)
│             for result:
│               ctx  = assemble_context(result, reader)
│               body = call_openai(SYSTEM_PROMPT, build_user_prompt(ctx))
│               write_finding(Finding(...), findings_path)
│
├── reader.py                 ← Read-only interface to context.db
│     get_all_workspaces()      (UNION across all three tables)
│     get_hot_files()
│     get_long_functions()
│     get_recent_save_paths()
│     get_recent_events_for_file()
│     get_symbols_for_file()
│
├── models.py                 ← Finding Pydantic model
│     Finding: id | timestamp | workspace | filePath
│             trigger | severity | title | body
│     Severity: info | warning | critical
│     TriggerName: high_velocity | long_function | uncovered_high_churn
│
├── writer.py                 ← findings.ndjson append with cooldown
│     write_finding(finding, path, cooldown_seconds=3600)
│     _is_on_cooldown()   ← scans last 200 lines of file
│
├── triggers/
│   ├── base.py               ← Abstract Trigger + TriggerResult dataclass
│   ├── velocity.py           ← HighVelocityTrigger (edits/day threshold)
│   ├── long_function.py      ← LongFunctionTrigger (lines threshold)
│   └── uncovered.py          ← UncoveredHighChurnTrigger (churn + no tests)
│
└── llm/
    ├── client.py             ← OpenAI chat completions (retry on RateLimitError)
    └── prompts.py            ← Per-trigger context assembly + prompt templates
          assemble_context()  → enriches TriggerResult with symbols + diffs
          build_user_prompt() → routes to trigger-specific template
          build_title()       → one-line VS Code notification title
```

---

## 4. Data Contracts

### File: `events.ndjson` — Layer 1 → Layer 2

Append-only. Each line is a JSON-serialised `CodeEvent`.

```jsonc
// file_change — emitted after debounceMs of inactivity
{
  "timestamp": 1713121200000,   // Unix ms
  "type": "file_change",
  "workspace": "my-project",
  "filePath": "/src/auth.ts",
  "language": "typescript",
  "diff": "--- a/auth.ts\n+++ b/auth.ts\n...",
  "metadata": { "isPaste": false, "linesAdded": 4, "linesRemoved": 1 }
}

// file_save — emitted on every Ctrl+S / auto-save
{ "type": "file_save", ... }

// cursor_move — emitted on active-editor file switch
{ "type": "cursor_move", ..., "metadata": { "line": 42, "character": 8 } }

// git_event — emitted on HEAD change
{
  "type": "git_event", ...,
  "metadata": { "action": "branch_change", "branch": "feature/x", "previousBranch": "main" }
}
```

### File: `context.db` — Layer 2 → Layer 3

SQLite database, WAL mode. Three tables:

```sql
-- Raw event log (all event types)
events (id, timestamp, type, workspace, file_path, language, diff, metadata)

-- Tree-sitter symbol index (updated on every file_save)
symbols (id, file_path, workspace, name, kind, start_line, end_line, signature)
         UNIQUE(file_path, name, kind, start_line)

-- Daily churn aggregates (one row per file per day)
velocity (file_path, workspace, date, edits, lines_added, lines_removed)
          PRIMARY KEY (file_path, workspace, date)
```

### File: `findings.ndjson` — Layer 3 → Layer 1

Append-only. Each line is a JSON-serialised `Finding`.

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "timestamp": 1713130000000,
  "workspace": "my-project",
  "filePath": "/src/auth.ts",
  "trigger": "high_velocity",
  "severity": "warning",          // "info" | "warning" | "critical"
  "title": "auth.ts saved 7x today — review recommended",
  "body": "This file has been modified heavily today. The login() function..."
}
```

### File: `cursor` — Layer 2 internal

Plain text containing a single integer: the byte offset of the last committed read position in `events.ndjson`. Written atomically via tmp-file rename.

---

## 5. Sequence Flows

### A. Edit → Event persisted in DB

```
Developer edits file
    │
    ▼
VS Code fires onDidChangeTextDocument
    │
    ▼
FileWatcher debounce timer resets (2 s default)
    │
    [2 s of silence]
    │
    ▼
FileWatcher computes unified diff (before ↔ after)
    │
    ▼
EventQueue.enqueue({ type: "file_change", diff, ... })
    │
    [up to 5 s flush interval]
    │
    ▼
EventQueue.flush() → appends line to events.ndjson
    │
    [up to 1 s poll interval]
    │
    ▼
Layer 2 Tailer.read_new_events() detects new bytes
    │
    ▼
Store.bulk_insert_events([event])    ← row in events table
    │
    ▼
Tailer.commit()                      ← cursor advances
```

### B. File saved → Symbols indexed + velocity updated

```
Developer saves file (Ctrl+S)
    │
    ▼
EditStream fires file_save event → EventQueue → events.ndjson
    │
    ▼
Layer 2 picks up event in next poll cycle
    │
    ├──► Store.bulk_insert_events()        ← raw row persisted first
    │
    ├──► SymbolIndexer.index(file_path)
    │         reads file from disk
    │         runs tree-sitter queries
    │         ▼
    │    Store.upsert_symbols(file_path, symbols)
    │         DELETE WHERE file_path = ?
    │         INSERT symbols (atomic)
    │
    ├──► VelocityTracker.record(event)
    │         INSERT OR REPLACE INTO velocity
    │         (file_path, date, edits+1, lines_added+n, lines_removed+m)
    │
    └──► Tailer.commit()
```

### C. Pattern detected → Finding surfaced in VS Code

```
Layer 3 poll cycle fires (every 60 s)
    │
    ▼
ContextReader.get_all_workspaces()
    │
    ▼
for each workspace:
    HighVelocityTrigger.evaluate(reader, workspace)
        ├── get_hot_files(workspace, days=1, min_edits=5)
        └── yields TriggerResult if threshold crossed
    │
    ▼
assemble_context(result, reader)
    ├── get_symbols_for_file(file_path)
    └── get_recent_events_for_file(file_path) → diffs
    │
    ▼
build_user_prompt(ctx) → trigger-specific prompt text
    │
    ▼
call_openai(SYSTEM_PROMPT, user_prompt)   ← HTTP to api.openai.com
    │
    ▼
write_finding(Finding(...), findings_path)
    ├── _is_on_cooldown() → skip if same (file, trigger) within 1 h
    └── append JSON line to findings.ndjson
    │
    ▼
FindingsWatcher polls findings.ndjson (every 3 s)
    ├── new byte range detected
    ├── parse Finding JSON
    └── route by severity:
          info     → Output Channel only
          warning  → showInformationMessage + Output Channel
          critical → showWarningMessage + Output Channel
```

---

## 6. Design Principles

| Principle | Rationale |
|---|---|
| **Collect dumbly** | Layer 1 has no analysis burden. It can be replaced or extended without touching Layers 2/3. |
| **Think lazily** | Layer 2 defers expensive reasoning to Layer 3. Layer 3 only calls OpenAI when a pattern threshold is crossed, not on every event. |
| **File-based contracts** | Any layer can be replaced, rewritten, or run on a different host as long as it honours its file contract. |
| **Crash-safe at every boundary** | The byte-offset cursor in Layer 2 and the byte-offset polling in Layer 1's `FindingsWatcher` both tolerate process restarts without data loss or duplication. |
| **Single-writer per file** | `events.ndjson` has exactly one writer (Layer 1). `context.db` has exactly one writer (Layer 2). `findings.ndjson` has exactly one writer (Layer 3). This eliminates write-contention entirely. |
| **Cooldown over deduplication** | Layer 3 uses a time-window cooldown rather than a persistent "seen" set. This survives restarts and is self-expiring. |

---

## 7. Layer Summaries

| | Layer 1 | Layer 2 | Layer 3 |
|---|---|---|---|
| **Language** | TypeScript | Python 3.11+ | Python 3.11+ |
| **Process** | VS Code Extension Host | Background process | Background process |
| **Input** | VS Code API events | `events.ndjson` | `context.db` |
| **Output** | `events.ndjson` | `context.db` | `findings.ndjson` |
| **Network calls** | None | None | OpenAI API |
| **State** | In-memory buffer | SQLite + cursor file | `findings.ndjson` tail |
| **Tests** | TypeScript strict + ESLint | 120 pytest | 115 pytest |
| **Entry point** | `activate()` in `extension.ts` | `ambient` CLI | `ambient-insight` CLI |

---

## 8. Further Reading

| Document | Contents |
|---|---|
| [layer1.md](layer1.md) | Collector design, event schema, configuration, debounce logic |
| [layer2.md](layer2.md) | Tailer, symbol indexer, velocity tracker, SQLite schema |
| [layer3.md](layer3.md) | Triggers, LLM pipeline, cooldown, findings schema |
| [tests.md](tests.md) | Every individual test across all 235 tests |
| [contributing.md](contributing.md) | Setup, workflow, conventions, PR checklist |
