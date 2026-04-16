"""
Long-function trigger: fires when any function or method in a recently-saved
file spans >= N lines.

Long functions are a proven proxy for high cyclomatic complexity.  When a
developer saves a file and one of its functions has grown beyond the threshold,
it is a good moment for the LLM to suggest decomposition.
"""

from __future__ import annotations

import logging

from ambient_insight.models import Severity, TriggerName
from ambient_insight.reader import ContextReader
from ambient_insight.triggers.base import Trigger, TriggerResult

logger = logging.getLogger(__name__)

_DEFAULT_MIN_LINES = 40


class LongFunctionTrigger(Trigger):
    """Fires for every function / method >= *min_lines* lines in a recently-saved file.

    Only files that were saved today are considered; the trigger does not
    re-fire on stale files that haven't changed.

    Parameters
    ----------
    min_lines:
        Body-line threshold (``end_line - start_line``).  Defaults to
        ``AMBIENT_FUNCTION_LINE_THRESHOLD`` env var or 40.
    """

    def __init__(self, min_lines: int = _DEFAULT_MIN_LINES) -> None:
        self._min_lines = min_lines

    def evaluate(self, reader: ContextReader, workspace: str) -> list[TriggerResult]:
        results: list[TriggerResult] = []

        try:
            # Only consider files that were actually saved today
            saved_today = set(reader.get_recent_save_paths(workspace, hours=24))
            long_syms = reader.get_long_functions(workspace, min_lines=self._min_lines)
        except Exception:
            logger.exception("LongFunctionTrigger: DB query failed")
            return []

        # Deduplicate by (file_path): emit at most one result per file,
        # carrying the longest function found in that file.
        seen_files: dict[str, TriggerResult] = {}

        for sym in long_syms:
            file_path = sym["file_path"]
            if file_path not in saved_today:
                continue

            line_count = sym["line_count"]
            severity = (
                Severity.CRITICAL if line_count >= 80
                else Severity.WARNING if line_count >= 60
                else Severity.INFO
            )

            existing = seen_files.get(file_path)
            if existing is None or line_count > existing.context_data["line_count"]:
                seen_files[file_path] = TriggerResult(
                    file_path=file_path,
                    workspace=workspace,
                    trigger_name=TriggerName.LONG_FUNCTION,
                    severity=severity,
                    context_data={
                        "function_name": sym["name"],
                        "kind": sym["kind"],
                        "start_line": sym["start_line"],
                        "end_line": sym["end_line"],
                        "line_count": line_count,
                        "signature": sym["signature"],
                    },
                )

        results.extend(seen_files.values())
        return results
