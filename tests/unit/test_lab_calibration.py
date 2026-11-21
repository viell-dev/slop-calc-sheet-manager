"""The Xvfb lab's pointer calibration takes the tree's offset from one point's two reports (#298).

`Lab.calibrate` takes the tree's screen offset from where the tree says the pointer is. The tree
hears a move only when LibreOffice's main thread gets to it, so a report can arrive well after
the move, after later moves (#209), or, in gtk3, not at all when the move came before the office
had finished with the previous report (#298). Its first points go down the tree's accessible
area, which can be out of place, before a scan of the window (#301). The methods are read from
`tests/ui/lab.py`, which imports UNO, and run against a fake tree whose reports a fake main
thread delivers in order, late when it is kept busy. The trees have the measured places and
sizes; some windows are placed so that the scan reaches the tree after a few points rather than
dozens.
"""

import re
import time
from collections.abc import Callable, Iterator
from functools import partial
from types import SimpleNamespace
from typing import Any, NamedTuple

import pytest

from tests.unit.motion_reports import LAB, Office, Tracker, lab_calibration
from tests.unit.source_methods import constant, method

STEPS = constant(LAB, "STEPS")


class Geometry(NamedTuple):
    origin: tuple[int, int]  # The tree's true screen position.
    size: tuple[int, int]
    # Where its accessible context places it on screen, with the tree's size; None for a tree
    # without one.
    accessible: tuple[int, int] | None
    # Where it places it once the pointer has crossed the window's toolbar, if elsewhere, and
    # how many seconds after the calibration starts it does so anyway.
    settled: tuple[int, int] | None = None
    settles_after: float | None = None
    # How many seconds after the calibration starts the tree is laid out. Until then it is
    # EARLY_HEIGHT tall, and its accessible area lies 17 pixels lower without a height, as a
    # reloaded gen tree's was in CI (#301).
    laid_out_after: float = 0.0


GEN = Geometry((1186, 136), (273, 784), (1186, 136))  # As in #209's gen session.
# As in #298's gtk3 session, in a workbook that has just opened: the accessible area begins 21
# pixels above the tree, so the first point misses it, until the pointer crosses the toolbar.
GTK3 = Geometry((1125, 176), (321, 743), (1123, 155), settled=(1123, 180))
TOOLBAR = 100  # Moves above this screen height cross the windows' toolbar.
EARLY_HEIGHT = 6
FIRST = (30, 12)  # Where the first point lands in GEN's tree: its accessible location + (30, 12).
# GEN's tree's points down its accessible area, in its own coordinates.
COLUMN = [(30, 12), (30, 36), (30, 60)]
WINDOW = (0, 0, 1500, 950)  # The lab's place for a document window: X, Y, width and height.
# Windows placed so that the scan's first row of points crosses the tree: GTK3's at its third
# point, as in #298, and GEN's on its left edge and then beside it.
GTK3_ROWS = (0, 120, 1500, 830)
NARROW = (1000, 100, 240, 850)


class Tree:
    """A fake tree, laid out and settled as its geometry says from when it is made."""

    def __init__(self, office: Office, geometry: Geometry, real_input: "Input") -> None:
        self.office, self.geometry, self.input = office, geometry, real_input
        real_input.created = time.monotonic()

    def addMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.append(listener)

    def removeMouseMotionListener(self, listener: Tracker) -> None:
        self.office.listeners.remove(listener)

    def getPosSize(self) -> Any:
        width, height = self.input.size()
        return SimpleNamespace(X=4, Y=38, Width=width, Height=height)

    def getProperty(self, name: str) -> Any:
        if self.geometry.accessible is None:
            raise RuntimeError("This tree has no accessible context")
        x, y = self.geometry.accessible
        width, height = self.geometry.size
        settles = self.geometry.settles_after
        if not self.input.laid_out():
            y, height = y + 17, 0
        elif self.geometry.settled and (
            self.input.crossed_toolbar or (settles is not None and self.input.age() >= settles)
        ):
            x, y = self.geometry.settled
        location = SimpleNamespace(X=x, Y=y)
        size = SimpleNamespace(Width=width, Height=height)
        context = SimpleNamespace(getLocationOnScreen=lambda: location, getSize=lambda: size)
        return SimpleNamespace(getAccessibleContext=lambda: context)


class Input:
    """Real-input moves over a fake tree, which reports only moves inside it.

    Before the report of move n, the main thread is busy for `busy[n]`, or for `slow` seconds.
    `dropped` moves are never reported, nor is a move made within `rearm` seconds of a report,
    as gtk3 drops a move made before it has finished with the previous report (#298). With
    `entering`, a move onto the tree from elsewhere is not reported either: VCL delivers it as
    the pointer entering the tree, which motion listeners do not hear (#253). `after(n)` may add
    reports after move n's, and `scale` stands for a tree whose coordinates are not screen pixels.
    A move above TOOLBAR crosses the window's toolbar, which settles gtk3's accessible places.
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
        self.crossed_toolbar = False
        self.created = time.monotonic()  # Reset when the fake tree is made.

    def age(self) -> float:
        return time.monotonic() - self.created

    def laid_out(self) -> bool:
        return self.age() >= self.geometry.laid_out_after

    def size(self) -> tuple[int, int]:
        width, height = self.geometry.size
        return (width, height) if self.laid_out() else (width, EARLY_HEIGHT)

    def move(self, x: int, y: int) -> None:
        self.moves.append((x, y))
        self.crossed_toolbar = self.crossed_toolbar or y < TOOLBAR
        number = len(self.moves)
        (left, top), (width, height) = self.geometry.origin, self.size()
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


def fake_lab(real_input: Input) -> Any:
    """What `Lab.calibrate` needs of its lab, with the check running named."""
    return SimpleNamespace(input=real_input, calibrations=[], check="a check")


def calibrate(
    office: Office,
    real_input: Input,
    geometry: Geometry = GEN,
    frame: tuple[int, int, int, int] = WINDOW,
    confirm: float | None = None,
    lab: Any = None,
    **constants: Any,
) -> tuple[int, int]:
    """The real `Lab.calibrate`, read from source, over a fake tree in a window at `frame`.

    `constants` replace `lab.py`'s, such as a shorter LAYOUT_SECONDS.
    """
    namespace = {**lab_calibration(confirm), **constants}
    calibration = method(LAB, "Lab", "calibrate", namespace)
    show = method(LAB, "Lab", "show_placement", namespace)
    x, y, width, height = frame
    window = SimpleNamespace(
        getPosSize=lambda: SimpleNamespace(X=x, Y=y, Width=width, Height=height)
    )
    lab = lab or fake_lab(real_input)
    lab.show_placement = partial(show, lab)
    return calibration(lab, Tree(office, geometry, real_input), window)


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


def test_a_new_gtk3_workbook_is_found_down_its_accessible_area(office: Office) -> None:
    # #301: the first point is above the tree, the second enters it and is not reported, and
    # the third is. Before, the window's scan reached the tree at its 58th point, in 17.6 s.
    # The tree's accessible location is then still 21 pixels out, until the pointer crosses
    # the window's toolbar, at the scan's first point.
    real_input = Input(office, GTK3, entering=True, rearm=0.1)
    lab = fake_lab(real_input)
    assert calibrate(office, real_input, GTK3, lab=lab) == GTK3.origin
    assert real_input.moves == [(1153, 167), (1153, 191), (1153, 215), (1155, 217), (1460, 60)]
    record = dict(lab.calibrations[0])
    assert isinstance(record.pop("seconds"), float)
    assert isinstance(record.pop("layout_seconds"), float)
    assert record == {
        "check": "a check",
        "accessible": (1123, 155, 321, 743),
        "tried": 3,
        "heard": [3],
        "point": (1153, 215),
        "step": (2, 2),
        "reports": [(28, 39), (30, 41)],
        "rejected": [],
        "accessible_drift": (-2, -21),
        "placement_drift": (-2, -21),
        "top_row_moves": 1,
        "drift_after_top_row": (-2, 4),
        "offset": GTK3.origin,
    }


def test_an_accessible_location_that_never_settles_is_recorded(
    office: Office, capsys: pytest.CaptureFixture[str]
) -> None:
    # The pointer goes along the whole top row, the calibration keeps its offset, and the log
    # says so, for a check that clicks at an accessible place and then fails (#309).
    geometry = GTK3._replace(settled=None)
    real_input = Input(office, geometry, entering=True)
    lab = fake_lab(real_input)
    assert calibrate(office, real_input, geometry, lab=lab) == GTK3.origin
    assert real_input.moves[4:] == [(x, 60) for x in range(1460, 750, -40)]
    record = lab.calibrations[0]
    assert (record["top_row_moves"], record["drift_after_top_row"]) == (18, (-2, -21))
    assert "accessible place is still (-2, -21)" in capsys.readouterr().out


def test_an_accessible_place_read_again_after_calibrating_decides(office: Office) -> None:
    # The accessible location read before calibrating is 17 pixels out and right by the time
    # the calibration ends, as gen's once was in CI: the pointer does not cross the toolbar.
    geometry = GEN._replace(accessible=(1186, 153), settled=GEN.origin, settles_after=0.45)
    real_input = Input(office, geometry)
    lab = fake_lab(real_input)
    assert calibrate(office, real_input, geometry, lab=lab) == GEN.origin
    assert real_input.moves == [at(GEN, (30, 29)), at(GEN, (32, 31))]
    record = lab.calibrations[0]
    assert (record["accessible_drift"], record["placement_drift"]) == ((0, 17), (0, 0))
    assert "top_row_moves" not in record


def test_an_accessible_place_within_the_tolerance_needs_no_top_row(office: Office) -> None:
    # Settled, gtk3's accessible place lay 4 pixels out: one a little further is not taken for
    # one 21 pixels out (#309).
    geometry = GEN._replace(accessible=(1186, 142))
    real_input = Input(office, geometry)
    lab = fake_lab(real_input)
    assert calibrate(office, real_input, geometry, lab=lab) == GEN.origin
    assert len(real_input.moves) == 2
    assert lab.calibrations[0]["placement_drift"] == (0, 6)


def test_a_tree_the_pointer_enters_at_the_first_point_is_found_at_the_second(
    office: Office,
) -> None:
    # #301: gen's first point, reached from outside the tree, is not reported. Before, the
    # window's scan then took 40 points, 12.2 s.
    # Its accessible location is right, so the pointer does not cross the toolbar.
    real_input = Input(office, entering=True)
    lab = fake_lab(real_input)
    assert calibrate(office, real_input, lab=lab) == GEN.origin
    assert real_input.moves == [at(GEN, COLUMN[0]), at(GEN, COLUMN[1]), at(GEN, (32, 38))]
    assert lab.calibrations[0]["accessible_drift"] == (0, 0)
    assert "top_row_moves" not in lab.calibrations[0]


def test_a_tree_still_being_laid_out_is_waited_for(office: Office) -> None:
    # #301: in CI, a reloaded gen tree was at most 8 pixels tall, with an accessible area 17
    # pixels low and 0 tall, when it was calibrated. No column point was left, and the window's
    # scan took 39 points, 11.9 s. The calibration now waits until the tree is laid out.
    geometry = GEN._replace(laid_out_after=0.5)
    real_input = Input(office, geometry)
    lab = fake_lab(real_input)
    assert calibrate(office, real_input, geometry, lab=lab) == GEN.origin
    assert real_input.moves == [at(GEN, COLUMN[0]), at(GEN, (32, 14))]
    record = lab.calibrations[0]
    assert record["layout_seconds"] >= 0.5
    assert (record["accessible"], record["accessible_drift"]) == ((*GEN.origin, *GEN.size), (0, 0))


def test_a_tree_never_laid_out_is_calibrated_after_the_wait(office: Office) -> None:
    # Once LAYOUT_SECONDS have passed, the calibration goes ahead: the 6-pixel tree is found by
    # the window's scan, its second move goes up, into it, and the record says it never settled.
    geometry = GEN._replace(laid_out_after=60)
    real_input = Input(office, geometry)
    lab = fake_lab(real_input)
    frame = (0, 80, 1500, 870)  # The scan's first row of points is 4 pixels into the tree.
    assert calibrate(office, real_input, geometry, frame, lab=lab, LAYOUT_SECONDS=0.5) == GEN.origin
    assert real_input.moves[:3] == [(1460, 140), (1420, 140), (1418, 138)]
    assert lab.calibrations[0]["layout_seconds"] is None


def test_the_second_move_waits_until_gtk3_hears_moves_again(office: Office) -> None:
    # #298: gtk3's tree reported the point (1380, 180) at once, as local (255, 4), and dropped
    # the second move, made as soon as that report was seen. The calibration then waited 10 s
    # and failed: "did not report the pointer's move to (1382, 182); its last report was
    # (255, 4)". The point before it was the pointer entering the tree, which is not reported.
    # Without an accessible area, the scan of the window reaches the tree as it did then.
    geometry = GTK3._replace(accessible=None)
    real_input = Input(office, geometry, entering=True, rearm=0.1)
    assert calibrate(office, real_input, geometry, GTK3_ROWS) == GTK3.origin
    # The point is in the tree's right half, so its second move goes left, into the tree.
    assert real_input.moves[-2:] == [(1380, 180), (1378, 182)]


def test_a_second_move_that_is_never_reported_moves_on_to_the_next_point(
    office: Office,
) -> None:
    # Both points are in the tree's top left quarter, so both second moves go right and down:
    # only their sizes tell the first point's pair from the second's.
    real_input = Input(office, dropped=frozenset({2}))
    lab = fake_lab(real_input)
    assert calibrate(office, real_input, confirm=0.5, lab=lab) == GEN.origin
    assert real_input.moves == [
        at(GEN, COLUMN[0]),
        at(GEN, (32, 14)),
        at(GEN, COLUMN[1]),
        at(GEN, (32, 40)),
    ]
    # The record keeps the point set aside.
    assert lab.calibrations[0]["rejected"] == [{"point": at(GEN, COLUMN[0]), "step": (2, 2)}]


def test_a_late_report_of_an_earlier_point_moves_on_to_the_next_point(office: Office) -> None:
    # Without an accessible area, the scan's first point is on the tree's left edge and the next
    # is beside it. The first point's report comes at the second, so that point's second move
    # goes unreported too, and the next row's point on the tree confirms.
    geometry = GEN._replace(accessible=None)
    real_input = Input(office, geometry, busy={1: 0.5})
    assert calibrate(office, real_input, geometry, NARROW, confirm=0.5) == GEN.origin
    assert real_input.moves == [(1200, 160), (1160, 160), (1162, 162), (1200, 200), (1202, 204)]


def test_reports_later_than_every_wait_still_give_the_true_offset(office: Office) -> None:
    # Every report comes 0.45 s after its move, after the first wait and after the quiet
    # time, so the report first heard at each point belongs to the point before. Taking the
    # second point's report for its second move's came out (+2, +2), the offset #209 found in
    # CI. Each report comes 0.15 s from the wait that it must miss or hit.
    real_input = Input(office, slow=0.45)
    assert calibrate(office, real_input) == GEN.origin
    assert real_input.moves == [at(GEN, COLUMN[0]), at(GEN, COLUMN[1]), at(GEN, (32, 38))]


def test_a_late_pair_ends_calibration_before_another_second_move(office: Office) -> None:
    # The first point's second move is reported after the point has been set aside, while the
    # next point waits for its first report: no further point is tried.
    real_input = Input(office, busy={2: 0.65})
    assert calibrate(office, real_input, confirm=0.5) == GEN.origin
    assert real_input.moves == [at(GEN, COLUMN[0]), at(GEN, (32, 14)), at(GEN, COLUMN[1])]


def test_a_late_pair_counts_for_its_own_point(office: Office) -> None:
    # The first point's report comes at the second point, which is given a second move and
    # set aside before its own reports come. They come while the third point is tried: the
    # second point's report in the third's first wait, and its second move's while the third
    # point's reports settle, so the third point is given a second move too. The pair is the
    # second point's, and gives its offset, not the third point's.
    real_input = Input(office, busy={1: 0.45, 2: 1.0, 3: 0.1, 4: 0.6})
    assert calibrate(office, real_input, confirm=0.5) == GEN.origin
    assert real_input.moves == [
        at(GEN, COLUMN[0]),
        at(GEN, COLUMN[1]),
        at(GEN, (32, 38)),
        at(GEN, COLUMN[2]),
        at(GEN, (32, 64)),
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
    assert real_input.moves[:2] == [point, (point[0] + step[0], point[1] + step[1])]


def test_reports_that_never_follow_the_moves_fail_with_the_points(office: Office) -> None:
    # A tree whose coordinates are twice the screen's: no two reports differ by a step.
    real_input = Input(office, scale=2)
    moves = [
        {"point": at(GEN, COLUMN[0]), "step": (2, 2)},
        {"point": at(GEN, COLUMN[1]), "step": (2, 4)},
        {"point": at(GEN, COLUMN[2]), "step": (4, 2)},
    ]
    message = f"differ by a point's second move; the points and their second moves: {moves}"
    with pytest.raises(AssertionError, match=re.escape(message)) as raised:
        calibrate(office, real_input, confirm=0.5)
    assert len(real_input.moves) == 2 * len(STEPS)
    # Only the message records a failed calibration, so it keeps where the tree said it was.
    assert str(raised.value).endswith("; accessible (1186, 136, 273, 784); tree (4, 38, 273, 784)")


def test_a_tree_that_reports_no_point_fails(office: Office) -> None:
    real_input = Input(office, dropped=frozenset(range(1, 10)))
    message = "Calibrating the sheet list: the pointer never reached it at any of 7 points"
    with pytest.raises(AssertionError, match=re.escape(message)):
        calibrate(office, real_input, frame=(0, 0, 200, 140))
    assert len(real_input.moves) == 7


def test_the_points_go_down_the_accessible_area_and_keep_clear_of_each_other() -> None:
    # #209's first point is 8 pixels from a point of the window's scan, which is left out.
    list_points = lab_calibration()["list_points"]
    frame = SimpleNamespace(X=0, Y=0, Width=1500, Height=950)
    found = list_points((*GEN.origin, *GEN.size), frame)  # Where GEN's accessible area is.
    assert found[:5] == [at(GEN, (30, 12 + 24 * index)) for index in range(5)]
    assert (1220, 140) in list_points(None, frame)
    assert (1220, 140) not in found
    assert all(
        max(abs(x - a), abs(y - b)) >= 20
        for index, (x, y) in enumerate(found)
        for a, b in found[index + 1 :]
    )
    # A short area keeps the points inside it.
    assert list_points((*GEN.origin, 273, 40), frame)[:3] == [
        at(GEN, (30, 12)),
        at(GEN, (30, 36)),
        (1460, 60),
    ]


def test_points_closer_than_the_spacing_are_refused_before_any_move(office: Office) -> None:
    # #300: the moves of points 3 pixels apart can differ by another point's step, and at 14
    # pixels two reports each 1 pixel off toward the other can too.
    confirmed_offset = lab_calibration()["confirmed_offset"]
    real_input = Input(office)
    with pytest.raises(
        AssertionError, match=re.escape("closer than 15 pixels: [((40, 0), (40, 14))]")
    ):
        confirmed_offset(real_input, Tracker(), [(0, 0), (40, 0), (40, 14)], (100, 100))
    assert real_input.moves == []
    # 15 pixels apart are accepted, and tried.
    with pytest.raises(AssertionError, match="never reached it at any of 2 points"):
        confirmed_offset(real_input, Tracker(), [(0, 0), (0, 15)], (100, 100))
    assert real_input.moves == [(0, 0), (0, 15)]
