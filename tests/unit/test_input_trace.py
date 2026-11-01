"""Diagnostic retention is bounded and cannot hide the input assertion it describes."""

import json
from pathlib import Path

import pytest

from tests.integration import input_trace


def test_failed_input_keeps_recent_events_without_unbounded_history(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    input_trace.configure(path)
    for number in range(1_000):
        input_trace.record("selection", 1, picked=[f"Sheet {number}"])
    failure = AssertionError("expected independent picks")
    input_trace.retain(failure)
    result = json.loads(path.read_text("utf-8"))
    assert result["failure"] == str(failure)
    assert 0 < len(result["events"]) < 1_000
    assert result["events"][-1]["picked"] == ["Sheet 999"]


def test_unwritable_diagnostics_preserve_the_original_assertion(tmp_path: Path) -> None:
    input_trace.configure(tmp_path / "missing" / "input.json")
    failure = AssertionError("the initial pick failed")
    input_trace.retain(failure)
    with pytest.raises(AssertionError, match="the initial pick failed") as raised:
        raise failure
    assert raised.value is failure
    assert "Retaining input observations also failed" in failure.__notes__[0]
