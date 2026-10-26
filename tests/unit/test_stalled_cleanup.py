"""After a stalled callback, clean-up makes no more office calls (#51, #52).

The suites and the UI runner import UNO, so the functions under test are read from their source
and run against fakes, with the real `teardown` module.
"""

import ast
import json
import time
import traceback
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.integration import teardown
from tests.integration.teardown import (
    Configured,
    close_leftovers,
    record_stalled_callback,
    run_checks,
    stalled_callbacks,
    start_session,
)

ROOT = Path(__file__).resolve().parents[2]
SUITES = {
    "reorder": ROOT / "tests" / "integration" / "test_reorder.py",
    "sheet_list": ROOT / "tests" / "integration" / "test_sheet_list.py",
}


def load(path: Path, name: str, namespace: dict[str, Any]) -> Any:
    """Compile one top-level function from `path` into `namespace` and return it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.fixture(autouse=True)
def fresh_session() -> Iterator[None]:
    start_session()
    yield
    start_session()


class Access:
    """A configuration access that records every call, as a UNO request would arrive."""

    def __init__(self, calls: list[str], fail_restore: bool = False) -> None:
        self.calls, self.fail_restore = calls, fail_restore

    def getPropertyValue(self, name: str) -> int:
        return 100

    def setPropertyValue(self, name: str, value: int) -> None:
        if teardown.stalled_callbacks():
            self.calls.append(f"after the stall: set {value}")
        if self.fail_restore and value == 100:
            raise RuntimeError("restoring failed")
        self.calls.append(f"set {value}")

    def commitChanges(self) -> None:
        self.calls.append("commit" if not stalled_callbacks() else "after the stall: commit")

    def dispose(self) -> None:
        self.calls.append("dispose" if not stalled_callbacks() else "after the stall: dispose")


class Context:
    """A component context whose service manager hands out one configuration access."""

    def __init__(self, access: Access) -> None:
        self.access = access
        self.ServiceManager = self

    def createInstanceWithContext(self, service: str, context: object) -> "Context":
        return self  # Stands in for the configuration provider too.

    def createInstanceWithArguments(self, service: str, arguments: object) -> Access:
        return self.access


class Value:
    Name: object = None
    Value: object = None


def prop(name: str, value: object) -> tuple[str, object]:
    return name, value


def undo_capacity(suite: str) -> Callable[[Any, int], Configured]:
    namespace: dict[str, Any] = {"Configured": Configured, "prop": prop, "PropertyValue": Value}
    return load(SUITES[suite], "undo_capacity", namespace)


def stalling_close(document: str) -> None:
    record_stalled_callback(f"{document} did not close")
    raise TimeoutError(f"{document} did not close")


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_undo_limit_is_restored_in_a_normal_block(suite: str) -> None:
    calls: list[str] = []
    with undo_capacity(suite)(Context(Access(calls)), 2):
        calls.append("block")
    assert calls == ["set 2", "commit", "block", "set 100", "commit", "dispose"]


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_no_restoration_after_a_close_times_out_in_the_block(suite: str) -> None:
    # The reorder suite's assert_scenarios under undo_capacity, closing through close_after.
    calls: list[str] = []
    with (
        pytest.raises(TimeoutError, match="did not close"),
        undo_capacity(suite)(Context(Access(calls)), 2),
    ):
        close_leftovers(["workbook"], stalling_close, None)
    assert calls == ["set 2", "commit"], "No office call may follow the stall"


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_an_earlier_failure_survives_a_close_timeout_in_the_block(suite: str) -> None:
    calls: list[str] = []
    with (
        pytest.raises(AssertionError, match="check failed") as caught,
        undo_capacity(suite)(Context(Access(calls)), 2),
    ):
        try:
            raise AssertionError("check failed")
        except BaseException as failure:
            close_leftovers(["workbook"], stalling_close, failure)
            raise
    assert calls == ["set 2", "commit"]
    assert any("stopped running callbacks" in note for note in caught.value.__notes__)


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_a_close_timeout_under_the_undo_limit_inside_run_checks_stops_the_suite(
    suite: str,
) -> None:
    # The sheet list suite's check_show: partial_failure under undo_capacity, inside run_checks.
    calls: list[str] = []
    ran: list[str] = []

    def check_show() -> object:
        with undo_capacity(suite)(Context(Access(calls)), 2):
            close_leftovers(["workbook"], stalling_close, None)
        return True

    checks = [("show", check_show), ("later", lambda: ran.append("later"))]
    with pytest.raises(TimeoutError, match="did not close"):
        run_checks(checks, ["left open"], lambda _: calls.append("leftover closed"))
    assert calls == ["set 2", "commit"] and ran == []


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_a_failed_restore_after_a_failure_becomes_its_note(suite: str) -> None:
    calls: list[str] = []
    with (
        pytest.raises(AssertionError, match="check failed") as caught,
        undo_capacity(suite)(Context(Access(calls, fail_restore=True)), 2),
    ):
        raise AssertionError("check failed")
    assert "restoring failed" in caught.value.__notes__[0]


class Lab:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.input = self

    def screenshot(self, name: str) -> None:
        self.calls.append(f"screenshot {name}")

    def tap(self, key: str, pause: float = 0) -> None:
        pass  # Real input reaches the display, not the office.


def ui_run_checks(calls: list[str], stall_at: str | None, fail_at: str | None = None) -> Any:
    """The UI runner's real check loop, with every check and workbook call faked."""
    path = ROOT / "tests" / "ui" / "run_ui.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "run_checks"
    )
    checks = sorted(
        {
            node.id
            for node in ast.walk(function)
            if isinstance(node, ast.Name) and node.id.startswith("check_")
        }
    )

    def fake(name: str) -> Callable[..., object]:
        def check(*_: object, **__: object) -> object:
            calls.append(name)
            if name == stall_at:
                record_stalled_callback("work on LibreOffice's main thread did not finish")
                raise AssertionError("The work on LibreOffice's main thread did not finish")
            if name == fail_at:
                raise AssertionError("an ordinary failure")
            return "evidence"

        return check

    class Workbook:
        def __init__(self, *_: object) -> None:
            pass

        def close(self) -> None:
            calls.append("close")

    def reset(book: object) -> None:
        calls.append("reset")

    namespace: dict[str, Any] = {name: fake(name) for name in checks}
    namespace.update(
        Workbook=Workbook,
        NAMES=[],
        reset=reset,
        time=time,
        json=json,
        traceback=traceback,
        stalled_callbacks=stalled_callbacks,
    )
    return load(path, "run_checks", namespace), checks


def test_ui_checks_continue_after_an_ordinary_failure(tmp_path: Path) -> None:
    calls: list[str] = []
    run, _ = ui_run_checks(calls, None, fail_at="check_click_activates")
    results = run(Lab(calls), tmp_path)
    assert calls[-1] == "close" and calls.count("reset") == len(results) > 1
    assert [result["pass"] for result in results.values()].count(False) == 1


@pytest.mark.parametrize("position", ["first", "check_picks_dropped_when_sheets_change"])
def test_ui_checks_stop_at_a_stall_without_more_office_calls(tmp_path: Path, position: str) -> None:
    calls: list[str] = []
    probe: list[str] = []
    run, _ = ui_run_checks(probe, None)
    order = [name for name in run(Lab(probe), tmp_path)]
    stalled_name = order[0] if position == "first" else "picks_dropped_when_sheets_change"
    # Several UI cases may share a parameterized check function, so their names need not
    # match that function. The first actual check call follows the first reset.
    stalled_check = (
        probe[probe.index("reset") + 1]
        if position == "first"
        else next(call for call in probe if call.endswith(stalled_name))
    )
    run, _ = ui_run_checks(calls, stalled_check)
    with pytest.raises(TimeoutError, match="main thread did not finish"):
        run(Lab(calls), tmp_path)
    assert calls[-2:] == [stalled_check, f"screenshot failed-{stalled_name}"]
    assert "close" not in calls, "The workbook must not be closed on a stuck office"
    assert calls.count("reset") == order.index(stalled_name) + 1
    saved = json.loads((tmp_path / "checks.json").read_text(encoding="utf-8"))
    assert list(saved)[-1] == stalled_name and saved[stalled_name]["pass"] is False
