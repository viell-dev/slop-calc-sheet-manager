"""The Xvfb lab's pointer calibration takes the tree's offset from one point's two reports (#298).

`Lab.calibrate` takes the tree's screen offset from where the tree says the pointer is. The tree
hears a move only when LibreOffice's main thread gets to it, so a report can arrive well after
the move, after later moves (#209), or, in gtk3, not at all when the move came before the office
had finished with the previous report (#298). The methods are read from `tests/ui/lab.py`, which
imports UNO, and run against a fake tree whose reports a fake main thread delivers in order, late
when it is kept busy. The trees have the measured places and sizes; some windows are placed so
that the scan reaches the tree after a few points rather than dozens.
"""

import re
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, NamedTuple

import pytest

from tests.unit.motion_reports import Office, Tracker
from tests.unit.source_methods import constant, function, method

LAB = "tests/ui/lab.py"
STEPS = constant(LAB, "STEPS")
CONFIRM_SECONDS = constant(LAB, "CONFIRM_SECONDS")


class Geometry(NamedTuple):
    origin: tuple[int, int]  # The tree's true screen position.
    size: tuple[int, int]
    accessible: tuple[int, int]  # Where its accessible context places it on screen.


GEN = Geometry((1186, 136), (273, 784), (1186, 136))  # As in #209's gen session.
# As in #298's gtk3 session, in a workbook that has just opened: the accessible location is 21
# pixels above the tree, so the first point misses it.
GTK3 = Geometry((1125, 176), (321, 743), (1123, 155))
FIRST = (30, 12)  # Where the first point lands in GEN's tree: its accessible location + (30, 12).
WINDOW = (0, 0, 1500, 950)  # The lab's place for a document window: X, Y, width and height.
# Windows placed lower, so that the scan's first row of points crosses the tree: in GEN's from
# the first point, after one point beside it, or at the first point in the tree's left half,
# and in GTK3's at the third point, as in #298.
GEN_ROWS = (0, 100, 1460, 850)
GEN_BESIDE = (0, 100, 1500, 850)
GEN_LEFT = (0, 100, 1340, 850)
GTK3_ROWS = (0, 120, 1500, 830)


class Tree:
    def __init__(self, office: Office, geometry: Geometry) -> None:
        self.office, self.geometry = office, geometry

    def addMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.append(listener)

    def removeMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.remove(listener)

    def getPosSize(self) -> Any:
        width, height = self.geometry.size
        return SimpleNamespace(X=4, Y=38, Width=width, Height=height)

    def getProperty(self, name: str) -> Any:
        location = SimpleNamespace(X=self.geometry.accessible[0], Y=self.geometry.accessible[1])
        context = SimpleNamespace(getLocationOnScreen=lambda: location)
        return SimpleNamespace(getAccessibleContext=lambda: context)


class Input:
    """Real-input moves over a fake tree, which reports only moves inside it.

    Before the report of move n, the main thread is busy for `busy[n]`, or for `slow` seconds.
    `dropped` moves are never reported, nor is a move made within `rearm` seconds of a report,
    as gtk3 drops a move made before it has finished with the previous report (#298). With
    `entering`, a move onto the tree from elsewhere is not reported either: VCL delivers it as
    the pointer entering the tree, which motion listeners do not hear (#253). `after(n)` may add
    reports after move n's, and `scale` stands for a tree whose coordinates are not screen pixels.
    """

    def __init__(
        self,
        office: Office,
        geometry: Geometry = GEN,
        busy: dict[int, float] | None = None,
        slow: float = 0.0,
        dropped: frozenset[int] = frozenset(),
        rearm: float = 0.0,
        entering: bool = False,
        after: Callable[[int], None] = lambda move: None,
        scale: int = 1,
    ) -> None:
        self.office, self.geometry, self.busy, self.slow = office, geometry, busy or {}, slow
        self.dropped, self.rearm, self.entering = dropped, rearm, entering
        self.after, self.scale = after, scale
        self.moves: list[tuple[int, int]] = []
        self.inside = False

    def move(self, x: int, y: int) -> None:
        self.moves.append((x, y))
        number = len(self.moves)
        (left, top), (width, height) = self.geometry.origin, self.geometry.size
        local = (x - left, y - top)
        was, self.inside = self.inside, 0 <= local[0] < width and 0 <= local[1] < height
        lost = number in self.dropped or time.monotonic() < self.office.delivered + self.rearm
        if self.inside and not lost and (was or not self.entering):
            reported = (local[0] * self.scale, local[1] * self.scale)
            self.office.reports.put((self.busy.get(number, self.slow), reported))
        self.after(number)


@pytest.fixture
def office() -> Iterator[Office]:
    running = Office()
    yield running
    running.stop()


def calibrate(
    office: Office,
    real_input: Input,
    geometry: Geometry = GEN,
    frame: tuple[int, int, int, int] = WINDOW,
    confirm: float = CONFIRM_SECONDS,
) -> tuple[int, int]:
    """The real `Lab.calibrate`, read from source, over a fake tree in a window at `frame`."""
    namespace: dict[str, Any] = {
        "Tracker": Tracker,
        "time": time,
        "STEPS": STEPS,
        "FIRST_SECONDS": constant(LAB, "FIRST_SECONDS"),
        "CONFIRM_SECONDS": confirm,
    }
    for name in ("settled_report", "list_points", "confirmed_offset", "_paired"):
        function(LAB, name, namespace)
    calibration = method(LAB, "Lab", "calibrate", namespace)
    x, y, width, height = frame
    window = SimpleNamespace(
        getPosSize=lambda: SimpleNamespace(X=x, Y=y, Width=width, Height=height)
    )
    return calibration(SimpleNamespace(input=real_input), Tree(office, geometry), window)


def at(geometry: Geometry, local: tuple[int, int]) -> tuple[int, int]:
    """The screen position of a point in a tree's own coordinates."""
    return (geometry.origin[0] + local[0], geometry.origin[1] + local[1])


def test_prompt_reports_give_the_true_offset(office: Office) -> None:
    assert calibrate(office, Input(office)) == GEN.origin


def test_a_late_report_of_the_second_move_still_gives_the_true_offset(office: Office) -> None:
    # #209: the report of the second move came after a fixed 0.2-second wait, so the first
    # position was read for the second and the offset came out (+2, +2).
    assert calibrate(office, Input(office, busy={2: 0.6})) == GEN.origin


def test_a_repeated_report_of_the_first_position_is_not_taken_for_the_second(
    office: Office,
) -> None:
    def repeat(move: int) -> None:
        if move == 1:
            office.reports.put((0.0, FIRST))

    assert calibrate(office, Input(office, busy={2: 0.6}, after=repeat)) == GEN.origin


def test_a_corrected_first_landing_reported_late_is_not_taken_for_the_second(
    office: Office,
) -> None:
    # As Windows can: a first landing one pixel off, corrected by a second absolute move.
    def corrected(move: int) -> None:
        if move == 1:
            office.reports.put((0.0, (FIRST[0] + 1, FIRST[1])))

    assert calibrate(office, Input(office, after=corrected)) == GEN.origin


def test_the_second_move_waits_until_gtk3_hears_moves_again(office: Office) -> None:
    # #298: gtk3's tree reported the point (1380, 180) at once, as local (255, 4), and dropped
    # the second move, made as soon as that report was seen. The calibration then waited 10 s
    # and failed: "did not report the pointer's move to (1382, 182); its last report was
    # (255, 4)". The point before it was the pointer entering the tree, which is not reported.
    real_input = Input(office, GTK3, entering=True, rearm=0.1)
    assert calibrate(office, real_input, GTK3, GTK3_ROWS) == GTK3.origin
    # The point is in the tree's right half, so its second move goes left, into the tree.
    assert real_input.moves[-2:] == [(1380, 180), (1378, 182)]


def test_a_second_move_that_is_never_reported_moves_on_to_the_next_point(
    office: Office,
) -> None:
    # Both points are in the tree's top left quarter, so both second moves go right and down:
    # only their sizes tell the first point's pair from the second's.
    real_input = Input(office, dropped=frozenset({2}))
    assert calibrate(office, real_input, frame=GEN_LEFT, confirm=0.5) == GEN.origin
    assert real_input.moves == [
        at(GEN, FIRST),
        at(GEN, (FIRST[0] + 2, FIRST[1] + 2)),
        (1300, 160),
        (1302, 164),
    ]


def test_a_late_report_of_an_earlier_point_moves_on_to_the_next_point(office: Office) -> None:
    # The first point's report comes while the pointer is at the next point, beside the tree,
    # so that point's second move goes unreported too; the old method waited for it and failed.
    real_input = Input(office, busy={1: 0.5})
    assert calibrate(office, real_input, frame=GEN_BESIDE, confirm=0.5) == GEN.origin
    assert real_input.moves[1:] == [(1460, 160), (1462, 162), (1420, 160), (1418, 164)]


def test_reports_later_than_every_wait_still_give_the_true_offset(office: Office) -> None:
    # Every report comes 0.6 s after its move, after the first wait and after the quiet
    # time, so the report first heard at each point belongs to the point before. The old
    # method took the second point's report for its second move's and came out (+2, +2), the
    # offset #209 found in CI.
    real_input = Input(office, slow=0.6)
    assert calibrate(office, real_input, frame=GEN_ROWS) == GEN.origin
    assert real_input.moves == [at(GEN, FIRST), (1420, 160), (1422, 162)]


def test_a_late_pair_ends_calibration_before_another_second_move(office: Office) -> None:
    # The first point's second move is reported after the point has been set aside, while the
    # next point waits for its first report: no further point is tried.
    real_input = Input(office, busy={2: 0.65})
    assert calibrate(office, real_input, frame=GEN_ROWS, confirm=0.5) == GEN.origin
    assert real_input.moves == [
        at(GEN, FIRST),
        at(GEN, (FIRST[0] + 2, FIRST[1] + 2)),
        (1420, 160),
    ]


def test_a_late_pair_counts_for_its_own_point(office: Office) -> None:
    # The first point's report comes at the second point, which is given a second move and
    # set aside before its own reports come. They come at the third point, the second's report
    # in its first wait and the second move's while its reports settle, after which it is given
    # a second move too. The pair is the second point's, and gives its offset, not the third's.
    real_input = Input(office, busy={1: 0.4, 2: 0.95, 3: 0.1, 4: 0.6})
    assert calibrate(office, real_input, frame=GEN_ROWS, confirm=0.5) == GEN.origin
    assert real_input.moves == [
        at(GEN, FIRST),
        (1420, 160),
        (1422, 162),
        (1380, 160),
        (1378, 164),
    ]


# Points on the tree's edges, in its own coordinates, and the second moves that keep inside it.
EDGES = {
    "right": ((GEN.size[0] - 1, 100), (-2, 2)),
    "bottom": ((100, GEN.size[1] - 1), (2, -2)),
    "top right": ((GEN.size[0] - 1, 0), (-2, 2)),
    "top left": ((0, 0), (2, 2)),
}


@pytest.mark.parametrize(("local", "step"), EDGES.values(), ids=list(EDGES))
def test_a_point_on_the_trees_edge_moves_into_the_tree(
    office: Office, local: tuple[int, int], step: tuple[int, int]
) -> None:
    # The first point lands on the tree's edge, where its accessible location puts it. Its
    # second move goes toward the tree's middle, so it is reported and confirms the point.
    point = at(GEN, local)
    geometry = GEN._replace(accessible=(point[0] - 30, point[1] - 12))
    real_input = Input(office, geometry)
    assert calibrate(office, real_input, geometry) == GEN.origin
    assert real_input.moves == [point, (point[0] + step[0], point[1] + step[1])]


def test_reports_that_never_follow_the_moves_fail_with_the_points(office: Office) -> None:
    # A tree whose coordinates are twice the screen's: no two reports differ by a step.
    real_input = Input(office, scale=2)
    moves = [
        {"point": at(GEN, FIRST), "step": (2, 2)},
        {"point": (1420, 160), "step": (-2, 4)},
        {"point": (1380, 160), "step": (-4, 2)},
    ]
    message = f"differ by a point's second move; the points and their second moves: {moves}"
    with pytest.raises(AssertionError, match=re.escape(message)):
        calibrate(office, real_input, frame=GEN_ROWS, confirm=0.5)
    assert len(real_input.moves) == 2 * len(STEPS)


def test_a_tree_that_reports_no_point_fails(office: Office) -> None:
    real_input = Input(office, dropped=frozenset(range(1, 10)))
    message = "Calibrating the sheet list: the pointer never reached it at any of 3 points"
    with pytest.raises(AssertionError, match=re.escape(message)):
        calibrate(office, real_input, frame=(0, 0, 200, 140))
    assert len(real_input.moves) == 3


def test_the_points_keep_clear_of_each_other() -> None:
    # #209's first point is 8 pixels from a point of the window's scan, which is left out.
    namespace: dict[str, Any] = {}
    list_points = function(LAB, "list_points", namespace)
    frame = SimpleNamespace(X=0, Y=0, Width=1500, Height=950)
    found = list_points(SimpleNamespace(X=GEN.accessible[0], Y=GEN.accessible[1]), frame)
    assert found[0] == at(GEN, FIRST)
    assert (1220, 140) in list_points(None, frame)
    assert (1220, 140) not in found
    assert all(
        max(abs(x - a), abs(y - b)) >= 20
        for index, (x, y) in enumerate(found)
        for a, b in found[index + 1 :]
    )
