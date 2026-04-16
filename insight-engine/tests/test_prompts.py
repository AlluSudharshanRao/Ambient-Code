"""
Unit tests for ambient_insight.llm.prompts.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ambient_insight.llm.prompts import (
    SYSTEM_PROMPT,
    _format_diffs,
    _format_symbols,
    assemble_context,
    build_title,
    build_user_prompt,
)
from ambient_insight.models import Severity, TriggerName
from ambient_insight.reader import ContextReader
from ambient_insight.triggers.base import TriggerResult
from tests.conftest import insert_event, insert_symbol, insert_velocity

NOW_MS = int(time.time() * 1000)


@pytest.fixture()
def reader(context_db):
    db_path, _ = context_db
    r = ContextReader(str(db_path))
    yield r
    r.close()


def _result(trigger=TriggerName.HIGH_VELOCITY, file_path="/src/app.py", **ctx_overrides):
    cd = {"total_edits": 7, "total_lines_added": 30, "total_lines_removed": 5}
    cd.update(ctx_overrides)
    return TriggerResult(
        file_path=file_path,
        workspace="ws",
        trigger_name=trigger,
        severity=Severity.WARNING,
        context_data=cd,
    )


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_is_non_empty_string(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 50

    def test_contains_expected_guidance(self):
        assert "concise" in SYSTEM_PROMPT.lower() or "short" in SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# _format_symbols
# ---------------------------------------------------------------------------


class TestFormatSymbols:
    def test_empty_returns_placeholder(self):
        out = _format_symbols([])
        assert "no symbols" in out

    def test_formats_symbol_correctly(self):
        syms = [{"name": "my_fn", "kind": "function", "start_line": 10, "signature": "def my_fn():"}]
        out = _format_symbols(syms)
        assert "my_fn" in out
        assert "10" in out

    def test_caps_at_15(self):
        syms = [
            {"name": f"fn_{i}", "kind": "function", "start_line": i, "signature": ""}
            for i in range(20)
        ]
        out = _format_symbols(syms)
        assert "and 5 more" in out


# ---------------------------------------------------------------------------
# _format_diffs
# ---------------------------------------------------------------------------


class TestFormatDiffs:
    def test_empty_returns_placeholder(self):
        out = _format_diffs([])
        assert "no recent diffs" in out

    def test_formats_diff(self):
        out = _format_diffs(["+added line\n-removed line"])
        assert "+added line" in out

    def test_truncates_long_diff(self):
        long_diff = "\n".join(f"+line {i}" for i in range(50))
        out = _format_diffs([long_diff])
        lines_in_output = out.split("\n")
        assert len(lines_in_output) <= 35  # 30 diff lines + header + some slack


# ---------------------------------------------------------------------------
# assemble_context
# ---------------------------------------------------------------------------


class TestAssembleContext:
    def test_returns_required_keys(self, context_db, reader):
        _, conn = context_db
        insert_velocity(conn, "/src/app.py", "ws", edits=7)
        ctx = assemble_context(_result(), reader)
        assert "file_name" in ctx
        assert "file_path" in ctx
        assert "workspace" in ctx
        assert "symbols" in ctx
        assert "recent_diffs" in ctx

    def test_file_name_is_basename(self, context_db, reader):
        ctx = assemble_context(_result(file_path="/some/deep/path/app.py"), reader)
        assert ctx["file_name"] == "app.py"

    def test_symbols_populated_from_db(self, context_db, reader):
        _, conn = context_db
        insert_symbol(conn, "/src/app.py", "ws", "main", "function", 1, 20)
        ctx = assemble_context(_result(), reader)
        assert any(s["name"] == "main" for s in ctx["symbols"])

    def test_recent_diffs_from_events(self, context_db, reader):
        _, conn = context_db
        insert_event(conn, "/src/app.py", "ws", "file_save", NOW_MS, diff="+new line")
        ctx = assemble_context(_result(), reader)
        assert any("+new line" in d for d in ctx["recent_diffs"])


# ---------------------------------------------------------------------------
# build_user_prompt
# ---------------------------------------------------------------------------


class TestBuildUserPrompt:
    def test_high_velocity_prompt_contains_file(self, context_db, reader):
        ctx = assemble_context(_result(trigger=TriggerName.HIGH_VELOCITY), reader)
        prompt = build_user_prompt(ctx)
        assert "/src/app.py" in prompt
        assert "7" in prompt  # total_edits

    def test_long_function_prompt_contains_function_name(self, context_db, reader):
        ctx = assemble_context(
            _result(
                trigger=TriggerName.LONG_FUNCTION,
                function_name="process_data",
                kind="function",
                start_line=10,
                end_line=60,
                line_count=50,
                signature="def process_data():",
            ),
            reader,
        )
        prompt = build_user_prompt(ctx)
        assert "process_data" in prompt

    def test_uncovered_churn_prompt(self, context_db, reader):
        ctx = assemble_context(
            _result(
                trigger=TriggerName.UNCOVERED_HIGH_CHURN,
                total_edits=4,
                any_test_saved=False,
            ),
            reader,
        )
        prompt = build_user_prompt(ctx)
        assert "test" in prompt.lower()

    def test_generic_fallback_for_unknown_trigger(self, context_db, reader):
        result = TriggerResult(
            file_path="/f.py",
            workspace="ws",
            trigger_name="custom_trigger",
            severity=Severity.INFO,
            context_data={},
        )
        ctx = assemble_context(result, reader)
        prompt = build_user_prompt(ctx)
        assert "custom_trigger" in prompt or "/f.py" in prompt


# ---------------------------------------------------------------------------
# build_title
# ---------------------------------------------------------------------------


class TestBuildTitle:
    def test_high_velocity_title(self):
        r = _result(trigger=TriggerName.HIGH_VELOCITY, file_path="/src/app.py", total_edits=7)
        title = build_title(r)
        assert "app.py" in title
        assert "7" in title

    def test_long_function_title(self):
        r = _result(
            trigger=TriggerName.LONG_FUNCTION,
            file_path="/src/app.py",
            function_name="do_stuff",
            line_count=55,
        )
        title = build_title(r)
        assert "do_stuff" in title
        assert "55" in title

    def test_uncovered_churn_title(self):
        r = _result(
            trigger=TriggerName.UNCOVERED_HIGH_CHURN,
            file_path="/src/service.py",
        )
        title = build_title(r)
        assert "service.py" in title
        assert "coverage" in title.lower() or "churn" in title.lower()

    def test_unknown_trigger_title(self):
        r = TriggerResult(
            file_path="/src/foo.py",
            workspace="ws",
            trigger_name="custom",
            severity=Severity.INFO,
            context_data={},
        )
        title = build_title(r)
        assert "foo.py" in title
