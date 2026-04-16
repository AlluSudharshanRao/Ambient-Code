"""
Read-only interface to the Layer 2 context database.

Layer 3 never writes to ``context.db``; all modifications are performed by
the Layer 2 context engine.  This module opens the database in read-only mode
(URI ``?mode=ro``) so it is impossible to accidentally write to Layer 2's data.

All queries return plain dicts so callers are not coupled to sqlite3.Row.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class ContextReader:
    """Read-only access to ``context.db``.

    Parameters
    ----------
    db_path:
        Absolute path to the SQLite database written by Layer 2.
        The database must already exist; Layer 3 does not create it.
    """

    def __init__(self, db_path: str) -> None:
        if not Path(db_path).exists():
            raise FileNotFoundError(
                f"context.db not found at {db_path}. "
                "Is the Layer 2 context engine running?"
            )
        uri = Path(db_path).as_uri() + "?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=True)
        self._conn.row_factory = sqlite3.Row

    # ------------------------------------------------------------------
    # Velocity queries
    # ------------------------------------------------------------------

    def get_hot_files(
        self,
        workspace: str,
        days: int = 1,
        min_edits: int = 5,
    ) -> list[dict]:
        """Return files with >= *min_edits* total edits in the last *days* day(s).

        Parameters
        ----------
        workspace:
            Workspace name to scope the query.
        days:
            Lookback window in calendar days (default: today only).
        min_edits:
            Minimum total edits threshold.
        """
        rows = self._conn.execute(
            """
            SELECT
                file_path,
                workspace,
                SUM(edits)         AS total_edits,
                SUM(lines_added)   AS total_lines_added,
                SUM(lines_removed) AS total_lines_removed
            FROM velocity
            WHERE workspace = ?
              AND date >= date('now', ? || ' days')
            GROUP BY file_path
            HAVING SUM(edits) >= ?
            ORDER BY total_edits DESC
            """,
            (workspace, f"-{days}", min_edits),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_workspaces(self) -> list[str]:
        """Return all distinct workspace names present in any Layer 2 table."""
        rows = self._conn.execute(
            """
            SELECT DISTINCT workspace FROM velocity
            UNION
            SELECT DISTINCT workspace FROM events
            UNION
            SELECT DISTINCT workspace FROM symbols
            """
        ).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Symbol queries
    # ------------------------------------------------------------------

    def get_symbols_for_file(self, file_path: str) -> list[dict]:
        """Return all symbols for *file_path*, ordered by start line."""
        rows = self._conn.execute(
            """
            SELECT file_path, workspace, name, kind, start_line, end_line, signature
            FROM symbols
            WHERE file_path = ?
            ORDER BY start_line
            """,
            (file_path,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_long_functions(
        self,
        workspace: str,
        min_lines: int = 40,
    ) -> list[dict]:
        """Return symbols whose body spans >= *min_lines* lines.

        Only ``function``, ``method``, and ``class`` kinds are considered.
        Results are ordered by length descending.
        """
        rows = self._conn.execute(
            """
            SELECT
                s.file_path,
                s.workspace,
                s.name,
                s.kind,
                s.start_line,
                s.end_line,
                s.signature,
                (s.end_line - s.start_line) AS line_count
            FROM symbols s
            WHERE s.workspace = ?
              AND s.kind IN ('function', 'method', 'class')
              AND (s.end_line - s.start_line) >= ?
            ORDER BY line_count DESC
            """,
            (workspace, min_lines),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Event queries
    # ------------------------------------------------------------------

    def get_recent_save_paths(
        self,
        workspace: str,
        hours: int = 24,
    ) -> list[str]:
        """Return distinct file paths that were saved in the last *hours* hours."""
        cutoff_ms = int((
            __import__("time").time() - hours * 3600
        ) * 1000)
        rows = self._conn.execute(
            """
            SELECT DISTINCT file_path
            FROM events
            WHERE workspace = ?
              AND type = 'file_save'
              AND timestamp >= ?
            """,
            (workspace, cutoff_ms),
        ).fetchall()
        return [r[0] for r in rows]

    def get_recent_events_for_file(
        self,
        file_path: str,
        hours: int = 24,
        limit: int = 20,
    ) -> list[dict]:
        """Return the most recent events for *file_path* within *hours* hours."""
        cutoff_ms = int((__import__("time").time() - hours * 3600) * 1000)
        rows = self._conn.execute(
            """
            SELECT timestamp, type, language, diff, metadata
            FROM events
            WHERE file_path = ?
              AND timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (file_path, cutoff_ms, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
