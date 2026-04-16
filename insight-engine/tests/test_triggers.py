"""
Unit tests for all three built-in pattern triggers.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ambient_insight.models import Severity, TriggerName
from ambient_insight.reader import ContextReader
from ambient_insight.triggers.long_function import LongFunctionTrigger
from ambient_insight.triggers.uncovered import UncoveredHighChurnTrigger
from ambient_insight.triggers.velocity import HighVelocityTrigger
from tests.conftest import (
    insert_event,
    insert_symbol,
    insert_velocity,
)

NOW_MS = int(time.time() * 1000)


@pytest.fixture()
def reader(context_db):
    db_path, _ = context_db
    r = ContextReader(str(db_path))
    yield r
    r.close()


# ===========================================================================
# HighVelocityTrigger
# ===========================================================================


class TestHighVelocityTrigger:
    def test_fires_for_hot_file(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/hot.py", "ws", edits=7)
        results = HighVelocityTrigger(min_edits=5).evaluate(reader, "ws")
        assert len(results) == 1
        assert results[0].file_path == "/hot.py"

    def test_does_not_fire_below_threshold(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/cold.py", "ws", edits=2)
        results = HighVelocityTrigger(min_edits=5).evaluate(reader, "ws")
        assert results == []

    def test_returns_empty_on_missing_workspace(self, reader):
        results = HighVelocityTrigger(min_edits=5).evaluate(reader, "nonexistent")
        assert results == []

    def test_severity_info_for_low_edits(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/f.py", "ws", edits=5)
        results = HighVelocityTrigger(min_edits=5).evaluate(reader, "ws")
        assert results[0].severity == Severity.INFO

    def test_severity_warning_for_medium_edits(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/f.py", "ws", edits=7)
        results = HighVelocityTrigger(min_edits=5).evaluate(reader, "ws")
        assert results[0].severity == Severity.WARNING

    def test_severity_critical_for_high_edits(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/f.py", "ws", edits=10)
        results = HighVelocityTrigger(min_edits=5).evaluate(reader, "ws")
        assert results[0].severity == Severity.CRITICAL

    def test_context_data_contains_edits(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/f.py", "ws", edits=6, lines_added=20, lines_removed=5)
        results = HighVelocityTrigger(min_edits=5).evaluate(reader, "ws")
        cd = results[0].context_data
        assert cd["total_edits"] == 6
        assert cd["total_lines_added"] == 20
        assert cd["total_lines_removed"] == 5

    def test_trigger_name_is_high_velocity(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/f.py", "ws", edits=5)
        results = HighVelocityTrigger(min_edits=5).evaluate(reader, "ws")
        assert results[0].trigger_name == TriggerName.HIGH_VELOCITY

    def test_multiple_hot_files_all_returned(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/a.py", "ws", edits=5)
        insert_velocity(conn, "/b.py", "ws", edits=6)
        results = HighVelocityTrigger(min_edits=5).evaluate(reader, "ws")
        assert len(results) == 2


# ===========================================================================
# LongFunctionTrigger
# ===========================================================================


class TestLongFunctionTrigger:
    def test_fires_for_long_function_in_saved_file(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS)
        insert_symbol(conn, "/f.py", "ws", "big_fn", "function", 1, 50)
        results = LongFunctionTrigger(min_lines=40).evaluate(reader, "ws")
        assert len(results) == 1
        assert results[0].file_path == "/f.py"

    def test_does_not_fire_for_unsaved_file(self, context_db, reader):
        _, conn = context_db
        # Symbol exists but file was not saved today
        insert_symbol(conn, "/f.py", "ws", "big_fn", "function", 1, 50)
        results = LongFunctionTrigger(min_lines=40).evaluate(reader, "ws")
        assert results == []

    def test_does_not_fire_for_short_function(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS)
        insert_symbol(conn, "/f.py", "ws", "tiny_fn", "function", 1, 5)
        results = LongFunctionTrigger(min_lines=40).evaluate(reader, "ws")
        assert results == []

    def test_severity_info_for_medium_function(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS)
        insert_symbol(conn, "/f.py", "ws", "med_fn", "function", 1, 45)
        results = LongFunctionTrigger(min_lines=40).evaluate(reader, "ws")
        assert results[0].severity == Severity.INFO

    def test_severity_warning_for_large_function(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS)
        insert_symbol(conn, "/f.py", "ws", "big_fn", "function", 1, 65)
        results = LongFunctionTrigger(min_lines=40).evaluate(reader, "ws")
        assert results[0].severity == Severity.WARNING

    def test_severity_critical_for_giant_function(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS)
        insert_symbol(conn, "/f.py", "ws", "monster", "function", 1, 90)
        results = LongFunctionTrigger(min_lines=40).evaluate(reader, "ws")
        assert results[0].severity == Severity.CRITICAL

    def test_one_result_per_file_longest_function(self, context_db, reader):
        """Multiple long functions in one file → single result for the longest."""
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS)
        insert_symbol(conn, "/f.py", "ws", "small", "function", 1, 45)
        insert_symbol(conn, "/f.py", "ws", "giant", "function", 50, 140)
        results = LongFunctionTrigger(min_lines=40).evaluate(reader, "ws")
        assert len(results) == 1
        assert results[0].context_data["function_name"] == "giant"

    def test_context_data_has_function_meta(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS)
        insert_symbol(conn, "/f.py", "ws", "fn", "function", 10, 60, "def fn():")
        results = LongFunctionTrigger(min_lines=40).evaluate(reader, "ws")
        cd = results[0].context_data
        assert cd["function_name"] == "fn"
        assert cd["start_line"] == 10
        assert cd["end_line"] == 60
        assert cd["line_count"] == 50
        assert cd["signature"] == "def fn():"

    def test_trigger_name_is_long_function(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/f.py", "ws", "file_save", NOW_MS)
        insert_symbol(conn, "/f.py", "ws", "fn", "function", 1, 50)
        results = LongFunctionTrigger(min_lines=40).evaluate(reader, "ws")
        assert results[0].trigger_name == TriggerName.LONG_FUNCTION


# ===========================================================================
# UncoveredHighChurnTrigger
# ===========================================================================


class TestUncoveredHighChurnTrigger:
    def test_fires_when_no_tests_saved(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/src/app.py", "ws", edits=5)
        insert_event(conn, "/src/app.py", "ws", "file_save", NOW_MS)
        results = UncoveredHighChurnTrigger(min_edits=3).evaluate(reader, "ws")
        assert any(r.file_path == "/src/app.py" for r in results)

    def test_does_not_fire_when_test_saved(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/src/app.py", "ws", edits=5)
        insert_event(conn, "/src/app.py", "ws", "file_save", NOW_MS)
        # A test file was saved in the same workspace
        insert_event(conn, "/tests/test_app.py", "ws", "file_save", NOW_MS)
        results = UncoveredHighChurnTrigger(min_edits=3).evaluate(reader, "ws")
        assert results == []

    def test_does_not_fire_below_threshold(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/src/app.py", "ws", edits=1)
        insert_event(conn, "/src/app.py", "ws", "file_save", NOW_MS)
        results = UncoveredHighChurnTrigger(min_edits=3).evaluate(reader, "ws")
        assert results == []

    def test_does_not_fire_on_test_files_themselves(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/tests/test_app.py", "ws", edits=5)
        insert_event(conn, "/tests/test_app.py", "ws", "file_save", NOW_MS)
        results = UncoveredHighChurnTrigger(min_edits=3).evaluate(reader, "ws")
        assert results == []

    def test_test_file_patterns_python(self):
        """Verify Python test file patterns are recognised."""
        from ambient_insight.triggers.uncovered import _is_test_file

        assert _is_test_file("/tests/test_foo.py")
        assert _is_test_file("/tests/foo_test.py")
        assert not _is_test_file("/src/app.py")

    def test_test_file_patterns_typescript(self):
        from ambient_insight.triggers.uncovered import _is_test_file

        assert _is_test_file("/src/app.test.ts")
        assert _is_test_file("/src/app.spec.ts")
        assert _is_test_file("/src/app.test.tsx")
        assert not _is_test_file("/src/app.ts")

    def test_test_file_patterns_javascript(self):
        from ambient_insight.triggers.uncovered import _is_test_file

        assert _is_test_file("/src/utils.test.js")
        assert _is_test_file("/src/utils.spec.js")

    def test_severity_is_warning(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/src/app.py", "ws", edits=4)
        insert_event(conn, "/src/app.py", "ws", "file_save", NOW_MS)
        results = UncoveredHighChurnTrigger(min_edits=3).evaluate(reader, "ws")
        assert results[0].severity == Severity.WARNING

    def test_trigger_name_is_uncovered_high_churn(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/src/app.py", "ws", edits=4)
        insert_event(conn, "/src/app.py", "ws", "file_save", NOW_MS)
        results = UncoveredHighChurnTrigger(min_edits=3).evaluate(reader, "ws")
        assert results[0].trigger_name == TriggerName.UNCOVERED_HIGH_CHURN

    def test_context_data_has_total_edits(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/src/app.py", "ws", edits=4)
        insert_event(conn, "/src/app.py", "ws", "file_save", NOW_MS)
        results = UncoveredHighChurnTrigger(min_edits=3).evaluate(reader, "ws")
        assert results[0].context_data["total_edits"] == 4
        assert results[0].context_data["any_test_saved"] is False
