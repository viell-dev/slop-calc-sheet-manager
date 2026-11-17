"""A refresh replaces the tree's nodes only when a name or label changes (#22)."""

from collections.abc import Mapping
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.sheet_list import SheetRow, node_text
from tests.unit.source_methods import method

NAMES = ("Alfa", "Bravo", "Charlie")
SHOWN = [SheetRow("Alfa", active=True), SheetRow("Bravo"), SheetRow("Charlie", color=0x2A6099)]


def refresh(fresh: list[SheetRow], *, nodes: bool = True, dropped: bool = False) -> Any:
    """Run `SheetList._refresh` over unchanged sheets whose rows now read as `fresh`."""
    observed = SimpleNamespace(
        sheets=[SimpleNamespace(name=row.name) for row in fresh],
        handles=[object() for _ in fresh],
    )
    owner = SimpleNamespace(
        _press=None,
        _observed=observed,
        _proven=0,
        _generation=0,
        _nodes=[object()] * len(SHOWN) if nodes else [],
        rows=list(SHOWN),
        _shown=("Bravo",),
        _view_generation=0,
        _view_names=frozenset(row.name for row in fresh),
        _view_stopped=True,
        _view_state=None,
        _input=0,
        _monitor=SimpleNamespace(check=lambda: 0),
        _identities_kept=Mock(return_value=True),
        _selection=SimpleNamespace(carry=Mock(return_value=dropped), names=lambda: ["Bravo"]),
        _take_tree_selection=Mock(return_value=False),
        selected_names=lambda: ["Bravo"],
        _rebuild=Mock(),
        _apply_selection=Mock(),
        _show_native=Mock(),
        _name_viewed=Mock(),
        _update_moves=Mock(),
        peer=SimpleNamespace(invalidate=Mock()),
        document=None,
        controller=None,
    )
    owner.names = lambda: [row.name for row in owner.rows]

    def snapshot(document: Any) -> Any:
        return observed

    def read_rows(controller: Any, picture: Any) -> list[SheetRow]:
        return fresh

    method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_refresh",
        {"snapshot": snapshot, "read_rows": read_rows, "Mapping": Mapping, "node_text": node_text},
    )(owner, {})
    return owner


@pytest.mark.parametrize(
    "fresh",
    [
        # Calc switched to Bravo: only the painted arrow moves.
        [replace(SHOWN[0], active=False), replace(SHOWN[1], active=True), SHOWN[2]],
        # A tab colour is set, changed and cleared.
        [replace(SHOWN[0], color=0x993322), SHOWN[1], replace(SHOWN[2], color=None)],
    ],
    ids=["switch", "colours"],
)
def test_painted_changes_keep_the_nodes_and_repaint(fresh: list[SheetRow]) -> None:
    owner = refresh(fresh)
    owner._rebuild.assert_not_called()
    assert owner.rows == fresh  # Painting and the accessible name read the new rows.
    owner.peer.invalidate.assert_called_once_with(0)
    owner._apply_selection.assert_not_called()
    owner._name_viewed.assert_called_once_with()


@pytest.mark.parametrize(
    "fresh",
    [
        [SHOWN[0], replace(SHOWN[1], visible=False), SHOWN[2]],
        [SHOWN[0], replace(SHOWN[1], protected=True), SHOWN[2]],
        [SHOWN[0], SHOWN[1], replace(SHOWN[2], scenario=True)],
        [SHOWN[0], replace(SHOWN[1], name="Bravo 2"), SHOWN[2]],
        [SHOWN[1], SHOWN[0], SHOWN[2]],
        [*SHOWN, SheetRow("Delta")],
    ],
    ids=["hidden", "protected", "scenario", "renamed", "moved", "inserted"],
)
def test_a_changed_name_or_label_replaces_the_nodes(fresh: list[SheetRow]) -> None:
    owner = refresh(fresh)
    owner._rebuild.assert_called_once_with(fresh)


def test_the_first_refresh_builds_nodes_even_for_equal_rows() -> None:
    refresh(list(SHOWN), nodes=False)._rebuild.assert_called_once_with(SHOWN)


def test_an_unchanged_refresh_neither_rebuilds_nor_repaints() -> None:
    owner = refresh(list(SHOWN))
    owner._rebuild.assert_not_called()
    owner.peer.invalidate.assert_not_called()


def test_dropped_picks_are_written_back_without_rebuilding_painted_changes() -> None:
    fresh = [replace(SHOWN[0], active=False), replace(SHOWN[1], active=True), SHOWN[2]]
    owner = refresh(fresh, dropped=True)
    owner._rebuild.assert_not_called()
    owner._apply_selection.assert_called_once_with()  # It repaints as it writes the picks.
    owner.peer.invalidate.assert_not_called()


def test_node_text_ignores_only_painted_state() -> None:
    painted = [replace(row, active=not row.active, color=0x123456) for row in SHOWN]
    assert node_text(painted) == node_text(SHOWN)
    assert node_text([replace(SHOWN[0], visible=False)])[0] == ("Alfa", "Alfa (hidden)")
