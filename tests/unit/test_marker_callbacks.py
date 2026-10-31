"""The own-move markers' callbacks never raise into LibreOffice's replay, not even from logging.

The markers run inside Calc's Undo and Redo (#91). An exception escaping them would interrupt the
native replay, so their error path, including the error report itself, must swallow everything.
Found by the 0.0.8 release review: a closed stderr made `report` raise out of `_Ends.replayed`.
"""

import ast
import contextlib
import io
import sys
import traceback
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.structure import OwnMove, StructureEvents
from tests.unit.source_methods import ROOT, method

REORDER = "src/sheet_manager/uno_reorder.py"
CALC = "src/sheet_manager/uno_calc.py"


def function(path: str, name: str, namespace: dict[str, Any]) -> Any:
    """A module-level function from source, like `source_methods.method` for a class's."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


def test_report_survives_a_closed_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    report = function(
        CALC, "report", {"sys": sys, "traceback": traceback, "contextlib": contextlib}
    )
    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr(sys, "stderr", closed)
    try:
        raise RuntimeError("probe")
    except RuntimeError:
        report("a probe")  # Must not raise, whatever the stream does.


def test_a_marker_callback_never_raises_even_when_logging_fails() -> None:
    """An own move the protocol trusts, whose view getter fails at the first marker, while the
    error report fails too: nothing escapes, and the move is revoked."""

    def failing_report(where: str) -> None:
        raise ValueError("I/O operation on closed file")

    events = StructureEvents(count=3)
    move = OwnMove(state="done", generation=events.generation, count=3, epoch=events.epoch)
    sample = Mock(side_effect=RuntimeError("a view getter failed"))
    ends = SimpleNamespace(
        move=move,
        _monitor=SimpleNamespace(events=events, count=lambda: 3, document=object()),
        _main=Mock(),
        _sample=sample,
    )
    replayed = method(
        REORDER,
        "_Ends",
        "replayed",
        {"report": failing_report, "RESTORING": "restoring", "contextlib": contextlib},
    )
    replayed(ends, opening=True, redo=False)  # Must not raise into Calc's replay.
    sample.assert_called_once()  # The trusted replay reached the failing getter.
    assert move.state == "revoked"
    assert events.replay is None and events.view_replay is None
    ends._main.post.assert_not_called()


def test_a_marker_callback_never_raises_even_when_the_revocation_fails() -> None:
    """A failure inside the revocation itself neither escapes nor leaves the replay open."""
    events = StructureEvents(count=3)
    move = OwnMove(state="done", generation=events.generation, count=3, epoch=events.epoch)

    class FailingOutcomes(dict[int, bool]):
        """Settling the aborted replay fails, inside the revocation."""

        def __setitem__(self, key: int, value: bool) -> None:
            raise RuntimeError("the settlement failed")

    events.outcomes = FailingOutcomes()
    ends = SimpleNamespace(
        move=move,
        _monitor=SimpleNamespace(events=events, count=lambda: 3, document=object()),
        _main=Mock(),
        _sample=Mock(side_effect=RuntimeError("a view getter failed")),
    )
    replayed = method(
        REORDER,
        "_Ends",
        "replayed",
        {"report": Mock(), "RESTORING": "restoring", "contextlib": contextlib},
    )
    replayed(ends, opening=True, redo=False)  # Must not raise into Calc's replay.
    assert move.state == "revoked"
    assert events.replay is None and events.view_replay is None
