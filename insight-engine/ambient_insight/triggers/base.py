"""
Abstract base for all pattern triggers.

A trigger encapsulates one detection rule.  It queries the read-only
:class:`~ambient_insight.reader.ContextReader` and returns zero or more
:class:`TriggerResult` objects that the :class:`~ambient_insight.main.InsightEngine`
passes to the LLM pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ambient_insight.models import Severity
from ambient_insight.reader import ContextReader


@dataclass
class TriggerResult:
    """Data produced by a trigger firing on a single file or symbol.

    Attributes
    ----------
    file_path:
        Absolute path to the affected file.
    workspace:
        VS Code workspace the file belongs to.
    trigger_name:
        The :class:`~ambient_insight.models.TriggerName` (or custom string)
        that produced this result.
    severity:
        How urgently the finding should be surfaced.
    context_data:
        Structured data assembled by the trigger for use in prompt building.
        Keys are trigger-specific (e.g. ``total_edits``, ``function_name``).
    """

    file_path: str
    workspace: str
    trigger_name: str
    severity: Severity
    context_data: dict = field(default_factory=dict)


class Trigger(ABC):
    """Abstract base for all pattern triggers.

    Subclasses implement :meth:`evaluate` which is called once per
    InsightEngine poll cycle for every active workspace.
    """

    @abstractmethod
    def evaluate(self, reader: ContextReader, workspace: str) -> list[TriggerResult]:
        """Query *reader* and return matching results for *workspace*.

        Returns an empty list when nothing matches — never raises.

        Parameters
        ----------
        reader:
            Open, read-only connection to ``context.db``.
        workspace:
            The workspace name to scope queries to.
        """
