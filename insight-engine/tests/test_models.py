"""
Unit tests for ambient_insight.models.
"""

from __future__ import annotations

import time
import uuid

import pytest
from pydantic import ValidationError

from ambient_insight.models import Finding, Severity, TriggerName

NOW_MS = int(time.time() * 1000)


def _valid_finding(**overrides) -> dict:
    """Return a minimal valid Finding dict (using camelCase alias)."""
    base = {
        "timestamp": NOW_MS,
        "workspace": "my-project",
        "filePath": "/src/app.py",
        "trigger": TriggerName.HIGH_VELOCITY,
        "severity": Severity.WARNING,
        "title": "app.py saved 7x today — review recommended",
        "body": "This file is being edited frequently. Consider reviewing.",
    }
    base.update(overrides)
    return base


class TestFindingCreation:
    def test_valid_finding_parses(self):
        f = Finding.model_validate(_valid_finding())
        assert f.file_path == "/src/app.py"
        assert f.workspace == "my-project"

    def test_id_auto_generated(self):
        f = Finding.model_validate(_valid_finding())
        assert f.id != ""
        uuid.UUID(f.id)  # must be valid UUID4

    def test_explicit_id_accepted(self):
        custom_id = str(uuid.uuid4())
        f = Finding.model_validate(_valid_finding(id=custom_id))
        assert f.id == custom_id

    def test_camelcase_file_path_alias(self):
        f = Finding.model_validate(_valid_finding())
        assert f.file_path == "/src/app.py"

    def test_snake_case_file_path_accepted(self):
        data = {k: v for k, v in _valid_finding().items() if k != "filePath"}
        data["file_path"] = "/src/utils.py"
        f = Finding.model_validate(data)
        assert f.file_path == "/src/utils.py"

    def test_serialises_with_file_path_alias(self):
        f = Finding.model_validate(_valid_finding())
        dumped = f.model_dump(by_alias=True)
        assert "filePath" in dumped
        assert "file_path" not in dumped

    def test_missing_required_field_raises(self):
        data = _valid_finding()
        del data["workspace"]
        with pytest.raises(ValidationError):
            Finding.model_validate(data)


class TestSeverityEnum:
    def test_info_value(self):
        assert Severity.INFO == "info"

    def test_warning_value(self):
        assert Severity.WARNING == "warning"

    def test_critical_value(self):
        assert Severity.CRITICAL == "critical"

    def test_invalid_severity_raises(self):
        with pytest.raises(ValidationError):
            Finding.model_validate(_valid_finding(severity="fatal"))

    def test_severity_is_string(self):
        assert isinstance(Severity.WARNING, str)


class TestTriggerNameEnum:
    def test_high_velocity_value(self):
        assert TriggerName.HIGH_VELOCITY == "high_velocity"

    def test_long_function_value(self):
        assert TriggerName.LONG_FUNCTION == "long_function"

    def test_uncovered_value(self):
        assert TriggerName.UNCOVERED_HIGH_CHURN == "uncovered_high_churn"

    def test_trigger_accepts_string(self):
        """trigger field is plain str — custom trigger names are allowed."""
        f = Finding.model_validate(_valid_finding(trigger="my_custom_trigger"))
        assert f.trigger == "my_custom_trigger"


class TestFindingRoundTrip:
    def test_json_round_trip(self):
        f = Finding.model_validate(_valid_finding())
        json_str = f.model_dump_json(by_alias=True)
        f2 = Finding.model_validate_json(json_str)
        assert f2.id == f.id
        assert f2.file_path == f.file_path
        assert f2.severity == f.severity

    def test_dict_round_trip_snake(self):
        f = Finding.model_validate(_valid_finding())
        d = f.model_dump()
        f2 = Finding.model_validate(d)
        assert f2.title == f.title
