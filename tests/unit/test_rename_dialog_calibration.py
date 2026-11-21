"""The rename dialog's pointer calibration attributes each report to its own move (#232, #300).

`Dialog.calibrate` in `tests/ui/rename_dialog.py` takes the dialog's screen offset from where the
dialog says the pointer is, trying points until one lands on the dialog's own background between
its controls, with the lab's `confirmed_offset`. The dialog hears a move only when LibreOffice's
main thread gets to it, so a report can arrive after the pointer has gone on to the next point.
The points start where the dialog's own coordinates begin, read from its buttons, rather than at
its accessible location, which includes the window manager's frame (#253). The methods are read
from source, as they import UNO, and run against a fake dialog whose reports a fake main thread
delivers in order, late when it is kept busy.
"""

import re
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.motion_reports import Office, Tracker, lab_calibration
from tests.unit.source_methods import function, method

RENAME = "tests/ui/rename_dialog.py"
ORIGIN = (600, 300)  # Where the dialog's own coordinates begin on screen.
SIZE = (560, 472)
MARGIN = 12  # The background around the controls, as in the real dialog; controls fill the rest.
# The points tried first: the top row's left, middle and right, then the next row's left.
LEFT, MIDDLE, RIGHT = 4, SIZE[0] // 2, SIZE[0] - 5
ROW = 15  # How far apart the rows of points are.
# The buttons' places in the dialog's own coordinates.
BUTTONS = {
    "Replace All": (420, 44),
    "Reset All": (16, 432),
    "Rename": (300, 432),
    "Cancel": (430, 432),
}
# Window manager frames around the dialog's own window, (left, top, right, bottom), which its
# accessible area includes, as measured for #253.
FRAMES = {
    "none": (0, 0, 0, 0),
    "openbox-gtk3": (1, 20, 1, 1),
    "openbox-gen": (0, 19, 2, 2),
    "windows": (8, 31, 8, 8),
}


def margins(x: int, y: int) -> bool:
    return x < MARGIN or y < MARGIN or x >= SIZE[0] - MARGIN or y >= SIZE[1] - MARGIN


def left_margin(x: int, y: int) -> bool:
    """A dialog whose top row is covered: only its left margin is background."""
    return x < MARGIN


def accessible(location: tuple[int, int], size: tuple[int, int]) -> Any:
    """An accessible context with this screen location and size."""
    place = SimpleNamespace(X=location[0], Y=location[1])
    extent = SimpleNamespace(Width=size[0], Height=size[1])
    context = SimpleNamespace(getLocationOnScreen=lambda: place, getSize=lambda: extent)
    return SimpleNamespace(getAccessibleContext=lambda: context)


class Window:
    """The dialog's own window, inside a frame its accessible area includes."""

    def __init__(self, office: Office, frame: tuple[int, int, int, int]) -> None:
        self.office, self.frame = office, frame

    def addMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.append(listener)

    def removeMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.remove(listener)

    def getOutputSize(self) -> Any:
        return SimpleNamespace(Width=SIZE[0], Height=SIZE[1])

    def getProperty(self, name: str) -> Any:
        left, top, right, bottom = self.frame
        location = ORIGIN[0] - left, ORIGIN[1] - top
        return accessible(location, (SIZE[0] + left + right, SIZE[1] + top + bottom))


class Button:
    """A button at `place` in the dialog's own coordinates; `shift` misplaces its accessible."""

    def __init__(self, place: tuple[int, int], shift: tuple[int, int] = (0, 0)) -> None:
        self.place, self.shift = place, shift

    def getPosSize(self) -> Any:
        return SimpleNamespace(X=self.place[0], Y=self.place[1], Width=100, Height=28)

    def getProperty(self, name: str) -> Any:
        screen = (
            ORIGIN[0] + self.place[0] + self.shift[0],
            ORIGIN[1] + self.place[1] + self.shift[1],
        )
        return accessible(screen, (100, 28))


class Input:
    """Real-input moves. Before the report of move n, the main thread is busy for `busy[n]`.
    A move is reported only over the background; `landed(n)` may report an earlier landing of
    move n first, and `scale` stands for a window whose coordinates are not screen pixels.
    With `entering`, a move onto the background from elsewhere is not reported either, as VCL
    delivers it as the pointer entering the window, which motion listeners do not hear (#253);
    the pointer starts elsewhere."""

    def __init__(
        self,
        office: Office,
        busy: dict[int, float],
        background: Callable[[int, int], bool] = margins,
        landed: Callable[[int, tuple[int, int]], tuple[int, int] | None] = lambda n, at: None,
        scale: int = 1,
        entering: bool = False,
    ) -> None:
        self.office, self.busy, self.background = office, busy, background
        self.landed, self.scale, self.entering = landed, scale, entering
        self.moves: list[tuple[int, int]] = []
        self.on_background = False

    def move(self, x: int, y: int) -> None:
        self.moves.append((x, y))
        local = (x - ORIGIN[0], y - ORIGIN[1])
        inside = 0 <= local[0] < SIZE[0] and 0 <= local[1] < SIZE[1]
        was, self.on_background = self.on_background, inside and self.background(*local)
        if not self.on_background or (self.entering and not was):
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


def dialog_for(
    office: Office,
    real_input: Input,
    confirm: float = 0.5,
    frame: tuple[int, int, int, int] = FRAMES["none"],
    shifts: dict[str, tuple[int, int]] | None = None,
) -> Any:
    """A fake dialog whose `calibrate` and `own_area` are the real methods, read from source."""
    namespace = {**lab_calibration(confirm), "Pointer": Pointer}
    function(RENAME, "scan_points", namespace)
    calibration = method(RENAME, "Dialog", "calibrate", namespace)
    own_area = method(RENAME, "Dialog", "own_area", namespace)
    shifts = shifts or {}
    dialog = SimpleNamespace(
        pointer=None,
        calibration=None,
        window=Window(office, frame),
        buttons={name: Button(place, shifts.get(name, (0, 0))) for name, place in BUTTONS.items()},
        book=SimpleNamespace(lab=SimpleNamespace(input=real_input)),
    )
    dialog.own_area = lambda: own_area(dialog)
    dialog.calibrate = lambda: calibration(dialog)
    return dialog


def calibrate(office: Office, real_input: Input, confirm: float = 0.5) -> tuple[int, int]:
    return dialog_for(office, real_input, confirm).calibrate().offset


def test_prompt_reports_give_the_true_offset(office: Office) -> None:
    assert calibrate(office, Input(office, {})) == ORIGIN


def test_a_late_report_is_not_taken_for_the_next_points(office: Office) -> None:
    # #232: the first point's report comes while the pointer is at the second point, after
    # the first wait, and that point's own report later still. Taking the first report after a
    # fixed 0.15-second wait read the first point's report for the second's, an offset half the
    # dialog's width out.
    assert calibrate(office, Input(office, {1: 0.45, 2: 0.15})) == ORIGIN


def test_reports_later_than_the_quiet_time_count_for_their_own_point(office: Office) -> None:
    # #300: every report comes 0.35 s after its move, later than the 0.3-second quiet time.
    # Requiring two settled reports 2 pixels apart, and taking the offset from the point being
    # tried, credited the top row's right point's pair to the next row's left point: (49, 303).
    real_input = Input(office, {move: 0.35 for move in range(1, 100)})
    assert calibrate(office, real_input, confirm=2) == ORIGIN


def test_a_late_report_over_a_control_moves_on_to_the_next_point(office: Office) -> None:
    # The first point's late report comes while the pointer is at the second point, which is
    # over a control, as is its second move: neither is reported, and the next points are tried.
    # The next row's left point confirms, with the second step.
    real_input = Input(office, {1: 0.45}, background=left_margin)
    assert calibrate(office, real_input) == ORIGIN
    assert real_input.moves[1:] == [
        (ORIGIN[0] + MIDDLE, ORIGIN[1] + 2),
        (ORIGIN[0] + MIDDLE + 2, ORIGIN[1] + 4),
        (ORIGIN[0] + RIGHT, ORIGIN[1] + 2),
        (ORIGIN[0] + LEFT, ORIGIN[1] + 2 + ROW),
        (ORIGIN[0] + LEFT + 2, ORIGIN[1] + 2 + ROW + 4),
    ]


def test_a_late_second_report_is_not_preceded_by_another_points_report(office: Office) -> None:
    # The first point's report comes at the second point, the second point's after it, and
    # the second move's report after both and late. Taking the newest report other than the
    # first point's for the second move would give an offset 2 pixels out on both axes.
    real_input = Input(office, {1: 0.45, 2: 0.1, 3: 0.6})
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
    # A window whose coordinates are twice the screen's: no two reports differ by a step.
    real_input = Input(office, {}, scale=2)
    moves = [
        {"point": (ORIGIN[0] + LEFT, ORIGIN[1] + 2), "step": (2, 2)},
        {"point": (ORIGIN[0] + MIDDLE, ORIGIN[1] + 2), "step": (-2, 4)},
        {"point": (ORIGIN[0] + RIGHT, ORIGIN[1] + 2), "step": (-4, 2)},
    ]
    message = (
        "Calibrating the Rename Sheets dialog: no two of its reports differ by a point's second "
        f"move; the points and their second moves: {moves}"
    )
    with pytest.raises(AssertionError, match=re.escape(message)):
        calibrate(office, real_input)
    assert len(real_input.moves) == 6


@pytest.mark.parametrize("frame", FRAMES.values(), ids=list(FRAMES))
def test_the_points_start_on_the_dialogs_own_window(
    office: Office, frame: tuple[int, int, int, int]
) -> None:
    # #253: the accessible area includes the window manager's frame, where the dialog hears
    # nothing, and the move that brings the pointer onto its background is not reported. The
    # points start where the dialog's own coordinates begin: the first, reached from off the
    # dialog, goes unheard, and the second, reached from the first, counts. Its second move
    # goes down and, from the middle, to the left.
    real_input = Input(office, {}, entering=True)
    dialog = dialog_for(office, real_input, frame=frame)
    assert dialog.calibrate().offset == ORIGIN
    assert real_input.moves == [
        (ORIGIN[0] + LEFT, ORIGIN[1] + 2),
        (ORIGIN[0] + MIDDLE, ORIGIN[1] + 2),
        (ORIGIN[0] + MIDDLE - 2, ORIGIN[1] + 4),
    ]
    left, top, right, bottom = frame
    assert dialog.calibration["accessible"] == [
        ORIGIN[0] - left,
        ORIGIN[1] - top,
        SIZE[0] + left + right,
        SIZE[1] + top + bottom,
    ]
    assert dialog.calibration["own_area"] == [*ORIGIN, *SIZE]
    assert (dialog.calibration["tried"], dialog.calibration["heard"]) == (2, [2])


def test_buttons_that_disagree_on_the_origin_stop_calibration(office: Office) -> None:
    # One button's accessible location a pixel off its place: the dialog's origin is unknown.
    real_input = Input(office, {})
    dialog = dialog_for(office, real_input, shifts={"Cancel": (1, 0)})
    with pytest.raises(AssertionError, match="buttons place its origin"):
        dialog.calibrate()
    assert real_input.moves == []
