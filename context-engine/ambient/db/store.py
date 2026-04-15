"""
SQLite persistence layer for the Ambient Code context engine.

Database location: ``~/.ambient-code/context.db``  (configurable via
the ``AMBIENT_DB_PATH`` environment variable).

Schema
------
events    — raw imported events (mirrors the NDJSON log in a queryable form)
symbols   — code symbols extracted by tree-sitter (one row per symbol)
velocity  — daily churn aggregates per file (used by Layer 3 for risk scoring)

All writes go through prepared statements inside explicit transactions.
The connection is opened in WAL mode so the Layer 3 reader can query
the database concurrently without blocking the writer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ambient.models import CodeEvent, Symbol


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     INTEGER NOT NULL,
    type          TEXT    NOT NULL,
    workspace     TEXT    NOT NULL,
    file_path     TEXT    NOT NULL,
    language      TEXT,
    diff          TEXT,
    metadata      TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events (type);
CREATE INDEX IF NOT EXISTS idx_events_file_path ON events (file_path);

CREATE TABLE IF NOT EXISTS symbols (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT    NOT NULL,
    workspace   TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    signature   TEXT,
    updated_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols (file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols (name);

CREATE TABLE IF NOT EXISTS velocity (
    file_path     TEXT    NOT NULL,
    workspace     TEXT    NOT NULL,
    date          TEXT    NOT NULL,   -- ISO-8601 date: YYYY-MM-DD
    edits         INTEGER NOT NULL DEFAULT 0,
    lines_added   INTEGER NOT NULL DEFAULT 0,
    lines_removed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (file_path, date)
);

CREATE INDEX IF NOT EXISTS idx_velocity_workspace_date ON velocity (workspace, date);
"""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Store:
    """Thread-unsafe SQLite store — designed for single-threaded use.

    All public methods execute within an implicit or explicit transaction
    and commit immediately.  For bulk operations, use :meth:`bulk_insert_events`
    which wraps multiple rows in a single transaction.

    Parameters
    ----------
    db_path:
        Absolute path to the SQLite database file.  The parent directory
        is created automatically if it does not exist.
    """

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=True)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def insert_event(self, event: CodeEvent) -> None:
        """Insert a single event row.  Commits immediately."""
        import json

        self._conn.execute(
            """
            INSERT INTO events (timestamp, type, workspace, file_path, language, diff, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.timestamp,
                event.event_type.value,
                event.workspace,
                event.file_path,
                event.language,
                event.diff,
                json.dumps(event.metadata) if event.metadata else None,
            ),
        )
        self._conn.commit()

    def bulk_insert_events(self, events: list[CodeEvent]) -> None:
        """Insert multiple events in a single transaction.

        Significantly faster than calling :meth:`insert_event` in a loop
        for large batches.
        """
        import json

        rows = [
            (
                e.timestamp,
                e.event_type.value,
                e.workspace,
                e.file_path,
                e.language,
                e.diff,
                json.dumps(e.metadata) if e.metadata else None,
            )
            for e in events
        ]
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO events (timestamp, type, workspace, file_path, language, diff, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    # ------------------------------------------------------------------
    # Symbols
    # ------------------------------------------------------------------

    def upsert_symbols(self, file_path: str, symbols: list[Symbol]) -> None:
        """Replace all symbols for *file_path* with the provided list.

        This is a delete-then-insert operation — the full re-parse on
        each save is intentional because the tree changes incrementally
        and tracking deletions/renames separately would add complexity
        without benefit at this scale.
        """
        with self._conn:
            self._conn.execute(
                "DELETE FROM symbols WHERE file_path = ?", (file_path,)
            )
            self._conn.executemany(
                """
                INSERT INTO symbols
                    (file_path, workspace, name, kind, start_line, end_line, signature, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s.file_path,
                        s.workspace,
                        s.name,
                        s.kind,
                        s.start_line,
                        s.end_line,
                        s.signature,
                        s.updated_at,
                    )
                    for s in symbols
                ],
            )

    def get_symbols(self, file_path: str) -> list[sqlite3.Row]:
        """Return all symbols for *file_path*, ordered by start line."""
        return self._conn.execute(
            "SELECT * FROM symbols WHERE file_path = ? ORDER BY start_line",
            (file_path,),
        ).fetchall()

    # ------------------------------------------------------------------
    # Velocity
    # ------------------------------------------------------------------

    def increment_velocity(
        self,
        file_path: str,
        workspace: str,
        date: str,
        lines_added: int,
        lines_removed: int,
    ) -> None:
        """Atomically increment the daily velocity row for *file_path*.

        Uses an INSERT OR IGNORE + UPDATE pattern to avoid a read-modify-write
        cycle while remaining compatible with SQLite's limited upsert support
        in older versions.

        Parameters
        ----------
        date:
            ISO-8601 date string ``YYYY-MM-DD``.
        """
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO velocity (file_path, workspace, date, edits, lines_added, lines_removed)
                VALUES (?, ?, ?, 0, 0, 0)
                """,
                (file_path, workspace, date),
            )
            self._conn.execute(
                """
                UPDATE velocity
                SET edits         = edits + 1,
                    lines_added   = lines_added   + ?,
                    lines_removed = lines_removed + ?
                WHERE file_path = ? AND date = ?
                """,
                (lines_added, lines_removed, file_path, date),
            )

    def get_hot_files(
        self,
        workspace: str,
        days: int = 7,
        top_n: int = 10,
    ) -> list[sqlite3.Row]:
        """Return the most frequently edited files in the last *days* days.

        Results are ordered by total edit count descending.

        Parameters
        ----------
        workspace:
            Workspace name to filter by.
        days:
            Lookback window in calendar days (inclusive of today).
        top_n:
            Maximum number of rows to return.
        """
        return self._conn.execute(
            """
            SELECT
                file_path,
                SUM(edits)         AS total_edits,
                SUM(lines_added)   AS total_lines_added,
                SUM(lines_removed) AS total_lines_removed
            FROM velocity
            WHERE workspace = ?
              AND date >= date('now', ? || ' days')
            GROUP BY file_path
            ORDER BY total_edits DESC
            LIMIT ?
            """,
            (workspace, f"-{days}", top_n),
        ).fetchall()

    def get_velocity_for_file(
        self, file_path: str, days: int = 30
    ) -> list[sqlite3.Row]:
        """Return the daily velocity rows for *file_path* over the last *days* days."""
        return self._conn.execute(
            """
            SELECT date, edits, lines_added, lines_removed
            FROM velocity
            WHERE file_path = ?
              AND date >= date('now', ? || ' days')
            ORDER BY date
            """,
            (file_path, f"-{days}"),
        ).fetchall()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
