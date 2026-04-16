"""
Uncovered-high-churn trigger: fires when a file is being edited heavily
today but no corresponding test file was saved in the same workspace.

A file that churns without its tests changing is a leading indicator of
technical debt accumulating undetected.  The naming heuristic for test
files mirrors common conventions:

- ``test_*.py`` / ``*_test.py``       (Python)
- ``*.test.ts`` / ``*.spec.ts``       (TypeScript)
- ``*.test.js`` / ``*.spec.js``       (JavaScript)
"""

from __future__ import annotations

import logging
import re

from ambient_insight.models import Severity, TriggerName
from ambient_insight.reader import ContextReader
from ambient_insight.triggers.base import Trigger, TriggerResult

logger = logging.getLogger(__name__)

_DEFAULT_MIN_EDITS = 3

_TEST_FILE_PATTERN = re.compile(
    r"(test_[^/\\]+\.py"
    r"|[^/\\]+_test\.py"
    r"|[^/\\]+\.test\.[jt]sx?"
    r"|[^/\\]+\.spec\.[jt]sx?)"
    r"$",
    re.IGNORECASE,
)


def _is_test_file(path: str) -> bool:
    return bool(_TEST_FILE_PATTERN.search(path))


class UncoveredHighChurnTrigger(Trigger):
    """Fires for files with >= *min_edits* saves today and no test saves.

    Parameters
    ----------
    min_edits:
        Minimum saves today before the file is considered "high churn".
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
            saved_paths = reader.get_recent_save_paths(workspace, hours=24)
        except Exception:
            logger.exception("UncoveredHighChurnTrigger: DB query failed")
            return []

        # Check whether any test file was saved in this workspace today
        any_test_saved = any(_is_test_file(p) for p in saved_paths)

        if any_test_saved:
            # At least one test file was touched today — skip all files
            return []

        for row in hot_files:
            file_path = row["file_path"]

            # Don't fire on test files themselves
            if _is_test_file(file_path):
                continue

            results.append(
                TriggerResult(
                    file_path=file_path,
                    workspace=workspace,
                    trigger_name=TriggerName.UNCOVERED_HIGH_CHURN,
                    severity=Severity.WARNING,
                    context_data={
                        "total_edits": row["total_edits"],
                        "any_test_saved": False,
                    },
                )
            )

        return results
