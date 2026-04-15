"""
Change velocity tracker.

Records how frequently files are edited and aggregates the data into
daily churn buckets.  This is the primary risk signal consumed by the
Layer 3 insight engine: files that churn rapidly are more likely to
contain regressions, inconsistencies, or architectural drift.

Velocity model
--------------
For each ``file_save`` event the tracker increments three counters in
the ``velocity`` table for the row ``(file_path, today)``:

- ``edits``         — number of save events on that day
- ``lines_added``   — cumulative lines added across all saves
- ``lines_removed`` — cumulative lines removed across all saves

Query API
---------
:meth:`VelocityTracker.hot_files`
    Returns the highest-churn files over a configurable window.

:meth:`VelocityTracker.file_trend`
    Returns day-by-day velocity for a single file (useful for sparklines
    in the Layer 3 digest view).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ambient.db.store import Store
from ambient.models import CodeEvent, EventType

logger = logging.getLogger(__name__)


class VelocityTracker:
    """Updates and queries the change velocity table.

    Parameters
    ----------
    store:
        An open :class:`~ambient.db.store.Store` instance.
    """

    def __init__(self, store: Store) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def record(self, event: CodeEvent) -> None:
        """Record velocity from a ``file_save`` event.

        Only ``file_save`` events are processed — ``file_change`` events
        are intentionally ignored to avoid double-counting (every editing
        session that ends in a save produces both a ``file_change`` and a
        subsequent ``file_save``).

        Parameters
        ----------
        event:
            A :class:`~ambient.models.CodeEvent`.  No-op if the event
            type is not ``file_save`` or if metadata is absent.
        """
        if event.event_type is not EventType.FILE_SAVE:
            return

        meta = event.as_file_change_metadata()
        if meta is None:
            logger.debug(
                "file_save event for %s has no FileChangeMetadata — skipping velocity update.",
                event.file_path,
            )
            return

        date_str = _utc_date(event.timestamp)

        try:
            self._store.increment_velocity(
                file_path=event.file_path,
                workspace=event.workspace,
                date=date_str,
                lines_added=meta.lines_added,
                lines_removed=meta.lines_removed,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to update velocity for %s on %s: %s",
                event.file_path,
                date_str,
                exc,
            )

    # ------------------------------------------------------------------
    # Query path
    # ------------------------------------------------------------------

    def hot_files(
        self,
        workspace: str,
        days: int = 7,
        top_n: int = 10,
    ) -> list[dict]:
        """Return the most frequently edited files in the last *days* days.

        Parameters
        ----------
        workspace:
            Workspace name to scope the query.
        days:
            Lookback window in calendar days.
        top_n:
            Maximum number of results.

        Returns
        -------
        list[dict]
            Each dict has keys: ``file_path``, ``total_edits``,
            ``total_lines_added``, ``total_lines_removed``.
        """
        rows = self._store.get_hot_files(workspace=workspace, days=days, top_n=top_n)
        return [dict(row) for row in rows]

    def file_trend(
        self,
        file_path: str,
        days: int = 30,
    ) -> list[dict]:
        """Return daily velocity rows for *file_path* over *days* days.

        Parameters
        ----------
        file_path:
            Absolute path to the file.
        days:
            Lookback window in calendar days.

        Returns
        -------
        list[dict]
            Ordered by date ascending.  Each dict has keys: ``date``,
            ``edits``, ``lines_added``, ``lines_removed``.
        """
        rows = self._store.get_velocity_for_file(file_path=file_path, days=days)
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utc_date(timestamp_ms: int) -> str:
    """Convert a Unix millisecond timestamp to an ISO-8601 date string (UTC)."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    return dt.strftime("%Y-%m-%d")
