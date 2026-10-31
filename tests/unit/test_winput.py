"""The pure parts of the Windows SendInput backend: key table, coordinates, layout, PNG output.

The input itself needs the runner's real desktop (`.github/workflows/windows-desktop.yml`).
"""

import ctypes
import re
import struct
import zlib
from pathlib import Path

import pytest

from tests.ui.winput import INPUT, KEYBDINPUT, KEYS, MOUSEINPUT, normalised, png_bytes

ROOT = Path(__file__).resolve().parents[2]
# Every module whose checks the Windows suite runs, and the suite itself.
SHARED_CHECKS = ("run_ui.py", "rename_dialog.py", "menu_lifetime.py", "run_windows_ui.py")


def pressed_keys() -> set[str]:
    """Key names the shared checks spell out: taps, modifiers, and (key, modifiers) pairs.

    Names built at run time are not found here; `WinInput.key` refuses an unknown one, which
    fails its check in the workflow.
    """
    names: set[str] = set()
    for name in SHARED_CHECKS:
        source = (ROOT / "tests" / "ui" / name).read_text(encoding="utf-8")
        names.update(re.findall(r'\btap\(\s*"([^"]+)"', source))
        names.update(re.findall(r'"((?:Control|Shift|Alt)_L)"', source))
        names.update(re.findall(r'\bkey\(\s*"([^"]+)"', source))
        names.update(re.findall(r'\(\s*"(\w+)",\s*\(', source))
        names.update(re.findall(r'\(\s*"(?:top|up|down|bottom)",\s*"(\w+)"\s*\)', source))
    return names


def test_every_key_the_shared_checks_press_has_a_windows_key() -> None:
    names = pressed_keys()
    assert {"Escape", "Menu", "F10", "Control_L", "Alt_L", "Shift_L", "numbersign", "End"} <= names
    assert sorted(names - set(KEYS)) == []


def test_typed_text_uses_letters_digits_and_mapped_punctuation() -> None:
    # rename_dialog.type_text maps " " and "/" to keysyms and types the rest as themselves.
    for char in "abcdefghijklmnopqrstuvwxyz0123456789":
        assert char in KEYS
    assert {"space", "slash"} <= set(KEYS)


def test_navigation_keys_are_extended_and_characters_are_not() -> None:
    for name in ("Prior", "Next", "End", "Home", "Up", "Down", "Left", "Right", "Delete", "Menu"):
        assert KEYS[name][1], name
    for name in ("a", "z", "0", "Return", "Escape", "space", "Control_L", "F10"):
        assert not KEYS[name][1], name
    assert KEYS["F10"][0] == 0x79 and KEYS["q"][0] == ord("Q") and KEYS["7"][0] == ord("7")


def test_input_structures_match_the_64_bit_windows_layout() -> None:
    assert ctypes.sizeof(MOUSEINPUT) == 32
    assert ctypes.sizeof(KEYBDINPUT) == 24
    assert ctypes.sizeof(INPUT) == 40


@pytest.mark.parametrize(
    ("pixel", "origin", "size", "expected"),
    [(0, 0, 1024, 0), (1023, 0, 1024, 65535), (512, 0, 1024, 32800), (-1920, -1920, 3840, 0)],
)
def test_absolute_coordinates_span_the_virtual_screen(
    pixel: int, origin: int, size: int, expected: int
) -> None:
    assert normalised(pixel, origin, size) == expected


def test_png_holds_the_pixels_in_rgb_order() -> None:
    # Two rows of two BGRA pixels: red, green / blue, white.
    bgra = bytes([0, 0, 255, 255, 0, 255, 0, 255, 255, 0, 0, 255, 255, 255, 255, 255])
    data = png_bytes(2, 2, bgra)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    chunks: dict[bytes, bytes] = {}
    offset = 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF
        chunks[kind] = body
        offset += 12 + length
    assert struct.unpack(">IIBBBBB", chunks[b"IHDR"]) == (2, 2, 8, 2, 0, 0, 0)
    assert zlib.decompress(chunks[b"IDAT"]) == bytes(
        [0, 255, 0, 0, 0, 255, 0, 0, 0, 0, 255, 255, 255, 255]
    )
    assert b"IEND" in chunks
