"""
High-velocity trigger: fires when a file has been saved >= N times today.

High edit frequency on a single file in one day is a leading indicator of
confusion, rework, or an area that deserves a code-quality review.
"""

from __future__ import annotations

import logging

from ambient_insight.models import Severity, TriggerName
from ambient_insight.reader import ContextReader
from ambient_insight.triggers.base import Trigger, TriggerResult

logger = logging.getLogger(__name__)

_DEFAULT_MIN_EDITS = 5


class HighVelocityTrigger(Trigger):
    """Fires for every file with >= *min_edits* saves today.

    Parameters
    ----------
    min_edits:
        Minimum number of ``file_save`` events recorded today before the
        trigger fires.  Defaults to ``AMBIENT_VELOCITY_THRESHOLD`` env var
        or 5.
    """

    def __init__(self, min_edits: int = _DEFAULT_MIN_EDITS) -> None:
        self._min_edits = min_edits

    def evaluate(self, reader: ContextReader, workspace: str) -> list[TriggerResult]:
        results: list[TriggerResult] = []

        try:
            hot_files = reader.get_hot_files(
                workspace=workspace,
                days=1,
                min_edits=self._min_edits,
            )
        except Exception:
            logger.exception("HighVelocityTrigger: DB query failed")
            return []

        for row in hot_files:
            file_path = row["file_path"]
            total_edits = row["total_edits"]

            severity = (
                Severity.CRITICAL if total_edits >= 10
                else Severity.WARNING if total_edits >= 7
                else Severity.INFO
            )

            results.append(
                TriggerResult(
                    file_path=file_path,
                    workspace=workspace,
                    trigger_name=TriggerName.HIGH_VELOCITY,
                    severity=severity,
                    context_data={
                        "total_edits": total_edits,
                        "total_lines_added": row["total_lines_added"],
                        "total_lines_removed": row["total_lines_removed"],
                    },
                )
            )

        return results
