# Ambient Code

> A developer tooling system that watches, remembers, and reasons about your codebase the way a senior engineer would — not at commit time, but continuously, as you work.

## What is this?

Ambient Code is a three-layer system:

| Layer | Technology | Status |
|---|---|---|
| **Layer 1 — Collection** | VS Code Extension (TypeScript) | ✅ Built |
| **Layer 2 — Context Engine** | Python background process (tree-sitter, SQLite) | 🔜 Planned |
| **Layer 3 — Insight Engine** | LLM reasoning + pattern triggers | 🔜 Planned |

Layer 1 is a VS Code extension that silently watches your editing session — file changes, saves, cursor moves, git operations — and streams structured events to a local append-only log (`~/.ambient-code/events.ndjson`). No analysis happens in the extension. It is purely a sensor.

Layer 2 will tail that log and build a living model of the codebase: a symbol index (via tree-sitter), a change velocity tracker, and a queryable SQLite store. Layer 3 will reason over that model using an LLM and surface findings as inline hints, digests, or chat notifications.

## Quick Start (Layer 1)

```bash
cd extension
npm install
npm run compile
# Press F5 in VS Code to launch the Extension Development Host
```

Once active, the status bar shows:
```
Ambient Code: collecting → ~/.ambient-code/events.ndjson
```

## Documentation

- [Architecture overview](docs/README.md)
- [Layer 1 — Collection layer deep-dive](docs/layer1.md)
- [Contributing guide](docs/contributing.md)

## Repository Layout

```
ambient-code/
├── extension/          # Layer 1 — VS Code extension (TypeScript)
├── context-engine/     # Layer 2 — Python context engine (coming soon)
├── docs/               # Architecture and API documentation
└── README.md           # This file
```

## Privacy

All data stays on your machine. The extension writes only to `~/.ambient-code/events.ndjson`. Nothing is sent to any remote service.
