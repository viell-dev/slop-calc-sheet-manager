"""A refresh keeps the tree's nodes only for identical rows or a painted-only change (#22)."""

from collections.abc import Mapping
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.sheet_list import SheetRow, node_text, row_label
from tests.unit.list_peer import Book, sheet_list
from tests.unit.source_methods import method

NAMES = ("Alfa", "Bravo", "Charlie")
SHOWN = [SheetRow("Alfa", active=True), SheetRow("Bravo"), SheetRow("Charlie", color=0x2A6099)]
# Calc switched to Bravo, or a tab colour was set, changed and cleared: only painted state moves.
SWITCH = [replace(SHOWN[0], active=False), replace(SHOWN[1], active=True), SHOWN[2]]
COLOURS = [replace(SHOWN[0], color=0x993322), SHOWN[1], replace(SHOWN[2], color=None)]


def refresh(
    fresh: list[SheetRow],
    *,
    shown: list[SheetRow] = SHOWN,
    nodes: bool = True,
    proven: bool = True,
    dropped: bool = False,
    picked: tuple[str, ...] = ("Bravo",),
    apply: Any = None,
) -> Any:
    """Run `SheetList._refresh` over sheets showing `shown` whose rows now read as `fresh`.

    The tree shows `Bravo` picked; the list's own picks are `picked`. `proven` is whether the
    handles still prove which sheet each row is, and `dropped` whether revalidating the picks,
    or dropping them all when the proof was lost, dropped any. `apply` runs as the write of the
    picks.
    """
    observed = SimpleNamespace(
        sheets=[SimpleNamespace(name=row.name) for row in fresh],
        handles=[object() for _ in fresh],
    )
    owner = SimpleNamespace(
        _press=None,
        _observed=observed,
        _proven=0,
        _generation=0,
        _nodes=[object()] * len(shown) if nodes else [],
        rows=list(shown),
        _shown=("Bravo",),
        _view_generation=0,
        _view_names=frozenset(row.name for row in fresh),
        _view_stopped=True,
        _view_state=None,
        _input=0,
        _monitor=SimpleNamespace(check=lambda: 0),
        _identities_kept=Mock(return_value=proven),
        _drop_all_picks=Mock(return_value=dropped),
        _selection=SimpleNamespace(carry=Mock(return_value=dropped), names=lambda: list(picked)),
        _take_tree_selection=Mock(return_value=False),
        selected_names=lambda: ["Bravo"],
        _rebuild=Mock(),
        _apply_selection=Mock(side_effect=apply),
        _show_native=Mock(),
        _name_viewed=Mock(),
        _update_moves=Mock(),
        peer=SimpleNamespace(invalidate=Mock()),
        document=None,
        controller=None,
    )
    owner.names = lambda: [row.name for row in owner.rows]
    reports: list[str] = []
    owner.reports = reports
    kept = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_apply_kept_selection",
        {"SheetRow": SheetRow, "report": reports.append},
    )

    def apply_kept_selection(rows: list[SheetRow]) -> None:
        kept(owner, rows)

    owner._apply_kept_selection = apply_kept_selection

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


@pytest.mark.parametrize("fresh", [SWITCH, COLOURS], ids=["switch", "colours"])
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


def test_a_label_kept_under_another_name_replaces_the_nodes() -> None:
    # A visible sheet literally named "Bravo (hidden)" becomes a hidden sheet named "Bravo": the
    # label reads the same, but the node's DataValue, which the list reads back, does not.
    shown = [SHOWN[0], SheetRow("Bravo (hidden)"), SHOWN[2]]
    fresh = [SHOWN[0], SheetRow("Bravo", visible=False), SHOWN[2]]
    assert [row_label(row) for row in fresh] == [row_label(row) for row in shown]
    refresh(fresh, shown=shown)._rebuild.assert_called_once_with(fresh)


def test_the_first_refresh_builds_nodes_even_for_equal_rows() -> None:
    refresh(list(SHOWN), nodes=False)._rebuild.assert_called_once_with(SHOWN)


def test_an_unchanged_refresh_neither_rebuilds_nor_repaints() -> None:
    owner = refresh(list(SHOWN))
    owner._rebuild.assert_not_called()
    owner.peer.invalidate.assert_not_called()


@pytest.mark.parametrize("dropped", [False, True], ids=["nothing owned", "picks dropped"])
def test_a_lost_proof_over_identical_rows_writes_the_picks_to_the_kept_nodes(
    dropped: bool,
) -> None:
    # A native selection awaiting intake was made against the sheets the proof covered:
    # writing the remaining picks clears it, even when the list owned none (`dropped` False).
    owner = refresh(
        list(SHOWN), proven=False, dropped=dropped, picked=() if dropped else ("Bravo",)
    )
    owner._drop_all_picks.assert_called_once_with()
    owner._rebuild.assert_not_called()
    owner._apply_selection.assert_called_once_with()


def test_a_lost_proof_with_painted_changes_replaces_the_nodes() -> None:
    owner = refresh(SWITCH, proven=False)
    owner._rebuild.assert_called_once_with(SWITCH)
    owner._apply_selection.assert_not_called()
    owner.peer.invalidate.assert_not_called()


@pytest.mark.parametrize("proven", [True, False])
def test_a_failed_write_to_the_kept_nodes_replaces_them(proven: bool) -> None:
    def fail() -> None:
        raise RuntimeError("the tree refused the write")

    fresh = list(SHOWN)
    owner = refresh(fresh, proven=proven, picked=("Bravo", "Charlie"), apply=fail)
    owner._rebuild.assert_called_once_with(fresh)
    assert owner.reports == ["writing the selection to the sheet list"]


@pytest.mark.parametrize(
    ("dropped", "picked"), [(True, ()), (False, ("Bravo", "Charlie"))], ids=["dropped", "newer"]
)
def test_changed_picks_with_painted_changes_replace_the_nodes(
    dropped: bool, picked: tuple[str, ...]
) -> None:
    owner = refresh(SWITCH, dropped=dropped, picked=picked)
    owner._rebuild.assert_called_once_with(SWITCH)
    owner.peer.invalidate.assert_not_called()


@pytest.mark.parametrize(
    ("dropped", "picked"), [(True, ()), (False, ("Bravo", "Charlie"))], ids=["dropped", "newer"]
)
def test_changed_picks_over_identical_rows_are_written_to_the_kept_nodes(
    dropped: bool, picked: tuple[str, ...]
) -> None:
    owner = refresh(list(SHOWN), dropped=dropped, picked=picked)
    owner._rebuild.assert_not_called()
    owner._apply_selection.assert_called_once_with()  # It repaints as it writes the picks.


def test_node_text_ignores_only_painted_state() -> None:
    painted = [replace(row, active=not row.active, color=0x123456) for row in SHOWN]
    assert node_text(painted) == node_text(SHOWN)
    assert node_text([replace(SHOWN[0], visible=False)])[0] == ("Alfa", "Alfa (hidden)")


@pytest.mark.parametrize("failures", [1, 2])
def test_a_failed_repaint_is_retried(failures: int) -> None:
    book = Book(list(NAMES))
    owner = sheet_list(book)
    owner._select(["Bravo"], "Bravo")
    nodes, rows, painted = owner._nodes, owner.rows, owner.peer.invalidations
    book.sheet("Charlie").color = 0x993322
    owner.peer.failures = failures
    for _ in range(failures):
        with pytest.raises(RuntimeError, match="invalidate"):
            owner._refresh({})  # The refresh, then its retries (#186).
        assert owner.rows == rows, "The rows were taken although their repaint failed"
    owner._refresh({})
    assert owner._nodes is nodes
    assert owner.peer.invalidations == painted + 1, "The retry did not repaint"
    assert owner.rows == book.rows()
    assert owner.tree.shown() == owner._selection.names() == ["Bravo"]
    owner._refresh({})  # Once it has succeeded, nothing is left to repaint.
    assert owner.peer.invalidations == painted + 1


@pytest.mark.parametrize("failures", [0, 1], ids=["written", "write failed"])
def test_a_replaced_pick_whose_row_reads_the_same_is_dropped_from_the_tree(failures: int) -> None:
    book = Book(list(NAMES))
    owner = sheet_list(book)
    owner._select(["Charlie"], "Charlie")
    nodes = owner._nodes
    book.replace("Charlie")  # Its row reads exactly the same, but the pick cannot be proved.
    assert book.rows() == owner.rows
    owner.tree.failures = failures  # The write of the dropped pick fails.
    owner._refresh({})
    # The kept nodes show the dropped pick no more; after a failed write, new nodes show none.
    assert (owner._nodes is nodes) == (not failures)
    assert owner.tree.shown() == owner._selection.names() == []
    assert owner.rows == book.rows()
