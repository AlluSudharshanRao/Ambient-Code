# Layer 1 — Collection Layer

## Overview

Layer 1 is a VS Code extension written in TypeScript. Its sole responsibility is to **observe editor activity and stream structured events to a local append-only log file**.

It embodies the "collect dumbly" principle: no analysis, no scoring, no LLM calls, no network traffic. It is a pure sensor. All reasoning is delegated to Layers 2 and 3.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Component Design](#component-design)
3. [Event Schema](#event-schema)
4. [Configuration Reference](#configuration-reference)
5. [File Output](#file-output)
6. [Development](#development)
7. [Known Limitations](#known-limitations)

---

## Architecture

### High-Level: Layer 1 in context

```
┌─────────────────────────────────────────────────────────────┐
│                    VS Code Extension Host                   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 Collection Subsystem                │   │
│  │                                                     │   │
│  │  FileWatcher      onDidChangeTextDocument           │   │
│  │  EditStream       onDidSaveTextDocument             │   │
│  │  CursorTracker    onDidChangeActiveTextEditor       │   │
│  │  GitWatcher       vscode.git state.onDidChange      │   │
│  │        │                                           │   │
│  │        ▼                                           │   │
│  │  ┌─────────────┐  enqueue()                        │   │
│  │  │ EventQueue  │◄─────────────────────────────     │   │
│  │  │ (buffer)    │                                   │   │
│  │  └──────┬──────┘                                   │   │
│  │         │  flush() every 5 s                       │   │
│  └─────────┼───────────────────────────────────────────┘  │
│            ▼                                               │
│  ~/.ambient-code/events.ndjson  (append-only NDJSON)       │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 Findings Subsystem                  │   │
│  │                                                     │   │
│  │  FindingsWatcher   polls findings.ndjson every 3 s  │   │
│  │       │                                             │   │
│  │       ├──► Output Channel (all severities)          │   │
│  │       ├──► showInformationMessage (warning)         │   │
│  │       └──► showWarningMessage (critical)            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Low-Level: Internal data flow

```
VS Code Event                 Collector            EventQueue         Disk
─────────────────────────────────────────────────────────────────────────
onDidChangeTextDocument ──► FileWatcher
                              debounce(2s)
                              compute diff ──────► enqueue()
                                                      │
onDidSaveTextDocument ──────► EditStream              │
                              compute diff ──────► enqueue()  ──[5s]──► events.ndjson
                                                      │
onDidChangeActiveTextEditor ► CursorTracker           │
                              capture line ──────► enqueue()
                                                      │
git state.onDidChange ──────► GitWatcher              │
                              diff HEAD ─────────► enqueue()
```

---

## Component Design

### `EventQueue` — `src/queue/eventQueue.ts`

Central write path. All four collectors call `queue.enqueue(event)`.

```
EventQueue
│
├── buffer: CodeEvent[]         ← in-memory accumulator
├── stream: WriteStream         ← opened with flags:'a', auto-creates dir
├── flushTimer: setInterval     ← unref()'d, fires every flushIntervalMs
│
├── enqueue(event)              ← push to buffer; no-op after dispose()
├── flush()                     ← drain buffer → NDJSON lines → stream.write()
│                                  no-op when buffer is empty
└── dispose()                   ← stop timer; flush() synchronously; close stream
                                   guarantees no events lost on shutdown
```

**Key invariants:**
- The `WriteStream` is opened once and never closed until `dispose()`.
- `flush()` serialises the entire buffer in a single `write()` call to minimise I/O syscalls.
- The timer is `unref()`'d so Node.js can exit even if the timer is pending.

---

### `FileWatcher` — `src/collectors/fileWatcher.ts`

Emits `file_change` events after a debounce window of inactivity.

```
onDidOpenTextDocument
    └──► capture baseline snapshot (content at open time)

onDidChangeTextDocument
    │
    ├── [if first change for this document]
    │       start debounce timer
    │       record "session start" snapshot
    │
    └── reset debounce timer
              │
              [debounceMs of silence]
              │
              ▼
         compute unified diff (snapshot @ session start ↔ current content)
         set metadata: { isPaste, linesAdded, linesRemoved }
         enqueue file_change event
         update snapshot to current content  ← baseline for next session
```

**Debounce invariant:** One `file_change` event is emitted per continuous editing session, not per keystroke.

**Paste detection heuristic:** `isPaste = true` when any single change in the batch inserts ≥ 50 characters with zero deletions.

---

### `EditStream` — `src/collectors/editStream.ts`

Emits `file_save` events on every explicit save.

```
onDidOpenTextDocument  ──► capture "last saved" snapshot
onDidCloseTextDocument ──► evict snapshot (memory management)

onDidSaveTextDocument
    ├── compute diff (last saved snapshot ↔ current content)
    ├── enqueue file_save event
    └── update "last saved" snapshot
```

**Accuracy:** The diff in `file_save` is always authoritative — it represents the exact delta between consecutive saved states. No estimation or approximation.

---

### `CursorTracker` — `src/collectors/cursorTracker.ts`

Emits `cursor_move` events on active-file switches.

```
activation
    └── emit cursor_move for currently active editor (startup context)

onDidChangeActiveTextEditor
    └── emit cursor_move with { line, character } at switch time
```

Intra-file cursor movement is intentionally not tracked — the signal-to-noise ratio for line changes within a file is too low to be useful for Layer 2.

---

### `GitWatcher` — `src/collectors/gitWatcher.ts`

Emits `git_event` events when the repository HEAD changes.

```
extension activate
    ├── getExtension('vscode.git')
    │     ├── [already active] attach immediately
    │     └── [pending]  wait for onDidChange, then attach
    │
    └── for each repo in git.repositories:
            store current HEAD { branch, commitHash }

repo.state.onDidChange
    ├── read new HEAD
    ├── compare with stored HEAD
    │     ├── branch changed ──► emit git_event { action: "branch_change" }
    │     ├── commit changed ──► emit git_event { action: "commit" }
    │     └── no change      ──► ignore
    └── update stored HEAD
```

Handles multi-root workspaces with multiple repositories. Defers attachment if the Git extension is not yet active.

---

### `FindingsWatcher` — `src/findings/findingsWatcher.ts`

Tails `findings.ndjson` for Layer 3 output and routes to VS Code UI.

```
start()
    └── initialise byteOffset = current file size
         (skip findings written before this session)

setInterval (every 3 s)
    ├── stat(findingsPath) → newSize
    ├── [newSize > byteOffset]
    │     ├── open file, read [byteOffset .. newSize]
    │     ├── advance byteOffset
    │     └── for each new line:
    │           parse Finding JSON
    │           logToOutput(finding)       ← always
    │           showNotification(finding)  ← severity ≥ warning
    └── [no change] → skip cycle
```

**Severity routing:**

| `severity` | VS Code surface |
|---|---|
| `info` | Output channel only (silent) |
| `warning` | `showInformationMessage` toast + output channel |
| `critical` | `showWarningMessage` toast + output channel |

---

## Event Schema

All events share a base structure and are serialised as JSON lines.

### Base `CodeEvent`

| Field | Type | Required | Description |
|---|---|---|---|
| `timestamp` | `number` | Yes | Unix timestamp in milliseconds |
| `type` | `string` | Yes | `file_change` · `file_save` · `cursor_move` · `git_event` |
| `workspace` | `string` | Yes | VS Code workspace folder name |
| `filePath` | `string` | Yes | Absolute path to the file |
| `language` | `string` | Yes | VS Code language identifier |
| `diff` | `string` | No | GNU unified diff (`file_change` and `file_save` only) |
| `metadata` | `object` | No | Event-type-specific payload |

---

### `file_change` — after debounce window

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

### `file_save` — on every Ctrl+S / auto-save

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

### `cursor_move` — on file switch

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

### `git_event` — on HEAD change

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

All settings are under the `ambientCode` namespace in VS Code settings.

| Setting | Type | Default | Description |
|---|---|---|---|
| `ambientCode.dbPath` | `string` | `~/.ambient-code/events.ndjson` | Override the NDJSON event log path. Useful for multi-workspace setups. |
| `ambientCode.debounceMs` | `number` | `2000` | Editing inactivity window (ms) before `FileWatcher` emits `file_change`. Lower = more events, more detail. Higher = less noise. |
| `ambientCode.flushIntervalMs` | `number` | `5000` | Flush interval (ms) for the in-memory event buffer. Affects latency to disk only — does not affect event capture fidelity. |

---

## File Output

| Path | Description |
|---|---|
| `~/.ambient-code/events.ndjson` | Append-only NDJSON event log. One JSON object per line, `\n`-terminated. Never truncated or rotated by Layer 1. Created (with parent directory) on first activation. |

---

## Development

```bash
cd extension
npm install        # install dependencies
npm run compile    # compile TypeScript → out/
npm run watch      # watch mode
npm run lint       # ESLint
npx tsc --noEmit   # type-check without emitting
```

Press **F5** in VS Code (with `extension/` open) to launch an Extension Development Host.

**Inspect the live event log:**

```bash
# macOS / Linux
tail -f ~/.ambient-code/events.ndjson | python3 -m json.tool --no-ensure-ascii

# Windows (PowerShell)
Get-Content "$env:USERPROFILE\.ambient-code\events.ndjson" -Wait |
  ForEach-Object { try { $_ | ConvertFrom-Json | ConvertTo-Json -Depth 5 } catch { $_ } }
```

---

## Known Limitations

| Limitation | Detail |
|---|---|
| First-edit baseline | For documents open before extension activated, `FileWatcher` uses an empty-string baseline for the first session diff. The `EditStream` diff (on next save) is always accurate. |
| Paste heuristic | The 50-character threshold for `isPaste` is a heuristic; fast typists or template expansions may trigger false positives. |
| Single workspace name | In multi-root workspaces, only the first `workspaceFolders` entry's name is recorded in `workspace`. |
| Git stash not detected | `GitWatcher` detects changes via HEAD diff. Stash operations do not change HEAD and are not captured. |
| No log rotation | `EventQueue` opens the file with `flags: 'a'`. If `events.ndjson` grows very large, Layer 2 must handle trimming (planned). |
