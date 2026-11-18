"""The Xvfb lab's pointer calibration waits for the tree's report of its second move (#209).

`Lab.calibrate` takes the tree's screen offset from where the tree says the pointer is. The tree
hears a move only when LibreOffice's main thread gets to it, so a report can arrive well after
the move. The method is read from `tests/ui/lab.py`, which imports UNO, and run against a fake
tree whose reports a fake main thread delivers in order, late when it is kept busy.
"""

import queue
import re
import threading
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.source_methods import function, method

LAB = "tests/ui/lab.py"
ORIGIN = (1186, 136)  # The tree's true screen position, as in #209's gen session.
SIZE = (273, 784)
FIRST = (30, 12)  # Where the first move lands in the tree: its accessible location + (30, 12).


class Tracker:
    def __init__(self) -> None:
        self.last: tuple[int, int] | None = None

    def mouseMoved(self, event: Any) -> None:
        self.last = (event.X, event.Y)


class Office:
    """A main thread that delivers the tree's reports in order, each after its busy time."""

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


class Tree:
    def __init__(self, office: Office) -> None:
        self.office = office

    def addMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.append(listener)

    def removeMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.remove(listener)

    def getProperty(self, name: str) -> Any:
        location = SimpleNamespace(X=ORIGIN[0], Y=ORIGIN[1])
        context = SimpleNamespace(getLocationOnScreen=lambda: location)
        return SimpleNamespace(getAccessibleContext=lambda: context)


class Input:
    """Real-input moves. Before the report of move n, the main thread is busy for `busy[n]`;
    `dropped` moves are never reported, and `after(n)` may add reports after move n's."""

    def __init__(
        self,
        office: Office,
        busy: dict[int, float],
        dropped: frozenset[int] = frozenset(),
        after: Callable[[int], None] = lambda move: None,
    ) -> None:
        self.office, self.busy, self.dropped, self.after = office, busy, dropped, after
        self.moves = 0

    def move(self, x: int, y: int) -> None:
        self.moves += 1
        local = (x - ORIGIN[0], y - ORIGIN[1])
        inside = 0 <= local[0] < SIZE[0] and 0 <= local[1] < SIZE[1]
        if inside and self.moves not in self.dropped:
            self.office.reports.put((self.busy.get(self.moves, 0.0), local))
        self.after(self.moves)


@pytest.fixture
def office() -> Iterator[Office]:
    running = Office()
    yield running
    running.stop()


def calibrate(office: Office, real_input: Input, timeout: float = 10) -> tuple[int, int]:
    namespace: dict[str, Any] = {"Tracker": Tracker, "time": time}
    settled = function(LAB, "settled_report", namespace)

    def settled_report(*arguments: object) -> object:
        return settled(*arguments, timeout=timeout)

    namespace["settled_report"] = settled_report
    calibration = method(LAB, "Lab", "calibrate", namespace)
    window = SimpleNamespace(getPosSize=lambda: SimpleNamespace(X=0, Y=0, Width=1500, Height=950))
    return calibration(SimpleNamespace(input=real_input), Tree(office), window)


def test_prompt_reports_give_the_true_offset(office: Office) -> None:
    assert calibrate(office, Input(office, {})) == ORIGIN


def test_a_late_report_of_the_second_move_still_gives_the_true_offset(office: Office) -> None:
    # #209: the report of the second move came after a fixed 0.2-second wait, so the first
    # position was read for the second and the offset came out (+2, +2).
    assert calibrate(office, Input(office, {2: 0.6})) == ORIGIN


def test_a_repeated_report_of_the_first_position_is_not_taken_for_the_second(
    office: Office,
) -> None:
    def repeat(move: int) -> None:
        if move == 1:
            office.reports.put((0.0, FIRST))

    assert calibrate(office, Input(office, {2: 0.6}, after=repeat)) == ORIGIN


def test_a_corrected_first_landing_reported_late_is_not_taken_for_the_second(
    office: Office,
) -> None:
    # As Windows can: a first landing one pixel off, corrected by a second absolute move.
    def corrected(move: int) -> None:
        if move == 1:
            office.reports.put((0.0, (FIRST[0] + 1, FIRST[1])))

    assert calibrate(office, Input(office, {}, after=corrected)) == ORIGIN


def test_a_second_move_that_is_never_reported_fails_with_both_positions(office: Office) -> None:
    target = (ORIGIN[0] + FIRST[0] + 2, ORIGIN[1] + FIRST[1] + 2)
    message = f"move to {target}; its last report was {FIRST}"
    with pytest.raises(AssertionError, match=re.escape(message)):
        calibrate(office, Input(office, {}, dropped=frozenset({2})), timeout=0.5)
