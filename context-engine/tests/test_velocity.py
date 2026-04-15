"""
Unit tests for ambient.velocity.tracker — VelocityTracker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ambient.db.store import Store
from ambient.models import EventType
from ambient.velocity.tracker import VelocityTracker, _utc_date
from tests.conftest import (
    NOW_MS,
    make_cursor_move_event,
    make_file_change_event,
    make_file_save_event,
    make_git_event,
)


@pytest.fixture()
def tracker(store: Store) -> VelocityTracker:
    return VelocityTracker(store)


# ---------------------------------------------------------------------------
# record()
# ---------------------------------------------------------------------------


class TestRecord:
    def test_file_save_increments_velocity(self, tracker: VelocityTracker, store: Store):
        event = make_file_save_event(lines_added=5, lines_removed=2)
        tracker.record(event)

        date = _utc_date(event.timestamp)
        rows = store.get_velocity_for_file(event.file_path)
        assert len(rows) == 1
        assert rows[0]["edits"] == 1
        assert rows[0]["lines_added"] == 5
        assert rows[0]["lines_removed"] == 2
        assert rows[0]["date"] == date

    def test_multiple_saves_accumulate(self, tracker: VelocityTracker, store: Store):
        event = make_file_save_event(lines_added=3, lines_removed=1)
        tracker.record(event)
        tracker.record(event)
        tracker.record(event)

        rows = store.get_velocity_for_file(event.file_path)
        assert rows[0]["edits"] == 3
        assert rows[0]["lines_added"] == 9
        assert rows[0]["lines_removed"] == 3

    def test_file_change_is_ignored(self, tracker: VelocityTracker, store: Store):
        event = make_file_change_event()
        tracker.record(event)
        rows = store.get_velocity_for_file(event.file_path)
        assert rows == []

    def test_cursor_move_is_ignored(self, tracker: VelocityTracker, store: Store):
        event = make_cursor_move_event()
        tracker.record(event)
        count = store._conn.execute("SELECT COUNT(*) FROM velocity").fetchone()[0]
        assert count == 0

    def test_git_event_is_ignored(self, tracker: VelocityTracker, store: Store):
        event = make_git_event()
        tracker.record(event)
        count = store._conn.execute("SELECT COUNT(*) FROM velocity").fetchone()[0]
        assert count == 0

    def test_event_without_metadata_is_skipped_gracefully(
        self, tracker: VelocityTracker, store: Store
    ):
        """A file_save with no metadata should not raise — just skip."""
        from ambient.models import CodeEvent

        event = CodeEvent.model_validate(
            {
                "timestamp": NOW_MS,
                "type": "file_save",
                "workspace": "ws",
                "filePath": "/src/auth.py",
                "language": "python",
                # No metadata
            }
        )
        tracker.record(event)  # must not raise
        count = store._conn.execute("SELECT COUNT(*) FROM velocity").fetchone()[0]
        assert count == 0

    def test_different_files_create_separate_rows(
        self, tracker: VelocityTracker, store: Store
    ):
        tracker.record(make_file_save_event(file_path="/src/a.py"))
        tracker.record(make_file_save_event(file_path="/src/b.py"))
        count = store._conn.execute("SELECT COUNT(*) FROM velocity").fetchone()[0]
        assert count == 2


# ---------------------------------------------------------------------------
# hot_files()
# ---------------------------------------------------------------------------


class TestHotFiles:
    def test_returns_files_ordered_by_edit_count(
        self, tracker: VelocityTracker, store: Store
    ):
        for _ in range(2):
            tracker.record(make_file_save_event(file_path="/src/a.py"))
        for _ in range(7):
            tracker.record(make_file_save_event(file_path="/src/b.py"))

        rows = tracker.hot_files("test-ws")
        assert rows[0]["file_path"] == "/src/b.py"
        assert rows[0]["total_edits"] == 7

    def test_respects_top_n(self, tracker: VelocityTracker):
        for i in range(6):
            tracker.record(make_file_save_event(file_path=f"/src/file{i}.py"))
        rows = tracker.hot_files("test-ws", top_n=3)
        assert len(rows) == 3

    def test_returns_empty_for_unknown_workspace(self, tracker: VelocityTracker):
        tracker.record(make_file_save_event(workspace="ws-a"))
        rows = tracker.hot_files("ws-b")
        assert rows == []

    def test_returns_dict_list(self, tracker: VelocityTracker):
        tracker.record(make_file_save_event())
        rows = tracker.hot_files("test-ws")
        assert isinstance(rows, list)
        assert isinstance(rows[0], dict)
        assert "file_path" in rows[0]
        assert "total_edits" in rows[0]


# ---------------------------------------------------------------------------
# file_trend()
# ---------------------------------------------------------------------------


class TestFileTrend:
    def test_returns_chronological_rows(self, tracker: VelocityTracker, store: Store):
        # Manually insert rows with specific dates
        store.increment_velocity("/src/auth.py", "ws", "2026-04-10", 1, 0)
        store.increment_velocity("/src/auth.py", "ws", "2026-04-12", 3, 1)
        store.increment_velocity("/src/auth.py", "ws", "2026-04-11", 2, 0)

        rows = tracker.file_trend("/src/auth.py", days=30)
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates)

    def test_returns_empty_for_unknown_file(self, tracker: VelocityTracker):
        assert tracker.file_trend("/nonexistent.py") == []

    def test_returns_dict_list(self, tracker: VelocityTracker, store: Store):
        store.increment_velocity("/src/auth.py", "ws", "2026-04-14", 2, 0)
        rows = tracker.file_trend("/src/auth.py")
        assert isinstance(rows, list)
        assert isinstance(rows[0], dict)
        assert "date" in rows[0]
        assert "edits" in rows[0]


# ---------------------------------------------------------------------------
# _utc_date helper
# ---------------------------------------------------------------------------


class TestUtcDate:
    def test_returns_iso_date_string(self):
        # 2025-04-15 00:00:00 UTC = 1744675200000 ms
        ts = 1744675200000
        result = _utc_date(ts)
        assert result == "2025-04-15"

    def test_format_is_yyyy_mm_dd(self):
        result = _utc_date(NOW_MS)
        parts = result.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month
        assert len(parts[2]) == 2  # day
