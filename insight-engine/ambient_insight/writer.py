"""
Findings NDJSON writer with cooldown.

Appends :class:`~ambient_insight.models.Finding` objects to
``~/.ambient-code/findings.ndjson`` as newline-delimited JSON.

Cooldown logic
--------------
Before writing, the writer scans the **tail** of the existing findings file
(last 200 lines) and checks whether a finding with the same
``(file_path, trigger)`` pair already exists within the last
``cooldown_seconds`` seconds.  If it does, the new finding is silently
dropped.  This prevents notification spam when the poll loop re-evaluates
the same pattern on every cycle.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from ambient_insight.models import Finding

logger = logging.getLogger(__name__)

_DEFAULT_COOLDOWN_S = 3600  # 1 hour
_TAIL_LINES = 200


def write_finding(
    finding: Finding,
    findings_path: str,
    cooldown_seconds: int = _DEFAULT_COOLDOWN_S,
) -> bool:
    """Append *finding* to the NDJSON findings log if the cooldown has elapsed.

    Parameters
    ----------
    finding:
        The :class:`~ambient_insight.models.Finding` to persist.
    findings_path:
        Absolute path to ``findings.ndjson``.  The parent directory is
        created automatically if it does not exist.
    cooldown_seconds:
        Minimum seconds between two findings for the same
        ``(file_path, trigger)`` pair.  Defaults to 3600 (1 hour).

    Returns
    -------
    bool
        ``True`` if the finding was written, ``False`` if suppressed by the
        cooldown.
    """
    path = Path(findings_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # --- Cooldown check ---
    if path.exists() and _is_on_cooldown(finding, path, cooldown_seconds):
        logger.debug(
            "Cooldown active for (%s, %s) — skipping finding",
            os.path.basename(finding.file_path),
            finding.trigger,
        )
        return False

    # --- Append finding ---
    line = (
        json.dumps(finding.model_dump(by_alias=True), default=str) + "\n"
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)

    logger.info(
        "Finding written: trigger=%s file=%s severity=%s",
        finding.trigger,
        os.path.basename(finding.file_path),
        finding.severity,
    )
    return True


def _is_on_cooldown(
    finding: Finding,
    path: Path,
    cooldown_seconds: int,
) -> bool:
    """Return True if a recent matching finding exists within the cooldown window."""
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - cooldown_seconds * 1000

    try:
        tail_lines = _read_tail(path, _TAIL_LINES)
    except OSError:
        return False

    for line in reversed(tail_lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Use alias 'filePath' since we serialise with by_alias=True
        same_file = obj.get("filePath") == finding.file_path
        same_trigger = obj.get("trigger") == finding.trigger
        recent = obj.get("timestamp", 0) >= cutoff_ms

        if same_file and same_trigger and recent:
            return True

    return False


def _read_tail(path: Path, n: int) -> list[str]:
    """Read the last *n* lines of *path* efficiently."""
    with path.open("rb") as fh:
        # Seek backwards to find the last n newlines
        try:
            fh.seek(0, 2)
            size = fh.tell()
            chunk_size = min(size, 8192)
            lines: list[bytes] = []
            pos = size

            while len(lines) < n + 1 and pos > 0:
                pos = max(0, pos - chunk_size)
                fh.seek(pos)
                chunk = fh.read(min(chunk_size, size - pos))
                lines = chunk.split(b"\n") + lines[1:] if lines else chunk.split(b"\n")

            return [ln.decode("utf-8", errors="replace") for ln in lines[-n:]]
        except OSError:
            return []
