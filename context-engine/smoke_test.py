"""
End-to-end smoke test for the Ambient Code context engine.

Creates a temporary NDJSON log with synthetic events, runs the full
pipeline (tailer → store → indexer → velocity), and asserts that the
expected symbols and velocity rows appear in the database.

Run with:  python smoke_test.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

print("Running Layer 2 smoke test...")


def _fail(msg: str) -> None:
    print(f"  FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"  OK:   {msg}")


# ---------------------------------------------------------------------------
# Write a real Python source file and a synthetic NDJSON event log
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    # --- Source file to index ---
    py_src = Path(tmp) / "auth.py"
    py_src.write_text(
        "def login(username, password):\n"
        "    return True\n"
        "\n"
        "class UserService:\n"
        "    def get_user(self, uid):\n"
        "        return uid\n",
        encoding="utf-8",
    )

    # --- NDJSON event log ---
    events_path = Path(tmp) / "events.ndjson"
    cursor_path = Path(tmp) / "cursor"
    db_path = Path(tmp) / "context.db"

    now_ms = int(time.time() * 1000)

    events = [
        {
            "timestamp": now_ms,
            "type": "file_save",
            "workspace": "test-ws",
            "filePath": str(py_src),
            "language": "python",
            "diff": "--- auth.py\n+++ auth.py\n@@ -0,0 +1,6 @@\n+def login...",
            "metadata": {"isPaste": False, "linesAdded": 6, "linesRemoved": 0},
        },
        {
            "timestamp": now_ms + 1000,
            "type": "cursor_move",
            "workspace": "test-ws",
            "filePath": str(py_src),
            "language": "python",
            "metadata": {"line": 0, "character": 0},
        },
        {
            "timestamp": now_ms + 2000,
            "type": "git_event",
            "workspace": "test-ws",
            "filePath": str(tmp),
            "language": "",
            "metadata": {
                "action": "branch_change",
                "branch": "feature/x",
                "previousBranch": "main",
            },
        },
    ]

    with events_path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")

    # ---------------------------------------------------------------------------
    # Run ContextEngine for one cycle
    # ---------------------------------------------------------------------------

    from ambient.main import ContextEngine

    engine = ContextEngine(
        log_path=str(events_path),
        db_path=str(db_path),
        cursor_path=str(cursor_path),
        poll_ms=100,
    )

    batch = engine._tailer.read_new_events()
    if not batch:
        _fail("Tailer returned no events — NDJSON parsing failed.")

    if len(batch) != 3:
        _fail(f"Expected 3 events, got {len(batch)}")
    _ok(f"Tailer read {len(batch)} events")

    engine._process_batch(batch)
    engine._tailer.commit()
    _ok("Batch processed and cursor committed")

    # ---------------------------------------------------------------------------
    # Assert DB state
    # ---------------------------------------------------------------------------

    # Raw events table
    rows = engine._store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    if rows != 3:
        _fail(f"Expected 3 rows in events table, got {rows}")
    _ok(f"events table: {rows} rows")

    # Symbols table — Python indexer should have extracted login, UserService, get_user
    sym_rows = engine._store._conn.execute(
        "SELECT name, kind FROM symbols ORDER BY start_line"
    ).fetchall()
    sym_names = {r["name"] for r in sym_rows}
    expected = {"login", "UserService", "get_user"}
    missing = expected - sym_names
    if missing:
        _fail(f"Missing symbols: {missing}. Got: {sym_names}")
    _ok(f"symbols table: {[dict(r) for r in sym_rows]}")

    # Velocity table
    vel_rows = engine._store._conn.execute("SELECT * FROM velocity").fetchall()
    if not vel_rows:
        _fail("velocity table is empty — VelocityTracker did not record.")
    vr = dict(vel_rows[0])
    if vr["edits"] != 1:
        _fail(f"Expected edits=1, got {vr['edits']}")
    if vr["lines_added"] != 6:
        _fail(f"Expected lines_added=6, got {vr['lines_added']}")
    _ok(f"velocity table: {vr}")

    # Cursor advanced
    committed_offset = int(cursor_path.read_text())
    if committed_offset == 0:
        _fail("Cursor was not advanced after commit.")
    _ok(f"Cursor committed at byte offset {committed_offset}")

    engine.close()

print("\nAll checks passed.")
