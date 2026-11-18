"""The private Xvfb lab: real XTEST input, whole-display screenshots and pointer calibration.

Checks reach the desktop only through a lab (see `workbook.py`). `run_ui.py` and
`update_dialog.py` use this one on their private displays; `run_windows_ui.WindowsLab` keeps its
`calibrate` and replaces input, window placement, screenshots and failure evidence for the
Windows desktop. Screenshots run the lab's system Python/Pillow, outside LibreOffice's Python
environment.
"""

import os
import subprocess
import time

import unohelper
from com.sun.star.awt import XMouseMotionListener
from xinput import XInput


class Tracker(unohelper.Base, XMouseMotionListener):
    """Records where the tree last saw the pointer, in its own coordinates."""

    def __init__(self):
        self.last = None

    def mouseMoved(self, e):
        self.last = (e.X, e.Y)

    def mouseDragged(self, e):
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

        The tree's first report shows that the pointer has reached it; the offset comes from its
        report of a second move, 2 pixels further on both axes. The tree hears a move only when
        LibreOffice's main thread gets to it, which a busy office delays, so `settled_report`
        waits for that report rather than a fixed time. Reading it after a fixed 0.2 seconds
        once took the first position for the second and gave an offset 2 pixels too large on
        both axes, which the painted-row check then saw as misplaced dividers (#209).
        """
        tracker = Tracker()
        tree.addMouseMotionListener(tracker)
        try:
            candidates = []
            try:
                accessible = tree.getProperty("XAccessible").getAccessibleContext()
                location = accessible.getLocationOnScreen()
                candidates.append((location.X + 30, location.Y + 12))
            except Exception:
                pass
            frame = window.getPosSize()
            for y in range(frame.Y + 60, frame.Y + frame.Height - 40, 40):
                for x in range(frame.X + frame.Width - 40, frame.X + frame.Width // 2, -40):
                    candidates.append((x, y))
            for x, y in candidates:
                tracker.last = None
                self.input.move(x, y)
                deadline = time.monotonic() + 0.3
                while tracker.last is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                if tracker.last is not None:
                    first = tracker.last
                    self.input.move(x + 2, y + 2)
                    local = settled_report(tracker, first, (x + 2, y + 2))
                    return (x + 2 - local[0], y + 2 - local[1])
            raise AssertionError("The pointer never reached the sheet list")
        finally:
            tree.removeMouseMotionListener(tracker)


def settled_report(tracker, first, target, quiet=0.3, timeout=10):
    """Where the tree says the pointer is, now that it has stopped at `target` after `first`.

    The tree's reports arrive in the order of the moves, so its last report, once it has
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
                f"The tree did not report the pointer's move to {target}; "
                f"its last report was {first}"
            )
        time.sleep(0.02)
        latest = tracker.last
    changed = time.monotonic()
    deadline = changed + timeout
    while time.monotonic() - changed < quiet:
        if time.monotonic() > deadline:
            raise AssertionError(f"The tree kept reporting new positions after a move to {target}")
        time.sleep(0.02)
        report = tracker.last
        if report is not None and report != latest:
            latest, changed = report, time.monotonic()
    return latest
