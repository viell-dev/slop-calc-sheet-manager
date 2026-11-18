"""A close posted to LibreOffice's main thread starts only if no stall was recorded first (#261).

`tests/integration/main_thread.py` imports UNO, so it is loaded from its source against minimal
fake UNO modules, with the real `teardown`, and takes its Windows path. The office's main thread
is a thread of this test, which runs the posted callback when the test lets it; the document
records whether a stall had been recorded when its close started.
"""

import importlib.util
import sys
import threading
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.integration import teardown

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def main_thread(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    modules = {name: types.ModuleType(name) for name in ("com", "com.sun", "com.sun.star")}
    unohelper = types.ModuleType("unohelper")
    vars(unohelper)["Base"] = type("Base", (), {})
    awt = types.ModuleType("com.sun.star.awt")
    vars(awt)["XCallback"] = type("XCallback", (), {})
    modules |= {"unohelper": unohelper, "com.sun.star.awt": awt}
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "teardown", teardown)  # Shared, so stalls are visible.
    spec = importlib.util.spec_from_file_location(
        "main_thread_under_test", ROOT / "tests" / "integration" / "main_thread.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "os", types.SimpleNamespace(name="nt"))  # The Windows close.
    teardown.start_session()
    try:
        yield module
    finally:
        teardown.start_session()


class Office:
    """LibreOffice's AsyncCallback service: each posted callback runs when the test says so."""

    def __init__(self) -> None:
        self.posted = threading.Event()
        self.callbacks: list[Any] = []
        factory = types.SimpleNamespace(createInstanceWithContext=self.create)
        self.context = types.SimpleNamespace(ServiceManager=factory)

    def create(self, name: str, context: object) -> "Office":
        assert name == "com.sun.star.awt.AsyncCallback"
        return self

    def addCallback(self, callback: Any, data: object) -> None:
        self.callbacks.append(callback)
        self.posted.set()

    def reach_callbacks(self) -> None:
        """Run the posted callbacks on another thread, as the office's main thread would."""
        thread = threading.Thread(target=lambda: [item.notify(None) for item in self.callbacks])
        thread.start()
        thread.join(10)
        assert not thread.is_alive()


class Document:
    def __init__(self, during_close: Any = None, error: Exception | None = None) -> None:
        self.closes: list[list[str]] = []  # The stalls recorded when each close started.
        self.during_close, self.error = during_close, error

    def close(self, deliver: bool) -> None:
        self.closes.append(teardown.stalled_callbacks())
        if self.during_close is not None:
            self.during_close()
        if self.error is not None:
            raise self.error


def close_in_background(main_thread: Any, office: Office, document: Document) -> Any:
    """Call `close_document` on its own thread; return a function giving what it raised."""
    outcome: list[BaseException | None] = []

    def close() -> None:
        try:
            main_thread.close_document(office.context, document)
        except BaseException as error:  # The helper's failure is the subject.
            outcome.append(error)
        else:
            outcome.append(None)

    caller = threading.Thread(target=close)
    caller.start()

    def result() -> BaseException | None:
        caller.join(10)
        assert not caller.is_alive(), "close_document did not return"
        return outcome[0]

    return result


def test_a_close_posted_before_a_stall_does_not_start_after_it(main_thread: Any) -> None:
    # The stall is recorded after close_document's own check and before the main thread reaches
    # the callback: the close must not start during the capture, and the caller must not be told
    # that the document closed.
    office, document = Office(), Document()
    result = close_in_background(main_thread, office, document)
    assert office.posted.wait(10)
    assert teardown.stall_if_idle(0, "a synthetic stall") is not None
    office.reach_callbacks()
    error = result()
    # The stalls seen by each close that started, and what close_document raised.
    assert (document.closes, type(error)) == ([], TimeoutError), error
    assert "a synthetic stall" in str(error)


def test_a_posted_close_runs_on_the_main_thread_when_nothing_has_stalled(
    main_thread: Any,
) -> None:
    office, document = Office(), Document()
    result = close_in_background(main_thread, office, document)
    assert office.posted.wait(10)
    office.reach_callbacks()
    assert result() is None
    assert document.closes == [[]]
    office, failing = Office(), Document(error=RuntimeError("synthetic close failure"))
    result = close_in_background(main_thread, office, failing)
    assert office.posted.wait(10)
    office.reach_callbacks()
    error = result()
    assert isinstance(error, AssertionError) and "synthetic close failure" in str(error)


def test_a_close_already_started_when_the_stall_is_recorded_finishes(main_thread: Any) -> None:
    office = Office()
    document = Document(during_close=lambda: teardown.stall_if_idle(0, "a synthetic stall"))
    result = close_in_background(main_thread, office, document)
    assert office.posted.wait(10)
    office.reach_callbacks()
    assert result() is None  # The document did close.
    assert document.closes == [[]] and teardown.stalled_callbacks() == ["a synthetic stall"]


def test_a_close_whose_caller_stopped_waiting_never_starts(
    main_thread: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The main thread reaches the close after the caller stopped waiting and before the caller
    # recorded its timeout as a stall, so only the abandoned close itself can refuse to start.
    monkeypatch.setattr(main_thread, "CLOSE_TIMEOUT", 0.1)
    office, document = Office(), Document()
    record = main_thread.record_stalled_callback

    def reach_then_record(message: str) -> None:
        assert teardown.stalled_callbacks() == []
        office.reach_callbacks()
        record(message)

    monkeypatch.setattr(main_thread, "record_stalled_callback", reach_then_record)
    result = close_in_background(main_thread, office, document)
    error = result()
    assert isinstance(error, TimeoutError) and "did not close a document" in str(error)
    assert office.callbacks and document.closes == []
