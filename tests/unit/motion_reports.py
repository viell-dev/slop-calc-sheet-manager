"""A fake LibreOffice main thread that delivers a window's pointer reports in order.

A window's motion listener hears a pointer move only when LibreOffice's main thread gets to it,
so a report can arrive well after its move, and after later moves. The calibration tests of the
sheet list (#209, #298) and the rename dialog (#232) run the real calibration methods, read from
source, against fake windows whose reports this thread delivers, each after a chosen busy time.
It records when it last began to deliver one, for fakes that drop a move made too soon after
(#298).
"""

import queue
import threading
import time
from types import SimpleNamespace
from typing import Any

from tests.unit.source_methods import constant, function

LAB = "tests/ui/lab.py"


def lab_calibration(confirm: float | None = None) -> dict[str, Any]:
    """`tests/ui/lab.py`'s calibration functions and constants, read from source (#300).

    The result is the functions' globals, with the fake `Tracker` below; `confirm`, when given,
    replaces CONFIRM_SECONDS so that a test can set points aside sooner.
    """
    namespace: dict[str, Any] = {"Tracker": Tracker, "time": time}
    for name in ("FIRST_SECONDS", "CONFIRM_SECONDS", "STEPS", "SPACING", "COLUMN"):
        namespace[name] = constant(LAB, name)
    if confirm is not None:
        namespace["CONFIRM_SECONDS"] = confirm
    for name in ("settled_report", "list_points", "confirmed_offset", "_paired"):
        function(LAB, name, namespace)
    return namespace


class Tracker:
    """Stands in for the UI modules' `Tracker`: every position a window reported, and the last."""

    def __init__(self) -> None:
        self.last: tuple[int, int] | None = None
        self.reports: list[tuple[int, int]] = []

    def mouseMoved(self, event: Any) -> None:
        self.reports.append((event.X, event.Y))
        self.last = (event.X, event.Y)


class Office:
    """A main thread that delivers reports in order, each after its busy time."""

    def __init__(self) -> None:
        self.listeners: list[Tracker] = []
        self.reports: queue.Queue[tuple[float, tuple[int, int]] | None] = queue.Queue()
        self.delivered = float("-inf")  # When the last report began to reach the listeners.
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while (item := self.reports.get()) is not None:
            busy, (x, y) = item
            time.sleep(busy)
            self.delivered = time.monotonic()
            for listener in list(self.listeners):
                listener.mouseMoved(SimpleNamespace(X=x, Y=y))

    def stop(self) -> None:
        self.reports.put(None)
        self.thread.join(5)
