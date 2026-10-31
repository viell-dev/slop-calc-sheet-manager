"""The viewed sheet's accessible name, and native picks awaiting intake across a rebuild (#83)."""

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.sheet_list import SheetRow, list_name
from tests.unit.source_methods import method

SOURCE = "src/sheet_manager/uno_list.py"
NAMES = ["Alfa", "Bravo", "Charlie", "Delta"]


def namer(rows: list[SheetRow]) -> Any:
    owner = SimpleNamespace(rows=rows, _viewed_name=None, peer=SimpleNamespace(setProperty=Mock()))
    name = method(SOURCE, "SheetList", "_name_viewed", {"list_name": list_name})
    return owner, lambda: name(owner)


def test_the_name_follows_the_active_row_and_is_set_only_when_it_changes() -> None:
    owner, name = namer([SheetRow("Alfa"), SheetRow("Bravo", active=True), SheetRow("Charlie")])
    name()
    owner.peer.setProperty.assert_called_once_with("AccessibleName", "Sheets, current sheet: Bravo")
    name()  # A refresh that leaves the viewed sheet announces nothing again.
    assert owner.peer.setProperty.call_count == 1
    owner.rows = [SheetRow("Alfa", active=True), SheetRow("Bravo"), SheetRow("Charlie")]
    name()
    owner.peer.setProperty.assert_called_with("AccessibleName", "Sheets, current sheet: Alfa")
    owner.rows = [SheetRow("Alfa"), SheetRow("Bravo")]  # Calc's active sheet could not be read.
    name()
    owner.peer.setProperty.assert_called_with("AccessibleName", "Sheets")


def test_the_name_never_depends_on_the_picks() -> None:
    source = method(SOURCE, "SheetList", "_name_viewed", {"list_name": list_name})
    assert "_selection" not in source.__code__.co_names
    assert "_shown" not in source.__code__.co_names


class Tree:
    def __init__(self, owner: Any, selected: list[str]):
        self.owner, self.selected = owner, list(selected)
        self.restoring: list[bool] = []

    def clearSelection(self) -> None:
        self.restoring.append(self.owner._restoring_cursor)
        self.selected = []

    def addSelection(self, node: str) -> None:
        self.restoring.append(self.owner._restoring_cursor)
        self.selected.append(node)


def shower(selected: list[str]) -> Any:
    owner = SimpleNamespace(
        _restoring_cursor=False,
        _nodes=list(NAMES),
        names=lambda: list(NAMES),
        peer=SimpleNamespace(invalidate=Mock()),
    )
    owner.tree = Tree(owner, selected)
    owner.selected_names = lambda: [name for name in NAMES if name in owner.tree.selected]
    show = method(SOURCE, "SheetList", "_show_native", {})

    def run(names: tuple[str, ...]) -> None:
        show(owner, names)

    return owner, run


def test_showing_native_picks_again_marks_the_writes_as_restoration() -> None:
    owner, show = shower(["Alfa"])
    show(("Bravo", "Delta"))
    assert owner.tree.selected == ["Bravo", "Delta"]
    assert owner.tree.restoring == [True, True, True]  # Cursor events are not user input.
    assert owner._restoring_cursor is False
    owner.peer.invalidate.assert_called_once_with(0)


def test_showing_the_selection_already_shown_writes_nothing() -> None:
    owner, show = shower(["Bravo"])
    show(("Bravo",))
    assert owner.tree.restoring == []
    owner.peer.invalidate.assert_not_called()


def refresher(change: str) -> Any:
    """A list whose tree shows `Delta`, picked natively, while its own picks are `Alfa`."""
    handles = [object() for _ in NAMES]
    order = list(NAMES)
    if change == "rename":
        order[2] = "Charles"
    observed = SimpleNamespace(
        sheets=[SimpleNamespace(name=name) for name in order], handles=handles
    )
    owner = SimpleNamespace(
        _press=None,
        _observed=observed,
        _proven=0,
        _generation=0,
        _nodes=[object()],
        rows=[SheetRow(name) for name in NAMES],
        _shown=("Alfa",),
        _view_generation=0,
        _view_names=frozenset(NAMES),
        _view_stopped=True,
        _view_state=None,
        _input=0,
        _monitor=SimpleNamespace(check=lambda: 1 if change == "generation" else 0),
        _identities_kept=Mock(return_value=change != "generation"),
        _selection=SimpleNamespace(carry=Mock(return_value=False), names=lambda: ["Alfa"]),
        _take_tree_selection=Mock(return_value=change != "none"),
        selected_names=lambda: ["Delta"] if change != "none" else ["Alfa"],
        _rebuild=Mock(),
        _apply_selection=Mock(),
        _show_native=Mock(),
        _name_viewed=Mock(),
        _update_moves=Mock(),
    )
    owner.names = lambda: [row.name for row in owner.rows]

    def drop() -> bool:
        owner._generation += 1
        return True

    owner._drop_all_picks = drop

    def rebuild(rows: list[SheetRow]) -> None:
        owner.rows = rows

    owner._rebuild.side_effect = rebuild

    def read_rows(controller: Any, picture: Any) -> list[SheetRow]:
        return [SheetRow(sheet.name, protected=sheet.name == "Charlie") for sheet in picture.sheets]

    refresh = method(
        SOURCE,
        "SheetList",
        "_refresh",
        {"snapshot": Mock(return_value=observed), "read_rows": read_rows, "Mapping": Mapping},
    )
    owner.document = owner.controller = None
    return owner, lambda: refresh(owner, {})


def test_a_rebuild_shows_native_picks_awaiting_intake_again() -> None:
    owner, refresh = refresher("property")
    refresh()
    owner._take_tree_selection.assert_called_once_with(defer=True)
    owner._rebuild.assert_called_once()
    owner._show_native.assert_called_once_with(("Delta",))
    owner._name_viewed.assert_called_once_with()


@pytest.mark.parametrize("change", ["generation", "rename", "none"])
def test_native_picks_are_not_shown_again_when_their_intake_would_refuse_them(
    change: str,
) -> None:
    owner, refresh = refresher(change)
    refresh()
    owner._show_native.assert_not_called()
    owner._name_viewed.assert_called_once_with()


def test_a_held_press_leaves_the_tree_selection_to_its_handlers() -> None:
    owner, refresh = refresher("property")
    owner._press = object()
    refresh()
    owner._take_tree_selection.assert_not_called()
    owner._show_native.assert_not_called()
