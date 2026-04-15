# Layer 2 — Context Engine

## Overview

Layer 2 is a Python background process that **tails the NDJSON event log** produced by the Layer 1 VS Code extension and maintains a living model of the codebase in a local SQLite database.

It is a pure consumer — it never writes to the event log, never communicates with the VS Code extension, and never calls any external API. The only coupling to Layer 1 is the append-only NDJSON file.

---

## Design Goals

| Goal | Implementation |
|---|---|
| Crash-safe delivery | Byte-offset cursor is committed only *after* a batch is persisted. Restarts re-deliver the last uncommitted batch. |
| No double-processing on restart | The cursor file survives process restarts; events already in the DB are not re-inserted. |
| Graceful shutdown | `SIGINT` / `SIGTERM` complete the current batch and commit the cursor before exiting. |
| Language-agnostic indexing | tree-sitter grammars are registered at startup; missing packages are silently skipped. |
| Zero remote calls | All computation is local; the process runs entirely offline. |

---

## Architecture

```
~/.ambient-code/events.ndjson   (written by Layer 1)
        │
        ▼
  ┌─────────────┐
  │   Tailer    │  reads new lines, tracks byte-offset cursor
  └──────┬──────┘
         │  list[CodeEvent]
         ▼
  ┌──────────────────────────────────────────────────────┐
  │                  ContextEngine (main.py)             │
  │                                                      │
  │   file_save  ──► SymbolIndexer  ──► store.upsert_symbols
  │                                                      │
  │   file_save  ──► VelocityTracker ─► store.increment_velocity
  │                                                      │
  │   all events ──► store.bulk_insert_events            │
  └──────────────────────────────────────────────────────┘
         │
         ▼
  ~/.ambient-code/context.db    (read by Layer 3)
```

---

## Components

### `ambient/tailer.py` — `Tailer`

Opens the NDJSON log and tracks a byte-offset cursor in `~/.ambient-code/cursor`.

**Key behaviours:**
- `read_new_events()` seeks to the last committed offset and reads all new complete lines. Returns them as `list[CodeEvent]`. Does not advance the cursor.
- `commit()` advances and persists the cursor after the caller has successfully processed the batch.
- Cursor file is written atomically via a tmp-file rename — safe on POSIX and Windows.
- Returns an empty list silently if the log file does not exist yet (extension not yet activated).
- Malformed JSON lines are skipped with a warning; they do not interrupt the stream.

---

### `ambient/models.py` — Pydantic models

Python mirror of the TypeScript types in `extension/src/types.ts`.

| Model | Description |
|---|---|
| `CodeEvent` | Base event. `filePath` / `type` aliased to `file_path` / `event_type` for Python ergonomics. |
| `FileChangeMetadata` | `isPaste`, `linesAdded`, `linesRemoved` |
| `CursorMoveMetadata` | `line`, `character` |
| `GitEventMetadata` | `action`, `branch`, `previousBranch`, `commitHash` |
| `Symbol` | Internal domain type — a code symbol extracted by tree-sitter. |

---

### `ambient/db/store.py` — `Store`

SQLite persistence layer (Python stdlib `sqlite3`, WAL mode).

**Schema:**

```sql
-- Raw event log
CREATE TABLE events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  INTEGER NOT NULL,
    type       TEXT    NOT NULL,
    workspace  TEXT    NOT NULL,
    file_path  TEXT    NOT NULL,
    language   TEXT,
    diff       TEXT,
    metadata   TEXT
);

-- Symbol index: one row per function/class/method/interface
CREATE TABLE symbols (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path  TEXT    NOT NULL,
    workspace  TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    signature  TEXT,
    updated_at INTEGER NOT NULL
);

-- Daily churn aggregates
CREATE TABLE velocity (
    file_path     TEXT NOT NULL,
    workspace     TEXT NOT NULL,
    date          TEXT NOT NULL,   -- YYYY-MM-DD
    edits         INTEGER NOT NULL DEFAULT 0,
    lines_added   INTEGER NOT NULL DEFAULT 0,
    lines_removed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (file_path, date)
);
```

**Key methods:**

| Method | Description |
|---|---|
| `insert_event(event)` | Insert a single event row |
| `bulk_insert_events(events)` | Insert many rows in one transaction |
| `upsert_symbols(file_path, symbols)` | Delete-then-insert all symbols for a file |
| `get_symbols(file_path)` | All symbols for a file, ordered by line |
| `increment_velocity(...)` | Atomic increment of a `(file_path, date)` velocity row |
| `get_hot_files(workspace, days, top_n)` | Top N files by edit count over last N days |
| `get_velocity_for_file(file_path, days)` | Daily velocity rows for a single file |

---

### `ambient/indexer/symbol_index.py` — `SymbolIndexer`

Parses source files on-demand using tree-sitter and extracts named symbols.

**Triggering:** Only `file_save` events trigger indexing. The file is read from disk at the path in `event.file_path` — the diff in the event is not used.

**Symbol kinds extracted:**

| Language | Kinds |
|---|---|
| Python | `function`, `class` |
| JavaScript | `function`, `class`, `method` |
| TypeScript / TSX | `function`, `class`, `method`, `interface`, `type_alias`, `enum` |

**Adding a language:** Register a `_LangConfig` in `_make_language_registry()` with the tree-sitter grammar factory and a list of query strings. Each query must use `@<kind>.name` and `@<kind>.def` capture names.

**API compatibility:** `_captures_to_pairs()` normalises the `captures()` return value across tree-sitter < 0.23 (list of tuples) and ≥ 0.23 (dict of lists).

---

### `ambient/velocity/tracker.py` — `VelocityTracker`

Records save-event velocity and exposes hot-file queries.

**Key methods:**

| Method | Description |
|---|---|
| `record(event)` | Increments today's velocity row for `event.file_path`. Only `file_save` events are processed. |
| `hot_files(workspace, days, top_n)` | Returns the top-N files by edit count over the last N days. |
| `file_trend(file_path, days)` | Returns day-by-day velocity for a single file. |

---

### `ambient/main.py` — `ContextEngine` + `run()`

Orchestrates the tailer, indexer, and velocity tracker in a poll loop.

**Processing order per batch:**
1. `bulk_insert_events` — persist raw rows first for durability
2. For each `file_save`: run symbol indexer, update velocity
3. For each `git_event`: log the action (raw row already persisted in step 1)
4. `tailer.commit()` — advance the cursor

---

## Installation

```bash
cd context-engine
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -e ".[dev]"
```

## Running

```bash
# Start with defaults
ambient

# Or via Python directly
python -m ambient.main

# With custom paths
AMBIENT_LOG_PATH=C:\Users\you\.ambient-code\events.ndjson \
AMBIENT_DB_PATH=C:\Users\you\.ambient-code\context.db \
AMBIENT_LOG_LEVEL=DEBUG \
ambient
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AMBIENT_LOG_PATH` | `~/.ambient-code/events.ndjson` | NDJSON event log path |
| `AMBIENT_DB_PATH` | `~/.ambient-code/context.db` | SQLite database path |
| `AMBIENT_CURSOR_PATH` | `~/.ambient-code/cursor` | Byte-offset cursor file |
| `AMBIENT_POLL_MS` | `1000` | Poll interval in milliseconds |
| `AMBIENT_LOG_LEVEL` | `INFO` | Python logging level |
| `AMBIENT_RESET_CURSOR` | unset | Set to `1` to reset cursor and replay entire log |

## Querying the database directly

```bash
# Windows (PowerShell) — find hot files
sqlite3 "$env:USERPROFILE\.ambient-code\context.db" \
  "SELECT file_path, total_edits FROM (SELECT file_path, SUM(edits) as total_edits FROM velocity GROUP BY file_path ORDER BY total_edits DESC LIMIT 10);"

# List all symbols in a file
sqlite3 "$env:USERPROFILE\.ambient-code\context.db" \
  "SELECT kind, name, start_line, signature FROM symbols WHERE file_path LIKE '%auth.ts' ORDER BY start_line;"
```

## Testing

### Running the suite

```bash
cd context-engine
pytest tests/ -v
```

All **120 tests** pass in under 5 seconds. No VS Code, no running extension, and no network access required — every test is fully isolated via `pytest`'s `tmp_path` fixture.

### Test structure

```
context-engine/tests/
├── conftest.py             # Shared fixtures: Store, CodeEvent factories, NDJSON helpers
├── test_models.py          # Pydantic parsing, camelCase aliases, metadata accessors
├── test_tailer.py          # Byte-offset cursor, commit, crash-safe redelivery, malformed lines
├── test_store.py           # Schema, events CRUD, symbol upsert isolation, velocity accumulation
├── test_symbol_index.py    # Python / TypeScript / JavaScript extraction + edge cases
├── test_velocity.py        # VelocityTracker record/hot_files/file_trend + UTC date helper
└── test_integration.py     # Full pipeline: NDJSON → ContextEngine → SQLite
```

### Key integration scenarios tested

| Scenario | Test |
|---|---|
| `file_save` populates all three tables | `TestBasicPipeline::test_file_save_populates_all_three_tables` |
| `cursor_move` and `git_event` land in events only | `test_cursor_move_stored_in_events_only`, `test_git_event_stored_in_events_only` |
| Symbols are updated on re-save | `TestIncrementalProcessing::test_symbols_updated_on_re_save` |
| Velocity accumulates across batches | `TestIncrementalProcessing::test_velocity_accumulates_across_batches` |
| Crash (no commit) → events re-delivered on restart | `TestCrashSafety::test_uncommitted_batch_redelivered` |
| Empty or missing log returns an empty batch | `TestEmptyLog::test_missing_log_returns_empty_batch` |

---

## Known Limitations

| Limitation | Detail |
|---|---|
| Single-threaded | The engine is not thread-safe. Run one instance per machine. |
| No log rotation | The tailer does not handle log rotation or file truncation. Do not truncate `events.ndjson`. |
| Save-only indexing | Symbols are only updated on `file_save`, not on `file_change`. Unsaved edits are not reflected in the symbol index. |
| Stash events not captured | `GitWatcher` in Layer 1 does not emit stash events. |
