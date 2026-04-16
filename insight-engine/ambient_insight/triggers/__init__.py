"""
Pattern triggers for the Ambient Code Insight Engine.

Each trigger is a subclass of :class:`~ambient_insight.triggers.base.Trigger`
that queries the Layer 2 context database and returns a list of
:class:`~ambient_insight.triggers.base.TriggerResult` objects — one per
file/symbol that matched the pattern.

Built-in triggers
-----------------
HighVelocityTrigger        File edited >= N times today.
LongFunctionTrigger        Function / method body spans >= N lines.
UncoveredHighChurnTrigger  File edited >= N times today with no test saves.
"""

from ambient_insight.triggers.base import Trigger, TriggerResult
from ambient_insight.triggers.long_function import LongFunctionTrigger
from ambient_insight.triggers.uncovered import UncoveredHighChurnTrigger
from ambient_insight.triggers.velocity import HighVelocityTrigger

__all__ = [
    "Trigger",
    "TriggerResult",
    "HighVelocityTrigger",
    "LongFunctionTrigger",
    "UncoveredHighChurnTrigger",
]
