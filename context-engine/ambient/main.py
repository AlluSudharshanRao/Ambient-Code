"""
Ambient Code — Layer 2 context engine entry point.

Run with::

    python -m ambient.main

or, after ``pip install -e .``::

    ambient

Environment variables
---------------------
AMBIENT_LOG_PATH      Path to the NDJSON event log.
                      Default: ~/.ambient-code/events.ndjson

AMBIENT_DB_PATH       Path to the SQLite context database.
                      Default: ~/.ambient-code/context.db

AMBIENT_CURSOR_PATH   Path to the byte-offset cursor file.
                      Default: ~/.ambient-code/cursor

AMBIENT_POLL_MS       Polling interval in milliseconds.
                      Default: 1000

AMBIENT_LOG_LEVEL     Python logging level (DEBUG, INFO, WARNING, ERROR).
                      Default: INFO

AMBIENT_RESET_CURSOR  Set to "1" to reset the cursor and re-process the
                      entire event log on startup.  Useful after a database
                      wipe.  Default: unset.

Lifecycle
---------
The engine runs a tight poll loop until it receives SIGINT or SIGTERM,
at which point it completes any in-flight batch, commits the cursor, and
exits cleanly.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path
from types import FrameType

from ambient.db.store import Store
from ambient.indexer.symbol_index import SymbolIndexer
from ambient.models import CodeEvent, EventType
from ambient.tailer import Tailer, default_cursor_path, default_log_path
from ambient.velocity.tracker import VelocityTracker


# ---------------------------------------------------------------------------
# Logging setup
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
# Engine
# ---------------------------------------------------------------------------


class ContextEngine:
    """Orchestrates the tailer, symbol indexer, and velocity tracker.

    Parameters
    ----------
    log_path:    Path to the NDJSON event log.
    db_path:     Path to the SQLite context database.
    cursor_path: Path to the persistent byte-offset cursor file.
    poll_ms:     Milliseconds to sleep between poll cycles when the log has
                 no new lines.
    """

    def __init__(
        self,
        log_path: str,
        db_path: str,
        cursor_path: str,
        poll_ms: int = 1000,
    ) -> None:
        self._poll_s = poll_ms / 1000

        logger.info("Opening store at %s", db_path)
        self._store = Store(db_path)

        logger.info("Tailing event log at %s (cursor: %s)", log_path, cursor_path)
        self._tailer = Tailer(log_path, cursor_path)

        self._indexer = SymbolIndexer()
        self._velocity = VelocityTracker(self._store)

        self._running = False

        logger.info(
            "Symbol indexer ready — supported languages: %s",
            ", ".join(self._indexer.supported_languages) or "none",
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the poll loop.  Blocks until :meth:`stop` is called."""
        self._running = True
        logger.info("Context engine started (poll interval: %.1fs)", self._poll_s)

        while self._running:
            events = self._tailer.read_new_events()

            if events:
                logger.debug("Processing batch of %d events", len(events))
                self._process_batch(events)
                self._tailer.commit()
            else:
                time.sleep(self._poll_s)

        logger.info("Context engine stopped.")

    def stop(self) -> None:
        """Signal the poll loop to exit after the current batch completes."""
        self._running = False

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def _process_batch(self, events: list[CodeEvent]) -> None:
        """Process a batch of events in order.

        Steps for each event:
        1. Persist the raw event row.
        2. If ``file_save``: run symbol indexer and update velocity.
        3. If ``git_event``: log the action.
        4. All other types: persisted only.
        """
        # Bulk-insert raw events first for durability
        self._store.bulk_insert_events(events)

        for event in events:
            try:
                if event.event_type is EventType.FILE_SAVE:
                    self._handle_file_save(event)
                elif event.event_type is EventType.GIT_EVENT:
                    self._handle_git_event(event)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Unhandled error processing event (type=%s, file=%s): %s",
                    event.event_type.value,
                    event.file_path,
                    exc,
                )

    def _handle_file_save(self, event: CodeEvent) -> None:
        """Run the symbol indexer and velocity tracker for a save event."""
        # Symbol indexing: reads the file from disk
        if Path(event.file_path).exists():
            symbols = self._indexer.index_file(
                file_path=event.file_path,
                workspace=event.workspace,
                language=event.language,
            )
            if symbols:
                self._store.upsert_symbols(event.file_path, symbols)
                logger.debug(
                    "Indexed %d symbol(s) in %s", len(symbols), event.file_path
                )
        else:
            logger.debug("Skipping symbol index — file not on disk: %s", event.file_path)

        # Velocity tracking
        self._velocity.record(event)

    def _handle_git_event(self, event: CodeEvent) -> None:
        """Log git events — no DB writes needed beyond the raw event row."""
        meta = event.as_git_event_metadata()
        if meta:
            logger.info(
                "Git event: action=%s branch=%s workspace=%s",
                meta.action,
                meta.branch,
                event.workspace,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._store.close()
        logger.info("Store closed.")


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def _install_signal_handlers(engine: ContextEngine) -> None:
    def _handler(signum: int, _frame: FrameType | None) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — shutting down...", sig_name)
        engine.stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Parse environment variables, configure logging, and start the engine."""
    _configure_logging(os.environ.get("AMBIENT_LOG_LEVEL", "INFO"))

    log_path = os.environ.get("AMBIENT_LOG_PATH", default_log_path())
    db_path = os.environ.get(
        "AMBIENT_DB_PATH",
        str(Path.home() / ".ambient-code" / "context.db"),
    )
    cursor_path = os.environ.get("AMBIENT_CURSOR_PATH", default_cursor_path())
    poll_ms = int(os.environ.get("AMBIENT_POLL_MS", "1000"))

    engine = ContextEngine(
        log_path=log_path,
        db_path=db_path,
        cursor_path=cursor_path,
        poll_ms=poll_ms,
    )

    if os.environ.get("AMBIENT_RESET_CURSOR") == "1":
        logger.warning("AMBIENT_RESET_CURSOR is set — resetting cursor to 0.")
        engine._tailer.reset()

    _install_signal_handlers(engine)

    try:
        engine.run()
    finally:
        engine.close()


if __name__ == "__main__":
    run()
