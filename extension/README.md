# Ambient Code

> A VS Code extension that watches your code continuously and builds a living model of your codebase — the collection layer of the Ambient Code system.

## What it does

Once active, the extension silently observes your editing session and writes structured events to a local log file (`~/.ambient-code/events.ndjson`). No analysis happens here — this is purely a sensor. The Ambient Code context engine (Layer 2) reads that log and builds the memory.

Events captured:

| Event | Trigger |
|---|---|
| `file_change` | Editing activity on a file, debounced to one event per editing session |
| `file_save` | Each explicit file save (`Ctrl+S` / auto-save) |
| `cursor_move` | Switching to a different file |
| `git_event` | Branch switch or new commit detected via the VS Code Git API |

## Requirements

- VS Code 1.85 or later
- The built-in **Git** extension must be enabled (it is by default)

## Getting started

1. Open the `extension/` folder in VS Code
2. Run `npm install` in a terminal
3. Press **F5** to launch the Extension Development Host

A status bar message confirms the extension is active:

```
Ambient Code: collecting → C:\Users\<you>\.ambient-code\events.ndjson
```

To verify events are flowing:

```powershell
Get-Content "$env:USERPROFILE\.ambient-code\events.ndjson" -Wait
```

## Extension settings

| Setting | Default | Description |
|---|---|---|
| `ambientCode.dbPath` | `~/.ambient-code/events.ndjson` | Override the event log path |
| `ambientCode.debounceMs` | `2000` | Editing inactivity window (ms) before a `file_change` event fires |
| `ambientCode.flushIntervalMs` | `5000` | Interval (ms) between log flushes |

## Architecture

This extension is Layer 1 of a three-layer system. See the full [architecture documentation](../docs/README.md) for details on how Layer 2 (the Python context engine) and Layer 3 (the insight engine) build on top of the event log this extension produces.

## Building

```bash
npm install          # install dependencies
npm run compile      # compile TypeScript → out/
npm run watch        # watch mode
npm run lint         # ESLint check
```

## Privacy

All data stays on your machine. Events are written only to `~/.ambient-code/events.ndjson`. Nothing is sent to any remote service by this extension.
