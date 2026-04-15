"""
Shared pytest fixtures for the Ambient Code context engine test suite.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ambient.db.store import Store
from ambient.models import CodeEvent, EventType


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

NOW_MS = int(time.time() * 1000)


# ---------------------------------------------------------------------------
# CodeEvent factories
# ---------------------------------------------------------------------------


def make_file_save_event(
    file_path: str = "/project/src/auth.py",
    workspace: str = "test-ws",
    language: str = "python",
    lines_added: int = 5,
    lines_removed: int = 1,
    timestamp: int | None = None,
) -> CodeEvent:
    return CodeEvent.model_validate(
        {
            "timestamp": timestamp or NOW_MS,
            "type": EventType.FILE_SAVE,
            "workspace": workspace,
            "filePath": file_path,
            "language": language,
            "diff": "--- auth.py\n+++ auth.py\n@@ -1,3 +1,7 @@\n+def login(): pass",
            "metadata": {
                "isPaste": False,
                "linesAdded": lines_added,
                "linesRemoved": lines_removed,
            },
        }
    )


def make_file_change_event(
    file_path: str = "/project/src/auth.py",
    workspace: str = "test-ws",
) -> CodeEvent:
    return CodeEvent.model_validate(
        {
            "timestamp": NOW_MS,
            "type": EventType.FILE_CHANGE,
            "workspace": workspace,
            "filePath": file_path,
            "language": "python",
            "diff": "--- auth.py\n+++ auth.py\n@@ -1 +1 @@\n-old\n+new",
            "metadata": {"isPaste": False, "linesAdded": 1, "linesRemoved": 1},
        }
    )


def make_cursor_move_event(
    file_path: str = "/project/src/auth.py",
    workspace: str = "test-ws",
    line: int = 10,
    character: int = 4,
) -> CodeEvent:
    return CodeEvent.model_validate(
        {
            "timestamp": NOW_MS,
            "type": EventType.CURSOR_MOVE,
            "workspace": workspace,
            "filePath": file_path,
            "language": "python",
            "metadata": {"line": line, "character": character},
        }
    )


def make_git_event(
    workspace: str = "test-ws",
    action: str = "branch_change",
    branch: str = "feature/x",
    previous_branch: str = "main",
) -> CodeEvent:
    return CodeEvent.model_validate(
        {
            "timestamp": NOW_MS,
            "type": EventType.GIT_EVENT,
            "workspace": workspace,
            "filePath": "/project",
            "language": "",
            "metadata": {
                "action": action,
                "branch": branch,
                "previousBranch": previous_branch,
                "commitHash": "abc1234",
            },
        }
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    """Return a fresh in-memory-like Store backed by a temp file."""
    s = Store(str(tmp_path / "context.db"))
    yield s
    s.close()


@pytest.fixture()
def sample_file_save(tmp_path: Path) -> CodeEvent:
    """A file_save event whose filePath points to a real temp Python file."""
    src = tmp_path / "auth.py"
    src.write_text(
        "def login(username, password):\n"
        "    return True\n"
        "\n"
        "class UserService:\n"
        "    def get_user(self, uid):\n"
        "        return uid\n",
        encoding="utf-8",
    )
    return make_file_save_event(file_path=str(src))


@pytest.fixture()
def ndjson_log(tmp_path: Path) -> tuple[Path, list[CodeEvent]]:
    """Write three events to a NDJSON file; return (path, events)."""
    log_path = tmp_path / "events.ndjson"
    events = [
        make_file_save_event(),
        make_cursor_move_event(),
        make_git_event(),
    ]
    with log_path.open("w", encoding="utf-8") as fh:
        for e in events:
            # Serialise via model_dump with alias so filePath/type are correct
            fh.write(
                json.dumps(
                    e.model_dump(by_alias=True, exclude_none=True),
                    default=str,
                )
                + "\n"
            )
    return log_path, events
