"""
Pydantic models for Layer 3 — Insight Engine.

The :class:`Finding` is the output unit of Layer 3.  One Finding is produced
per trigger firing per file.  It is serialised as an NDJSON line and appended
to ``~/.ambient-code/findings.ndjson`` where the Layer 1 VS Code extension
reads and surfaces it.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    """Finding severity levels, ordered from lowest to highest urgency."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class TriggerName(StrEnum):
    """Identifiers for the built-in pattern triggers."""

    HIGH_VELOCITY = "high_velocity"
    LONG_FUNCTION = "long_function"
    UNCOVERED_HIGH_CHURN = "uncovered_high_churn"


class Finding(BaseModel):
    """A single actionable insight produced by the Insight Engine.

    Attributes
    ----------
    id:
        UUID4 string — globally unique across all findings.
    timestamp:
        Unix millisecond timestamp of when the finding was generated.
    workspace:
        Name of the VS Code workspace the affected file belongs to.
    file_path:
        Absolute path to the file that triggered the finding.
    trigger:
        The :class:`TriggerName` that fired (or any string for custom triggers).
    severity:
        :class:`Severity` level used by Layer 1 to decide how loudly to
        surface the finding (info → output channel, warning → toast,
        critical → modal-style error message).
    title:
        Short one-line summary suitable for a VS Code notification toast.
    body:
        Full LLM-generated analysis text (up to 500 tokens).  Displayed in
        the "Ambient Code" output channel and the findings detail view.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: int
    workspace: str
    file_path: str = Field(alias="filePath")
    trigger: str
    severity: Severity
    title: str
    body: str
