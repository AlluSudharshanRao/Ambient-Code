# Ambient Code

> A developer tooling system that watches, remembers, and reasons about your codebase the way a senior engineer would — not at commit time, but continuously, as you work.

## What is this?

Ambient Code is a three-layer system:

| Layer | Technology | Status |
|---|---|---|
| **Layer 1 — Collection** | VS Code Extension (TypeScript) | ✅ Built |
| **Layer 2 — Context Engine** | Python background process (tree-sitter, SQLite) | ✅ Built |
| **Layer 3 — Insight Engine** | LLM reasoning + pattern triggers | 🔜 Planned |

**Layer 1** is a VS Code extension that silently watches your editing session — file changes, saves, cursor moves, git operations — and streams structured events to a local append-only log (`~/.ambient-code/events.ndjson`). No analysis happens in the extension. It is purely a sensor.

**Layer 2** tails that log and builds a living model of the codebase: a symbol index (via tree-sitter), a daily change velocity tracker, and a queryable SQLite store (`~/.ambient-code/context.db`). It runs as a Python background process with graceful shutdown and crash-safe event delivery.

**Layer 3** (planned) will reason over that model using an LLM and surface findings as inline hints, digests, or chat notifications.

---

## Quick Start

### Layer 1 — VS Code Extension

**Prerequisites:** Node.js ≥ 18, VS Code ≥ 1.85

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

### Layer 2 — Context Engine

**Prerequisites:** Python ≥ 3.11

```bash
cd context-engine
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate # macOS / Linux
pip install -e ".[dev]"
ambient
```

The engine starts tailing `~/.ambient-code/events.ndjson` and writing to `~/.ambient-code/context.db`. Stop with `Ctrl+C`.

---

## Documentation

- [Architecture overview](docs/README.md)
- [Layer 1 — Collection layer deep-dive](docs/layer1.md)
- [Layer 2 — Context engine deep-dive](docs/layer2.md)
- [Contributing guide](docs/contributing.md)

---

## Repository Layout

```
ambient-code/
├── extension/              # Layer 1 — VS Code extension (TypeScript)
│   ├── src/
│   │   ├── extension.ts
│   │   ├── types.ts
│   │   ├── collectors/     # FileWatcher, CursorTracker, EditStream, GitWatcher
│   │   └── queue/          # EventQueue (NDJSON writer)
│   └── package.json
│
├── context-engine/         # Layer 2 — Python context engine
│   ├── ambient/
│   │   ├── models.py       # Pydantic event models
│   │   ├── tailer.py       # NDJSON tailer + byte-offset cursor
│   │   ├── main.py         # Orchestration loop + graceful shutdown
│   │   ├── db/store.py     # SQLite schema + queries
│   │   ├── indexer/        # tree-sitter symbol extractor
│   │   └── velocity/       # Change velocity tracker
│   └── pyproject.toml
│
├── docs/                   # Architecture and API documentation
│   ├── README.md           # Architecture overview (this file's sibling)
│   ├── layer1.md           # Layer 1 deep-dive
│   ├── layer2.md           # Layer 2 deep-dive
│   └── contributing.md     # Development guide
│
└── .gitignore
```

---

## Privacy

All data stays on your machine. The extension writes only to `~/.ambient-code/events.ndjson`. The context engine writes only to `~/.ambient-code/context.db`. Nothing is sent to any remote service.
