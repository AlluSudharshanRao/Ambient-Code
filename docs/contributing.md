# Contributing Guide

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Node.js | ≥ 18 | Extension build toolchain |
| npm | ≥ 9 | Package management |
| VS Code | ≥ 1.85 | Extension host for development |
| Python | ≥ 3.11 | Context engine (Layer 2 — future) |
| Git | any | Version control |

## Repository Setup

```bash
git clone <repo-url>
cd ambient-code

# Install extension dependencies
cd extension
npm install
```

## Development Workflow — Extension (Layer 1)

```bash
cd extension

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

## Linting

```bash
cd extension
npm run lint
```

ESLint is configured via `.eslintrc.json` with the `@typescript-eslint` rule set.

## Adding a New Collector

1. Create `src/collectors/<name>.ts` — implement `vscode.Disposable`
2. Add the new event type to the `EventType` enum in `src/types.ts` if needed
3. Define a `*Metadata` interface in `src/types.ts` extending `Record<string, unknown>`
4. Instantiate the collector in `src/extension.ts` inside `activate()` and push it to `collectors`
5. Document the new event type in `docs/layer1.md`

## Adding a New tree-sitter Language (Layer 2)

1. Add the language package to `context-engine/pyproject.toml`
2. Register the language in `ambient/indexer/symbol_index.py` in the `LANGUAGE_MAP` dictionary
3. Add a test fixture file under `context-engine/tests/fixtures/`

## Commit Conventions

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(layer1): add rename detection to FileWatcher
fix(queue): handle write stream errors gracefully
docs: update layer1 event schema with cursor_move example
refactor(gitWatcher): split attach from init for testability
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Scopes: `layer1`, `layer2`, `layer3`, `queue`, `docs`, `ci`

## Pull Request Checklist

- [ ] `npm run lint` passes with no errors
- [ ] `npm run compile` produces no TypeScript errors
- [ ] New collectors include JSDoc on the class and all public methods
- [ ] New event types are documented in `docs/layer1.md` with an example payload
- [ ] `.gitignore` updated if new build artifacts are introduced
