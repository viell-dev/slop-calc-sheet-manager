"""The private Xvfb lab: real XTEST input, whole-display screenshots and pointer calibration.

Checks reach the desktop only through a lab (see `workbook.py`). `run_ui.py` and
`update_dialog.py` use this one on their private displays; `run_windows_ui.WindowsLab` keeps its
`calibrate` and replaces input, window placement, screenshots and failure evidence for the
Windows desktop. Screenshots run the lab's system Python/Pillow, outside LibreOffice's Python
environment. `Tracker` and `settled_report` also calibrate the rename dialog
(`rename_dialog.Dialog.calibrate`).
"""

import os
import subprocess
import time

import unohelper
from com.sun.star.awt import XMouseMotionListener
from xinput import XInput

# The sheet list's calibration (#298): how long the tree may take to report a point before the
# next point is tried, and to report that point's second move before the point is set aside.
FIRST_SECONDS = 0.3
CONFIRM_SECONDS = 2
# The second moves, one for each point given one; calibration fails once all have been used
# without a pair. No two have the same slope, whatever their signs, so that two reports that
# differ by one of them belong to that step's point, also in a window whose coordinates are
# scaled, which would stretch another step's pair but not turn it.
STEPS = ((2, 2), (2, 4), (4, 2))


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
        offset came out 2 pixels too large on both axes (#209).
        """
        try:
            location = tree.getProperty("XAccessible").getAccessibleContext().getLocationOnScreen()
        except Exception:
            location = None
        size = tree.getPosSize()
        tracker = Tracker()
        tree.addMouseMotionListener(tracker)
        try:
            return confirmed_offset(
                self.input,
                tracker,
                list_points(location, window.getPosSize()),
                (size.Width, size.Height),
            )
        except AssertionError as error:
            raise AssertionError(f"Calibrating the sheet list: {error}") from None
        finally:
            tree.removeMouseMotionListener(tracker)


def list_points(location, frame):
    """The points that calibrate the sheet list: near its accessible location, then the window's.

    The accessible location can be wrong: in a gtk3 workbook that had just opened, it was 21
    pixels above the tree (#298). The window's points cover its right half, 40 pixels apart.
    A window point within 20 pixels of the first point is left out, so that moves to different
    points, or those moves and their second moves of at most 4 pixels, never differ by a step
    in `STEPS`.
    """
    found = [] if location is None else [(location.X + 30, location.Y + 12)]
    for y in range(frame.Y + 60, frame.Y + frame.Height - 40, 40):
        for x in range(frame.X + frame.Width - 40, frame.X + frame.Width // 2, -40):
            if all(max(abs(x - a), abs(y - b)) >= 20 for a, b in found):
                found.append((x, y))
    return found


def confirmed_offset(real_input, tracker, points, size):
    """Try `points` until a window of `size` confirms one, and return its screen offset (#298).

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
    it arrives. Fails, with each point given a second move and every report, once every step
    has been used or the points have run out, and when the window reports none of the points.
    """
    moves = []
    for x, y in points:
        tracker.last = None
        real_input.move(x, y)
        deadline = time.monotonic() + FIRST_SECONDS
        while tracker.last is None and time.monotonic() < deadline:
            time.sleep(0.02)
        offset = _paired(tracker, moves, 0)
        if offset is not None:
            return offset
        if tracker.last is None:
            continue
        near = settled_report(tracker, None, (x, y))
        step = tuple(
            length if at < extent / 2 else -length
            for length, at, extent in zip(STEPS[len(moves)], near, size, strict=True)
        )
        moves.append(((x, y), step))
        real_input.move(x + step[0], y + step[1])
        offset = _paired(tracker, moves, CONFIRM_SECONDS)
        if offset is not None:
            return offset
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
    """The offset that two of the window's reports prove within `seconds`, or None.

    Two reports prove an offset when the later differs from the earlier by a point's step.
    """
    deadline = time.monotonic() + seconds
    while True:
        reports = list(tracker.reports)
        for index, first in enumerate(reports):
            for second in reports[index + 1 :]:
                for (x, y), (dx, dy) in moves:
                    if (second[0] - first[0], second[1] - first[1]) == (dx, dy):
                        return (x + dx - second[0], y + dy - second[1])
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
