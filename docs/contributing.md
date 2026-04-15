# Contributing Guide

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Node.js | ≥ 18 | Extension build toolchain |
| npm | ≥ 9 | Package management (Layer 1) |
| VS Code | ≥ 1.85 | Extension host for development |
| Python | ≥ 3.11 | Context engine (Layer 2) |
| Git | any | Version control |

---

## Layer 1 — VS Code Extension

### Setup

```bash
cd extension
npm install
```

### Development workflow

```bash
# Compile once
npm run compile

# Compile in watch mode (recommended during development)
npm run watch
```

Press **F5** in VS Code with the `extension/` folder open to launch an Extension Development Host. The extension activates automatically (`onStartupFinished`) and begins writing to `~/.ambient-code/events.ndjson`.

**Inspecting the live event log (Windows):**

```powershell
Get-Content "$env:USERPROFILE\.ambient-code\events.ndjson" -Wait | ForEach-Object {
    try { $_ | ConvertFrom-Json | ConvertTo-Json -Depth 5 } catch { $_ }
}
```

**Inspecting the live event log (macOS/Linux):**

```bash
tail -f ~/.ambient-code/events.ndjson | python3 -c "
import sys, json
for line in sys.stdin:
    print(json.dumps(json.loads(line), indent=2))
"
```

### Linting

```bash
cd extension
npm run lint
```

ESLint is configured via `.eslintrc.json` with the `@typescript-eslint` rule set.

### Adding a new collector

1. Create `src/collectors/<name>.ts` implementing `vscode.Disposable`
2. Add the new event type to `EventType` in `src/types.ts` if needed
3. Define a `*Metadata` interface in `src/types.ts` extending `Record<string, unknown>`
4. Instantiate the collector in `src/extension.ts` inside `activate()` and push it to `collectors`
5. Document the new event type in `docs/layer1.md` with an example payload

---

## Layer 2 — Python Context Engine

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
```

Set `AMBIENT_LOG_LEVEL=DEBUG` for verbose output.

### Smoke test

```bash
cd context-engine
python smoke_test.py
```

All checks should pass. This test runs the full pipeline end-to-end using a temporary directory — no VS Code or running extension needed.

### Linting

```bash
ruff check ambient/
```

Ruff is configured in `pyproject.toml`.

### Adding a new tree-sitter language

1. Install the grammar package: `pip install tree-sitter-<lang>`
2. Add the package to `[project.dependencies]` in `pyproject.toml`
3. Register the language in `ambient/indexer/symbol_index.py` inside `_make_language_registry()`:
   - Provide a `language_factory` callable returning a `tree_sitter.Language`
   - Write query strings using the `@<kind>.name` / `@<kind>.def` capture convention
4. Add the language identifier to `docs/layer2.md` in the supported languages table
5. Add a fixture file to `context-engine/tests/fixtures/` and extend the smoke test

### Adding a new query to an existing language

1. Open `ambient/indexer/symbol_index.py`
2. Find the `_LangConfig` for your language in `_make_language_registry()`
3. Append a new query string to its `queries` list
4. Use the `@<kind>.name` / `@<kind>.def` naming convention for captures
5. Run `python smoke_test.py` to verify nothing is broken

### Adding a new database table or query

1. Add the DDL to the `_SCHEMA` constant in `ambient/db/store.py`
2. Add typed read/write methods to the `Store` class
3. Document the new table in `docs/layer2.md` under the Schema section

---

## Commit Conventions

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(layer1): add rename detection to FileWatcher
fix(queue): handle write stream errors gracefully
feat(layer2): add Go language support to SymbolIndexer
fix(tailer): handle UTF-8 BOM in events.ndjson
docs: update layer2 schema with new velocity columns
refactor(store): extract query helpers into separate module
test: add smoke test coverage for git_event processing
chore: update tree-sitter to 0.25
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Scopes: `layer1`, `layer2`, `layer3`, `queue`, `tailer`, `store`, `indexer`, `velocity`, `docs`, `ci`

---

## Pull Request Checklist

**Layer 1 (TypeScript)**
- [ ] `npm run lint` passes with no errors
- [ ] `npm run compile` produces no TypeScript errors
- [ ] New collectors include JSDoc on the class and all public methods
- [ ] New event types are documented in `docs/layer1.md` with an example payload

**Layer 2 (Python)**
- [ ] `ruff check ambient/` passes
- [ ] `python smoke_test.py` passes
- [ ] New public methods include docstrings
- [ ] New languages / queries are documented in `docs/layer2.md`
- [ ] New environment variables are documented in `docs/layer2.md` and `docs/README.md`

**Both**
- [ ] `.gitignore` updated if new build artifacts are introduced
- [ ] Root `README.md` updated if the build/run instructions change
