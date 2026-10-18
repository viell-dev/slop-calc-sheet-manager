"""Decide who handles a key pressed while the sheet list has focus. No UNO is required.

LibreOffice delivers a key that the list's tree control does not use to the tree's parents. The
sidebar swallows the navigation and editing keys (arrows, Home, End, Page Up and Page Down,
Return, Escape, Insert, Delete, Backspace) whatever the modifiers, and passes every other key on
to the document view, which types it into the current cell or runs its shortcut. Keys are
therefore routed as follows:

- navigation keys go to the tree, because whatever it ignores the sidebar swallows;
- keys the list handles itself (Enter, typed characters, the menu keys) are consumed;
- other shortcuts are consumed and their Calc command is dispatched to the panel's own frame,
  because the sidebar swallows some of them (Ctrl+Page Down) before they reach Calc;
- focus travel, the menu bar, and Escape are left to LibreOffice;
- everything else is consumed so that it cannot reach a cell.

The numbers below are the values of the ``com.sun.star.awt.Key`` and ``KeyModifier`` constants;
the integration tests compare them with the running office.
"""

from enum import Enum

SHIFT, MOD1, MOD2, MOD3 = 1, 2, 4, 8

A = 512
F1, F2, F6, F10, F26 = 768, 769, 773, 777, 793
DOWN, UP, LEFT, RIGHT, HOME, END, PAGEUP, PAGEDOWN = range(1024, 1032)
RETURN, ESCAPE, TAB, BACKSPACE, SPACE, INSERT, DELETE = range(1280, 1287)
CONTEXTMENU = 1305

NAVIGATION = frozenset((DOWN, UP, LEFT, RIGHT, HOME, END, PAGEUP, PAGEDOWN))
TYPE_AHEAD_SECONDS = 1.0


class KeyRoute(Enum):
    LIBREOFFICE = "libreoffice"  # Not consumed: focus travel, menu bar, Escape.
    TREE = "tree"  # Not consumed: the tree handles it, the sidebar swallows what it ignores.
    ACTIVATE = "activate"  # Consumed: go to the selected sheet.
    TYPE_AHEAD = "type-ahead"  # Consumed: select the next sheet whose name starts so.
    MENU = "menu"  # Consumed: open the sheet tab menu for the selection.
    SHORTCUT = "shortcut"  # Consumed if Calc has a command for it; see unbound_route().
    IGNORE = "ignore"  # Consumed: the key has no meaning in the list and must not reach a cell.

    @property
    def consumed(self) -> bool:
        return self not in (KeyRoute.LIBREOFFICE, KeyRoute.TREE)


def typed_character(char: str, modifiers: int) -> bool:
    """A printable character typed without Ctrl, Alt, or macOS Ctrl, or with Ctrl+Alt (AltGr)."""
    if len(char) != 1 or not char.isprintable() or char.isspace():
        return False
    held = modifiers & (MOD1 | MOD2 | MOD3)
    return held in (0, MOD1 | MOD2)


def route_key(code: int, modifiers: int, char: str = "") -> KeyRoute:
    """Route one key press received while the list has focus."""
    shift, ctrl, alt = bool(modifiers & SHIFT), bool(modifiers & MOD1), bool(modifiers & MOD2)
    if typed_character(char, modifiers):
        return KeyRoute.TYPE_AHEAD
    if code == 0:
        return KeyRoute.LIBREOFFICE  # A modifier on its own.
    if code in (TAB, F6, ESCAPE):
        return KeyRoute.LIBREOFFICE
    if code == CONTEXTMENU or (code == F10 and shift and not ctrl and not alt):
        return KeyRoute.MENU
    if code == F10:
        return KeyRoute.LIBREOFFICE
    if alt and not ctrl:
        return KeyRoute.SHORTCUT  # A menu mnemonic when Calc has no shortcut for it.
    if code in NAVIGATION:
        if ctrl and code in (PAGEUP, PAGEDOWN):
            return KeyRoute.SHORTCUT  # Previous and next sheet.
        return KeyRoute.TREE
    if code == SPACE:
        if ctrl and not shift and not alt:
            return KeyRoute.TREE  # Toggle the focused row.
        return KeyRoute.SHORTCUT if ctrl or alt else KeyRoute.IGNORE
    if code == RETURN:
        return KeyRoute.SHORTCUT if ctrl or alt else KeyRoute.ACTIVATE
    if code == A and modifiers == MOD1:
        return KeyRoute.TREE  # Select every row.
    if ctrl or alt or modifiers & MOD3 or F1 <= code <= F26:
        return KeyRoute.SHORTCUT
    return KeyRoute.IGNORE


def unbound_route(modifiers: int) -> KeyRoute:
    """Route a shortcut-like key for which Calc's shortcut configuration has no command."""
    if modifiers & MOD2 and not modifiers & MOD1:
        return KeyRoute.LIBREOFFICE  # Alt+letter opens a menu.
    return KeyRoute.IGNORE


class TypeAhead:
    """Collect characters typed in quick succession into one search prefix."""

    def __init__(self, timeout: float = TYPE_AHEAD_SECONDS) -> None:
        self.timeout = timeout
        self.prefix = ""
        self._last: float | None = None

    def feed(self, char: str, now: float) -> str:
        if self._last is None or now - self._last > self.timeout:
            self.prefix = ""
        self._last = now
        self.prefix += char
        return self.prefix


def find_prefix(names: list[str], prefix: str, current: int | None) -> int | None:
    """Return the row whose name starts with prefix, searching from the current row onward.

    A single character moves past the current row, so repeating a letter cycles through the
    sheets that start with it; a longer prefix may stay on the current row.
    """
    if not names or not prefix:
        return None
    wanted = prefix.casefold()
    start = 0 if current is None else current + (1 if len(prefix) == 1 else 0)
    for offset in range(len(names)):
        row = (start + offset) % len(names)
        if names[row].casefold().startswith(wanted):
            return row
    return None
