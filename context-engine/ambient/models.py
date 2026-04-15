"""
Pydantic v2 data models for the Ambient Code event schema.

These models are the Python mirror of the TypeScript types defined in
``extension/src/types.ts``.  They validate every JSON line read from
the NDJSON event log so the context engine fails fast on schema drift
rather than silently corrupting the database.

The field names use camelCase to match the serialised JSON produced by
the VS Code extension.  Snake-case aliases are provided for ergonomic
use inside Python code via ``model_config``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EventType(StrEnum):
    """Discriminated union of all event types in the NDJSON log.

    String values must remain stable — they form the Layer 1 ↔ Layer 2
    contract and are written verbatim by the VS Code extension.
    """

    FILE_CHANGE = "file_change"
    CURSOR_MOVE = "cursor_move"
    FILE_SAVE = "file_save"
    GIT_EVENT = "git_event"


# ---------------------------------------------------------------------------
# Metadata payloads
# ---------------------------------------------------------------------------


class FileChangeMetadata(BaseModel):
    """Metadata attached to ``file_change`` and ``file_save`` events."""

    model_config = ConfigDict(populate_by_name=True)

    is_paste: bool = Field(alias="isPaste")
    lines_added: int = Field(alias="linesAdded")
    lines_removed: int = Field(alias="linesRemoved")


class CursorMoveMetadata(BaseModel):
    """Metadata attached to ``cursor_move`` events."""

    model_config = ConfigDict(populate_by_name=True)

    line: int
    character: int


class GitEventMetadata(BaseModel):
    """Metadata attached to ``git_event`` events."""

    model_config = ConfigDict(populate_by_name=True)

    action: str
    branch: str | None = None
    previous_branch: str | None = Field(default=None, alias="previousBranch")
    commit_hash: str | None = Field(default=None, alias="commitHash")


# ---------------------------------------------------------------------------
# Core event model
# ---------------------------------------------------------------------------


class CodeEvent(BaseModel):
    """A single event read from the NDJSON event log.

    Field names match the camelCase keys produced by the TypeScript
    extension.  Access them in Python via their snake_case aliases.

    Example
    -------
    >>> import json
    >>> line = '{"timestamp":1713121200000,"type":"file_save","workspace":"my-project",' \
    ...        '"filePath":"/home/u/src/auth.ts","language":"typescript","diff":"---...",' \
    ...        '"metadata":{"isPaste":false,"linesAdded":4,"linesRemoved":1}}'
    >>> event = CodeEvent.model_validate_json(line)
    >>> event.file_path
    '/home/u/src/auth.ts'
    >>> event.event_type
    <EventType.FILE_SAVE: 'file_save'>
    """

    model_config = ConfigDict(populate_by_name=True)

    timestamp: int
    event_type: EventType = Field(alias="type")
    workspace: str
    file_path: str = Field(alias="filePath")
    language: str
    diff: str | None = None
    metadata: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Typed metadata accessors
    # ------------------------------------------------------------------

    def as_file_change_metadata(self) -> FileChangeMetadata | None:
        """Return typed metadata if this is a file_change or file_save event."""
        if self.event_type in (EventType.FILE_CHANGE, EventType.FILE_SAVE) and self.metadata:
            return FileChangeMetadata.model_validate(self.metadata)
        return None

    def as_cursor_move_metadata(self) -> CursorMoveMetadata | None:
        """Return typed metadata if this is a cursor_move event."""
        if self.event_type is EventType.CURSOR_MOVE and self.metadata:
            return CursorMoveMetadata.model_validate(self.metadata)
        return None

    def as_git_event_metadata(self) -> GitEventMetadata | None:
        """Return typed metadata if this is a git_event."""
        if self.event_type is EventType.GIT_EVENT and self.metadata:
            return GitEventMetadata.model_validate(self.metadata)
        return None


# ---------------------------------------------------------------------------
# Internal domain types (not part of the NDJSON schema)
# ---------------------------------------------------------------------------


class Symbol(BaseModel):
    """A code symbol extracted by the tree-sitter indexer."""

    file_path: str
    workspace: str
    name: str
    kind: str  # 'function' | 'class' | 'method' | 'interface' | 'type_alias' | 'enum'
    start_line: int
    end_line: int
    signature: str
    updated_at: int  # Unix ms timestamp
