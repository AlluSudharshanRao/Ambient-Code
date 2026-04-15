"""
Unit tests for ambient.tailer — NDJSON file tailer with byte-offset cursor.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ambient.models import CodeEvent, EventType
from ambient.tailer import Tailer
from tests.conftest import make_cursor_move_event, make_file_save_event, make_git_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_events(path: Path, events: list[CodeEvent]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(
                json.dumps(e.model_dump(by_alias=True, exclude_none=True), default=str)
                + "\n"
            )


def _append_events(path: Path, events: list[CodeEvent]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(
                json.dumps(e.model_dump(by_alias=True, exclude_none=True), default=str)
                + "\n"
            )


# ---------------------------------------------------------------------------
# Missing file
# ---------------------------------------------------------------------------


class TestMissingFile:
    def test_returns_empty_when_file_does_not_exist(self, tmp_path: Path):
        tailer = Tailer(
            str(tmp_path / "events.ndjson"),
            str(tmp_path / "cursor"),
        )
        assert tailer.read_new_events() == []

    def test_offset_stays_zero_when_file_missing(self, tmp_path: Path):
        tailer = Tailer(
            str(tmp_path / "events.ndjson"),
            str(tmp_path / "cursor"),
        )
        tailer.read_new_events()
        assert tailer.offset == 0


# ---------------------------------------------------------------------------
# Basic reading
# ---------------------------------------------------------------------------


class TestBasicReading:
    def test_reads_all_events_from_fresh_file(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        events = [make_file_save_event(), make_cursor_move_event(), make_git_event()]
        _write_events(log, events)

        tailer = Tailer(str(log), str(tmp_path / "cursor"))
        result = tailer.read_new_events()

        assert len(result) == 3
        assert result[0].event_type == EventType.FILE_SAVE
        assert result[1].event_type == EventType.CURSOR_MOVE
        assert result[2].event_type == EventType.GIT_EVENT

    def test_returns_empty_on_empty_file(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        log.write_text("", encoding="utf-8")

        tailer = Tailer(str(log), str(tmp_path / "cursor"))
        assert tailer.read_new_events() == []

    def test_returns_empty_on_file_with_only_blank_lines(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        log.write_text("\n\n\n", encoding="utf-8")

        tailer = Tailer(str(log), str(tmp_path / "cursor"))
        assert tailer.read_new_events() == []

    def test_event_fields_preserved(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        _write_events(log, [make_file_save_event(workspace="acme", language="go")])

        tailer = Tailer(str(log), str(tmp_path / "cursor"))
        result = tailer.read_new_events()

        assert result[0].workspace == "acme"
        assert result[0].language == "go"


# ---------------------------------------------------------------------------
# Cursor and commit
# ---------------------------------------------------------------------------


class TestCursorAndCommit:
    def test_offset_not_advanced_before_commit(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        _write_events(log, [make_file_save_event()])

        tailer = Tailer(str(log), str(tmp_path / "cursor"))
        tailer.read_new_events()

        assert tailer.offset == 0  # not yet committed

    def test_commit_advances_offset(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        _write_events(log, [make_file_save_event()])

        tailer = Tailer(str(log), str(tmp_path / "cursor"))
        tailer.read_new_events()
        tailer.commit()

        assert tailer.offset > 0

    def test_no_redelivery_after_commit(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        _write_events(log, [make_file_save_event()])

        tailer = Tailer(str(log), str(tmp_path / "cursor"))
        tailer.read_new_events()
        tailer.commit()

        # Read again — should return nothing new
        result = tailer.read_new_events()
        assert result == []

    def test_cursor_persists_across_restart(self, tmp_path: Path):
        """Events already committed are not re-delivered to a fresh Tailer instance."""
        log = tmp_path / "events.ndjson"
        cursor = tmp_path / "cursor"
        events = [make_file_save_event(), make_cursor_move_event()]
        _write_events(log, events)

        # First tailer: read and commit both events
        t1 = Tailer(str(log), str(cursor))
        t1.read_new_events()
        t1.commit()

        # Append one more event
        _append_events(log, [make_git_event()])

        # Second tailer starts from saved cursor — only sees the new event
        t2 = Tailer(str(log), str(cursor))
        result = t2.read_new_events()
        assert len(result) == 1
        assert result[0].event_type == EventType.GIT_EVENT

    def test_commit_without_prior_read_is_noop(self, tmp_path: Path):
        tailer = Tailer(str(tmp_path / "events.ndjson"), str(tmp_path / "cursor"))
        tailer.commit()  # no _pending_offset set
        assert tailer.offset == 0

    def test_cursor_file_written_on_commit(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        cursor = tmp_path / "cursor"
        _write_events(log, [make_file_save_event()])

        tailer = Tailer(str(log), str(cursor))
        tailer.read_new_events()
        tailer.commit()

        assert cursor.exists()
        assert int(cursor.read_text()) > 0


# ---------------------------------------------------------------------------
# Crash-safe at-least-once delivery
# ---------------------------------------------------------------------------


class TestAtLeastOnceDelivery:
    def test_redelivers_uncommitted_batch_on_restart(self, tmp_path: Path):
        """Simulates a crash: read without commit → new Tailer re-delivers events."""
        log = tmp_path / "events.ndjson"
        cursor = tmp_path / "cursor"
        _write_events(log, [make_file_save_event(), make_cursor_move_event()])

        # "Crash" — read but never commit
        t1 = Tailer(str(log), str(cursor))
        batch1 = t1.read_new_events()
        assert len(batch1) == 2

        # New tailer (same cursor file) → replays the same events
        t2 = Tailer(str(log), str(cursor))
        batch2 = t2.read_new_events()
        assert len(batch2) == 2
        assert [e.event_type for e in batch2] == [e.event_type for e in batch1]


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_reprocesses_all_events(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        cursor = tmp_path / "cursor"
        _write_events(log, [make_file_save_event(), make_git_event()])

        tailer = Tailer(str(log), str(cursor))
        tailer.read_new_events()
        tailer.commit()

        # Reset to beginning
        tailer.reset()
        assert tailer.offset == 0

        result = tailer.read_new_events()
        assert len(result) == 2

    def test_reset_updates_cursor_file(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        cursor = tmp_path / "cursor"
        _write_events(log, [make_file_save_event()])

        tailer = Tailer(str(log), str(cursor))
        tailer.read_new_events()
        tailer.commit()
        assert int(cursor.read_text()) > 0

        tailer.reset()
        assert int(cursor.read_text()) == 0


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_malformed_json_line_is_skipped(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        good = make_file_save_event()
        good_line = (
            json.dumps(good.model_dump(by_alias=True, exclude_none=True), default=str)
            + "\n"
        )
        # Sandwich a bad line between two good ones
        log.write_text(
            good_line + "{ not valid json }\n" + good_line,
            encoding="utf-8",
        )

        tailer = Tailer(str(log), str(tmp_path / "cursor"))
        result = tailer.read_new_events()

        # Bad line skipped; 2 good events returned
        assert len(result) == 2
        assert all(e.event_type == EventType.FILE_SAVE for e in result)

    def test_empty_lines_skipped(self, tmp_path: Path):
        log = tmp_path / "events.ndjson"
        good = make_file_save_event()
        good_line = (
            json.dumps(good.model_dump(by_alias=True, exclude_none=True), default=str)
            + "\n"
        )
        log.write_text("\n" + good_line + "\n", encoding="utf-8")

        tailer = Tailer(str(log), str(tmp_path / "cursor"))
        result = tailer.read_new_events()
        assert len(result) == 1
