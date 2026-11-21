"""The private Xvfb lab: real XTEST input, whole-display screenshots and pointer calibration.

Checks reach the desktop only through a lab (see `workbook.py`). `run_ui.py` and
`update_dialog.py` use this one on their private displays; `run_windows_ui.WindowsLab` keeps its
`calibrate` and replaces input, window placement, screenshots and failure evidence for the
Windows desktop. Screenshots run the lab's system Python/Pillow, outside LibreOffice's Python
environment. `Tracker` and `confirmed_offset` also calibrate the rename dialog
(`rename_dialog.Dialog.calibrate`, #300).
"""

import os
import subprocess
import time

import unohelper
from com.sun.star.awt import XMouseMotionListener
from xinput import XInput

# Calibration (#298): how long a window may take to report a point before the next point is
# tried, and to report that point's second move before the point is set aside.
FIRST_SECONDS = 0.3
CONFIRM_SECONDS = 2
# The second moves, one for each point given one; calibration fails once all have been used
# without a pair. No two have the same slope, whatever their signs, so that two reports that
# differ by one of them belong to that step's point, also in a window whose coordinates are
# scaled, which would stretch another step's pair but not turn it.
STEPS = ((2, 2), (2, 4), (4, 2))
# How far apart, on at least one axis, the points must be (#300). A step is at most 4 pixels on
# each axis and a landing can be 1 pixel off, so the moves of two points this far apart never
# differ by a step: they can close the distance by 4 + 4 + 1 pixels and still differ by 5.
SPACING = 14
# The points down the tree's accessible area that come before the window's (#301): how many,
# how far apart, and how far in from the area's left and top.
COLUMN = (5, 24, (30, 12))
# How far the tree's accessible location may lie from its calibrated place before the lab makes
# gtk3 learn where its window is (#301). Settled, gtk3's lies 2 and 4 pixels out, gen's and
# Windows' nowhere; unsettled, gtk3's was 21 pixels above the tree.
PLACEMENT_TOLERANCE = 4


class Tracker(unohelper.Base, XMouseMotionListener):
    """Records every position a window reports for the pointer, in its own coordinates."""

    def __init__(self):
        self.last = None
        self.reports = []

    def mouseMoved(self, e):
        self.reports.append((e.X, e.Y))
        self.last = (e.X, e.Y)

    def mouseDragged(self, e):
        self.reports.append((e.X, e.Y))
        self.last = (e.X, e.Y)

    def disposing(self, Source):
        pass


class Lab:
    def __init__(self, context, desktop, directory, output):
        self.context = context
        self.desktop = desktop
        self.directory = directory
        self.output = output
        self.input = XInput()
        # How each sheet list calibration went, for the session's results (#301).
        self.calibrations = []

    def place(self, window):
        """Give a document window the lab's fixed size on the private display."""
        window.IsMaximized = False
        window.setPosSize(0, 0, 1500, 950, 15)

    def failure_evidence(self):
        """Desktop state worth keeping beside a failed check's screenshot; none under Xvfb."""
        return {}

    def screenshot(self, name):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "URE_BOOTSTRAP")
        }
        subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                "-c",
                "from PIL import ImageGrab; import sys; ImageGrab.grab().save(sys.argv[1])",
                str(self.output / f"{name}.png"),
            ],
            check=True,
            env=environment,
        )

    def calibrate(self, tree, window):
        """Find the tree's screen offset: move the pointer and ask the tree where it is.

        `list_points` chooses the points, and `confirmed_offset` takes the offset only from the
        tree's reports of a point and of that point's own second move. The tree hears a move
        only when LibreOffice's main thread gets to it, which a busy office delays: reading the
        second report after a fixed 0.2 seconds once took the first position for it, and the
        offset came out 2 pixels too large on both axes (#209). `calibrations` gets the record
        of each calibration that succeeds, with the accessible area, what `show_placement` did
        and the seconds it took.
        """
        started = time.monotonic()
        size = tree.getPosSize()
        try:
            context = tree.getProperty("XAccessible").getAccessibleContext()
            location, extent = context.getLocationOnScreen(), context.getSize()
            area = (location.X, location.Y, extent.Width, extent.Height)
        except Exception:
            area = None
        # The column goes down the tree's own height from its accessible location: a reloaded
        # panel's tree once had an accessible height of 0 while it was laid out (#301).
        column = None if area is None else (area[0], area[1], size.Width, size.Height)
        tracker = Tracker()
        tree.addMouseMotionListener(tracker)
        try:
            offset, found = confirmed_offset(
                self.input,
                tracker,
                list_points(column, window.getPosSize()),
                (size.Width, size.Height),
            )
        except AssertionError as error:
            raise AssertionError(
                f"Calibrating the sheet list: {error}; accessible {area}"
            ) from None
        finally:
            tree.removeMouseMotionListener(tracker)
        if area is not None:
            found.update(self.show_placement(tree, window, offset, area))
        seconds = round(time.monotonic() - started, 2)
        self.calibrations.append(
            {"accessible": area, **found, "offset": offset, "seconds": seconds}
        )
        return offset

    def show_placement(self, tree, window, offset, area):
        """Make gtk3 learn where the window manager put a new window, if it has not (#301).

        Until the pointer crosses the window's toolbar, gtk3 places every accessible location in
        a window it has just shown 25 pixels above its settled place, which put the tree's 21
        pixels above the tree. Moves in the tree or over the cells do not correct it; 40 seconds
        without input did not either. The window scan's first row, which every new workbook's
        calibration crossed before #301, did. Without it, `tab_selection_sync`'s Ctrl+click at
        the native sheet tab's accessible centre hit the scroll bar above the tabs. So when the
        tree's accessible location lies more than PLACEMENT_TOLERANCE from its calibrated place,
        the pointer goes along that row until it does not. Returns the difference before and,
        when the row was used, after it and the moves made.
        """
        drift = (area[0] - offset[0], area[1] - offset[1])
        found = {"accessible_drift": drift}
        if max(map(abs, drift)) <= PLACEMENT_TOLERANCE:
            return found
        frame = window.getPosSize()
        moves = 0
        for x in range(frame.X + frame.Width - 40, frame.X + frame.Width // 2, -40):
            self.input.move(x, frame.Y + 60)
            moves += 1
            time.sleep(0.05)
            location = tree.getProperty("XAccessible").getAccessibleContext().getLocationOnScreen()
            drift = (location.X - offset[0], location.Y - offset[1])
            if max(map(abs, drift)) <= PLACEMENT_TOLERANCE:
                break
        return {**found, "top_row_moves": moves, "drift_after_top_row": drift}


def list_points(area, frame):
    """The points that calibrate the sheet list: down its accessible area, then the window's.

    `area` is the tree's accessible location on screen with the tree's own size, (x, y, width,
    height). The location can be wrong: in a gtk3 workbook that had just opened, it was 21
    pixels above the tree (#298). Nor is a move onto the tree from elsewhere reported: it is
    the pointer entering the tree (#253). So `COLUMN`'s points go down the area, each reached
    from the one before, and one inside the tree counts even when the area is that far out or
    the first point entered the tree. Without them, a new workbook's calibration often scanned
    the window for 12 to 18 seconds (#301). The window's points cover its right half, 40 pixels
    apart; one within 20 pixels of an earlier point is left out, which keeps every point
    `SPACING` apart.
    """
    found = []
    if area is not None:
        count, apart, (left, top) = COLUMN
        x, y, _, height = area
        column = [(x + left, y + top + apart * index) for index in range(count)]
        found = [point for point in column if point[1] < y + height]
    for y in range(frame.Y + 60, frame.Y + frame.Height - 40, 40):
        for x in range(frame.X + frame.Width - 40, frame.X + frame.Width // 2, -40):
            if all(max(abs(x - a), abs(y - b)) >= 20 for a, b in found):
                found.append((x, y))
    return found


def confirmed_offset(real_input, tracker, points, size):
    """Try `points` until a window of `size` confirms one; return its screen offset and a record.

    `tracker` listens to the window. A point that the window reports within FIRST_SECONDS
    gets a second move once the window's reports have stopped for `settled_report`'s quiet
    time. gtk3 drops a move made before it has finished with the previous report, and a busy
    machine stretches that time: moved at once, the second move went unreported in one
    calibration in five beside other busy processes.

    Each point's second move is the next step in `STEPS`, pointed into the window from the
    point's settled report, so that a point near an edge keeps its second move inside. Two
    reports that differ by a point's step are that point's own two moves, however late they
    came, so the offset follows from that point, never from the point being tried when they
    arrive. A point whose reports do not pair within CONFIRM_SECONDS, because the window
    dropped the second move, the second move left the window, or the first report belonged to
    an earlier point, is set aside and the next point is tried; a late pair still counts when
    it arrives (#298). That holds only for points `SPACING` apart, so closer ones are refused
    before any move (#300). Fails, with each point given a second move and every report, once
    every step has been used or the points have run out, and when the window reports none of
    the points.

    The record lists how many points were tried, which of them the window reported within
    FIRST_SECONDS, the point that counted with its step and its two reports, and the other
    points given a second move.
    """
    close = [
        (a, b)
        for index, a in enumerate(points)
        for b in points[index + 1 :]
        if max(abs(a[0] - b[0]), abs(a[1] - b[1])) < SPACING
    ]
    assert not close, f"calibration points closer than {SPACING} pixels: {close[:3]}"
    moves, heard = [], []

    def found(tried, match):
        point, step, first, second = match
        record = {"tried": tried, "heard": heard, "point": point, "step": step}
        others = [{"point": other, "step": rest} for other, rest in moves if other != point]
        record.update(reports=[first, second], rejected=others)
        return (point[0] + step[0] - second[0], point[1] + step[1] - second[1]), record

    for tried, (x, y) in enumerate(points, 1):
        tracker.last = None
        real_input.move(x, y)
        deadline = time.monotonic() + FIRST_SECONDS
        while tracker.last is None and time.monotonic() < deadline:
            time.sleep(0.02)
        match = _paired(tracker, moves, 0)
        if match is not None:
            return found(tried, match)
        if tracker.last is None:
            continue
        heard.append(tried)
        near = settled_report(tracker, None, (x, y))
        step = tuple(
            length if at < extent / 2 else -length
            for length, at, extent in zip(STEPS[len(moves)], near, size, strict=True)
        )
        moves.append(((x, y), step))
        real_input.move(x + step[0], y + step[1])
        match = _paired(tracker, moves, CONFIRM_SECONDS)
        if match is not None:
            return found(tried, match)
        if len(moves) == len(STEPS):
            break
    if not moves:
        raise AssertionError(f"the pointer never reached it at any of {len(points)} points")
    raise AssertionError(
        "no two of its reports differ by a point's second move; the points and their second "
        f"moves: {[{'point': point, 'step': step} for point, step in moves]}; "
        f"its reports: {tracker.reports}"
    )


def _paired(tracker, moves, seconds):
    """Two of the window's reports that prove an offset within `seconds`, or None.

    Two reports prove an offset when the later differs from the earlier by a point's step.
    Returns that point, its step and the two reports.
    """
    deadline = time.monotonic() + seconds
    while True:
        reports = list(tracker.reports)
        for index, first in enumerate(reports):
            for second in reports[index + 1 :]:
                for point, step in moves:
                    if (second[0] - first[0], second[1] - first[1]) == step:
                        return point, step, first, second
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.02)


def settled_report(tracker, first, target, quiet=0.3, timeout=10):
    """Where a window says the pointer is, now that it has stopped at `target` after `first`.

    `first` is the window's last report before the move to `target`, or None if it had none.
    The window's reports arrive in the order of the moves, so its last report, once it has
    reported something other than `first` and then nothing new for `quiet` seconds, is the
    position at `target`. Waiting for a newer report rather than a fixed time keeps a late report
    from being missed; waiting for quiet keeps a further report of the earlier position, such as
    a corrected landing, from being taken for it. Fails, with both positions, if no newer report
    arrives within `timeout` seconds, and if reports then keep changing for `timeout` seconds.
    """
    deadline = time.monotonic() + timeout
    latest = tracker.last
    while latest is None or latest == first:
        if time.monotonic() > deadline:
            raise AssertionError(
                f"The window did not report the pointer's move to {target}; "
                f"its last report was {first}"
            )
        time.sleep(0.02)
        latest = tracker.last
    changed = time.monotonic()
    deadline = changed + timeout
    while time.monotonic() - changed < quiet:
        if time.monotonic() > deadline:
            raise AssertionError(
                f"The window kept reporting new positions after a move to {target}"
            )
        time.sleep(0.02)
        report = tracker.last
        if report is not None and report != latest:
            latest, changed = report, time.monotonic()
    return latest
