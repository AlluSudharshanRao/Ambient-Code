# Layer 1 — Collection Layer

## Overview

Layer 1 is a VS Code extension written in TypeScript. Its sole responsibility is to **observe editor activity and write lightweight structured events to a local append-only log file**.

It implements the "collect dumbly, think lazily" principle: no analysis, no scoring, no LLM calls. It is purely a sensor. All reasoning is delegated to Layer 2 and Layer 3.

---

## Design Goals

| Goal | Implementation |
|---|---|
| Zero perceived latency | All event handlers are synchronous. Disk I/O is batched and deferred via a flush timer. |
| No missed events on shutdown | The `EventQueue` performs a final flush synchronously in its `dispose()` method. |
| Configurable noise floor | Debounce window and flush interval are user-configurable. |
| Safe on write errors | `EventQueue` stream errors are caught and logged to the extension host output; collection continues. |

---

## Architecture

```
VS Code Extension Host
│
├── FileWatcher        onDidChangeTextDocument  →  debounced diff  →  file_change
├── CursorTracker      onDidChangeActiveTextEditor               →  cursor_move
├── EditStream         onDidSaveTextDocument    →  accurate diff  →  file_save
└── GitWatcher         vscode.git API state change              →  git_event
          │
          └──► EventQueue (in-memory buffer)
                    │
                    └──[flush every 5s]──► ~/.ambient-code/events.ndjson
```

---

## Components

### `EventQueue` (`src/queue/eventQueue.ts`)

The central write path. All four collectors call `queue.enqueue(event)`, which appends to an in-memory buffer. A `setInterval` timer (default: every 5 seconds) drains the buffer by calling `flush()`, which serialises all pending events as NDJSON lines and writes them to the log file in a single `WriteStream.write()` call.

**Key behaviours:**
- The `WriteStream` is opened with `flags: 'a'` (append) on construction. If the file or directory does not exist, both are created.
- `flush()` is a no-op when the buffer is empty — the timer fires frequently but is cheap.
- `dispose()` stops the timer and calls `flush()` synchronously before closing the stream, ensuring no events are lost when VS Code shuts down.
- The timer is `unref()`'d so it does not prevent Node.js from exiting if the extension host tears down.
- After `dispose()` is called, `enqueue()` silently ignores further events.

---

### `FileWatcher` (`src/collectors/fileWatcher.ts`)

Listens to `vscode.workspace.onDidChangeTextDocument` and emits one `file_change` event per editing *session* per file.

**Debounce behaviour:**

A session begins with the first keystroke in a file and ends when there has been no further change for `debounceMs` milliseconds (default: 2000 ms). When the session ends, a unified diff is computed between the snapshot taken at session start and the current document content, and a single event is enqueued.

```
  keystroke → reset timer
  keystroke → reset timer
  keystroke → reset timer
  (silence for 2000 ms)
       └──► emit file_change with full session diff
```

**Snapshot accuracy:**

When `onDidOpenTextDocument` fires, the document content is captured as a clean baseline. When the first edit arrives, this snapshot is used as the "before" side of the diff. After each debounced event fires, the snapshot is updated to the current content so the next session diffs from the correct baseline.

If a document was open before the extension activated (no `onDidOpen` fired), the baseline defaults to an empty string. This produces a diff showing the full current file as added lines — a conservative fallback. The authoritative diff for those cases is provided by `EditStream`.

**Paste detection:**

If any individual change in the batch inserts ≥ 50 characters with zero deletions, `metadata.isPaste` is set to `true`. This is a heuristic, not a guarantee.

---

### `CursorTracker` (`src/collectors/cursorTracker.ts`)

Listens to `vscode.window.onDidChangeActiveTextEditor` and emits one `cursor_move` event per file switch. Intra-file cursor movement is not tracked — the signal-to-noise ratio is too low.

On extension activation, an initial `cursor_move` event is emitted for the currently active editor so the context engine knows which file was open at startup.

---

### `EditStream` (`src/collectors/editStream.ts`)

Listens to `vscode.workspace.onDidSaveTextDocument` and emits one `file_save` event per save. The diff is computed against the content captured at the previous save (or document open), making it strictly accurate — not an approximation.

`EditStream` also maintains snapshots via `onDidOpenTextDocument` and evicts them on `onDidCloseTextDocument` to avoid unbounded memory growth.

---

### `GitWatcher` (`src/collectors/gitWatcher.ts`)

Uses the VS Code built-in Git extension API (`vscode.extensions.getExtension('vscode.git')`) to subscribe to repository state changes. On each `state.onDidChange` event, the current HEAD is compared to the previously stored HEAD:

| Condition | `action` value |
|---|---|
| Branch name changed | `branch_change` |
| Commit SHA changed on the same branch | `commit` |
| Neither changed | (event silently ignored) |

The watcher handles multi-root workspaces with multiple repositories, and defers attachment if the Git extension has not yet activated.

---

## Event Schema

All events share a common base structure and are written as JSON lines to `~/.ambient-code/events.ndjson`.

### Base `CodeEvent`

| Field | Type | Description |
|---|---|---|
| `timestamp` | `number` | Unix timestamp in milliseconds when the event was enqueued |
| `type` | `string` | One of `file_change`, `cursor_move`, `file_save`, `git_event` |
| `workspace` | `string` | VS Code workspace folder name (first folder in multi-root workspaces) |
| `filePath` | `string` | Absolute path to the associated file |
| `language` | `string` | VS Code language identifier (e.g. `typescript`, `python`) |
| `diff` | `string?` | GNU unified diff string. Present on `file_change` and `file_save` only |
| `metadata` | `object?` | Event-type-specific payload (see below) |

---

### `file_change` event

Emitted after `debounceMs` of editing inactivity on a file.

**`metadata` shape (`FileChangeMetadata`):**

| Field | Type | Description |
|---|---|---|
| `isPaste` | `boolean` | True if a single change inserted ≥ 50 chars with no deletions |
| `linesAdded` | `number` | Lines added in the session diff |
| `linesRemoved` | `number` | Lines removed in the session diff |

**Example:**

```json
{
  "timestamp": 1713121200000,
  "type": "file_change",
  "workspace": "my-project",
  "filePath": "/home/user/my-project/src/auth.ts",
  "language": "typescript",
  "diff": "--- auth.ts\n+++ auth.ts\n@@ -12,6 +12,10 @@\n ...",
  "metadata": {
    "isPaste": false,
    "linesAdded": 4,
    "linesRemoved": 1
  }
}
```

---

### `file_save` event

Emitted on every explicit file save (`Ctrl+S` or auto-save).

**`metadata` shape:** same as `file_change` (`FileChangeMetadata`).

The diff here is authoritative — it reflects the exact delta between the previous saved state and the current saved state.

**Example:**

```json
{
  "timestamp": 1713121245000,
  "type": "file_save",
  "workspace": "my-project",
  "filePath": "/home/user/my-project/src/auth.ts",
  "language": "typescript",
  "diff": "--- auth.ts\n+++ auth.ts\n@@ -12,6 +12,10 @@\n ...",
  "metadata": {
    "isPaste": false,
    "linesAdded": 4,
    "linesRemoved": 1
  }
}
```

---

### `cursor_move` event

Emitted when the active editor changes to a different file.

**`metadata` shape (`CursorMoveMetadata`):**

| Field | Type | Description |
|---|---|---|
| `line` | `number` | Zero-based line number of the cursor at switch time |
| `character` | `number` | Zero-based character offset within the line |

**Example:**

```json
{
  "timestamp": 1713121300000,
  "type": "cursor_move",
  "workspace": "my-project",
  "filePath": "/home/user/my-project/src/user.ts",
  "language": "typescript",
  "metadata": {
    "line": 42,
    "character": 8
  }
}
```

---

### `git_event` event

Emitted when a git repository's HEAD changes.

**`metadata` shape (`GitEventMetadata`):**

| Field | Type | Description |
|---|---|---|
| `action` | `string` | `branch_change` or `commit` |
| `branch` | `string?` | Branch name after the event |
| `previousBranch` | `string?` | Branch name before a `branch_change` |
| `commitHash` | `string?` | Full commit SHA after a `commit` event |

**Example — branch switch:**

```json
{
  "timestamp": 1713121400000,
  "type": "git_event",
  "workspace": "my-project",
  "filePath": "/home/user/my-project",
  "language": "",
  "metadata": {
    "action": "branch_change",
    "branch": "feature/auth-refactor",
    "previousBranch": "main",
    "commitHash": "a3f9c12"
  }
}
```

**Example — new commit:**

```json
{
  "timestamp": 1713121500000,
  "type": "git_event",
  "workspace": "my-project",
  "filePath": "/home/user/my-project",
  "language": "",
  "metadata": {
    "action": "commit",
    "branch": "feature/auth-refactor",
    "commitHash": "b7d2e45"
  }
}
```

---

## Configuration Reference

All settings are under the `ambientCode` namespace in VS Code settings (`Ctrl+,`).

| Setting | Type | Default | Description |
|---|---|---|---|
| `ambientCode.dbPath` | `string` | `~/.ambient-code/events.ndjson` | Absolute path override for the NDJSON event log. Useful for pointing multiple workspaces at a shared log. |
| `ambientCode.debounceMs` | `number` | `2000` | Milliseconds of editing inactivity before `FileWatcher` emits a `file_change` event. Lower values increase event frequency; higher values reduce noise. |
| `ambientCode.flushIntervalMs` | `number` | `5000` | Milliseconds between periodic flushes of the in-memory event buffer to disk. Does not affect event capture — only the delay before events appear in the log. |

---

## File Output

| Path | Description |
|---|---|
| `~/.ambient-code/events.ndjson` | Append-only NDJSON event log. One JSON object per line, `\n`-terminated. Never truncated or rotated by Layer 1. |

The directory `~/.ambient-code/` is created automatically on first activation.

---

## Known Limitations

| Limitation | Detail |
|---|---|
| First-edit baseline | For documents open before the extension activated, `FileWatcher` uses an empty-string baseline for the first session diff. The `EditStream` diff (on next save) is always accurate. |
| Paste heuristic | The 50-character threshold for `isPaste` is a heuristic. Fast typists or template expansions may trigger false positives. |
| Single workspace name | In multi-root workspaces, only the first `workspaceFolders` entry's name is recorded. |
| Git stash not detected | The `GitWatcher` detects branch changes and commits via HEAD diff. Stash operations do not change HEAD and are not captured. |

---

## Development

```bash
cd extension
npm install       # install dependencies
npm run compile   # compile TypeScript → out/
npm run watch     # watch mode for development
npm run lint      # ESLint
```

Press **F5** in VS Code to launch a new Extension Development Host with the extension active.

To inspect the live event log:

```bash
# macOS / Linux
tail -f ~/.ambient-code/events.ndjson | python3 -m json.tool --no-ensure-ascii

# Windows (PowerShell)
Get-Content "$env:USERPROFILE\.ambient-code\events.ndjson" -Wait | ForEach-Object { $_ | ConvertFrom-Json | ConvertTo-Json }
```
