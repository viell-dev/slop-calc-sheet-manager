"""After a stalled callback, clean-up makes no more office calls (#51).

The suites import UNO, so the functions under test are read from their source and run against
fakes, with the real `teardown` module.
"""

import ast
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.integration import teardown
from tests.integration.teardown import (
    Configured,
    close_leftovers,
    record_stalled_callback,
    stalled_callbacks,
    start_session,
)

ROOT = Path(__file__).resolve().parents[2]
SUITES = {
    "reorder": ROOT / "tests" / "integration" / "test_reorder.py",
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
def test_a_failed_restore_after_a_failure_becomes_its_note(suite: str) -> None:
    calls: list[str] = []
    with (
        pytest.raises(AssertionError, match="check failed") as caught,
        undo_capacity(suite)(Context(Access(calls, fail_restore=True)), 2),
    ):
        raise AssertionError("check failed")
    assert "restoring failed" in caught.value.__notes__[0]
