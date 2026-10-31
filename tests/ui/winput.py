"""Real pointer and keyboard input through Win32 `SendInput`, on a visible Windows desktop.

Only for a disposable GitHub-hosted runner, whose job runs in the active console session
(#114): `.github/workflows/windows-desktop.yml` opts in with SHEET_MANAGER_REAL_DESKTOP=1.
The input goes to whatever window has the focus on that desktop, so never run it on a person's
computer. It is the Windows counterpart of `xinput.XInput`, with the same interface and the same
X keysym names, so that `xinput.Pointer` and the shared checks of `run_ui.py` drive either.

Rules for changing it:

- Input goes only through `SendInput`, the path a keyboard or mouse driver's events take, never
  through window messages or LibreOffice's own synthetic events: those bypass the key handler and
  cannot start a native drag, which is what this suite exists to observe.
- Keys use the en-US layout's virtual-key codes in `KEYS`, with scan codes from the live
  layout; `WinInput` refuses another layout rather than typing different characters.
- Pointer positions are absolute screen pixels, normalised to the live virtual screen and read
  back with `GetCursorPos`; this process is made per-monitor DPI aware first, so that the pixels
  agree with LibreOffice's own screen coordinates. Never assume the screen size or DPI.
- Popups and modal dialogs are found among the office process's visible top-level windows, by
  window style, as `xinput` finds X11 popups by their override-redirect state. `inventory()`
  records what was seen, for failure evidence.
- 64-bit Windows only, which the pinned MSI is: there `CDLL` and `CFUNCTYPE` use the platform's
  one calling convention, which also lets Pyright check this module on Linux. Nothing here loads
  a Windows library until `WinInput` is created, so the pure parts are unit-tested anywhere.
"""

import ctypes
import os
import platform
import struct
import time
import zlib
from typing import Any

LEFT, MIDDLE, RIGHT, WHEEL_UP, WHEEL_DOWN = 1, 2, 3, 4, 5

# X keysym name -> (en-US virtual-key code, extended key). Letters and digits are their own codes.
KEYS: dict[str, tuple[int, bool]] = {
    "BackSpace": (0x08, False),
    "Tab": (0x09, False),
    "Return": (0x0D, False),
    "Escape": (0x1B, False),
    "space": (0x20, False),
    "Prior": (0x21, True),
    "Next": (0x22, True),
    "End": (0x23, True),
    "Home": (0x24, True),
    "Left": (0x25, True),
    "Up": (0x26, True),
    "Right": (0x27, True),
    "Down": (0x28, True),
    "Insert": (0x2D, True),
    "Delete": (0x2E, True),
    "Menu": (0x5D, True),
    "Shift_L": (0x10, False),
    "Control_L": (0x11, False),
    "Alt_L": (0x12, False),
    # Characters by the key that types them unshifted; callers press Shift where X needs it.
    "numbersign": (0x33, False),
    "slash": (0xBF, False),
    "minus": (0xBD, False),
    "period": (0xBE, False),
    "comma": (0xBC, False),
    **{f"F{number}": (0x6F + number, False) for number in range(1, 13)},
    **{chr(code).lower(): (code, False) for code in range(ord("A"), ord("Z") + 1)},
    **{chr(code): (code, False) for code in range(ord("0"), ord("9") + 1)},
}
EN_US = 0x0409
# How long a tap holds its key, as a hand does. Windows generates no repeat for injected keys,
# and native loops that sample key state, such as a drag's, can miss a shorter press.
KEY_HOLD = 0.05

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
MOUSEEVENTF_WHEEL, WHEEL_DELTA = 0x0800, 120
BUTTON_FLAGS = {LEFT: (0x0002, 0x0004), RIGHT: (0x0008, 0x0010), MIDDLE: (0x0020, 0x0040)}
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
GWL_STYLE, GWL_EXSTYLE, GW_OWNER = -16, -20, 4
WS_POPUP, WS_CAPTION = 0x80000000, 0x00C00000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DESKTOP_SWITCHDESKTOP = 0x0100
PER_MONITOR_AWARE_V2 = -4
OFFICE_IMAGE = "soffice.bin"


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint32),
        ("wParamL", ctypes.c_uint16),
        ("wParamH", ctypes.c_uint16),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_int32),
        ("top", ctypes.c_int32),
        ("right", ctypes.c_int32),
        ("bottom", ctypes.c_int32),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


ENUM_WINDOWS = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _last_error() -> int:
    """The thread's last Win32 error, as `use_last_error` libraries keep it (Windows only)."""
    return getattr(ctypes, "get_last_error")()  # noqa: B009 - absent from typeshed off Windows


def normalised(pixel: int, origin: int, size: int) -> int:
    """A screen pixel as SendInput's absolute coordinate, 0 to 65535 across the virtual screen."""
    return round((pixel - origin) * 65535 / max(1, size - 1))


def png_bytes(width: int, height: int, bgra: bytes) -> bytes:
    """Encode top-down 32-bit BGRA pixels as an RGB PNG, without a third-party library."""
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    stride = width * 3
    raw = b"".join(b"\0" + bytes(rgb[row * stride : (row + 1) * stride]) for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def _libraries() -> tuple[Any, Any, Any]:
    user32 = ctypes.CDLL("user32", use_last_error=True)
    kernel32 = ctypes.CDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.CDLL("gdi32", use_last_error=True)
    handle = ctypes.c_void_p
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
    user32.MapVirtualKeyW.restype = ctypes.c_uint
    user32.GetKeyboardLayout.argtypes = [ctypes.c_uint32]
    user32.GetKeyboardLayout.restype = handle
    user32.EnumWindows.argtypes = [ENUM_WINDOWS, handle]
    user32.IsWindowVisible.argtypes = [handle]
    user32.GetWindowThreadProcessId.argtypes = [handle, ctypes.POINTER(ctypes.c_uint32)]
    user32.GetWindowLongPtrW.argtypes = [handle, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowRect.argtypes = [handle, ctypes.POINTER(RECT)]
    user32.GetClassNameW.argtypes = [handle, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [handle, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindow.argtypes = [handle, ctypes.c_uint]
    user32.GetWindow.restype = handle
    user32.GetForegroundWindow.restype = handle
    user32.GetDC.argtypes = [handle]
    user32.GetDC.restype = handle
    user32.ReleaseDC.argtypes = [handle, handle]
    user32.SetProcessDpiAwarenessContext.argtypes = [handle]
    user32.GetDpiForSystem.restype = ctypes.c_uint
    user32.GetThreadDpiAwarenessContext.restype = handle
    user32.GetAwarenessFromDpiAwarenessContext.argtypes = [handle]
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = handle
    kernel32.QueryFullProcessImageNameW.argtypes = [
        handle,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel32.CloseHandle.argtypes = [handle]
    kernel32.ProcessIdToSessionId.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    user32.OpenInputDesktop.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    user32.OpenInputDesktop.restype = handle
    user32.CloseDesktop.argtypes = [handle]
    gdi32.CreateCompatibleDC.argtypes = [handle]
    gdi32.CreateCompatibleDC.restype = handle
    gdi32.CreateDIBSection.argtypes = [
        handle,
        ctypes.POINTER(BITMAPINFOHEADER),
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p),
        handle,
        ctypes.c_uint32,
    ]
    gdi32.CreateDIBSection.restype = handle
    gdi32.SelectObject.argtypes = [handle, handle]
    gdi32.SelectObject.restype = handle
    gdi32.BitBlt.argtypes = [handle] + [ctypes.c_int] * 4 + [handle] + [ctypes.c_int] * 2
    gdi32.BitBlt.argtypes += [ctypes.c_uint32]
    gdi32.DeleteObject.argtypes = [handle]
    gdi32.DeleteDC.argtypes = [handle]
    return user32, kernel32, gdi32


class WinInput:
    """`xinput.XInput`'s interface on the real Windows desktop of this session."""

    def __init__(self):
        self.held = set()  # Buttons pressed and not yet released.
        # platform.system(), not os.name: Pyright would treat the rest as unreachable on Linux.
        if platform.system() != "Windows" or os.environ.get("SHEET_MANAGER_REAL_DESKTOP") != "1":
            raise RuntimeError("SendInput needs the disposable runner's explicit opt-in")
        if ctypes.sizeof(ctypes.c_void_p) != 8 or ctypes.sizeof(INPUT) != 40:
            raise RuntimeError("SendInput structures are laid out for 64-bit Windows only")
        self._user32, self._kernel32, self._gdi32 = _libraries()
        # Physical pixels everywhere, as LibreOffice uses. This fails when the interpreter's
        # manifest has already set an awareness; `desktop()` records the one in effect.
        self._user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR_AWARE_V2))
        layout = self._user32.GetKeyboardLayout(0) or 0
        if layout & 0xFFFF != EN_US:
            raise RuntimeError(f"The keys are mapped for en-US, not layout {layout & 0xFFFF:#06x}")
        self.pointer_corrections = 0  # Absolute moves that needed a second step to land.
        self._images: dict[int, bool] = {}
        self.last_inventory: list[dict[str, Any]] = []

    # The desktop

    def screen(self):
        """The virtual screen's origin and size, and the system DPI, read now."""
        metrics = self._user32.GetSystemMetrics
        return {
            "x": metrics(SM_XVIRTUALSCREEN),
            "y": metrics(SM_YVIRTUALSCREEN),
            "width": metrics(SM_CXVIRTUALSCREEN),
            "height": metrics(SM_CYVIRTUALSCREEN),
            "dpi": int(self._user32.GetDpiForSystem()),
        }

    def desktop(self):
        """Whether this process can reach the interactive desktop, and what that desktop is.

        Session 0 has no interactive desktop: LibreOffice is invisible there and input never
        reaches it, as on the maintainers' own agent shells.
        """
        session = ctypes.c_uint32()
        self._kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
        handle = self._user32.OpenInputDesktop(0, 0, DESKTOP_SWITCHDESKTOP)
        if handle:
            self._user32.CloseDesktop(handle)
        layout = self._user32.GetKeyboardLayout(0) or 0
        return {
            "session": session.value,
            "input_desktop": bool(handle),
            "keyboard_layout": f"{layout & 0xFFFF:#06x}",
            # 0 unaware (scaled), 1 system aware, 2 per-monitor aware.
            "dpi_awareness": self._user32.GetAwarenessFromDpiAwarenessContext(
                self._user32.GetThreadDpiAwarenessContext()
            ),
            **self.screen(),
        }

    def screenshot(self, path):
        """Save the whole virtual screen as a PNG."""
        screen = self.screen()
        width, height = screen["width"], screen["height"]
        source = self._user32.GetDC(None)
        memory = self._gdi32.CreateCompatibleDC(source)
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth, header.biHeight = width, -height  # Top-down rows.
        header.biPlanes, header.biBitCount = 1, 32
        bits = ctypes.c_void_p()
        bitmap = self._gdi32.CreateDIBSection(memory, ctypes.byref(header), 0, bits, None, 0)
        try:
            if not bitmap or not bits.value:
                raise OSError(_last_error(), "CreateDIBSection failed")
            previous = self._gdi32.SelectObject(memory, bitmap)
            copied = self._gdi32.BitBlt(
                memory, 0, 0, width, height, source, screen["x"], screen["y"], 0x40CC0020
            )
            self._gdi32.SelectObject(memory, previous)
            if not copied:
                raise OSError(_last_error(), "BitBlt failed")
            pixels = ctypes.string_at(bits.value, width * height * 4)
        finally:
            if bitmap:
                self._gdi32.DeleteObject(bitmap)
            self._gdi32.DeleteDC(memory)
            self._user32.ReleaseDC(None, source)
        path.write_bytes(png_bytes(width, height, pixels))

    # Windows of the office

    def _is_office(self, hwnd):
        pid = ctypes.c_uint32()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in self._images:
            process = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid.value)
            name = ""
            if process:
                buffer = ctypes.create_unicode_buffer(1024)
                size = ctypes.c_uint32(len(buffer))
                if self._kernel32.QueryFullProcessImageNameW(process, 0, buffer, size):
                    name = buffer.value.rsplit("\\", 1)[-1]
                self._kernel32.CloseHandle(process)
            self._images[pid.value] = name.lower() == OFFICE_IMAGE
        return self._images[pid.value]

    def _describe(self, hwnd) -> dict[str, Any]:
        rect = RECT()
        self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
        name, title = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
        self._user32.GetClassNameW(hwnd, name, len(name))
        self._user32.GetWindowTextW(hwnd, title, len(title))
        style = self._user32.GetWindowLongPtrW(hwnd, GWL_STYLE) & 0xFFFFFFFF
        return {
            "hwnd": hwnd,
            "class": name.value,
            "title": title.value,
            "style": f"{style:#010x}",
            "ex_style": f"{self._user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF:#010x}",
            "owner": self._user32.GetWindow(hwnd, GW_OWNER) or 0,
            "rect": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
            "popup": bool(style & WS_POPUP) and (style & WS_CAPTION) != WS_CAPTION,
            "caption": (style & WS_CAPTION) == WS_CAPTION,
        }

    def inventory(self):
        """The office's visible top-level windows, described for evidence."""
        found: list[int] = []

        def visit(hwnd, _):
            if hwnd and self._user32.IsWindowVisible(hwnd) and self._is_office(hwnd):
                found.append(hwnd)
            return 1

        self._user32.EnumWindows(ENUM_WINDOWS(visit), None)
        self.last_inventory = [self._describe(hwnd) for hwnd in found]
        return self.last_inventory

    def popup_windows(self):
        """Visible captionless popup windows of the office, such as an open menu."""
        return {
            window["hwnd"]
            for window in self.inventory()
            if window["popup"] and window["rect"][2] > 1 and window["rect"][3] > 1
        }

    def modal_dialog(self):
        """Whether the foreground window is an office dialog: captioned and owned by a frame."""
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd or not self._is_office(hwnd):
            return False
        window = self._describe(hwnd)
        return bool(window["caption"] and window["owner"])

    def foreground(self):
        hwnd = self._user32.GetForegroundWindow()
        return self._describe(hwnd) if hwnd else None

    # Input

    def _send(self, *events):
        array = (INPUT * len(events))(*events)
        sent = self._user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
        if sent != len(events):
            raise OSError(_last_error(), "SendInput was blocked")

    def _mouse(self, flags, x=0, y=0, data=0):
        event = INPUT(type=INPUT_MOUSE)
        event.u.mi = MOUSEINPUT(x, y, data & 0xFFFFFFFF, flags, 0, 0)
        return event

    def cursor(self):
        point = POINT()
        self._user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def move(self, x, y):
        x, y = int(round(x)), int(round(y))
        screen = self.screen()
        flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        dx = normalised(x, screen["x"], screen["width"])
        dy = normalised(y, screen["y"], screen["height"])
        self._send(self._mouse(flags, dx, dy))
        landed = self.cursor()
        if landed != (x, y):
            # Rounding between the normalised and pixel grids: one corrective absolute step.
            self.pointer_corrections += 1
            step_x = 65535 / max(1, screen["width"] - 1)
            step_y = 65535 / max(1, screen["height"] - 1)
            dx += round((x - landed[0]) * step_x)
            dy += round((y - landed[1]) * step_y)
            self._send(self._mouse(flags, dx, dy))
            landed = self.cursor()
            if landed != (x, y):
                raise AssertionError(f"The pointer landed at {landed}, not {(x, y)}")

    def button(self, button, down):
        if button in (WHEEL_UP, WHEEL_DOWN):
            if down:
                delta = WHEEL_DELTA if button == WHEEL_UP else -WHEEL_DELTA
                self._send(self._mouse(MOUSEEVENTF_WHEEL, data=delta))
            return
        press, release = BUTTON_FLAGS[button]
        self._send(self._mouse(press if down else release))
        (self.held.add if down else self.held.discard)(button)

    def release_held(self):
        """Release any button a failed check left pressed, so that the next check starts clean."""
        for button in sorted(self.held):
            self.button(button, False)

    def key(self, keysym, down):
        if keysym not in KEYS:
            raise ValueError(f"No key code for {keysym}")
        code, extended = KEYS[keysym]
        event = INPUT(type=INPUT_KEYBOARD)
        flags = (KEYEVENTF_EXTENDEDKEY if extended else 0) | (0 if down else KEYEVENTF_KEYUP)
        event.u.ki = KEYBDINPUT(code, self._user32.MapVirtualKeyW(code, 0), flags, 0, 0)
        self._send(event)
        time.sleep(0.01)

    def tap(self, keysym, modifiers=(), pause=0.08):
        for modifier in modifiers:
            self.key(modifier, True)
        self.key(keysym, True)
        time.sleep(KEY_HOLD)
        self.key(keysym, False)
        for modifier in reversed(modifiers):
            self.key(modifier, False)
        time.sleep(pause)
