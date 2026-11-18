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
        """Find the tree's screen offset: move the pointer and ask the tree where it is."""
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
                    self.input.move(x + 2, y + 2)
                    time.sleep(0.2)
                    local = tracker.last
                    return (x + 2 - local[0], y + 2 - local[1])
            raise AssertionError("The pointer never reached the sheet list")
        finally:
            tree.removeMouseMotionListener(tracker)
