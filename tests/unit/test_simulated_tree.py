"""The simulated tree's presses, releases and anchor follow VCL's selection engine (#328).

Each case is a step of `SelectionEngine::SelMouseButtonDown`, `SelMouseButtonUp` or
`SvImpLBox::SetAnchorSelection`, read in 26.8.3.1. What the tree shows after a range press was
compared with real input on gtk3 and gen (#321's and #349's measurements).
"""

import pytest

from tests.unit.list_peer import MOD1, RIGHT, SHIFT, Faults, NodeModel, Tree

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
CTRL_SHIFT = MOD1 | SHIFT


def tree(*selected: str) -> Tree:
    """A tree over `NAMES`, painted, showing `selected` and the cursor on the last of them."""
    faults = Faults()
    made, model = Tree(faults), NodeModel(faults)
    root = model.createNode("", False)
    model.setRoot(root)
    for name in NAMES:
        node = model.createNode(name, False)
        node.DataValue = name
        root.appendChild(node)
    made.model.DataModel = model
    made.paint_cursor()
    for name in selected:
        made.cursor = made.node(name)
        made.selected.append(made.cursor)
    return made


def click(made: Tree, name: str, modifiers: int = 0) -> list[str]:
    made.press(NAMES.index(name), modifiers)
    made.release()
    return made.shown()


def cursor(made: Tree) -> str | None:
    return made.cursor.DataValue if made.cursor is not None else None


def test_a_plain_press_waits_for_its_release_only_on_a_selected_row() -> None:
    made = tree("Bravo", "Delta")
    made.press(NAMES.index("Bravo"))
    assert made.shown() == ["Bravo", "Delta"] and cursor(made) == "Delta"
    made.release()
    assert made.shown() == ["Bravo"] and cursor(made) == "Bravo"
    made.press(NAMES.index("Echo"))
    assert made.shown() == ["Echo"] == click(made, "Echo")
    before = made.notified
    made.release()
    assert made.notified == before, "a second release without a press changed the selection"


@pytest.mark.parametrize("modifiers", [SHIFT, MOD1, CTRL_SHIFT])
def test_the_release_of_a_press_with_a_modifier_changes_nothing(modifiers: int) -> None:
    made = tree("Bravo", "Delta")
    made.press(NAMES.index("Bravo"), modifiers)
    shown, notified = made.shown(), made.notified
    made.release()
    assert made.shown() == shown and made.notified == notified


def test_a_held_presss_release_selects_the_row_scrolled_to_its_position() -> None:
    made = tree("Bravo")
    made.visible = 3
    made.press(made.line(NAMES.index("Bravo")))
    made.scroll_to(2)
    made.release()
    assert made.shown() == ["Delta"]


@pytest.mark.parametrize(
    "selected, end, shown",
    [
        (["Bravo"], "Delta", ["Bravo", "Charlie", "Delta"]),
        (["Delta"], "Bravo", ["Bravo", "Charlie", "Delta"]),
        # After a list's write of a range: no anchor, and the cursor on the range's end.
        (["Bravo", "Charlie", "Delta", "Echo"], "Charlie", ["Charlie", "Delta", "Echo"]),
        (["Bravo", "Charlie", "Delta"], "Foxtrot", ["Delta", "Echo", "Foxtrot"]),
        ([], "Charlie", ["Alfa", "Bravo", "Charlie"]),  # From the first row, VCL's paint's.
    ],
)
def test_a_shift_press_without_an_anchor_ranges_from_the_cursor(
    selected: list[str], end: str, shown: list[str]
) -> None:
    made = tree(*selected)
    before = made.notified
    assert click(made, end, SHIFT) == shown and cursor(made) == end
    assert made.notified - before == len(selected) + len(shown), "one change for each row"


def test_further_shift_presses_move_the_end_of_the_range() -> None:
    made = tree("Charlie")
    assert click(made, "Foxtrot", SHIFT) == ["Charlie", "Delta", "Echo", "Foxtrot"]
    assert click(made, "Delta", SHIFT) == ["Charlie", "Delta"]
    assert click(made, "Alfa", SHIFT) == ["Alfa", "Bravo", "Charlie"]
    assert click(made, "Bravo", SHIFT) == ["Bravo", "Charlie"]
    assert click(made, "Echo", SHIFT) == ["Charlie", "Delta", "Echo"]
    assert click(made, "Delta", MOD1) == ["Charlie", "Echo"], "a Ctrl press toggles its row"
    assert click(made, "Foxtrot", SHIFT) == ["Delta", "Echo", "Foxtrot"], "from the new cursor"


def test_a_ctrl_shift_press_adds_from_the_cursor_and_starts_add_mode() -> None:
    made = tree("Alfa", "Charlie")
    heard: list[int] = []
    made.cursor_listener = heard.append
    assert click(made, "Echo", CTRL_SHIFT) == ["Alfa", "Charlie", "Delta", "Echo"]
    assert made.add_mode and heard == [], "the cursor's move in add mode is not announced"
    assert click(made, "Foxtrot", MOD1) == ["Alfa", "Charlie", "Delta", "Echo"]
    assert cursor(made) == "Foxtrot", "a Ctrl press on an unselected row only moves the cursor"
    assert click(made, "Alfa", MOD1) == ["Charlie", "Delta", "Echo"]
    assert click(made, "Bravo") == ["Bravo"] and not made.add_mode
    assert heard == [0, 1]


def test_a_right_press_and_a_later_click_of_a_double_click_change_nothing() -> None:
    made = tree("Bravo")
    made.press(NAMES.index("Delta"), button=RIGHT)
    made.press(NAMES.index("Delta"), clicks=2)
    made.press(NAMES.index("Delta"), MOD1, clicks=2)
    made.release()
    assert made.shown() == ["Bravo"] and cursor(made) == "Bravo"


@pytest.mark.parametrize("selected, kept", [(True, False), (False, True)])
def test_clearing_drops_the_anchor_only_with_a_selected_row(selected: bool, kept: bool) -> None:
    made = tree("Bravo")
    click(made, "Delta", SHIFT)
    if not selected:
        made.assistive_clear()
    assert made.anchor is made.node("Bravo"), "an assistive change keeps the anchor"
    made.clearSelection()
    assert (made.anchor is not None, made.anchored) == (kept, kept)


def test_a_write_drops_the_anchor_and_a_new_model_leaves_the_engine_believing_in_one() -> None:
    made = tree("Bravo")
    click(made, "Delta", SHIFT)
    made.model.SelectionType = "SINGLE"
    made.select(made.node("Delta"))
    made.model.SelectionType = "MULTI"
    assert made.shown() == ["Delta"] and made.anchor is None and not made.anchored
    click(made, "Echo", SHIFT)
    assert made.data is not None
    made.model.DataModel = made.data
    assert made.anchor is None and made.anchored and made.cursor is None
    assert click(made, "Delta", SHIFT) == ["Delta"], "no range, as the engine makes no anchor"
