"""
Ambient Code — Layer 3 Insight Engine entry point.

Run with::

    ambient-insight

or::

    python -m ambient_insight.main

Environment variables
---------------------
OPENAI_API_KEY                  Required.  Your OpenAI API key.
OPENAI_MODEL                    Default: gpt-4o-mini
AMBIENT_DB_PATH                 Default: ~/.ambient-code/context.db
AMBIENT_FINDINGS_PATH           Default: ~/.ambient-code/findings.ndjson
AMBIENT_POLL_MS                 Default: 60000 (1 minute)
AMBIENT_VELOCITY_THRESHOLD      Default: 5   (edits/day before high-velocity trigger)
AMBIENT_FUNCTION_LINE_THRESHOLD Default: 40  (lines before long-function trigger)
AMBIENT_LOG_LEVEL               Default: INFO

Lifecycle
---------
The engine polls the context database on a fixed interval.  On each cycle it
evaluates all triggers, calls OpenAI for each match, and appends findings to
``findings.ndjson``.  SIGINT / SIGTERM complete the current cycle and exit.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path
from types import FrameType

from ambient_insight.llm.client import call_openai
from ambient_insight.llm.prompts import (
    SYSTEM_PROMPT,
    assemble_context,
    build_title,
    build_user_prompt,
)
from ambient_insight.models import Finding
from ambient_insight.reader import ContextReader
from ambient_insight.triggers import (
    HighVelocityTrigger,
    LongFunctionTrigger,
    Trigger,
    UncoveredHighChurnTrigger,
)
from ambient_insight.writer import write_finding

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging(level_name: str = "INFO") -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------


def _default_db_path() -> str:
    return str(Path.home() / ".ambient-code" / "context.db")


def _default_findings_path() -> str:
    return str(Path.home() / ".ambient-code" / "findings.ndjson")


# ---------------------------------------------------------------------------
# InsightEngine
# ---------------------------------------------------------------------------


class InsightEngine:
    """Orchestrates trigger evaluation, LLM calls, and findings writing.

    Parameters
    ----------
    db_path:
        Path to the Layer 2 ``context.db``.
    findings_path:
        Path to the output ``findings.ndjson``.
    poll_ms:
        Milliseconds between poll cycles.
    velocity_threshold:
        Minimum daily saves before :class:`HighVelocityTrigger` fires.
    function_line_threshold:
        Minimum function body lines before :class:`LongFunctionTrigger` fires.
    """

    def __init__(
        self,
        db_path: str,
        findings_path: str,
        poll_ms: int = 60_000,
        velocity_threshold: int = 5,
        function_line_threshold: int = 40,
    ) -> None:
        self._db_path = db_path
        self._findings_path = findings_path
        self._poll_s = poll_ms / 1000
        self._running = False

        self._triggers: list[Trigger] = [
            HighVelocityTrigger(min_edits=velocity_threshold),
            LongFunctionTrigger(min_lines=function_line_threshold),
            UncoveredHighChurnTrigger(min_edits=max(3, velocity_threshold // 2)),
        ]

        logger.info(
            "InsightEngine configured — db=%s findings=%s poll=%.0fs",
            db_path,
            findings_path,
            self._poll_s,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the poll loop.  Blocks until :meth:`stop` is called."""
        self._running = True
        logger.info("Insight engine started.")

        while self._running:
            self._tick()
            if self._running:
                time.sleep(self._poll_s)

        logger.info("Insight engine stopped.")

    def stop(self) -> None:
        """Signal the poll loop to exit after the current tick completes."""
        self._running = False

    # ------------------------------------------------------------------
    # Single poll cycle
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """Run one complete evaluation cycle across all workspaces and triggers."""
        try:
            reader = ContextReader(self._db_path)
        except FileNotFoundError:
            logger.warning(
                "context.db not found at %s — is Layer 2 running?", self._db_path
            )
            return

        try:
            workspaces = reader.get_all_workspaces()
            if not workspaces:
                logger.debug("No workspaces in context.db yet — nothing to evaluate.")
                return

            logger.debug("Evaluating %d workspace(s): %s", len(workspaces), workspaces)

            for workspace in workspaces:
                for trigger in self._triggers:
                    self._evaluate_trigger(trigger, reader, workspace)

        except Exception:
            logger.exception("Unexpected error during insight engine tick")
        finally:
            reader.close()

    def _evaluate_trigger(
        self, trigger: Trigger, reader: ContextReader, workspace: str
    ) -> None:
        """Run one trigger for one workspace and write findings."""
        try:
            results = trigger.evaluate(reader, workspace)
        except Exception:
            logger.exception(
                "Trigger %s raised an exception — skipping",
                type(trigger).__name__,
            )
            return

        for result in results:
            try:
                ctx = assemble_context(result, reader)
                user_prompt = build_user_prompt(ctx)
                title = build_title(result)

                logger.debug(
                    "Calling OpenAI for %s / %s",
                    result.trigger_name,
                    result.file_path,
                )
                body = call_openai(SYSTEM_PROMPT, user_prompt)

                finding = Finding(
                    timestamp=int(time.time() * 1000),
                    workspace=result.workspace,
                    file_path=result.file_path,
                    trigger=result.trigger_name,
                    severity=result.severity,
                    title=title,
                    body=body.strip(),
                )

                written = write_finding(finding, self._findings_path)
                if written:
                    logger.info(
                        "Finding surfaced: [%s] %s", finding.severity.upper(), finding.title
                    )

            except Exception:
                logger.exception(
                    "Failed to generate finding for trigger=%s file=%s",
                    result.trigger_name,
                    result.file_path,
                )

    def close(self) -> None:
        """No persistent state to close beyond the per-tick reader."""


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def _install_signal_handlers(engine: InsightEngine) -> None:
    def _handler(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received %s — shutting down...", signal.Signals(signum).name)
        engine.stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Parse environment variables, configure logging, and start the engine."""
    _configure_logging(os.environ.get("AMBIENT_LOG_LEVEL", "INFO"))

    db_path = os.environ.get("AMBIENT_DB_PATH", _default_db_path())
    findings_path = os.environ.get("AMBIENT_FINDINGS_PATH", _default_findings_path())
    poll_ms = int(os.environ.get("AMBIENT_POLL_MS", "60000"))
    velocity_threshold = int(os.environ.get("AMBIENT_VELOCITY_THRESHOLD", "5"))
    function_line_threshold = int(os.environ.get("AMBIENT_FUNCTION_LINE_THRESHOLD", "40"))

    engine = InsightEngine(
        db_path=db_path,
        findings_path=findings_path,
        poll_ms=poll_ms,
        velocity_threshold=velocity_threshold,
        function_line_threshold=function_line_threshold,
    )

    _install_signal_handlers(engine)

    try:
        engine.run()
    finally:
        engine.close()


if __name__ == "__main__":
    run()
