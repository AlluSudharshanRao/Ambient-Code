"""
NDJSON event log tailer.

Reads new lines from ``~/.ambient-code/events.ndjson`` by tracking the
last-read byte offset in a cursor file (``~/.ambient-code/cursor``).
On each call to :meth:`Tailer.read_new_events`, the file is seeked to
the saved offset, all new complete lines are read, and the offset is
updated.

Design choices
--------------
- **Byte-offset cursor** rather than line count: survives log rotation
  and is O(1) to seek regardless of file size.
- **No inotify/FSEvents**: polling is used by default to keep the
  dependency footprint minimal.  The poll interval is set by the caller.
- **Crash-safe**: the cursor is only written *after* the caller has
  successfully processed and persisted the batch.  If the process
  crashes between read and persist, events are re-delivered on restart.
  The caller is responsible for idempotent processing.
- **Tolerant of missing file**: if the log file does not yet exist (the
  VS Code extension has not activated), :meth:`read_new_events` returns
  an empty list silently.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import ValidationError

from ambient.models import CodeEvent

logger = logging.getLogger(__name__)


class Tailer:
    """Stateful NDJSON file tailer with a persistent byte-offset cursor.

    Parameters
    ----------
    log_path:
        Absolute path to the NDJSON event log produced by Layer 1.
    cursor_path:
        Path where the byte-offset cursor is persisted between runs.
        The file contains a single integer representing the number of
        bytes already consumed.
    """

    def __init__(self, log_path: str, cursor_path: str) -> None:
        self._log_path = Path(log_path)
        self._cursor_path = Path(cursor_path)
        self._offset: int = self._load_cursor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_new_events(self) -> list[CodeEvent]:
        """Read and parse all new complete lines since the last call.

        Returns
        -------
        list[CodeEvent]
            Parsed events in the order they appear in the log.
            Returns an empty list if there are no new lines or the log
            file does not exist yet.

        Notes
        -----
        The cursor is **not** advanced here — call :meth:`commit` after
        the batch has been successfully processed to advance and persist
        the cursor.  This gives the caller crash-safe at-least-once
        delivery semantics.
        """
        if not self._log_path.exists():
            return []

        try:
            file_size = self._log_path.stat().st_size
        except OSError:
            return []

        if file_size <= self._offset:
            return []

        events: list[CodeEvent] = []
        new_offset = self._offset

        try:
            with self._log_path.open("r", encoding="utf-8") as fh:
                fh.seek(self._offset)
                for raw_line in fh:
                    line = raw_line.rstrip("\n")
                    if not line:
                        new_offset += len(raw_line.encode("utf-8"))
                        continue
                    try:
                        event = CodeEvent.model_validate_json(line)
                        events.append(event)
                    except ValidationError as exc:
                        logger.warning(
                            "Skipping malformed event line (offset=%d): %s",
                            new_offset,
                            exc,
                        )
                    new_offset += len(raw_line.encode("utf-8"))
        except OSError as exc:
            logger.error("Failed to read event log %s: %s", self._log_path, exc)
            return []

        self._pending_offset = new_offset
        return events

    def commit(self) -> None:
        """Advance and persist the cursor to the end of the last read batch.

        Must be called *after* the batch returned by :meth:`read_new_events`
        has been successfully written to the database.
        """
        if not hasattr(self, "_pending_offset"):
            return
        self._offset = self._pending_offset
        self._save_cursor(self._offset)
        del self._pending_offset

    def reset(self) -> None:
        """Reset the cursor to 0, re-processing the entire log on next read.

        Useful during development or after a database wipe.
        """
        self._offset = 0
        self._save_cursor(0)

    @property
    def offset(self) -> int:
        """Current committed byte offset."""
        return self._offset

    # ------------------------------------------------------------------
    # Cursor persistence
    # ------------------------------------------------------------------

    def _load_cursor(self) -> int:
        """Read the persisted cursor offset, defaulting to 0."""
        try:
            return int(self._cursor_path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return 0

    def _save_cursor(self, offset: int) -> None:
        """Persist the cursor offset atomically using a rename."""
        self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cursor_path.with_suffix(".tmp")
        tmp.write_text(str(offset), encoding="utf-8")
        os.replace(tmp, self._cursor_path)  # atomic on POSIX and Windows


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------


def default_log_path() -> str:
    """Return the default NDJSON log path: ``~/.ambient-code/events.ndjson``."""
    return str(Path.home() / ".ambient-code" / "events.ndjson")


def default_cursor_path() -> str:
    """Return the default cursor path: ``~/.ambient-code/cursor``."""
    return str(Path.home() / ".ambient-code" / "cursor")
