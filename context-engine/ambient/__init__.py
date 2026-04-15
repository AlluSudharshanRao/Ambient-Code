"""
Ambient Code — Layer 2 Context Engine.

Tails the NDJSON event log produced by the VS Code collection extension
(Layer 1) and maintains a living model of the codebase in a local SQLite
database (~/.ambient-code/context.db).

Components
----------
tailer        : Reads new events from ~/.ambient-code/events.ndjson
models        : Pydantic event models (mirrors the TypeScript types)
db.store      : SQLite schema + all read/write queries
indexer       : tree-sitter symbol extraction → symbols table
velocity      : Change velocity aggregation → velocity table
main          : Orchestration loop + graceful shutdown
"""

__version__ = "0.1.0"
