"""Pointer and keyboard ranges share an anchor that stays with the original sheet."""

from types import SimpleNamespace

from sheet_manager.selection import Selection


def test_range_can_grow_shrink_and_add_to_disjoint_picks() -> None:
    order = ["Alfa", "Bravo", "Charlie", "Delta", "Echo"]
    tokens = {name: object() for name in order}
    selection = Selection(lambda ref: True)
    selection.choose("Bravo", tokens, order)
    selection.choose("Delta", tokens, order, toggle=True)
    assert selection.names() == ["Bravo", "Delta"]
    selection.choose("Echo", tokens, order, extend=True)
    assert selection.names() == ["Delta", "Echo"]
    selection.choose("Charlie", tokens, order, extend=True)
    assert selection.names() == ["Charlie", "Delta"]
    selection.choose("Alfa", tokens, order, extend=True, toggle=True)
    assert selection.names() == order[:4]


def test_press_on_a_picked_row_preserves_a_drag_group_until_the_click_finishes() -> None:
    order = ["Alfa", "Bravo", "Charlie"]
    tokens = {name: object() for name in order}
    selection = Selection(lambda ref: True)
    selection.choose("Alfa", tokens, order)
    selection.choose("Charlie", tokens, order, toggle=True)
    selection.choose("Alfa", tokens, order, preserve=True)
    assert selection.names() == ["Alfa", "Charlie"]
    selection.choose("Alfa", tokens, order)
    assert selection.names() == ["Alfa"]


def test_range_anchor_follows_a_move_and_is_dropped_after_a_rename() -> None:
    order = ["Alfa", "Bravo", "Charlie", "Delta"]
    tokens = {name: SimpleNamespace(name=name) for name in order}
    selection = Selection(lambda ref: ref.token.name == ref.name)
    selection.choose("Bravo", tokens, order)
    anchor = selection.anchor
    moved = ["Alfa", "Charlie", "Delta", "Bravo"]
    selection.choose("Charlie", tokens, moved, extend=True)
    assert selection.names() == moved[1:]
    assert selection.anchor is anchor
    tokens["Bravo"].name = "Echo"
    selection.revalidate()
    assert selection.anchor is None
    selection.choose("Alfa", tokens, moved, extend=True)
    assert selection.names() == moved[:2]
    selection.clear()
    assert selection.anchor is None and selection.cursor is None and not selection.picked
