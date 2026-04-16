"""
Context assembly and prompt templates for the Insight Engine.

Each trigger type has a dedicated context assembler and user-prompt builder.
The system prompt is shared across all triggers.
"""

from __future__ import annotations

import os

from ambient_insight.models import TriggerName
from ambient_insight.reader import ContextReader
from ambient_insight.triggers.base import TriggerResult

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert senior software engineer performing a continuous ambient
code review.  You have been given structured context about a file that has
triggered a pattern of concern.

Your job is to produce a SHORT, ACTIONABLE finding — like a helpful colleague
dropping by to share a specific observation.

Rules:
- Be concise: 3-6 sentences maximum.
- Be specific: reference function names, line numbers, or patterns from the context.
- Be constructive: suggest one concrete improvement, not a lecture.
- Never make up code that isn't in the context.
- Do not repeat the trigger title in your response — the caller adds that.
- Respond in plain text only (no markdown headings, no bullet lists).
"""

# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def assemble_context(result: TriggerResult, reader: ContextReader) -> dict:
    """Build a structured context dict for a trigger result.

    Fetches additional data from the DB (symbols, recent events) and merges
    it with the trigger's own ``context_data``.

    Parameters
    ----------
    result:
        The :class:`~ambient_insight.triggers.base.TriggerResult` to enrich.
    reader:
        Open read-only connection to ``context.db``.
    """
    symbols = reader.get_symbols_for_file(result.file_path)
    recent_events = reader.get_recent_events_for_file(result.file_path, hours=24, limit=10)

    # Keep only the most informative diff snippets to stay under token limits
    diffs = [
        e["diff"]
        for e in recent_events
        if e.get("diff") and e["type"] in ("file_save", "file_change")
    ][:3]

    file_name = os.path.basename(result.file_path)

    return {
        "file_name": file_name,
        "file_path": result.file_path,
        "workspace": result.workspace,
        "trigger": result.trigger_name,
        "severity": result.severity,
        "trigger_context": result.context_data,
        "symbols": [
            {
                "name": s["name"],
                "kind": s["kind"],
                "start_line": s["start_line"],
                "end_line": s["end_line"],
                "signature": s["signature"],
            }
            for s in symbols
        ],
        "recent_diffs": diffs,
    }


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_user_prompt(ctx: dict) -> str:
    """Render a user-turn prompt from an assembled context dict."""
    trigger = ctx["trigger"]

    if trigger == TriggerName.HIGH_VELOCITY:
        return _prompt_high_velocity(ctx)
    if trigger == TriggerName.LONG_FUNCTION:
        return _prompt_long_function(ctx)
    if trigger == TriggerName.UNCOVERED_HIGH_CHURN:
        return _prompt_uncovered_churn(ctx)

    # Generic fallback for custom triggers
    return _prompt_generic(ctx)


def _prompt_high_velocity(ctx: dict) -> str:
    tc = ctx["trigger_context"]
    symbols_summary = _format_symbols(ctx["symbols"])
    diffs_summary = _format_diffs(ctx["recent_diffs"])

    return f"""\
File: {ctx['file_path']}
Workspace: {ctx['workspace']}

This file has been saved {tc['total_edits']} times today \
(+{tc['total_lines_added']} / -{tc['total_lines_removed']} lines net).

Current symbols in this file:
{symbols_summary}

Most recent changes (unified diff snippets):
{diffs_summary}

Based on this activity, what specific concern would you raise about this file?
What is the one most important thing the developer should know or do?
"""


def _prompt_long_function(ctx: dict) -> str:
    tc = ctx["trigger_context"]
    symbols_summary = _format_symbols(ctx["symbols"])

    return f"""\
File: {ctx['file_path']}
Workspace: {ctx['workspace']}

A function in this file has grown large:
  Name:       {tc['function_name']}
  Kind:       {tc['kind']}
  Signature:  {tc['signature']}
  Lines:      {tc['start_line']}–{tc['end_line']} ({tc['line_count']} lines)

All symbols currently in this file:
{symbols_summary}

What specific refactoring would you suggest for `{tc['function_name']}`?
"""


def _prompt_uncovered_churn(ctx: dict) -> str:
    tc = ctx["trigger_context"]
    symbols_summary = _format_symbols(ctx["symbols"])
    diffs_summary = _format_diffs(ctx["recent_diffs"])

    return f"""\
File: {ctx['file_path']}
Workspace: {ctx['workspace']}

This file has been saved {tc['total_edits']} times today, \
but no test file was saved anywhere in this workspace.

Current symbols in this file:
{symbols_summary}

Most recent changes:
{diffs_summary}

Which specific function or behaviour change most needs a test written for it?
"""


def _prompt_generic(ctx: dict) -> str:
    symbols_summary = _format_symbols(ctx["symbols"])
    return f"""\
File: {ctx['file_path']}
Workspace: {ctx['workspace']}
Trigger: {ctx['trigger']}
Context: {ctx['trigger_context']}

Symbols in this file:
{symbols_summary}

What is the most important observation you can make about this file right now?
"""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_symbols(symbols: list[dict]) -> str:
    if not symbols:
        return "  (no symbols indexed for this file)"
    lines = []
    for s in symbols[:15]:  # cap at 15 to avoid token bloat
        lines.append(
            f"  [{s['kind']:10}] line {s['start_line']:>4}  {s['signature'] or s['name']}"
        )
    if len(symbols) > 15:
        lines.append(f"  ... and {len(symbols) - 15} more")
    return "\n".join(lines)


def _format_diffs(diffs: list[str]) -> str:
    if not diffs:
        return "  (no recent diffs available)"
    combined = []
    for i, diff in enumerate(diffs, 1):
        # Truncate individual diffs to 30 lines each
        trimmed = "\n".join(diff.splitlines()[:30])
        combined.append(f"  --- diff {i} ---\n{trimmed}")
    return "\n".join(combined)


# ---------------------------------------------------------------------------
# Title generator
# ---------------------------------------------------------------------------


def build_title(result: TriggerResult) -> str:
    """Generate a short notification title for a trigger result."""
    file_name = os.path.basename(result.file_path)
    tc = result.context_data

    if result.trigger_name == TriggerName.HIGH_VELOCITY:
        return f"{file_name} saved {tc.get('total_edits', '?')}x today — review recommended"
    if result.trigger_name == TriggerName.LONG_FUNCTION:
        fn = tc.get("function_name", "a function")
        lc = tc.get("line_count", "?")
        return f"{file_name}: `{fn}` is {lc} lines — consider refactoring"
    if result.trigger_name == TriggerName.UNCOVERED_HIGH_CHURN:
        return f"{file_name} is churning without test coverage"
    return f"Ambient Code finding in {file_name}"
