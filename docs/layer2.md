# Layer 2 — Context Engine

## Overview

Layer 2 is a Python background process that **tails the NDJSON event log** written by the Layer 1 VS Code extension and maintains a living model of the codebase in a local SQLite database.

It is a pure consumer: it never writes to the event log, never communicates with the VS Code extension directly, and never calls any external API. The only coupling to Layer 1 is the append-only NDJSON file on disk.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Component Design](#component-design)
3. [Database Schema](#database-schema)
4. [Processing Pipeline](#processing-pipeline)
5. [Installation & Running](#installation--running)
6. [Environment Variables](#environment-variables)
7. [Querying the Database](#querying-the-database)
8. [Testing](#testing)
9. [Known Limitations](#known-limitations)

---

## Architecture

### High-Level: Layer 2 in context

```
~/.ambient-code/events.ndjson
         │  (written by Layer 1, never modified by Layer 2)
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                  Layer 2 — Context Engine               │
│                                                         │
│  ┌──────────┐  read_new_events()                        │
│  │  Tailer  │◄─────────── events.ndjson                 │
│  │          │  commit()   ──► ~/.ambient-code/cursor    │
│  └────┬─────┘                                           │
│       │ list[CodeEvent]                                  │
│       ▼                                                  │
│  ┌──────────────────────────────────────────────────┐   │
│  │            ContextEngine (main.py)               │   │
│  │                                                  │   │
│  │  ┌─────────────────────────────────────────┐    │   │
│  │  │  Step 1: bulk_insert_events(batch)       │    │   │
│  │  │          ▼  (all events, always first)   │    │   │
│  │  │  Step 2: for file_save events:           │    │   │
│  │  │    SymbolIndexer.index(file_path)        │    │   │
│  │  │      reads file from disk               │    │   │
│  │  │      runs tree-sitter queries           │    │   │
│  │  │      Store.upsert_symbols(...)          │    │   │
│  │  │                                         │    │   │
│  │  │    VelocityTracker.record(event)        │    │   │
│  │  │      Store.increment_velocity(...)      │    │   │
│  │  │                                         │    │   │
│  │  │  Step 3: Tailer.commit()                │    │   │
│  │  └─────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────┘   │
│       │                                                  │
│       ▼                                                  │
│  ┌─────────────────────┐                                 │
│  │  Store (SQLite WAL)  │                                │
│  │  ─────────────────── │                                │
│  │  events   table      │                                │
│  │  symbols  table      │                                │
│  │  velocity table      │                                │
│  └─────────────────────┘                                 │
└─────────────────────────────────────────────────────────┘
         │
         ▼
~/.ambient-code/context.db
         │  (read-only by Layer 3)
```

### Low-Level: Component dependency graph

```
main.py (ContextEngine)
  │
  ├── tailer.py (Tailer)
  │     ├── reads: events.ndjson
  │     ├── writes: ~/.ambient-code/cursor
  │     └── returns: list[CodeEvent]  via models.py (Pydantic)
  │
  ├── db/store.py (Store)
  │     ├── writes: context.db (events, symbols, velocity tables)
  │     └── reads:  context.db (hot_files, velocity queries)
  │
  ├── indexer/symbol_index.py (SymbolIndexer)
  │     ├── reads: source files from disk (at file_path)
  │     ├── uses:  tree-sitter grammars (python, js, ts, tsx)
  │     └── calls: Store.upsert_symbols()
  │
  └── velocity/tracker.py (VelocityTracker)
        └── calls: Store.increment_velocity()
```

---

## Component Design

### `tailer.py` — `Tailer`

Reads new lines from the event log using a persistent byte-offset cursor.

```
Tailer state
├── log_path:    ~/.ambient-code/events.ndjson
└── cursor_path: ~/.ambient-code/cursor  (single integer, byte offset)

read_new_events()
    ├── if log file missing → return []  (extension not yet started)
    ├── open log, seek to cursor_offset
    ├── read all complete lines (up to last \n)
    ├── parse each line as CodeEvent (skip malformed lines with warning)
    └── return list[CodeEvent]  (cursor NOT advanced yet)

commit(new_offset)
    ├── write new_offset to tmp file
    └── rename tmp → cursor_path  (atomic on POSIX and Windows)
```

**Crash-safe guarantee:** The cursor is only committed *after* the batch is fully persisted to SQLite. If Layer 2 crashes between `bulk_insert_events` and `commit`, the next restart re-delivers the same batch. SQLite's `INSERT OR IGNORE` / upsert semantics make this idempotent.

---

### `models.py` — Pydantic models

Python mirror of the TypeScript event types. Uses Pydantic v2 with `populate_by_name=True` to accept both camelCase (from JSON) and snake_case (for Python code).

| Model | Description |
|---|---|
| `CodeEvent` | Base event. `filePath` aliased to `file_path`. `type` aliased to `event_type`. |
| `EventType` | `StrEnum`: `file_change`, `file_save`, `cursor_move`, `git_event` |
| `FileChangeMetadata` | `isPaste` (bool), `linesAdded` (int), `linesRemoved` (int) |
| `CursorMoveMetadata` | `line` (int), `character` (int) |
| `GitEventMetadata` | `action`, `branch`, `previousBranch`, `commitHash` |
| `Symbol` | Internal domain type: `name`, `kind`, `start_line`, `end_line`, `signature` |

---

### `db/store.py` — `Store`

SQLite persistence layer using the Python standard library `sqlite3`. WAL mode is enabled for concurrent reads while Layer 3 queries the database.

**Key operations:**

| Method | Description |
|---|---|
| `bulk_insert_events(events)` | Batch insert with `executemany` in a single transaction |
| `upsert_symbols(file_path, symbols)` | `DELETE` all for file, then `INSERT` — ensures no stale symbols |
| `increment_velocity(...)` | `INSERT OR REPLACE` with arithmetic increment on `edits`, `lines_added`, `lines_removed` |
| `get_hot_files(workspace, days, top_n)` | `SUM(edits) GROUP BY file_path ORDER BY DESC LIMIT n` |
| `get_velocity_for_file(file_path, days)` | Day-by-day churn rows for a single file |

---

### `indexer/symbol_index.py` — `SymbolIndexer`

Parses source files on save using tree-sitter and extracts named symbols.

```
SymbolIndexer
│
├── _registry: dict[language_id → _LangConfig]
│     ├── python     → grammar + queries for function, class
│     ├── javascript → grammar + queries for function, class, method
│     └── typescript / typescriptreact
│                   → grammar + queries for function, class, method,
│                                           interface, type_alias, enum
│
└── index(file_path, language) → list[Symbol]
      ├── [language not in registry] → return []
      ├── read file from disk
      ├── parse with tree-sitter
      ├── run each query → captures
      ├── normalise captures (handles API diff between ts < 0.23 and ≥ 0.23)
      └── return [Symbol(name, kind, start_line, end_line, signature), ...]
```

**Symbol kinds by language:**

| Language | `function` | `class` | `method` | `interface` | `type_alias` | `enum` |
|---|---|---|---|---|---|---|
| Python | Yes | Yes | — | — | — | — |
| JavaScript | Yes | Yes | Yes | — | — | — |
| TypeScript / TSX | Yes | Yes | Yes | Yes | Yes | Yes |

---

### `velocity/tracker.py` — `VelocityTracker`

Aggregates daily file churn into the `velocity` table.

```
VelocityTracker

record(event: CodeEvent)
    ├── [event.type != file_save] → skip (only saves count)
    ├── extract linesAdded, linesRemoved from metadata
    ├── date = UTC today (YYYY-MM-DD)
    └── Store.increment_velocity(file_path, workspace, date, ...)

hot_files(workspace, days, top_n) → list[dict]
    └── delegates to Store.get_hot_files()

file_trend(file_path, days) → list[dict]
    └── delegates to Store.get_velocity_for_file()
```

---

## Database Schema

```sql
-- All raw events (every type from Layer 1)
CREATE TABLE events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  INTEGER NOT NULL,
    type       TEXT    NOT NULL,      -- file_change | file_save | cursor_move | git_event
    workspace  TEXT    NOT NULL,
    file_path  TEXT    NOT NULL,
    language   TEXT,
    diff       TEXT,
    metadata   TEXT                   -- JSON string
);
CREATE INDEX idx_events_file_path ON events(file_path);
CREATE INDEX idx_events_workspace ON events(workspace, type);

-- Symbol index: updated on every file_save (delete-then-insert per file)
CREATE TABLE symbols (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path  TEXT    NOT NULL,
    workspace  TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    kind       TEXT    NOT NULL,      -- function | class | method | interface | ...
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    signature  TEXT,
    UNIQUE(file_path, name, kind, start_line)
);

-- Daily churn: one row per (file, workspace, date)
CREATE TABLE velocity (
    file_path     TEXT    NOT NULL,
    workspace     TEXT    NOT NULL,
    date          TEXT    NOT NULL,   -- YYYY-MM-DD UTC
    edits         INTEGER NOT NULL DEFAULT 0,
    lines_added   INTEGER NOT NULL DEFAULT 0,
    lines_removed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(file_path, workspace, date)
);
```

---

## Processing Pipeline

Every poll cycle (default: 1 second) follows this strict order:

```
1. Tailer.read_new_events()
       ↓
   list[CodeEvent]  (empty → sleep, no-op)
       ↓
2. Store.bulk_insert_events(batch)
       ↓  raw rows persisted FIRST (durability)
3. For each event in batch:
       ├── event.type == file_save
       │       ├── SymbolIndexer.index(file_path)
       │       │       → Store.upsert_symbols(file_path, symbols)
       │       └── VelocityTracker.record(event)
       │               → Store.increment_velocity(...)
       └── other types → (already persisted in step 2, no further action)
       ↓
4. Tailer.commit(new_byte_offset)
       ↓  cursor advances LAST (crash-safe guarantee)
5. Sleep(poll_ms)
```

**Why raw events first?** If a crash occurs between step 2 and step 4, the next restart re-delivers the batch. The re-inserted events hit `INSERT OR IGNORE` in the events table, and `upsert_symbols` is idempotent (delete-then-insert). No data is lost or duplicated.

---

## Installation & Running

```bash
cd context-engine
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

```bash
# Start with default settings
ambient

# Or via Python module
python -m ambient.main

# With custom paths and verbose logging
AMBIENT_LOG_LEVEL=DEBUG ambient
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AMBIENT_LOG_PATH` | `~/.ambient-code/events.ndjson` | NDJSON event log written by Layer 1 |
| `AMBIENT_DB_PATH` | `~/.ambient-code/context.db` | SQLite database output |
| `AMBIENT_CURSOR_PATH` | `~/.ambient-code/cursor` | Byte-offset cursor file |
| `AMBIENT_POLL_MS` | `1000` | Poll interval in milliseconds |
| `AMBIENT_LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`) |
| `AMBIENT_RESET_CURSOR` | unset | Set to `1` to reset cursor and replay the entire log |

---

## Querying the Database

```bash
# Top 10 most-edited files today
sqlite3 ~/.ambient-code/context.db \
  "SELECT file_path, SUM(edits) as total
   FROM velocity
   WHERE date = date('now')
   GROUP BY file_path
   ORDER BY total DESC
   LIMIT 10;"

# All symbols in a specific file
sqlite3 ~/.ambient-code/context.db \
  "SELECT kind, name, start_line, end_line, signature
   FROM symbols
   WHERE file_path LIKE '%auth.ts'
   ORDER BY start_line;"

# Recent save events for a file
sqlite3 ~/.ambient-code/context.db \
  "SELECT datetime(timestamp/1000, 'unixepoch'), type, diff
   FROM events
   WHERE file_path LIKE '%auth.ts'
     AND type = 'file_save'
   ORDER BY timestamp DESC
   LIMIT 5;"
```

---

## Testing

```bash
cd context-engine
pytest tests/ -v
# 120 tests, ~3 s
```

All tests use `tmp_path` fixtures — no VS Code, no running extension, no network, no `~/.ambient-code` access.

**Test modules:**

| Module | Tests | Coverage focus |
|---|---|---|
| `test_models.py` | 19 | Pydantic parsing, camelCase aliases, metadata accessors, enum validation |
| `test_tailer.py` | 17 | Byte-offset cursor, commit, crash-safe redelivery, malformed lines |
| `test_store.py` | 23 | Schema DDL, WAL mode, events CRUD, symbol upsert isolation, velocity accumulation |
| `test_symbol_index.py` | 22 | Python / TypeScript / JavaScript extraction + edge cases |
| `test_velocity.py` | 16 | `record()` filtering, `hot_files` ordering, `file_trend`, UTC date helper |
| `test_integration.py` | 13 | Full pipeline: NDJSON log → `ContextEngine` → SQLite, crash safety |

For a per-test description of all 120 tests, see [docs/tests.md](tests.md).

---

## Known Limitations

| Limitation | Detail |
|---|---|
| Single-threaded | The engine processes one batch at a time. Run one instance per machine. |
| No log rotation | `Tailer` does not handle log rotation or file truncation. Do not truncate `events.ndjson` while Layer 2 is running. |
| Save-only indexing | Symbols are updated only on `file_save`. Unsaved edits are not reflected in the symbol index. |
| Stash events not captured | `GitWatcher` (Layer 1) does not emit stash events — they do not change HEAD. |
