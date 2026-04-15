"""
Integration tests for the full Layer 2 pipeline.

These tests exercise the complete path:
  NDJSON log → Tailer → ContextEngine → SQLite (events + symbols + velocity)

They use real files on disk, a real SQLite database, and the full
ContextEngine orchestration — no mocking.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ambient.main import ContextEngine
from ambient.models import EventType
from tests.conftest import (
    make_cursor_move_event,
    make_file_save_event,
    make_git_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_ndjson(path: Path, events: list) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(
                json.dumps(e.model_dump(by_alias=True, exclude_none=True), default=str)
                + "\n"
            )


def _append_ndjson(path: Path, events: list) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(
                json.dumps(e.model_dump(by_alias=True, exclude_none=True), default=str)
                + "\n"
            )


@pytest.fixture()
def engine(tmp_path: Path):
    eng = ContextEngine(
        log_path=str(tmp_path / "events.ndjson"),
        db_path=str(tmp_path / "context.db"),
        cursor_path=str(tmp_path / "cursor"),
        poll_ms=100,
    )
    yield eng
    eng.close()


@pytest.fixture()
def py_source(tmp_path: Path) -> Path:
    """A real Python source file on disk for the symbol indexer to parse."""
    src = tmp_path / "auth.py"
    src.write_text(
        "def login(username, password):\n"
        "    return True\n"
        "\n"
        "def logout():\n"
        "    pass\n"
        "\n"
        "class AuthService:\n"
        "    def validate(self, token):\n"
        "        return bool(token)\n",
        encoding="utf-8",
    )
    return src


@pytest.fixture()
def ts_source(tmp_path: Path) -> Path:
    """A real TypeScript source file on disk."""
    src = tmp_path / "user.ts"
    src.write_text(
        "interface User { id: string; name: string; }\n"
        "function getUser(id: string): User { return { id, name: 'Alice' }; }\n"
        "class UserService { list(): User[] { return []; } }\n",
        encoding="utf-8",
    )
    return src


# ---------------------------------------------------------------------------
# Basic pipeline
# ---------------------------------------------------------------------------


class TestBasicPipeline:
    def test_file_save_populates_all_three_tables(
        self, engine: ContextEngine, tmp_path: Path, py_source: Path
    ):
        log = tmp_path / "events.ndjson"
        event = make_file_save_event(
            file_path=str(py_source), workspace="test-ws", language="python"
        )
        _write_ndjson(log, [event])

        batch = engine._tailer.read_new_events()
        engine._process_batch(batch)
        engine._tailer.commit()

        # events table
        event_count = engine._store._conn.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
        assert event_count == 1

        # symbols table
        symbols = engine._store.get_symbols(str(py_source))
        sym_names = {r["name"] for r in symbols}
        assert "login" in sym_names
        assert "logout" in sym_names
        assert "AuthService" in sym_names

        # velocity table
        vel_rows = engine._store.get_velocity_for_file(str(py_source), days=30)
        assert len(vel_rows) == 1
        assert vel_rows[0]["edits"] == 1

    def test_cursor_move_stored_in_events_only(
        self, engine: ContextEngine, tmp_path: Path
    ):
        log = tmp_path / "events.ndjson"
        _write_ndjson(log, [make_cursor_move_event()])

        batch = engine._tailer.read_new_events()
        engine._process_batch(batch)
        engine._tailer.commit()

        event_count = engine._store._conn.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
        assert event_count == 1

        # No symbols or velocity rows from a cursor_move
        assert engine._store._conn.execute(
            "SELECT COUNT(*) FROM symbols"
        ).fetchone()[0] == 0
        assert engine._store._conn.execute(
            "SELECT COUNT(*) FROM velocity"
        ).fetchone()[0] == 0

    def test_git_event_stored_in_events_only(
        self, engine: ContextEngine, tmp_path: Path
    ):
        log = tmp_path / "events.ndjson"
        _write_ndjson(log, [make_git_event()])

        batch = engine._tailer.read_new_events()
        engine._process_batch(batch)
        engine._tailer.commit()

        assert (
            engine._store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        )
        assert (
            engine._store._conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
        )

    def test_mixed_batch_processed_correctly(
        self, engine: ContextEngine, tmp_path: Path, py_source: Path
    ):
        log = tmp_path / "events.ndjson"
        events = [
            make_file_save_event(str(py_source), language="python"),
            make_cursor_move_event(str(py_source)),
            make_git_event(),
        ]
        _write_ndjson(log, events)

        batch = engine._tailer.read_new_events()
        engine._process_batch(batch)
        engine._tailer.commit()

        assert (
            engine._store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3
        )

    def test_typescript_symbols_indexed(
        self, engine: ContextEngine, tmp_path: Path, ts_source: Path
    ):
        log = tmp_path / "events.ndjson"
        _write_ndjson(
            log,
            [make_file_save_event(str(ts_source), language="typescript")],
        )

        batch = engine._tailer.read_new_events()
        engine._process_batch(batch)

        symbols = engine._store.get_symbols(str(ts_source))
        names = {r["name"] for r in symbols}
        assert "getUser" in names
        assert "UserService" in names
        assert "User" in names


# ---------------------------------------------------------------------------
# Incremental processing
# ---------------------------------------------------------------------------


class TestIncrementalProcessing:
    def test_second_batch_appended_to_events(
        self, engine: ContextEngine, tmp_path: Path, py_source: Path
    ):
        log = tmp_path / "events.ndjson"
        _write_ndjson(log, [make_file_save_event(str(py_source), language="python")])

        # First batch
        b1 = engine._tailer.read_new_events()
        engine._process_batch(b1)
        engine._tailer.commit()

        # Append second batch
        _append_ndjson(log, [make_cursor_move_event(), make_git_event()])

        # Second batch
        b2 = engine._tailer.read_new_events()
        engine._process_batch(b2)
        engine._tailer.commit()

        total = engine._store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert total == 3

    def test_symbols_updated_on_re_save(
        self, engine: ContextEngine, tmp_path: Path, py_source: Path
    ):
        log = tmp_path / "events.ndjson"
        _write_ndjson(
            log, [make_file_save_event(str(py_source), language="python")]
        )

        b1 = engine._tailer.read_new_events()
        engine._process_batch(b1)
        engine._tailer.commit()
        count_before = len(engine._store.get_symbols(str(py_source)))

        # Add a new function to the source and re-save
        with py_source.open("a", encoding="utf-8") as fh:
            fh.write("\ndef new_function():\n    pass\n")

        _append_ndjson(
            log, [make_file_save_event(str(py_source), language="python")]
        )

        b2 = engine._tailer.read_new_events()
        engine._process_batch(b2)
        engine._tailer.commit()

        count_after = len(engine._store.get_symbols(str(py_source)))
        assert count_after > count_before

    def test_velocity_accumulates_across_batches(
        self, engine: ContextEngine, tmp_path: Path, py_source: Path
    ):
        log = tmp_path / "events.ndjson"
        event = make_file_save_event(str(py_source), language="python", lines_added=3)
        _write_ndjson(log, [event])

        b1 = engine._tailer.read_new_events()
        engine._process_batch(b1)
        engine._tailer.commit()

        _append_ndjson(log, [event])
        b2 = engine._tailer.read_new_events()
        engine._process_batch(b2)
        engine._tailer.commit()

        rows = engine._store.get_velocity_for_file(str(py_source))
        assert rows[0]["edits"] == 2
        assert rows[0]["lines_added"] == 6


# ---------------------------------------------------------------------------
# Crash safety
# ---------------------------------------------------------------------------


class TestCrashSafety:
    def test_uncommitted_batch_redelivered(
        self, engine: ContextEngine, tmp_path: Path
    ):
        log = tmp_path / "events.ndjson"
        cursor = tmp_path / "cursor"
        db = tmp_path / "context.db"

        _write_ndjson(log, [make_cursor_move_event(), make_git_event()])

        # "Crash" — read but never commit
        batch = engine._tailer.read_new_events()
        assert len(batch) == 2
        engine.close()

        # New engine from same cursor — redelivers the same events
        engine2 = ContextEngine(
            log_path=str(log),
            db_path=str(db),
            cursor_path=str(cursor),
            poll_ms=100,
        )
        batch2 = engine2._tailer.read_new_events()
        assert len(batch2) == 2
        engine2.close()

    def test_duplicate_event_rows_on_redelivery(
        self, engine: ContextEngine, tmp_path: Path
    ):
        """
        If a batch is re-processed after a crash, events are inserted twice
        (at-least-once semantics). This is acceptable at the current stage.
        Layer 3 de-duplication is a future concern.
        """
        log = tmp_path / "events.ndjson"
        cursor = tmp_path / "cursor"
        db = tmp_path / "context.db"

        _write_ndjson(log, [make_cursor_move_event()])

        # Process without commit → "crash"
        b1 = engine._tailer.read_new_events()
        engine._process_batch(b1)
        engine.close()

        # Restart and process again
        engine2 = ContextEngine(
            log_path=str(log),
            db_path=str(db),
            cursor_path=str(cursor),
            poll_ms=100,
        )
        b2 = engine2._tailer.read_new_events()
        engine2._process_batch(b2)
        engine2._tailer.commit()

        count = engine2._store._conn.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
        assert count == 2  # Both deliveries inserted
        engine2.close()


# ---------------------------------------------------------------------------
# Empty log / no-op cases
# ---------------------------------------------------------------------------


class TestEmptyLog:
    def test_no_events_returns_empty_batch(
        self, engine: ContextEngine, tmp_path: Path
    ):
        log = tmp_path / "events.ndjson"
        log.write_text("", encoding="utf-8")

        batch = engine._tailer.read_new_events()
        assert batch == []

    def test_missing_log_returns_empty_batch(
        self, engine: ContextEngine, tmp_path: Path
    ):
        # log file does not exist at all
        batch = engine._tailer.read_new_events()
        assert batch == []

    def test_process_empty_batch_is_noop(self, engine: ContextEngine, tmp_path: Path):
        engine._process_batch([])
        assert (
            engine._store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        )
