"""
Unit tests for ambient.db.store — SQLite schema, events, symbols, velocity.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ambient.db.store import Store
from ambient.models import CodeEvent, EventType, Symbol
from tests.conftest import (
    make_cursor_move_event,
    make_file_save_event,
    make_git_event,
)

NOW_MS = int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Schema / setup
# ---------------------------------------------------------------------------


class TestSchemaCreation:
    def test_tables_exist_after_init(self, store: Store):
        tables = {
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"events", "symbols", "velocity"}.issubset(tables)

    def test_wal_mode_enabled(self, store: Store):
        mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_creates_parent_directory(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "context.db"
        s = Store(str(nested))
        s.close()
        assert nested.exists()

    def test_idempotent_init(self, tmp_path: Path):
        """Calling Store twice on the same DB path should not fail."""
        path = str(tmp_path / "context.db")
        s1 = Store(path)
        s1.close()
        s2 = Store(path)
        s2.close()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestInsertEvent:
    def test_insert_single_event(self, store: Store):
        event = make_file_save_event()
        store.insert_event(event)
        count = store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1

    def test_event_fields_persisted(self, store: Store):
        event = make_file_save_event(workspace="acme", language="go")
        store.insert_event(event)
        row = store._conn.execute("SELECT * FROM events").fetchone()
        assert row["workspace"] == "acme"
        assert row["language"] == "go"
        assert row["type"] == "file_save"

    def test_event_diff_persisted(self, store: Store):
        event = make_file_save_event()
        store.insert_event(event)
        row = store._conn.execute("SELECT diff FROM events").fetchone()
        assert row["diff"] is not None
        assert "@@" in row["diff"]

    def test_event_metadata_persisted_as_json(self, store: Store):
        import json

        event = make_file_save_event(lines_added=7, lines_removed=2)
        store.insert_event(event)
        row = store._conn.execute("SELECT metadata FROM events").fetchone()
        meta = json.loads(row["metadata"])
        assert meta["linesAdded"] == 7
        assert meta["linesRemoved"] == 2

    def test_null_diff_persisted_as_null(self, store: Store):
        event = make_cursor_move_event()
        store.insert_event(event)
        row = store._conn.execute("SELECT diff FROM events").fetchone()
        assert row["diff"] is None

    def test_autoincrement_id(self, store: Store):
        store.insert_event(make_file_save_event())
        store.insert_event(make_cursor_move_event())
        rows = store._conn.execute("SELECT id FROM events ORDER BY id").fetchall()
        assert [r[0] for r in rows] == [1, 2]


class TestBulkInsertEvents:
    def test_inserts_all_events(self, store: Store):
        events = [make_file_save_event(), make_cursor_move_event(), make_git_event()]
        store.bulk_insert_events(events)
        count = store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 3

    def test_empty_list_is_noop(self, store: Store):
        store.bulk_insert_events([])
        count = store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 0

    def test_preserves_event_types(self, store: Store):
        events = [make_file_save_event(), make_cursor_move_event(), make_git_event()]
        store.bulk_insert_events(events)
        types = [
            r[0]
            for r in store._conn.execute("SELECT type FROM events ORDER BY id").fetchall()
        ]
        assert types == ["file_save", "cursor_move", "git_event"]


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------


def _make_symbols(file_path: str, count: int = 3) -> list[Symbol]:
    return [
        Symbol(
            file_path=file_path,
            workspace="test-ws",
            name=f"func_{i}",
            kind="function",
            start_line=i * 5,
            end_line=i * 5 + 4,
            signature=f"def func_{i}():",
            updated_at=NOW_MS,
        )
        for i in range(count)
    ]


class TestUpsertSymbols:
    def test_inserts_symbols(self, store: Store):
        symbols = _make_symbols("/src/auth.py")
        store.upsert_symbols("/src/auth.py", symbols)
        count = store._conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        assert count == 3

    def test_replaces_existing_symbols_for_file(self, store: Store):
        store.upsert_symbols("/src/auth.py", _make_symbols("/src/auth.py", count=3))
        # Re-parse produces 5 symbols
        store.upsert_symbols("/src/auth.py", _make_symbols("/src/auth.py", count=5))
        count = store._conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        assert count == 5

    def test_does_not_affect_other_files(self, store: Store):
        store.upsert_symbols("/src/auth.py", _make_symbols("/src/auth.py", count=2))
        store.upsert_symbols("/src/user.py", _make_symbols("/src/user.py", count=4))
        # Re-upsert auth.py — user.py symbols must survive
        store.upsert_symbols("/src/auth.py", _make_symbols("/src/auth.py", count=1))

        user_count = store._conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE file_path='/src/user.py'"
        ).fetchone()[0]
        assert user_count == 4

    def test_empty_list_clears_symbols_for_file(self, store: Store):
        store.upsert_symbols("/src/auth.py", _make_symbols("/src/auth.py", count=3))
        store.upsert_symbols("/src/auth.py", [])
        count = store._conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        assert count == 0

    def test_get_symbols_returns_ordered_by_line(self, store: Store):
        symbols = [
            Symbol(
                file_path="/src/auth.py",
                workspace="ws",
                name="z_last",
                kind="function",
                start_line=20,
                end_line=25,
                signature="def z_last():",
                updated_at=NOW_MS,
            ),
            Symbol(
                file_path="/src/auth.py",
                workspace="ws",
                name="a_first",
                kind="function",
                start_line=0,
                end_line=5,
                signature="def a_first():",
                updated_at=NOW_MS,
            ),
        ]
        store.upsert_symbols("/src/auth.py", symbols)
        rows = store.get_symbols("/src/auth.py")
        assert rows[0]["name"] == "a_first"
        assert rows[1]["name"] == "z_last"

    def test_get_symbols_returns_empty_for_unknown_file(self, store: Store):
        assert store.get_symbols("/nonexistent.py") == []


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------


class TestIncrementVelocity:
    def test_creates_row_on_first_call(self, store: Store):
        store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 5, 1)
        count = store._conn.execute("SELECT COUNT(*) FROM velocity").fetchone()[0]
        assert count == 1

    def test_increments_edits_on_repeated_calls(self, store: Store):
        store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 5, 0)
        store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 3, 2)
        store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 1, 0)
        row = store._conn.execute("SELECT * FROM velocity").fetchone()
        assert row["edits"] == 3
        assert row["lines_added"] == 9
        assert row["lines_removed"] == 2

    def test_separate_dates_create_separate_rows(self, store: Store):
        store.increment_velocity("/src/auth.py", "ws", "2026-04-13", 2, 0)
        store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 3, 1)
        count = store._conn.execute("SELECT COUNT(*) FROM velocity").fetchone()[0]
        assert count == 2

    def test_separate_files_create_separate_rows(self, store: Store):
        store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 3, 0)
        store.increment_velocity("/src/user.py", "ws", "2026-04-14", 2, 1)
        count = store._conn.execute("SELECT COUNT(*) FROM velocity").fetchone()[0]
        assert count == 2


class TestGetHotFiles:
    def test_returns_files_ordered_by_edits_desc(self, store: Store):
        # auth.py: 3 edits, user.py: 10 edits
        for _ in range(3):
            store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 1, 0)
        for _ in range(10):
            store.increment_velocity("/src/user.py", "ws", "2026-04-14", 1, 0)

        rows = store.get_hot_files("ws", days=7, top_n=10)
        assert rows[0]["file_path"] == "/src/user.py"
        assert rows[0]["total_edits"] == 10
        assert rows[1]["file_path"] == "/src/auth.py"

    def test_respects_top_n(self, store: Store):
        for i in range(5):
            store.increment_velocity(f"/src/file{i}.py", "ws", "2026-04-14", 1, 0)
        rows = store.get_hot_files("ws", days=7, top_n=3)
        assert len(rows) == 3

    def test_workspace_scoped(self, store: Store):
        store.increment_velocity("/src/auth.py", "ws-a", "2026-04-14", 5, 0)
        store.increment_velocity("/src/user.py", "ws-b", "2026-04-14", 3, 0)
        rows = store.get_hot_files("ws-a", days=7, top_n=10)
        assert len(rows) == 1
        assert rows[0]["file_path"] == "/src/auth.py"

    def test_returns_empty_for_unknown_workspace(self, store: Store):
        store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 5, 0)
        assert store.get_hot_files("other-ws", days=7, top_n=10) == []


class TestGetVelocityForFile:
    def test_returns_rows_ordered_by_date(self, store: Store):
        store.increment_velocity("/src/auth.py", "ws", "2026-04-12", 1, 0)
        store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 3, 0)
        store.increment_velocity("/src/auth.py", "ws", "2026-04-13", 2, 0)

        rows = store.get_velocity_for_file("/src/auth.py", days=30)
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates)

    def test_returns_empty_for_unknown_file(self, store: Store):
        assert store.get_velocity_for_file("/nonexistent.py") == []
