"""
Unit tests for ambient_insight.main.InsightEngine.

The LLM client is always monkeypatched so no real API calls are made.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ambient_insight.main import InsightEngine
from tests.conftest import insert_event, insert_symbol, insert_velocity

NOW_MS = int(time.time() * 1000)

_FAKE_BODY = "This is a fake LLM response for testing."


@pytest.fixture()
def engine(context_db, tmp_path):
    """InsightEngine wired to a temp DB + findings path; LLM is mocked."""
    db_path, _ = context_db
    findings_path = str(tmp_path / "findings.ndjson")

    with patch("ambient_insight.main.call_openai", return_value=_FAKE_BODY):
        eng = InsightEngine(
            db_path=str(db_path),
            findings_path=findings_path,
            poll_ms=100,
            velocity_threshold=3,
            function_line_threshold=20,
        )
        yield eng, db_path, findings_path


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestInsightEngineConstruction:
    def test_creates_successfully(self, context_db, tmp_path):
        db_path, _ = context_db
        eng = InsightEngine(
            db_path=str(db_path),
            findings_path=str(tmp_path / "f.ndjson"),
        )
        eng.close()

    def test_has_three_triggers(self, context_db, tmp_path):
        db_path, _ = context_db
        eng = InsightEngine(
            db_path=str(db_path),
            findings_path=str(tmp_path / "f.ndjson"),
        )
        assert len(eng._triggers) == 3
        eng.close()


# ---------------------------------------------------------------------------
# _tick
# ---------------------------------------------------------------------------


class TestInsightEngineTick:
    def test_tick_on_empty_db_does_not_crash(self, engine):
        eng, _, _ = engine
        eng._tick()  # Should complete silently

    def test_tick_writes_finding_for_hot_file(self, engine, context_db):
        eng, db_path, findings_path = engine
        _, conn = context_db
        insert_velocity(conn, "/hot.py", "ws", edits=5)
        insert_event(conn, "/hot.py", "ws", "file_save", NOW_MS)

        with patch("ambient_insight.main.call_openai", return_value=_FAKE_BODY):
            eng._tick()

        assert Path(findings_path).exists()
        lines = Path(findings_path).read_text().strip().splitlines()
        assert len(lines) >= 1

    def test_finding_has_correct_fields(self, engine, context_db):
        eng, db_path, findings_path = engine
        _, conn = context_db
        insert_velocity(conn, "/hot.py", "ws", edits=5)
        insert_event(conn, "/hot.py", "ws", "file_save", NOW_MS)

        with patch("ambient_insight.main.call_openai", return_value=_FAKE_BODY):
            eng._tick()

        lines = Path(findings_path).read_text().strip().splitlines()
        obj = json.loads(lines[0])
        assert "trigger" in obj
        assert "severity" in obj
        assert "title" in obj
        assert "body" in obj
        assert obj["body"] == _FAKE_BODY

    def test_tick_with_missing_db_does_not_crash(self, tmp_path):
        eng = InsightEngine(
            db_path=str(tmp_path / "no_such.db"),
            findings_path=str(tmp_path / "f.ndjson"),
        )
        eng._tick()  # Should log warning, not raise
        eng.close()

    def test_long_function_trigger_fires(self, engine, context_db):
        eng, db_path, findings_path = engine
        _, conn = context_db
        insert_event(conn, "/src/big.py", "ws", "file_save", NOW_MS)
        insert_symbol(conn, "/src/big.py", "ws", "huge_fn", "function", 1, 50)

        with patch("ambient_insight.main.call_openai", return_value=_FAKE_BODY):
            eng._tick()

        assert Path(findings_path).exists()
        content = Path(findings_path).read_text()
        assert "long_function" in content

    def test_openai_error_does_not_crash_tick(self, engine, context_db):
        eng, db_path, findings_path = engine
        _, conn = context_db
        insert_velocity(conn, "/hot.py", "ws", edits=5)
        insert_event(conn, "/hot.py", "ws", "file_save", NOW_MS)

        with patch("ambient_insight.main.call_openai", side_effect=RuntimeError("API down")):
            eng._tick()  # Should log, not raise

        # No findings written due to error
        assert not Path(findings_path).exists() or Path(findings_path).stat().st_size == 0


# ---------------------------------------------------------------------------
# stop / run lifecycle
# ---------------------------------------------------------------------------


class TestInsightEngineLifecycle:
    def test_stop_prevents_further_ticks(self, context_db, tmp_path):
        db_path, _ = context_db
        eng = InsightEngine(
            db_path=str(db_path),
            findings_path=str(tmp_path / "f.ndjson"),
            poll_ms=1,
        )
        eng._running = True
        eng.stop()
        assert eng._running is False

    def test_close_does_not_raise(self, context_db, tmp_path):
        db_path, _ = context_db
        eng = InsightEngine(
            db_path=str(db_path),
            findings_path=str(tmp_path / "f.ndjson"),
        )
        eng.close()
