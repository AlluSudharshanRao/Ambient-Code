# Layer 3 — Insight Engine

## Overview

The Insight Engine is the reasoning layer of Ambient Code. It runs as a lightweight Python background process that:

1. **Polls** the Layer 2 SQLite database (`context.db`) on a configurable interval.
2. **Evaluates** pattern triggers against accumulated code activity.
3. **Assembles context** from the database (symbols, diffs, velocity) for each match.
4. **Calls OpenAI** to generate a concise, actionable finding.
5. **Writes** findings to `~/.ambient-code/findings.ndjson`.
6. The Layer 1 VS Code extension tails that file and surfaces findings as notifications.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Component Design](#component-design)
3. [Triggers](#triggers)
4. [LLM Pipeline](#llm-pipeline)
5. [Findings Schema](#findings-schema)
6. [Data Contracts](#data-contracts)
7. [Installation & Running](#installation--running)
8. [Environment Variables](#environment-variables)
9. [Testing](#testing)
10. [Design Decisions](#design-decisions)
11. [Known Limitations](#known-limitations)

---

## Architecture

### High-Level: Layer 3 in context

```
~/.ambient-code/context.db
         │  (written by Layer 2 — Layer 3 opens READ-ONLY)
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│                  Layer 3 — Insight Engine                    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                InsightEngine (main.py)              │    │
│  │                                                     │    │
│  │  every POLL_MS:                                     │    │
│  │    ContextReader.get_all_workspaces()               │    │
│  │    for each workspace:                              │    │
│  │      for each trigger:                              │    │
│  │        results = trigger.evaluate(reader, ws)       │    │
│  │        for each result:                             │    │
│  │          ctx  = assemble_context(result, reader)    │    │
│  │          body = call_openai(system, user_prompt)    │    │
│  │          write_finding(Finding(...), path)          │    │
│  └─────────────────────────────────────────────────────┘    │
│                           │                                  │
│       ┌───────────────────┤                                  │
│       │                   │                                  │
│  ┌────▼──────┐    ┌────────▼──────┐    ┌───────────────┐    │
│  │ContextReader│  │   Triggers    │    │  LLM Pipeline │    │
│  │(read-only) │  │               │    │               │    │
│  │            │  │HighVelocity   │    │ client.py     │    │
│  │get_hot_    │  │LongFunction   │    │ prompts.py    │    │
│  │  files()   │  │UncoveredChurn │    │               │    │
│  │get_symbols │  │               │    │ SYSTEM_PROMPT │    │
│  │get_events  │  │               │    │ build_user_   │    │
│  │            │  │               │    │  prompt()     │    │
│  └────────────┘  └───────────────┘    └───────────────┘    │
│                                                              │
│  ┌─────────────────────────────────┐                        │
│  │  FindingsWriter (writer.py)     │                        │
│  │  cooldown: 1h per (file,trigger)│                        │
│  └─────────────────────────────────┘                        │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
~/.ambient-code/findings.ndjson
         │  (tailed by Layer 1 FindingsWatcher)
         ▼
   VS Code notifications + Output Channel
```

### Low-Level: Component dependency graph

```
main.py (InsightEngine)
  │
  ├── reader.py (ContextReader)
  │     └── opens context.db with URI ?mode=ro  (cannot write)
  │
  ├── triggers/
  │     ├── base.py     (abstract Trigger + TriggerResult dataclass)
  │     ├── velocity.py (HighVelocityTrigger)
  │     │     └── uses: ContextReader.get_hot_files()
  │     ├── long_function.py (LongFunctionTrigger)
  │     │     └── uses: ContextReader.get_recent_save_paths()
  │     │               ContextReader.get_long_functions()
  │     └── uncovered.py (UncoveredHighChurnTrigger)
  │           └── uses: ContextReader.get_hot_files()
  │                     ContextReader.get_recent_save_paths()
  │
  ├── llm/
  │     ├── client.py   (call_openai → OpenAI chat completions API)
  │     └── prompts.py
  │           ├── assemble_context()  → enriches TriggerResult from DB
  │           ├── build_user_prompt() → routes to per-trigger template
  │           └── build_title()       → one-line notification title
  │
  ├── writer.py (write_finding)
  │     ├── _is_on_cooldown() → scans tail of findings.ndjson
  │     └── appends Finding as JSON line
  │
  └── models.py
        ├── Finding     (output unit)
        ├── Severity    (info | warning | critical)
        └── TriggerName (high_velocity | long_function | uncovered_high_churn)
```

---

## Component Design

### `reader.py` — `ContextReader`

Read-only interface to `context.db`. Opens the database with SQLite's URI `?mode=ro` flag — the connection will error rather than write, making accidental corruption impossible.

```
ContextReader(db_path)
  └── opens: sqlite3.connect("file:///path/context.db?mode=ro", uri=True)

Workspace queries:
  get_all_workspaces()
      → UNION across events, symbols, velocity tables
        (discovers workspace even if only one table has data)

Velocity queries:
  get_hot_files(workspace, days, min_edits)
      → SELECT file_path, SUM(edits), SUM(lines_added), SUM(lines_removed)
           FROM velocity
          WHERE workspace=? AND date >= date('now', '-N days')
         HAVING SUM(edits) >= min_edits
         ORDER BY total_edits DESC

Symbol queries:
  get_symbols_for_file(file_path)
      → all symbols ordered by start_line

  get_long_functions(workspace, min_lines)
      → symbols WHERE kind IN ('function','method','class')
                  AND (end_line - start_line) >= min_lines
        ORDER BY line_count DESC

Event queries:
  get_recent_save_paths(workspace, hours)
      → DISTINCT file_path from events
         WHERE type='file_save' AND timestamp >= cutoff_ms

  get_recent_events_for_file(file_path, hours, limit)
      → last N events with diffs, ordered by timestamp DESC
```

---

### `triggers/base.py` — `Trigger` and `TriggerResult`

```python
@dataclass
class TriggerResult:
    file_path:    str
    workspace:    str
    trigger_name: str        # TriggerName or custom string
    severity:     Severity   # info | warning | critical
    context_data: dict       # trigger-specific structured data

class Trigger(ABC):
    @abstractmethod
    def evaluate(self, reader: ContextReader, workspace: str) -> list[TriggerResult]:
        ...  # return [] when nothing matches; never raise
```

---

### `triggers/velocity.py` — `HighVelocityTrigger`

Fires when a file has been saved >= N times today.

```
evaluate(reader, workspace)
    ├── get_hot_files(workspace, days=1, min_edits=self._min_edits)
    └── for each hot file:
          severity = CRITICAL if edits >= 10
                   | WARNING  if edits >= 7
                   | INFO     otherwise
          yield TriggerResult(
              file_path=row["file_path"],
              severity=severity,
              context_data={ total_edits, total_lines_added, total_lines_removed }
          )
```

---

### `triggers/long_function.py` — `LongFunctionTrigger`

Fires when a function or method in a recently-saved file exceeds N lines.

```
evaluate(reader, workspace)
    ├── saved_today = get_recent_save_paths(workspace, hours=24)
    ├── long_syms   = get_long_functions(workspace, min_lines=self._min_lines)
    ├── for each symbol where file_path in saved_today:
    │       keep only the LONGEST per file (one result per file)
    │       severity = CRITICAL if lines >= 80
    │                | WARNING  if lines >= 60
    │                | INFO     otherwise
    │       context_data = { function_name, kind, start_line, end_line,
    │                        line_count, signature }
    └── yield deduplicated TriggerResults
```

---

### `triggers/uncovered.py` — `UncoveredHighChurnTrigger`

Fires when a file has heavy churn today but no test file was saved.

```
evaluate(reader, workspace)
    ├── hot_files   = get_hot_files(workspace, days=1, min_edits=min_edits)
    ├── saved_paths = get_recent_save_paths(workspace, hours=24)
    ├── any_test_saved = any(_is_test_file(p) for p in saved_paths)
    │
    ├── [any_test_saved == True] → return []
    │     (at least one test touched — workspace has test awareness)
    │
    └── for each hot file (excluding test files themselves):
          yield TriggerResult(severity=WARNING, context_data={total_edits, any_test_saved=False})
```

**Test file detection patterns:**

| Pattern | Language |
|---|---|
| `test_*.py`, `*_test.py` | Python |
| `*.test.ts`, `*.spec.ts`, `*.test.tsx` | TypeScript |
| `*.test.js`, `*.spec.js` | JavaScript |

---

## LLM Pipeline

### Context assembly — `llm/prompts.py`

```
assemble_context(result: TriggerResult, reader: ContextReader) → dict
    ├── get_symbols_for_file(result.file_path)  → up to 15 symbols
    ├── get_recent_events_for_file(result.file_path, hours=24, limit=10)
    │     → extract up to 3 diff snippets (30 lines each, save/change only)
    └── return {
          file_name, file_path, workspace, trigger, severity,
          trigger_context, symbols, recent_diffs
        }
```

### Prompt routing

```
build_user_prompt(ctx)
    ├── trigger == high_velocity     → _prompt_high_velocity(ctx)
    ├── trigger == long_function     → _prompt_long_function(ctx)
    ├── trigger == uncovered_churn   → _prompt_uncovered_churn(ctx)
    └── other                        → _prompt_generic(ctx)
```

Each template injects: `file_path`, `workspace`, trigger-specific metrics, formatted symbol list, and diff snippets.

### OpenAI call — `llm/client.py`

```
call_openai(system_prompt, user_prompt) → str
    ├── read OPENAI_API_KEY from env (raise RuntimeError if missing)
    ├── model = OPENAI_MODEL env var | "gpt-4o-mini"
    ├── openai.chat.completions.create(
    │     model=model, max_tokens=500, temperature=0.2,
    │     messages=[{role:system,...}, {role:user,...}]
    │   )
    ├── [RateLimitError on first attempt] → sleep 5 s, retry once
    └── return response.choices[0].message.content
```

---

## Findings Schema

Each line in `findings.ndjson` is a JSON object.

| Field | Type | Description |
|---|---|---|
| `id` | string | UUID4 — globally unique across all findings |
| `timestamp` | integer | Unix milliseconds when the finding was generated |
| `workspace` | string | VS Code workspace name |
| `filePath` | string | Absolute path to the affected file |
| `trigger` | string | `high_velocity` · `long_function` · `uncovered_high_churn` |
| `severity` | string | `info` · `warning` · `critical` |
| `title` | string | One-line summary for a VS Code notification |
| `body` | string | Full LLM-generated analysis (≤ 500 tokens) |

**Example:**

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "timestamp": 1713130000000,
  "workspace": "my-project",
  "filePath": "/src/auth.ts",
  "trigger": "high_velocity",
  "severity": "warning",
  "title": "auth.ts saved 7x today — review recommended",
  "body": "This file has been heavily modified today. The validateToken() function has grown to 68 lines and mixes token parsing with database lookups — consider extracting the lookup into a repository method."
}
```

---

## Data Contracts

| File | Direction | Format | Notes |
|---|---|---|---|
| `~/.ambient-code/context.db` | Layer 2 → Layer 3 | SQLite (WAL) | Opened read-only by Layer 3 |
| `~/.ambient-code/findings.ndjson` | Layer 3 → Layer 1 | NDJSON (append-only) | Tailed by `FindingsWatcher` |

---

## Installation & Running

```bash
cd insight-engine
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

```bash
# Set API key (required)
set OPENAI_API_KEY=sk-...        # Windows
export OPENAI_API_KEY=sk-...     # macOS / Linux

# Start with defaults (polls every 60 s)
ambient-insight

# Or via Python module
python -m ambient_insight.main

# With custom settings
AMBIENT_POLL_MS=30000 AMBIENT_VELOCITY_THRESHOLD=3 ambient-insight
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | **(required)** | Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model override (e.g. `gpt-4o`) |
| `AMBIENT_DB_PATH` | `~/.ambient-code/context.db` | Path to Layer 2 database |
| `AMBIENT_FINDINGS_PATH` | `~/.ambient-code/findings.ndjson` | Path to write findings |
| `AMBIENT_POLL_MS` | `60000` | Poll interval in milliseconds |
| `AMBIENT_VELOCITY_THRESHOLD` | `5` | Min saves/day for `HighVelocityTrigger` |
| `AMBIENT_FUNCTION_LINE_THRESHOLD` | `40` | Min lines for `LongFunctionTrigger` |
| `AMBIENT_LOG_LEVEL` | `INFO` | Python log level |

---

## Testing

```bash
cd insight-engine
pytest tests/ -v
# 115 tests, ~4 s — LLM is always mocked (no API key required)
```

**Test modules:**

| Module | Tests | Coverage focus |
|---|---|---|
| `test_models.py` | 18 | `Finding` model, enums, camelCase aliases, round-trips |
| `test_reader.py` | 21 | All `ContextReader` methods, read-only mode, edge cases |
| `test_triggers.py` | 30 | All three triggers: fire/no-fire, severity ladder, context data |
| `test_writer.py` | 14 | NDJSON append, cooldown suppression, `_is_on_cooldown` internals |
| `test_prompts.py` | 22 | Context assembly, per-trigger templates, title generation |
| `test_main.py` | 10 | `InsightEngine` lifecycle, tick, OpenAI error resilience |

For a per-test description of all 115 tests, see [docs/tests.md](tests.md).

---

## Design Decisions

### Why a separate Python process?
The Insight Engine performs blocking I/O (SQLite reads, OpenAI HTTP calls with 1–5 s latency) on a slow poll interval. Running it out of process keeps both the VS Code extension and the Layer 2 context engine completely non-blocking.

### Why NDJSON for findings?
Maintains the same file-contract pattern as the Layer 1→2 boundary. NDJSON is append-only, crash-safe, human-readable, and trivially consumed by TypeScript with a byte-offset cursor — no protocol, no socket, no version negotiation.

### Why a cooldown instead of a "seen" set?
An in-memory "seen" set resets every time the process restarts, causing findings to re-fire on the next boot. The file-based cooldown persists across restarts and self-expires naturally: entries older than the cooldown window are no longer matched.

### Why `gpt-4o-mini` as default?
- Latency: ~1 s per call (acceptable for a 60 s poll cycle)
- Cost: ~$0.15 / 1M input tokens
- Quality: sufficient for the 3–6 sentence code-review output the system produces

Override with `OPENAI_MODEL=gpt-4o` for higher quality at ~10x cost.

### Why read-only DB access?
Opening `context.db` with `?mode=ro` makes accidental writes (e.g. a bug creating a table) a hard error rather than a silent corruption. Layer 2 is the sole writer of `context.db`.

---

## Known Limitations

| Limitation | Detail |
|---|---|
| Single-threaded poll loop | A slow OpenAI call (5+ s) delays subsequent trigger evaluations for that cycle. A future improvement would use `asyncio` or a thread pool for concurrent LLM calls. |
| Cooldown is per (file, trigger) | Renaming a file resets its cooldown for all triggers. |
| Symbols must be indexed first | `LongFunctionTrigger` cannot fire for a file until Layer 2 has indexed it at least once (requires a `file_save` event to reach Layer 2). |
| No finding deduplication across restarts | The cooldown window suppresses repeated findings within 1 hour, but restarting Layer 3 before the window expires may allow a duplicate if the findings file is deleted. |
