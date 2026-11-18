"""The rename dialog's pointer calibration attributes each report to its own move (#232).

`Dialog.calibrate` in `tests/ui/rename_dialog.py` takes the dialog's screen offset from where the
dialog says the pointer is, trying points until one lands on the dialog's own background between
its controls. The dialog hears a move only when LibreOffice's main thread gets to it, so a report
can arrive after the pointer has gone on to the next point. The method is read from source, as it
imports UNO, and run against a fake dialog whose reports a fake main thread delivers in order,
late when it is kept busy.
"""

import re
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.motion_reports import Office, Tracker
from tests.unit.source_methods import function, method

RENAME = "tests/ui/rename_dialog.py"
LAB = "tests/ui/lab.py"
ORIGIN = (600, 300)  # The dialog's true screen position.
SIZE = (560, 472)
MARGIN = 12  # The background around the controls, as in the real dialog; controls fill the rest.
# The points tried first: the top row's left, middle and right, then the next row's left.
LEFT, MIDDLE, RIGHT = 4, SIZE[0] // 2, SIZE[0] - 5


def margins(x: int, y: int) -> bool:
    return x < MARGIN or y < MARGIN or x >= SIZE[0] - MARGIN or y >= SIZE[1] - MARGIN


def left_margin(x: int, y: int) -> bool:
    """A dialog whose top row is covered: only its left margin is background."""
    return x < MARGIN


class Window:
    def __init__(self, office: Office) -> None:
        self.office = office

    def addMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.append(listener)

    def removeMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.remove(listener)

    def getProperty(self, name: str) -> Any:
        location = SimpleNamespace(X=ORIGIN[0], Y=ORIGIN[1])
        size = SimpleNamespace(Width=SIZE[0], Height=SIZE[1])
        context = SimpleNamespace(getLocationOnScreen=lambda: location, getSize=lambda: size)
        return SimpleNamespace(getAccessibleContext=lambda: context)


class Input:
    """Real-input moves. Before the report of move n, the main thread is busy for `busy[n]`.
    A move is reported only over the background; `landed(n)` may report an earlier landing of
    move n first, and `scale` stands for a window whose coordinates are not screen pixels."""

    def __init__(
        self,
        office: Office,
        busy: dict[int, float],
        background: Callable[[int, int], bool] = margins,
        landed: Callable[[int, tuple[int, int]], tuple[int, int] | None] = lambda n, at: None,
        scale: int = 1,
    ) -> None:
        self.office, self.busy, self.background = office, busy, background
        self.landed, self.scale = landed, scale
        self.moves: list[tuple[int, int]] = []

    def move(self, x: int, y: int) -> None:
        self.moves.append((x, y))
        local = (x - ORIGIN[0], y - ORIGIN[1])
        if not (0 <= local[0] < SIZE[0] and 0 <= local[1] < SIZE[1]):
            return
        if not self.background(*local):
            return
        earlier = self.landed(len(self.moves), local)
        if earlier is not None:
            self.office.reports.put((0.0, earlier))
        reported = (local[0] * self.scale, local[1] * self.scale)
        self.office.reports.put((self.busy.get(len(self.moves), 0.0), reported))


class Pointer:
    def __init__(self, real_input: Input, offset: tuple[int, int]) -> None:
        self.offset = offset


@pytest.fixture
def office() -> Iterator[Office]:
    running = Office()
    yield running
    running.stop()


def calibrate(office: Office, real_input: Input, confirm: float = 0.5) -> tuple[int, int]:
    namespace: dict[str, Any] = {
        "Tracker": Tracker,
        "Pointer": Pointer,
        "time": time,
        "CONFIRM_SECONDS": confirm,
        "REJECTED_POINTS": 3,
    }
    namespace["settled_report"] = function(LAB, "settled_report", namespace)
    function(RENAME, "_reported", namespace)
    calibration = method(RENAME, "Dialog", "calibrate", namespace)
    lab = SimpleNamespace(input=real_input)
    dialog = SimpleNamespace(pointer=None, window=Window(office), book=SimpleNamespace(lab=lab))
    return calibration(dialog).offset


def test_prompt_reports_give_the_true_offset(office: Office) -> None:
    assert calibrate(office, Input(office, {})) == ORIGIN


def test_a_late_report_is_not_taken_for_the_next_points(office: Office) -> None:
    # #232: the first point's report comes while the pointer is at the second point, and that
    # point's own report later still. Taking the first report after a fixed 0.15-second wait
    # read the first point's report for the second's, an offset half the dialog's width out.
    assert calibrate(office, Input(office, {1: 0.25, 2: 0.15})) == ORIGIN


def test_a_late_report_over_a_control_moves_on_to_the_next_point(office: Office) -> None:
    # The first point's late report comes while the pointer is at the second point, which is
    # over a control, as is its second move: neither is reported, and the next points are tried.
    real_input = Input(office, {1: 0.25}, background=left_margin)
    assert calibrate(office, real_input) == ORIGIN
    assert real_input.moves[1:] == [
        (ORIGIN[0] + MIDDLE, ORIGIN[1] + 2),
        (ORIGIN[0] + MIDDLE + 2, ORIGIN[1] + 4),
        (ORIGIN[0] + RIGHT, ORIGIN[1] + 2),
        (ORIGIN[0] + LEFT, ORIGIN[1] + 5),
        (ORIGIN[0] + LEFT + 2, ORIGIN[1] + 7),
    ]


def test_a_late_second_report_is_not_preceded_by_another_points_report(office: Office) -> None:
    # The second point's report comes after the first's, and the second move's report after
    # both and late. Taking the newest report other than the first point's for the second move
    # would give an offset 2 pixels out on both axes.
    real_input = Input(office, {1: 0.25, 2: 0.1, 3: 0.6})
    assert calibrate(office, real_input, confirm=2) == ORIGIN
    assert len(real_input.moves) == 3


def test_a_corrected_landing_is_not_taken_for_the_point(office: Office) -> None:
    # As Windows can: a first landing one pixel off, corrected by a second absolute move.
    def landed(move: int, at: tuple[int, int]) -> tuple[int, int] | None:
        return (at[0] + 1, at[1]) if move == 1 else None

    real_input = Input(office, {}, landed=landed)
    assert calibrate(office, real_input) == ORIGIN
    assert len(real_input.moves) == 2


def test_reports_that_never_follow_the_move_fail_with_the_points(office: Office) -> None:
    # A window whose coordinates are twice the screen's: no pair differs by (2, 2).
    real_input = Input(office, {}, scale=2)
    point = (ORIGIN[0] + LEFT, ORIGIN[1] + 2)
    message = f"{{'point': {point}, 'reports': [{(2 * LEFT, 4)}, {(2 * LEFT + 4, 8)}]}}"
    with pytest.raises(AssertionError, match=re.escape(message)):
        calibrate(office, real_input)
    assert len(real_input.moves) == 6
