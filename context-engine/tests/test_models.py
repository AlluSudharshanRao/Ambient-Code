"""
Unit tests for ambient.models — Pydantic event model parsing and validation.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ambient.models import (
    CodeEvent,
    CursorMoveMetadata,
    EventType,
    FileChangeMetadata,
    GitEventMetadata,
    Symbol,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FILE_SAVE_JSON = json.dumps(
    {
        "timestamp": 1713121200000,
        "type": "file_save",
        "workspace": "my-project",
        "filePath": "/home/u/src/auth.ts",
        "language": "typescript",
        "diff": "--- auth.ts\n+++ auth.ts\n@@ -1 +1 @@",
        "metadata": {"isPaste": False, "linesAdded": 4, "linesRemoved": 1},
    }
)

FILE_CHANGE_JSON = json.dumps(
    {
        "timestamp": 1713121100000,
        "type": "file_change",
        "workspace": "my-project",
        "filePath": "/home/u/src/auth.ts",
        "language": "typescript",
        "diff": "--- auth.ts\n+++ auth.ts",
        "metadata": {"isPaste": True, "linesAdded": 50, "linesRemoved": 0},
    }
)

CURSOR_MOVE_JSON = json.dumps(
    {
        "timestamp": 1713121300000,
        "type": "cursor_move",
        "workspace": "my-project",
        "filePath": "/home/u/src/user.ts",
        "language": "typescript",
        "metadata": {"line": 42, "character": 8},
    }
)

GIT_EVENT_JSON = json.dumps(
    {
        "timestamp": 1713121400000,
        "type": "git_event",
        "workspace": "my-project",
        "filePath": "/home/u/my-project",
        "language": "",
        "metadata": {
            "action": "branch_change",
            "branch": "feature/auth",
            "previousBranch": "main",
            "commitHash": "a3f9c12",
        },
    }
)


# ---------------------------------------------------------------------------
# CodeEvent parsing
# ---------------------------------------------------------------------------


class TestCodeEventParsing:
    def test_file_save_parses_correctly(self):
        event = CodeEvent.model_validate_json(FILE_SAVE_JSON)
        assert event.event_type == EventType.FILE_SAVE
        assert event.file_path == "/home/u/src/auth.ts"
        assert event.workspace == "my-project"
        assert event.language == "typescript"
        assert event.timestamp == 1713121200000
        assert event.diff is not None

    def test_file_change_parses_correctly(self):
        event = CodeEvent.model_validate_json(FILE_CHANGE_JSON)
        assert event.event_type == EventType.FILE_CHANGE

    def test_cursor_move_parses_correctly(self):
        event = CodeEvent.model_validate_json(CURSOR_MOVE_JSON)
        assert event.event_type == EventType.CURSOR_MOVE
        assert event.diff is None

    def test_git_event_parses_correctly(self):
        event = CodeEvent.model_validate_json(GIT_EVENT_JSON)
        assert event.event_type == EventType.GIT_EVENT
        assert event.language == ""

    def test_camelcase_file_path_alias(self):
        """filePath in JSON must map to file_path in Python."""
        event = CodeEvent.model_validate_json(FILE_SAVE_JSON)
        assert event.file_path == "/home/u/src/auth.ts"
        event2 = CodeEvent.model_validate(_base_fields(file_path="/x.py"))
        assert event2.file_path == "/x.py"

    def test_snake_case_file_path_also_accepted(self):
        """snake_case file_path is accepted because populate_by_name=True."""
        data = {k: v for k, v in _base_fields().items() if k != "filePath"}
        data["file_path"] = "/y.py"
        event = CodeEvent.model_validate(data)
        assert event.file_path == "/y.py"

    def test_event_type_alias(self):
        """'type' in JSON maps to event_type in Python."""
        event = CodeEvent.model_validate(_base_fields())
        assert event.event_type == EventType.FILE_SAVE

    def test_optional_diff_defaults_to_none(self):
        data = {**_base_fields(), "type": "cursor_move"}
        event = CodeEvent.model_validate(data)
        assert event.diff is None

    def test_optional_metadata_defaults_to_none(self):
        data = {**_base_fields(), "type": "cursor_move"}
        event = CodeEvent.model_validate(data)
        assert event.metadata is None

    def test_invalid_event_type_raises_validation_error(self):
        """Unknown event type strings must be rejected by Pydantic enum validation."""
        data = {**_base_fields(), "type": "unknown_future_type"}
        with pytest.raises(ValidationError):
            CodeEvent.model_validate(data)

    def test_missing_required_field_raises_validation_error(self):
        # Missing 'timestamp'
        with pytest.raises(ValidationError):
            CodeEvent.model_validate(
                {
                    "type": "file_save",
                    "workspace": "ws",
                    "filePath": "/x.py",
                    "language": "python",
                }
            )

    def test_extra_fields_are_ignored(self):
        """Unknown fields in the NDJSON should not cause errors."""
        data = {**_base_fields(), "unknownField": "value"}
        event = CodeEvent.model_validate(data)
        assert event.event_type == EventType.FILE_SAVE


# ---------------------------------------------------------------------------
# Typed metadata accessors
# ---------------------------------------------------------------------------


class TestMetadataAccessors:
    def test_file_save_returns_file_change_metadata(self):
        event = CodeEvent.model_validate_json(FILE_SAVE_JSON)
        meta = event.as_file_change_metadata()
        assert isinstance(meta, FileChangeMetadata)
        assert meta.lines_added == 4
        assert meta.lines_removed == 1
        assert meta.is_paste is False

    def test_file_change_returns_file_change_metadata(self):
        event = CodeEvent.model_validate_json(FILE_CHANGE_JSON)
        meta = event.as_file_change_metadata()
        assert isinstance(meta, FileChangeMetadata)
        assert meta.is_paste is True
        assert meta.lines_added == 50

    def test_cursor_move_returns_none_for_file_change_metadata(self):
        event = CodeEvent.model_validate_json(CURSOR_MOVE_JSON)
        assert event.as_file_change_metadata() is None

    def test_cursor_move_returns_cursor_metadata(self):
        event = CodeEvent.model_validate_json(CURSOR_MOVE_JSON)
        meta = event.as_cursor_move_metadata()
        assert isinstance(meta, CursorMoveMetadata)
        assert meta.line == 42
        assert meta.character == 8

    def test_git_event_returns_git_metadata(self):
        event = CodeEvent.model_validate_json(GIT_EVENT_JSON)
        meta = event.as_git_event_metadata()
        assert isinstance(meta, GitEventMetadata)
        assert meta.action == "branch_change"
        assert meta.branch == "feature/auth"
        assert meta.previous_branch == "main"
        assert meta.commit_hash == "a3f9c12"

    def test_file_save_returns_none_for_cursor_metadata(self):
        event = CodeEvent.model_validate_json(FILE_SAVE_JSON)
        assert event.as_cursor_move_metadata() is None

    def test_no_metadata_returns_none_for_all_accessors(self):
        event = CodeEvent.model_validate(_base_fields())
        assert event.as_file_change_metadata() is None

    def test_previous_branch_alias(self):
        """previousBranch in JSON must map to previous_branch in Python."""
        event = CodeEvent.model_validate_json(GIT_EVENT_JSON)
        meta = event.as_git_event_metadata()
        assert meta.previous_branch == "main"


# ---------------------------------------------------------------------------
# EventType
# ---------------------------------------------------------------------------


class TestEventType:
    def test_string_values_are_stable(self):
        assert EventType.FILE_CHANGE == "file_change"
        assert EventType.CURSOR_MOVE == "cursor_move"
        assert EventType.FILE_SAVE == "file_save"
        assert EventType.GIT_EVENT == "git_event"

    def test_is_str(self):
        assert isinstance(EventType.FILE_SAVE, str)


# ---------------------------------------------------------------------------
# Symbol model
# ---------------------------------------------------------------------------


class TestSymbol:
    def test_symbol_construction(self):
        sym = Symbol(
            file_path="/src/auth.py",
            workspace="ws",
            name="login",
            kind="function",
            start_line=0,
            end_line=2,
            signature="def login(u, p):",
            updated_at=NOW_MS,
        )
        assert sym.name == "login"
        assert sym.kind == "function"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_fields(*, file_path: str = "/x.py") -> dict:
    """All required CodeEvent fields using camelCase aliases."""
    return {
        "timestamp": 1713121200000,
        "type": "file_save",
        "workspace": "ws",
        "filePath": file_path,
        "language": "python",
    }


NOW_MS = 1713121200000
