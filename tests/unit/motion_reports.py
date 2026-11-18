"""A fake LibreOffice main thread that delivers a window's pointer reports in order.

A window's motion listener hears a pointer move only when LibreOffice's main thread gets to it,
so a report can arrive well after its move, and after later moves. The calibration tests of the
sheet list (#209) and the rename dialog (#232) run the real calibration methods, read from
source, against fake windows whose reports this thread delivers, each after a chosen busy time.
"""

import queue
import threading
import time
from types import SimpleNamespace
from typing import Any


class Tracker:
    """Stands in for the UI modules' `Tracker`: the last position a window reported."""

    def __init__(self) -> None:
        self.last: tuple[int, int] | None = None

    def mouseMoved(self, event: Any) -> None:
        self.last = (event.X, event.Y)


class Office:
    """A main thread that delivers reports in order, each after its busy time."""

    def __init__(self) -> None:
        self.listeners: list[Tracker] = []
        self.reports: queue.Queue[tuple[float, tuple[int, int]] | None] = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while (item := self.reports.get()) is not None:
            busy, (x, y) = item
            time.sleep(busy)
            for listener in list(self.listeners):
                listener.mouseMoved(SimpleNamespace(X=x, Y=y))

    def stop(self) -> None:
        self.reports.put(None)
        self.thread.join(5)
