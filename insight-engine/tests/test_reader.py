"""
Unit tests for ambient_insight.reader.ContextReader.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from ambient_insight.reader import ContextReader
from tests.conftest import (
    insert_event,
    insert_symbol,
    insert_velocity,
)

NOW_MS = int(time.time() * 1000)
TODAY = time.strftime("%Y-%m-%d", time.gmtime())


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


@pytest.fixture()
def reader(context_db):
    db_path, _ = context_db
    r = ContextReader(str(db_path))
    yield r
    r.close()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestContextReaderConstruction:
    def test_missing_db_raises_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="context.db not found"):
            ContextReader(str(tmp_path / "no_such.db"))

    def test_opens_successfully(self, context_db):
        db_path, _ = context_db
        r = ContextReader(str(db_path))
        r.close()

    def test_close_is_idempotent(self, context_db):
        db_path, _ = context_db
        r = ContextReader(str(db_path))
        r.close()
        # Should not raise
        r.close()


# ---------------------------------------------------------------------------
# get_all_workspaces
# ---------------------------------------------------------------------------


class TestGetAllWorkspaces:
    def test_empty_db_returns_empty(self, reader):
        assert reader.get_all_workspaces() == []

    def test_single_workspace(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/a.py", "ws1", edits=2)
        result = reader.get_all_workspaces()
        assert result == ["ws1"]

    def test_multiple_workspaces_deduplicated(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/a.py", "ws1", edits=2)
        insert_velocity(conn, "/b.py", "ws1", edits=1)
        insert_velocity(conn, "/c.py", "ws2", edits=3)
        result = reader.get_all_workspaces()
        assert sorted(result) == ["ws1", "ws2"]


# ---------------------------------------------------------------------------
# get_hot_files
# ---------------------------------------------------------------------------


class TestGetHotFiles:
    def test_returns_files_above_threshold(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/hot.py", "ws", edits=7)
        insert_velocity(conn, "/cold.py", "ws", edits=2)
        hot = reader.get_hot_files("ws", days=1, min_edits=5)
        paths = [r["file_path"] for r in hot]
        assert "/hot.py" in paths
        assert "/cold.py" not in paths

    def test_excludes_different_workspace(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/a.py", "ws1", edits=10)
        hot = reader.get_hot_files("ws2", days=1, min_edits=5)
        assert hot == []

    def test_returns_aggregated_metrics(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/f.py", "ws", edits=6, lines_added=30, lines_removed=10)
        hot = reader.get_hot_files("ws", days=1, min_edits=5)
        assert hot[0]["total_edits"] == 6
        assert hot[0]["total_lines_added"] == 30
        assert hot[0]["total_lines_removed"] == 10

    def test_ordered_by_edits_descending(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/b.py", "ws", edits=5)
        insert_velocity(conn, "/a.py", "ws", edits=9)
        hot = reader.get_hot_files("ws", days=1, min_edits=5)
        assert hot[0]["file_path"] == "/a.py"

    def test_old_entries_excluded(self, context_db, reader):
        _, conn = context_db
        old_date = "2000-01-01"
        insert_velocity(conn, "/old.py", "ws", edits=10, date=old_date)
        hot = reader.get_hot_files("ws", days=1, min_edits=5)
        assert hot == []


# ---------------------------------------------------------------------------
# get_symbols_for_file
# ---------------------------------------------------------------------------


class TestGetSymbolsForFile:
    def test_empty_returns_empty(self, reader):
        assert reader.get_symbols_for_file("/no_such.py") == []

    def test_returns_symbols_ordered_by_start_line(self, context_db, reader):
        _, conn = context_db
        insert_symbol(conn, "/f.py", "ws", "beta", "function", 20, 30)
        insert_symbol(conn, "/f.py", "ws", "alpha", "function", 5, 15)
        syms = reader.get_symbols_for_file("/f.py")
        assert syms[0]["name"] == "alpha"
        assert syms[1]["name"] == "beta"

    def test_scoped_to_file_path(self, context_db, reader):
        _, conn = context_db
        insert_symbol(conn, "/a.py", "ws", "fn_a", "function", 1, 10)
        insert_symbol(conn, "/b.py", "ws", "fn_b", "function", 1, 10)
        syms = reader.get_symbols_for_file("/a.py")
        assert all(s["file_path"] == "/a.py" for s in syms)


# ---------------------------------------------------------------------------
# get_long_functions
# ---------------------------------------------------------------------------


class TestGetLongFunctions:
    def test_returns_functions_above_threshold(self, context_db, reader):
        _, conn = context_db
        insert_symbol(conn, "/f.py", "ws", "big_fn", "function", 1, 50)
        insert_symbol(conn, "/f.py", "ws", "small_fn", "function", 51, 55)
        long = reader.get_long_functions("ws", min_lines=40)
        names = [r["name"] for r in long]
        assert "big_fn" in names
        assert "small_fn" not in names

    def test_excludes_non_function_kinds(self, context_db, reader):
        _, conn = context_db
        insert_symbol(conn, "/f.py", "ws", "MY_CONST", "constant", 1, 50)
        long = reader.get_long_functions("ws", min_lines=40)
        assert long == []

    def test_includes_method_and_class(self, context_db, reader):
        _, conn = context_db
        insert_symbol(conn, "/c.py", "ws", "MyClass", "class", 1, 60)
        insert_symbol(conn, "/c.py", "ws", "my_method", "method", 10, 55)
        long = reader.get_long_functions("ws", min_lines=40)
        kinds = [r["kind"] for r in long]
        assert "class" in kinds
        assert "method" in kinds

    def test_ordered_by_line_count_desc(self, context_db, reader):
        _, conn = context_db
        insert_symbol(conn, "/f.py", "ws", "medium", "function", 1, 45)
        insert_symbol(conn, "/f.py", "ws", "giant", "function", 50, 130)
        long = reader.get_long_functions("ws", min_lines=40)
        assert long[0]["name"] == "giant"


# ---------------------------------------------------------------------------
# get_recent_save_paths
# ---------------------------------------------------------------------------


class TestGetRecentSavePaths:
    def test_returns_paths_saved_within_window(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/recent.py", "ws", "file_save", NOW_MS)
        paths = reader.get_recent_save_paths("ws", hours=24)
        assert "/recent.py" in paths

    def test_excludes_old_events(self, context_db, reader):
        _, conn = context_db
        old_ms = NOW_MS - (25 * 3600 * 1000)
        insert_event(conn, "/old.py", "ws", "file_save", old_ms)
        paths = reader.get_recent_save_paths("ws", hours=24)
        assert "/old.py" not in paths

    def test_excludes_non_save_events(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/changed.py", "ws", "file_change", NOW_MS)
        paths = reader.get_recent_save_paths("ws", hours=24)
        assert "/changed.py" not in paths

    def test_deduplicated(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS)
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS - 1000)
        paths = reader.get_recent_save_paths("ws", hours=24)
        assert paths.count("/f.py") == 1


# ---------------------------------------------------------------------------
# get_recent_events_for_file
# ---------------------------------------------------------------------------


class TestGetRecentEventsForFile:
    def test_returns_events_for_file(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS, diff="+line")
        evts = reader.get_recent_events_for_file("/f.py", hours=24)
        assert len(evts) == 1
        assert evts[0]["diff"] == "+line"

    def test_respects_limit(self, context_db, reader):
        _, conn = context_db
        for i in range(25):
            insert_event(conn, "/f.py", "ws", "file_save", NOW_MS - i * 1000)
        evts = reader.get_recent_events_for_file("/f.py", hours=24, limit=10)
        assert len(evts) == 10

    def test_excludes_other_files(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/other.py", "ws", "file_save", NOW_MS)
        evts = reader.get_recent_events_for_file("/f.py", hours=24)
        assert evts == []
