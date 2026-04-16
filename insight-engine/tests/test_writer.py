"""
Unit tests for ambient_insight.writer.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ambient_insight.models import Finding, Severity, TriggerName
from ambient_insight.writer import _is_on_cooldown, write_finding

NOW_MS = int(time.time() * 1000)


def _make_finding(**overrides) -> Finding:
    base = dict(
        timestamp=NOW_MS,
        workspace="ws",
        filePath="/src/app.py",
        trigger=TriggerName.HIGH_VELOCITY,
        severity=Severity.WARNING,
        title="Test finding title",
        body="Test finding body text.",
    )
    base.update(overrides)
    return Finding.model_validate(base)


# ---------------------------------------------------------------------------
# write_finding
# ---------------------------------------------------------------------------


class TestWriteFinding:
    def test_creates_file_if_not_exists(self, tmp_path: Path):
        findings_path = str(tmp_path / "out" / "findings.ndjson")
        f = _make_finding()
        result = write_finding(f, findings_path, cooldown_seconds=0)
        assert result is True
        assert Path(findings_path).exists()

    def test_written_line_is_valid_json(self, tmp_path: Path):
        findings_path = str(tmp_path / "findings.ndjson")
        f = _make_finding()
        write_finding(f, findings_path, cooldown_seconds=0)
        line = Path(findings_path).read_text(encoding="utf-8").strip()
        obj = json.loads(line)
        assert obj["title"] == "Test finding title"

    def test_serialises_with_camelcase_alias(self, tmp_path: Path):
        findings_path = str(tmp_path / "findings.ndjson")
        f = _make_finding()
        write_finding(f, findings_path, cooldown_seconds=0)
        line = Path(findings_path).read_text(encoding="utf-8").strip()
        obj = json.loads(line)
        assert "filePath" in obj

    def test_appends_multiple_findings(self, tmp_path: Path):
        findings_path = str(tmp_path / "findings.ndjson")
        write_finding(_make_finding(filePath="/a.py"), findings_path, cooldown_seconds=0)
        write_finding(_make_finding(filePath="/b.py"), findings_path, cooldown_seconds=0)
        lines = Path(findings_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_cooldown_suppresses_duplicate(self, tmp_path: Path):
        findings_path = str(tmp_path / "findings.ndjson")
        f = _make_finding()
        write_finding(f, findings_path, cooldown_seconds=3600)
        # Second call with same (file, trigger) within cooldown → suppressed
        result = write_finding(f, findings_path, cooldown_seconds=3600)
        assert result is False

    def test_cooldown_zero_always_writes(self, tmp_path: Path):
        findings_path = str(tmp_path / "findings.ndjson")
        f = _make_finding()
        r1 = write_finding(f, findings_path, cooldown_seconds=0)
        r2 = write_finding(f, findings_path, cooldown_seconds=0)
        assert r1 is True
        assert r2 is True
        lines = Path(findings_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_different_file_not_suppressed(self, tmp_path: Path):
        findings_path = str(tmp_path / "findings.ndjson")
        write_finding(_make_finding(filePath="/a.py"), findings_path, cooldown_seconds=3600)
        result = write_finding(_make_finding(filePath="/b.py"), findings_path, cooldown_seconds=3600)
        assert result is True

    def test_different_trigger_not_suppressed(self, tmp_path: Path):
        findings_path = str(tmp_path / "findings.ndjson")
        write_finding(
            _make_finding(trigger=TriggerName.HIGH_VELOCITY), findings_path, cooldown_seconds=3600
        )
        result = write_finding(
            _make_finding(trigger=TriggerName.LONG_FUNCTION), findings_path, cooldown_seconds=3600
        )
        assert result is True

    def test_returns_true_on_new_finding(self, tmp_path: Path):
        findings_path = str(tmp_path / "findings.ndjson")
        result = write_finding(_make_finding(), findings_path, cooldown_seconds=3600)
        assert result is True

    def test_parent_dir_created_automatically(self, tmp_path: Path):
        deep_path = str(tmp_path / "a" / "b" / "c" / "findings.ndjson")
        write_finding(_make_finding(), deep_path, cooldown_seconds=0)
        assert Path(deep_path).exists()


# ---------------------------------------------------------------------------
# _is_on_cooldown (unit tests for the helper)
# ---------------------------------------------------------------------------


class TestIsOnCooldown:
    def test_empty_file_returns_false(self, tmp_path: Path):
        p = tmp_path / "findings.ndjson"
        p.write_text("", encoding="utf-8")
        f = _make_finding()
        assert _is_on_cooldown(f, p, 3600) is False

    def test_old_finding_not_on_cooldown(self, tmp_path: Path):
        p = tmp_path / "findings.ndjson"
        old_ts = NOW_MS - (2 * 3600 * 1000)  # 2 hours ago
        old_finding = _make_finding(timestamp=old_ts)
        p.write_text(
            json.dumps(old_finding.model_dump(by_alias=True)) + "\n",
            encoding="utf-8",
        )
        new_finding = _make_finding()
        # 1 hour cooldown → 2-hour-old finding is outside window
        assert _is_on_cooldown(new_finding, p, 3600) is False

    def test_recent_finding_on_cooldown(self, tmp_path: Path):
        p = tmp_path / "findings.ndjson"
        recent_finding = _make_finding()
        p.write_text(
            json.dumps(recent_finding.model_dump(by_alias=True)) + "\n",
            encoding="utf-8",
        )
        assert _is_on_cooldown(recent_finding, p, 3600) is True

    def test_malformed_line_ignored(self, tmp_path: Path):
        p = tmp_path / "findings.ndjson"
        p.write_text("not valid json\n", encoding="utf-8")
        f = _make_finding()
        assert _is_on_cooldown(f, p, 3600) is False
