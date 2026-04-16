"""
Shared pytest fixtures for the Layer 3 Insight Engine test suite.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

NOW_MS = int(time.time() * 1000)
TODAY_DATE = time.strftime("%Y-%m-%d", time.gmtime())


# ---------------------------------------------------------------------------
# SQLite database fixture — mirrors the Layer 2 schema exactly
# ---------------------------------------------------------------------------


@pytest.fixture()
def context_db(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    """Create a temp context.db with the Layer 2 schema and return (path, conn)."""
    db_path = tmp_path / "context.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            type      TEXT    NOT NULL,
            workspace TEXT    NOT NULL,
            file_path TEXT    NOT NULL,
            language  TEXT,
            diff      TEXT,
            metadata  TEXT
        );

        CREATE TABLE IF NOT EXISTS symbols (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            workspace TEXT NOT NULL,
            name      TEXT NOT NULL,
            kind      TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line   INTEGER NOT NULL,
            signature  TEXT,
            UNIQUE(file_path, name, kind, start_line)
        );

        CREATE TABLE IF NOT EXISTS velocity (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path     TEXT    NOT NULL,
            workspace     TEXT    NOT NULL,
            date          TEXT    NOT NULL,
            edits         INTEGER NOT NULL DEFAULT 0,
            lines_added   INTEGER NOT NULL DEFAULT 0,
            lines_removed INTEGER NOT NULL DEFAULT 0,
            UNIQUE(file_path, workspace, date)
        );
        """
    )
    conn.commit()
    yield db_path, conn
    conn.close()


def insert_velocity(
    conn: sqlite3.Connection,
    file_path: str,
    workspace: str,
    edits: int,
    date: str | None = None,
    lines_added: int = 0,
    lines_removed: int = 0,
) -> None:
    """Helper to insert a velocity row."""
    conn.execute(
        """
        INSERT OR REPLACE INTO velocity
            (file_path, workspace, date, edits, lines_added, lines_removed)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (file_path, workspace, date or TODAY_DATE, edits, lines_added, lines_removed),
    )
    conn.commit()


def insert_symbol(
    conn: sqlite3.Connection,
    file_path: str,
    workspace: str,
    name: str,
    kind: str,
    start_line: int,
    end_line: int,
    signature: str = "",
) -> None:
    """Helper to insert a symbol row."""
    conn.execute(
        """
        INSERT OR REPLACE INTO symbols
            (file_path, workspace, name, kind, start_line, end_line, signature)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (file_path, workspace, name, kind, start_line, end_line, signature),
    )
    conn.commit()


def insert_event(
    conn: sqlite3.Connection,
    file_path: str,
    workspace: str,
    event_type: str = "file_save",
    timestamp: int | None = None,
    diff: str = "",
) -> None:
    """Helper to insert an event row."""
    conn.execute(
        """
        INSERT INTO events (timestamp, type, workspace, file_path, language, diff)
        VALUES (?, ?, ?, ?, 'python', ?)
        """,
        (timestamp or NOW_MS, event_type, workspace, file_path, diff),
    )
    conn.commit()
