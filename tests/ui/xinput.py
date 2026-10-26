"""Real pointer, wheel, and keyboard input through the X server's XTEST extension.

Only for the private Xvfb display of the Linux test image; never point DISPLAY at a desktop.
Uses ctypes so that LibreOffice's bundled Python needs no extra packages.
"""

import ctypes
import os
import re
import subprocess
import time

_x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
_xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
_x11.XOpenDisplay.restype = ctypes.c_void_p
_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
_x11.XAutoRepeatOff.argtypes = [ctypes.c_void_p]
_x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
_x11.XStringToKeysym.restype = ctypes.c_ulong
_x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_x11.XKeysymToKeycode.restype = ctypes.c_ubyte
_xtst.XTestQueryExtension.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_int)] * 4
_xtst.XTestFakeMotionEvent.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_ulong,
]
_xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
_xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]

LEFT, RIGHT, WHEEL_UP, WHEEL_DOWN = 1, 3, 4, 5


class XInput:
    def __init__(self):
        if os.environ.get("SHEET_MANAGER_PRIVATE_DISPLAY") != "1" or not os.environ.get("DISPLAY"):
            raise RuntimeError("XTEST input needs the private Xvfb launcher's explicit opt-in")
        self._display = _x11.XOpenDisplay(None)
        if not self._display:
            raise RuntimeError("Cannot open the X display")
        values = [ctypes.c_int() for _ in range(4)]
        if not _xtst.XTestQueryExtension(self._display, *(ctypes.byref(v) for v in values)):
            raise RuntimeError("The X server has no XTEST extension")
        # A descheduled client between a flushed press and release must not turn one
        # intended tap into repeated keys. This display belongs to the private test lab.
        _x11.XAutoRepeatOff(self._display)
        self._sync()

    def _sync(self):
        _x11.XSync(self._display, 0)

    def popup_windows(self):
        """Mapped X11 popup windows on this private display, independent of Calc tab state."""
        children = subprocess.check_output(["xwininfo", "-root", "-children"], text=True, timeout=5)
        visible = set()
        for window in re.findall(r"^\s+(0x[0-9a-fA-F]+)\s", children, re.MULTILINE):
            info = subprocess.check_output(["xwininfo", "-id", window], text=True, timeout=5)
            width = re.search(r"Width:\s+(\d+)", info)
            height = re.search(r"Height:\s+(\d+)", info)
            if (
                "Map State: IsViewable" in info
                and "Override Redirect State: yes" in info
                and width is not None
                and height is not None
                and int(width[1]) > 1
                and int(height[1]) > 1
            ):
                visible.add(window)
        return visible

    def move(self, x, y):
        _xtst.XTestFakeMotionEvent(self._display, -1, int(x), int(y), 0)
        self._sync()

    def button(self, button, down):
        _xtst.XTestFakeButtonEvent(self._display, button, 1 if down else 0, 0)
        self._sync()

    def key(self, keysym, down):
        code = _x11.XKeysymToKeycode(self._display, _x11.XStringToKeysym(keysym.encode()))
        if not code:
            raise ValueError(f"No key code for {keysym}")
        _xtst.XTestFakeKeyEvent(self._display, code, 1 if down else 0, 0)
        self._sync()

    def tap(self, keysym, modifiers=(), pause=0.08):
        for modifier in modifiers:
            self.key(modifier, True)
        self.key(keysym, True)
        self.key(keysym, False)
        for modifier in reversed(modifiers):
            self.key(modifier, False)
        time.sleep(pause)


class Pointer:
    """Pointer input in a window's own coordinates, given that window's screen offset."""

    def __init__(self, xinput, offset):
        self.input = xinput
        self.offset = offset

    def at(self, x, y, pause=0.03):
        self.input.move(self.offset[0] + x, self.offset[1] + y)
        time.sleep(pause)

    def click(self, x, y, modifiers=(), button=LEFT, pause=0.6):
        # The pause keeps the next click on the same row from becoming a double click.
        for modifier in modifiers:
            self.input.key(modifier, True)
        self.at(x, y)
        self.input.button(button, True)
        time.sleep(0.05)
        self.input.button(button, False)
        time.sleep(0.05)
        for modifier in reversed(modifiers):
            self.input.key(modifier, False)
        time.sleep(pause)

    def press(self, x, y, button=LEFT):
        self.at(x, y)
        self.input.button(button, True)
        time.sleep(0.05)

    def release(self, button=LEFT):
        self.input.button(button, False)
        time.sleep(0.05)

    def glide(self, start, end, step=3, pause=0.02):
        """Move in small steps, as a hand does, so that drag feedback sees every position."""
        (x0, y0), (x1, y1) = start, end
        steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / step))
        for index in range(1, steps + 1):
            self.at(x0 + (x1 - x0) * index / steps, y0 + (y1 - y0) * index / steps, pause)

    def wheel(self, x, y, down, ticks):
        self.at(x, y)
        for _ in range(ticks):
            button = WHEEL_DOWN if down else WHEEL_UP
            self.input.button(button, True)
            self.input.button(button, False)
            time.sleep(0.05)
        time.sleep(0.4)
