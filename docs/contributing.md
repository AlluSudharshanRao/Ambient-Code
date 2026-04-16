# Contributing Guide

Thank you for contributing to Ambient Code. This guide covers environment setup, development workflows, testing, linting, and the pull-request process for all three layers.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Repository Layout](#repository-layout)
3. [Layer 1 — VS Code Extension](#layer-1--vs-code-extension)
4. [Layer 2 — Context Engine](#layer-2--context-engine)
5. [Layer 3 — Insight Engine](#layer-3--insight-engine)
6. [Commit Conventions](#commit-conventions)
7. [Pull Request Checklist](#pull-request-checklist)

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| VS Code | >= 1.85 | Extension host for Layer 1 development |
| Node.js | >= 18 | Build toolchain for Layer 1 |
| npm | >= 9 | Package management for Layer 1 |
| Python | >= 3.11 | Runtime for Layers 2 and 3 |
| Git | any | Version control |
| OpenAI API key | — | Required only for running Layer 3 (not for tests) |

---

## Repository Layout

```
ambient-code/
├── extension/         # Layer 1 — TypeScript VS Code extension
├── context-engine/    # Layer 2 — Python context engine
├── insight-engine/    # Layer 3 — Python insight engine
└── docs/              # Architecture + API documentation
```

Each layer has its own virtual environment and dependency manifest. They do not share Python packages.

---

## Layer 1 — VS Code Extension

### Setup

```bash
cd extension
npm install
```

### Development workflow

```bash
npm run compile   # compile TypeScript once
npm run watch     # watch mode (recommended during development)
npm run lint      # ESLint
npx tsc --noEmit  # type-check without emitting
```

Press **F5** in VS Code (with `extension/` open) to launch an Extension Development Host. The extension activates automatically on startup (`onStartupFinished`) and begins writing to `~/.ambient-code/events.ndjson`.

**Inspect the live event stream:**

```powershell
# Windows (PowerShell)
Get-Content "$env:USERPROFILE\.ambient-code\events.ndjson" -Wait |
  ForEach-Object { try { $_ | ConvertFrom-Json | ConvertTo-Json -Depth 5 } catch { $_ } }
```

```bash
# macOS / Linux
tail -f ~/.ambient-code/events.ndjson | python3 -m json.tool --no-ensure-ascii
```

### Adding a new collector

1. Create `src/collectors/<name>.ts` implementing `vscode.Disposable`.
2. Add the new event type to `EventType` in `src/types.ts` if needed.
3. Define a `*Metadata` interface in `src/types.ts`.
4. Instantiate the collector in `activate()` in `src/extension.ts` and push it to `context.subscriptions`.
5. Document the new event type in `docs/layer1.md` with a full JSON example payload.

---

## Layer 2 — Context Engine

### Setup

```bash
cd context-engine
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -e ".[dev]"
```

### Running

```bash
ambient
# or
python -m ambient.main
# verbose
AMBIENT_LOG_LEVEL=DEBUG ambient
```

### Running the test suite

```bash
cd context-engine
pytest tests/ -v
```

All **120 tests** should pass in under 5 seconds. Tests use `tmp_path` fixtures — no VS Code, no running extension, and no network access required.

| Module | Tests | Focus |
|---|---|---|
| `test_models.py` | 19 | Pydantic parsing, aliases, enum validation |
| `test_tailer.py` | 17 | Byte-offset cursor, crash-safe redelivery, malformed lines |
| `test_store.py` | 23 | Schema DDL, WAL mode, CRUD, symbol upsert, velocity |
| `test_symbol_index.py` | 22 | Symbol extraction for Python, TypeScript, JavaScript |
| `test_velocity.py` | 16 | `record()` filtering, `hot_files`, `file_trend`, UTC dates |
| `test_integration.py` | 13 | Full pipeline: NDJSON → ContextEngine → SQLite |

Run a single module or test:

```bash
pytest tests/test_tailer.py -v
pytest tests/test_integration.py::TestCrashSafety::test_uncommitted_batch_redelivered -v
```

### Linting

```bash
ruff check ambient/       # lint
ruff check ambient/ --fix  # auto-fix
```

### Adding a new tree-sitter language

1. Install the grammar: `pip install tree-sitter-<lang>` and add it to `[project.dependencies]` in `pyproject.toml`.
2. Register a `_LangConfig` in `_make_language_registry()` in `ambient/indexer/symbol_index.py`.
3. Use `@<kind>.name` / `@<kind>.def` capture names in all queries.
4. Add the language to the supported-languages table in `docs/layer2.md`.
5. Add test cases in `tests/test_symbol_index.py` and run `pytest tests/test_symbol_index.py -v`.

### Adding a new query to an existing language

1. Append a query string to the language's `_LangConfig.queries` list in `symbol_index.py`.
2. Use the `@<kind>.name` / `@<kind>.def` naming convention.
3. Add a test in `tests/test_symbol_index.py` and run `pytest tests/test_symbol_index.py -v`.

### Adding a new database table or query

1. Add DDL to the `_SCHEMA` constant in `ambient/db/store.py`.
2. Add typed read/write methods to the `Store` class.
3. Document the new table in `docs/layer2.md` under the Schema section.

---

## Layer 3 — Insight Engine

### Setup

```bash
cd insight-engine
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -e ".[dev]"
```

### Running

```bash
set OPENAI_API_KEY=sk-...        # Windows
# export OPENAI_API_KEY=sk-...  # macOS / Linux
ambient-insight
# or
python -m ambient_insight.main
```

### Running the test suite

```bash
cd insight-engine
pytest tests/ -v
```

All **115 tests** should pass in under 5 seconds. The OpenAI client is always mocked — no API key is needed.

| Module | Tests | Focus |
|---|---|---|
| `test_models.py` | 18 | `Finding` model, enums, aliases, round-trips |
| `test_reader.py` | 21 | `ContextReader` queries, read-only mode, edge cases |
| `test_triggers.py` | 30 | All three triggers: fire/no-fire, severities, context data |
| `test_writer.py` | 14 | NDJSON append, cooldown suppression, helper internals |
| `test_prompts.py` | 22 | Context assembly, per-trigger templates, title generation |
| `test_main.py` | 10 | `InsightEngine` lifecycle, tick, error resilience |

### Linting

```bash
ruff check ambient_insight/
ruff check ambient_insight/ --fix
```

### Adding a new trigger

1. Create `ambient_insight/triggers/<name>.py` extending `Trigger`.
2. Implement `evaluate(reader, workspace) -> list[TriggerResult]` — never raise; return `[]` on error.
3. Add a `TriggerName` value in `ambient_insight/models.py` if needed.
4. Register the trigger in `InsightEngine.__init__` in `ambient_insight/main.py`.
5. Add a per-trigger prompt builder in `ambient_insight/llm/prompts.py` and route from `build_user_prompt()`.
6. Add a `build_title()` branch in `prompts.py`.
7. Document the trigger in `docs/layer3.md`.
8. Add tests in `tests/test_triggers.py` covering fire, no-fire, severity ladder, and `context_data` fields.

### Adding a new LLM prompt template

1. Add `_prompt_<name>(ctx: dict) -> str` in `ambient_insight/llm/prompts.py`.
2. Route to it in `build_user_prompt(ctx)`.
3. Add test cases in `tests/test_prompts.py`.

---

## Commit Conventions

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`

**Scopes:** `layer1`, `layer2`, `layer3`, `queue`, `tailer`, `store`, `indexer`, `velocity`, `triggers`, `llm`, `writer`, `docs`, `ci`

**Examples:**

```
feat(layer1): add rename detection to FileWatcher
fix(tailer): handle UTF-8 BOM in events.ndjson
feat(triggers): add DeadCodeTrigger for unreferenced symbols
fix(writer): prevent race condition on concurrent findings writes
docs(layer2): add SQL index diagram to schema section
test(triggers): add edge-case coverage for empty workspace
chore: update tree-sitter to 0.26
```

---

## Pull Request Checklist

Before requesting review, confirm all items are checked.

### Layer 1 (TypeScript)

- [ ] `npx tsc --noEmit` — zero TypeScript errors
- [ ] `npm run lint` — zero ESLint errors
- [ ] New collectors implement `vscode.Disposable` and are registered in `context.subscriptions`
- [ ] New event types are documented in `docs/layer1.md` with a JSON example payload

### Layer 2 (Python)

- [ ] `ruff check ambient/` — zero errors
- [ ] `pytest tests/ -v` — all **120** tests pass (or more if new ones added)
- [ ] New behaviour is covered by a test in the appropriate module
- [ ] New languages or queries documented in `docs/layer2.md`
- [ ] New environment variables documented in `docs/layer2.md` and `docs/README.md`

### Layer 3 (Python)

- [ ] `ruff check ambient_insight/` — zero errors
- [ ] `pytest tests/ -v` — all **115** tests pass (or more if new ones added)
- [ ] New triggers have tests covering fire, no-fire, all severity levels, and `context_data` keys
- [ ] New environment variables documented in `docs/layer3.md`

### Documentation

- [ ] `docs/README.md` updated if the system architecture changes
- [ ] Root `README.md` updated if the quick-start instructions change
- [ ] `docs/tests.md` updated with descriptions of any new test functions

### General

- [ ] `.gitignore` updated for any new build artifacts or generated files
- [ ] No secrets, credentials, or personal paths committed
