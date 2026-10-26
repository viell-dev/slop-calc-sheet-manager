"""Which keys the focused sheet list keeps, passes on, or turns into Calc commands."""

import pytest

from sheet_manager.keys import (
    BACKSPACE,
    CONTEXTMENU,
    DELETE,
    DOWN,
    END,
    ESCAPE,
    F1,
    F2,
    F6,
    F10,
    HOME,
    INSERT,
    MOD1,
    MOD2,
    MOD3,
    PAGEDOWN,
    PAGEUP,
    RETURN,
    SHIFT,
    SPACE,
    TAB,
    UP,
    A,
    KeyRoute,
    TypeAhead,
    button_route,
    find_prefix,
    move_action,
    route_key,
    typed_character,
    unbound_route,
)

S = 530  # Key S


@pytest.mark.parametrize(
    ("code", "modifiers", "char", "expected"),
    [
        (RETURN, 0, "\r", KeyRoute.LIBREOFFICE),
        (SPACE, 0, " ", KeyRoute.LIBREOFFICE),
        (UP, 0, "", KeyRoute.LIBREOFFICE),
        (A, 0, "a", KeyRoute.IGNORE),
        (DOWN, MOD2, "", KeyRoute.MOVE),
        (PAGEDOWN, MOD1, "", KeyRoute.SHORTCUT),
    ],
)
def test_button_keys_activate_natively_and_keep_text_out_of_cells(
    code: int, modifiers: int, char: str, expected: KeyRoute
) -> None:
    assert button_route(route_key(code, modifiers, char), code, modifiers) is expected


@pytest.mark.parametrize(
    ("code", "modifiers", "char", "route"),
    [
        (A, 0, "a", KeyRoute.TYPE_AHEAD),
        (A, SHIFT, "A", KeyRoute.TYPE_AHEAD),
        (0, 0, "#", KeyRoute.TYPE_AHEAD),  # Characters without a VCL key code.
        (A + 16, MOD1 | MOD2, "@", KeyRoute.TYPE_AHEAD),  # AltGr on Windows.
        (0, SHIFT, "\0", KeyRoute.LIBREOFFICE),  # A modifier on its own.
        (UP, 0, "", KeyRoute.TREE),
        (DOWN, SHIFT, "", KeyRoute.TREE),
        (HOME, MOD1, "", KeyRoute.TREE),
        (END, MOD1 | SHIFT, "", KeyRoute.TREE),
        (PAGEUP, 0, "", KeyRoute.TREE),
        (PAGEDOWN, MOD1, "", KeyRoute.SHORTCUT),
        (PAGEUP, MOD1 | SHIFT, "", KeyRoute.SHORTCUT),
        (DOWN, MOD2, "", KeyRoute.MOVE),
        (SPACE, 0, " ", KeyRoute.IGNORE),
        (SPACE, SHIFT, " ", KeyRoute.IGNORE),
        (SPACE, MOD1, " ", KeyRoute.TREE),
        (SPACE, MOD1 | SHIFT, " ", KeyRoute.SHORTCUT),
        (RETURN, 0, "\r", KeyRoute.ACTIVATE),
        (RETURN, SHIFT, "\r", KeyRoute.ACTIVATE),
        (RETURN, MOD1, "\r", KeyRoute.SHORTCUT),
        (RETURN, MOD2, "\r", KeyRoute.SHORTCUT),
        (CONTEXTMENU, 0, "", KeyRoute.MENU),
        (F10, SHIFT, "", KeyRoute.MENU),
        (F10, 0, "", KeyRoute.LIBREOFFICE),
        (F10, MOD1 | SHIFT, "", KeyRoute.LIBREOFFICE),  # Docks or undocks the sidebar.
        (TAB, 0, "\t", KeyRoute.LIBREOFFICE),
        (TAB, MOD1 | SHIFT, "\t", KeyRoute.LIBREOFFICE),
        (F6, MOD1, "", KeyRoute.LIBREOFFICE),
        (ESCAPE, 0, "\x1b", KeyRoute.LIBREOFFICE),
        (A, MOD1, "\x01", KeyRoute.TREE),
        (A, MOD1 | SHIFT, "\x01", KeyRoute.SHORTCUT),
        (S, MOD1, "\x13", KeyRoute.SHORTCUT),
        (S, MOD2, "s", KeyRoute.SHORTCUT),
        (S, MOD3, "s", KeyRoute.SHORTCUT),
        (F1, 0, "", KeyRoute.SHORTCUT),
        (F2, 0, "", KeyRoute.SHORTCUT),
        (DELETE, 0, "\x7f", KeyRoute.IGNORE),
        (DELETE, SHIFT, "", KeyRoute.IGNORE),
        (BACKSPACE, 0, "\b", KeyRoute.IGNORE),
        (INSERT, SHIFT, "", KeyRoute.IGNORE),
        (DELETE, MOD1, "", KeyRoute.SHORTCUT),
    ],
)
def test_route_key(code: int, modifiers: int, char: str, route: KeyRoute) -> None:
    assert route_key(code, modifiers, char) is route


def test_only_tree_and_libreoffice_routes_pass_keys_on() -> None:
    passed = {route for route in KeyRoute if not route.consumed}
    assert passed == {KeyRoute.LIBREOFFICE}


def test_unbound_shortcuts() -> None:
    assert unbound_route(MOD2) is KeyRoute.LIBREOFFICE  # Menu mnemonics.
    assert unbound_route(MOD2 | SHIFT) is KeyRoute.LIBREOFFICE
    assert unbound_route(MOD1) is KeyRoute.IGNORE
    assert unbound_route(MOD1 | MOD2) is KeyRoute.IGNORE
    assert unbound_route(0) is KeyRoute.IGNORE


@pytest.mark.parametrize(
    "code,action", [(HOME, "top"), (UP, "up"), (DOWN, "down"), (END, "bottom")]
)
def test_move_shortcuts_are_exact_and_preserve_calc_and_tree_combinations(
    code: int, action: str
) -> None:
    assert move_action(code, MOD2) == action
    assert route_key(code, MOD2) is KeyRoute.MOVE
    for modifiers in (0, SHIFT, MOD1 | SHIFT, MOD2 | SHIFT, MOD1 | MOD2, MOD3 | MOD2):
        assert move_action(code, modifiers) is None
        assert route_key(code, modifiers) is not KeyRoute.MOVE


def test_typed_character() -> None:
    assert typed_character("é", 0)
    assert not typed_character(" ", 0)
    assert not typed_character("ab", 0)
    assert not typed_character("", 0)
    assert not typed_character("a", MOD1)
    assert not typed_character("a", MOD2)


def test_type_ahead_collects_quick_characters() -> None:
    typing = TypeAhead(timeout=1.0)
    assert typing.feed("s", 10.0) == "s"
    assert typing.feed("h", 10.5) == "sh"
    assert typing.feed("x", 12.0) == "x"


def test_repeating_a_letter_cycles_until_a_different_letter_extends_it() -> None:
    typing = TypeAhead(timeout=1.0)
    names = ["Beta", "Bravo", "Berry"]
    cursor = None
    for expected in (0, 1, 2, 0):
        cursor = find_prefix(names, typing.feed("b", 10.0), cursor)
        assert cursor == expected
    assert find_prefix(names, typing.feed("r", 10.1), cursor) == 1


def test_find_prefix() -> None:
    names = ["Alpha", "beta", "Bravo", "Charlie", "able"]
    assert find_prefix(names, "b", None) == 1
    assert find_prefix(names, "b", 1) == 2  # One letter moves on: repeating it cycles.
    assert find_prefix(names, "b", 2) == 1  # And wraps around.
    assert find_prefix(names, "br", 2) == 2  # A longer prefix may stay.
    assert find_prefix(names, "AB", None) == 4
    assert find_prefix(names, "z", 0) is None
    assert find_prefix([], "a", None) is None
    assert find_prefix(names, "", None) is None
