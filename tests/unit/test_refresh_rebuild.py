"""A refresh keeps the tree's nodes for identical rows, and for a purely painted change (#22).

A painted change, a sheet switch or a tab colour, keeps the nodes only while nothing else is owed
(`SheetList._painted_only`); every other case takes `main`'s path: a replacement when the rows
changed, the in-place write of the picks when they read the same.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.selection import Ref
from sheet_manager.sheet_list import SheetRow, node_text, row_label
from tests.unit.list_peer import Book, Handle, sheet_list
from tests.unit.source_methods import method

NAMES = ("Alfa", "Bravo", "Charlie")
SHOWN = [SheetRow("Alfa", active=True), SheetRow("Bravo"), SheetRow("Charlie", color=0x2A6099)]
# Calc switched to Bravo, or a tab colour was set, changed and cleared: only painted state moves.
SWITCH = [replace(SHOWN[0], active=False), replace(SHOWN[1], active=True), SHOWN[2]]
COLOURS = [replace(SHOWN[0], color=0x993322), SHOWN[1], replace(SHOWN[2], color=None)]


def prepare(
    fresh: list[SheetRow],
    *,
    shown: list[SheetRow] = SHOWN,
    nodes: bool = True,
    proven: bool = True,
    dropped: bool = False,
    picked: tuple[str, ...] = ("Bravo",),
    written: tuple[str, ...] = ("Bravo",),
    tree: tuple[str, ...] = ("Bravo",),
    apply: Any = None,
) -> tuple[Any, Callable[[], None]]:
    """A list over sheets showing `shown` whose rows now read as `fresh`, and its `_refresh`.

    The list's own picks are `picked`, it last wrote `written` to the tree (`_shown`), and the
    tree shows `tree`. `proven` is whether the handles still prove which sheet each row is, and
    `dropped` whether revalidating the picks, or dropping them all when the proof was lost,
    dropped any. `apply` runs as the write of the picks.
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
        _replacement_pending=False,
        _refresh_failures=0,
        rows=list(shown),
        _shown=written,
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
        selected_names=lambda: list(tree),
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
    painted = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_painted_only",
        {"SheetRow": SheetRow, "node_text": node_text},
    )

    def painted_only(rows: list[SheetRow], proven: bool, dropped: bool) -> bool:
        return painted(owner, rows, proven, dropped)

    owner._painted_only = painted_only
    reports: list[str] = []
    owner.reports = reports

    def snapshot(document: Any) -> Any:
        return observed

    def read_rows(controller: Any, picture: Any) -> list[SheetRow]:
        return fresh

    run = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_refresh",
        {
            "snapshot": snapshot,
            "read_rows": read_rows,
            "Mapping": Mapping,
            "report": reports.append,
        },
    )
    return owner, lambda: run(owner, {})


def refresh(fresh: list[SheetRow], **arguments: Any) -> Any:
    """Run `SheetList._refresh` as `prepare` sets it up; the list afterwards."""
    owner, run = prepare(fresh, **arguments)
    run()
    return owner


@pytest.mark.parametrize("fresh", [SWITCH, COLOURS], ids=["switch", "colours"])
def test_painted_changes_keep_the_nodes_and_repaint(fresh: list[SheetRow]) -> None:
    owner = refresh(fresh)
    owner._rebuild.assert_not_called()
    assert owner.rows == fresh  # Painting and the accessible name read the new rows.
    owner.peer.invalidate.assert_called_once_with(0)
    owner._apply_selection.assert_not_called()
    owner._name_viewed.assert_called_once_with()


def test_a_failed_repaint_request_replaces_the_nodes_in_the_same_refresh() -> None:
    owner, run = prepare(SWITCH)
    owner.peer.invalidate.side_effect = RuntimeError("the peer refused to invalidate")
    run()  # Nothing had changed: the refresh replaces the nodes, as for any other change.
    owner._rebuild.assert_called_once_with(SWITCH)
    assert owner.rows == SHOWN, "The rows were taken although their repaint failed"
    assert owner.reports == ["repainting the sheet list"]
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


def refuse_the_write() -> None:
    raise RuntimeError("the tree refused the write")


@pytest.mark.parametrize("proven", [True, False], ids=["proof intact", "proof lost"])
def test_a_failed_write_to_the_kept_nodes_is_left_to_the_retry(proven: bool) -> None:
    # As on `main`: no replacement follows a failed in-place write, even after a lost proof,
    # where one would select the cursor's row first and could fail in its turn (#257).
    owner, run = prepare(
        list(SHOWN), proven=proven, picked=("Bravo", "Charlie"), apply=refuse_the_write
    )
    with pytest.raises(RuntimeError, match="refused the write"):
        run()  # `refresh` schedules the retry (#186).
    owner._rebuild.assert_not_called()


@pytest.mark.parametrize(
    ("dropped", "picked"),
    [(True, ()), (True, ("Bravo",)), (False, ("Bravo", "Charlie"))],
    ids=["dropped", "cursor dropped", "newer"],
)
def test_changed_picks_with_painted_changes_replace_the_nodes(
    dropped: bool, picked: tuple[str, ...]
) -> None:
    owner = refresh(SWITCH, dropped=dropped, picked=picked)
    owner._rebuild.assert_called_once_with(SWITCH)
    owner.peer.invalidate.assert_not_called()


@pytest.mark.parametrize(
    ("dropped", "picked"),
    [(True, ()), (True, ("Bravo",)), (False, ("Bravo", "Charlie"))],
    ids=["dropped", "cursor dropped", "newer"],
)
def test_changed_picks_over_identical_rows_are_written_to_the_kept_nodes(
    dropped: bool, picked: tuple[str, ...]
) -> None:
    owner = refresh(list(SHOWN), dropped=dropped, picked=picked)
    owner._rebuild.assert_not_called()
    owner._apply_selection.assert_called_once_with()  # It repaints as it writes the picks.


@pytest.mark.parametrize(
    "owed",
    [
        "press held",
        "earlier refresh failed",
        "replacement not installed",
        "selection awaiting intake",
        "tree shows part of a write",
        "picks reordered by others",
    ],
)
def test_a_painted_change_is_replaced_while_anything_else_is_owed(owed: str) -> None:
    arguments: dict[str, Any] = {}
    if owed == "selection awaiting intake":
        arguments["tree"] = ("Bravo", "Charlie")  # As selected through accessibility.
    elif owed == "tree shows part of a write":
        arguments["tree"] = ("Charlie",)  # A cursor's row selected before a failed clear.
    elif owed == "picks reordered by others":
        arguments.update(picked=("Charlie", "Bravo"), written=("Bravo", "Charlie"))
        arguments["tree"] = ("Bravo", "Charlie")
    owner, run = prepare(SWITCH, **arguments)
    if owed == "press held":
        owner._press = object()
    elif owed == "earlier refresh failed":
        owner._refresh_failures = 1
    elif owed == "replacement not installed":
        owner._replacement_pending = True
    run()
    owner._rebuild.assert_called_once_with(SWITCH)
    owner.peer.invalidate.assert_not_called()


def test_node_text_ignores_only_painted_state() -> None:
    painted = [replace(row, active=not row.active, color=0x123456) for row in SHOWN]
    assert node_text(painted) == node_text(SHOWN)
    assert node_text([replace(SHOWN[0], visible=False)])[0] == ("Alfa", "Alfa (hidden)")


@pytest.mark.parametrize("failures", [1, 2])
def test_a_failed_repaint_takes_the_replacement_at_once(failures: int) -> None:
    book = Book(list(NAMES))
    owner = sheet_list(book)
    owner._select(["Bravo"], "Bravo")
    nodes = owner._nodes
    book.sheet("Charlie").color = 0x993322
    owner.peer.failures = failures
    if failures == 1:
        owner.attempt()
    else:
        # The replacement's own repaint fails too, after it took the rows with its nodes, as
        # on `main`; its retry finds nothing left to write (#186).
        with pytest.raises(RuntimeError, match="invalidate"):
            owner.attempt()
        assert owner.waits == [0.5]
        owner.attempt()
    assert owner._nodes is not nodes, "A failed repaint kept the nodes"
    assert owner.tree.data is not None and owner.tree.data.root.children == owner._nodes
    assert owner.rows == book.rows()
    assert owner.tree.shown() == owner._selection.names() == ["Bravo"]
    assert owner.reports == ["repainting the sheet list"]
    assert owner._refresh_failures == 0 and owner.peer.failures == 0
    nodes, painted = owner._nodes, owner.peer.invalidations
    book.sheet("Charlie").color = None  # Once one has succeeded, a colour only repaints again.
    owner.attempt()
    assert owner._nodes is nodes
    assert owner.peer.invalidations == painted + 1
    assert owner.rows == book.rows()


def test_a_failed_repaint_and_then_a_failed_clear_leave_only_the_picks_to_take() -> None:
    book = Book([*NAMES, "Delta"])
    owner = sheet_list(book)
    owner._select(["Bravo"], "Delta")  # The keyboard cursor is on an unpicked row.
    book.sheet("Alfa").color = 0x993322
    owner.peer.failures = 1  # The repaint request fails,
    owner.attempt()
    owner.tree.failures = 1  # and then a clear, as in the next write.
    owner.attempt()
    owner.run_queue()
    # The failed request was followed at once by the replacement, whose write completed, so
    # the later refreshes have nothing to write: a retry that replaced the nodes only then
    # would select Delta for the cursor and fail at the clear, leaving Delta to take.
    assert owner.tree.shown() == ["Bravo"]
    owner.tree.failures = 0
    assert [ref.name for ref in owner._current_picks()] == ["Bravo"], "An unpicked row was taken"


def test_a_replaced_pick_whose_row_reads_the_same_is_dropped_from_the_tree() -> None:
    book = Book(list(NAMES))
    owner = sheet_list(book)
    owner._select(["Charlie"], "Charlie")
    nodes = owner._nodes
    book.replace("Charlie")  # Its row reads exactly the same, but the pick cannot be proved.
    assert book.rows() == owner.rows
    owner.attempt()
    assert owner._nodes is nodes  # The kept nodes show the dropped pick no more.
    assert owner.tree.shown() == owner._selection.names() == []
    assert owner.rows == book.rows()


def test_picks_reordered_by_others_take_the_replacement_for_painted_changes() -> None:
    book = Book([*NAMES, "Delta"])
    owner = sheet_list(book)
    owner._select(["Bravo", "Charlie"], "Delta")
    book.move("Charlie", 1)  # Others move Charlie ahead of Bravo; both stay picked.
    owner.attempt()
    # The tree shows the picks in the rows' order; the list keeps the order they were made in,
    # which no longer shows that the tree holds exactly them (`_painted_only`): a missed
    # repaint-only refresh, as on `main`, rather than a membership comparison that a failed
    # write can satisfy.
    assert owner._shown == ("Charlie", "Bravo")
    assert owner._selection.names() == ["Bravo", "Charlie"]
    for colour in (0x993322, 0x2A6099, None):
        nodes = owner._nodes
        book.sheet("Alfa").color = colour
        owner.attempt()
        assert owner._nodes is not nodes
        assert owner.rows == book.rows()
        assert owner.tree.shown() == ["Charlie", "Bravo"]


@dataclass
class HeldPress:
    """A press on a row whose release is still to come."""

    voided: bool = False


@pytest.mark.parametrize("reordered", [True, False], ids=["picks reordered", "picks in order"])
def test_a_retry_rewrites_picks_a_failed_rebuild_left_unwritten(reordered: bool) -> None:
    book = Book([*NAMES, "Delta"])
    owner = sheet_list(book)
    owner._select(["Bravo", "Charlie"], "Delta")  # The keyboard cursor is on an unpicked row,
    owner._press = HeldPress()  # as after a held Ctrl-press that deselects it.
    if reordered:
        book.move("Charlie", 1)  # Others move Charlie ahead of Bravo: the nodes are replaced.
    else:
        book.sheet("Delta").color = 0x993322  # Only painted, but a press is held: replaced too.
    owner.tree.failures = 1  # The new nodes' write selects Delta for the cursor, then fails.
    with pytest.raises(RuntimeError, match="clear"):
        owner.attempt()
    assert owner.tree.shown() == ["Delta"]
    owner.attempt()  # The healthy retry, with the press still held (#186).
    owner.run_queue()
    if reordered:
        # As on `main`: the rows read the same as the failed rebuild's, and the picks in their
        # own order differ from the rows' order, so the retry writes them again.
        assert owner.tree.shown() == ["Charlie", "Bravo"], "A partial write was left shown"
        owner._press = None  # The release, or a drag, reads the picks.
        assert sorted(ref.name for ref in owner._current_picks()) == ["Bravo", "Charlie"]
    else:
        # The same picks in the rows' order find nothing to write, also on `main`: the failed
        # write's Delta stays shown (#257).
        assert owner.tree.shown() == ["Delta"]


def test_a_painted_change_replaces_a_tree_left_showing_part_of_a_write() -> None:
    book = Book([*NAMES, "Delta"])
    owner = sheet_list(book)
    owner._select(["Bravo"], "Bravo")
    owner._selection.cursor = owner._ref("Delta")
    owner.tree.failures = 1  # A write outside a refresh selects Delta for the cursor, then fails.
    with pytest.raises(RuntimeError, match="clear"):
        owner._apply_selection()
    assert owner.tree.shown() == ["Delta"] and owner._shown == ("Bravo",)
    owner._context_target = object()  # A context menu is open: the intake waits for it.
    nodes = owner._nodes
    book.sheet("Alfa").color = 0x993322
    owner.attempt()
    # The tree does not show what the list last wrote, so the nodes are replaced, which
    # writes the picks (`_painted_only`); kept nodes would leave Delta for the next intake.
    assert owner._nodes is not nodes
    assert owner.tree.shown() == ["Bravo"]
    owner._context_target = None
    assert [ref.name for ref in owner._current_picks()] == ["Bravo"]


def test_a_failed_write_after_a_lost_proof_attempts_no_replacement() -> None:
    book = Book([*NAMES, "Delta"])
    owner = sheet_list(book)
    owner._select(["Bravo"], "Bravo")
    nodes = owner._nodes
    book.handle(book.sheet("Delta")).readable = False  # The proof is lost; the rows read the same.
    owner.tree.failures = 1  # The write of the dropped pick fails,
    owner.tree.model.failures, owner.tree.model.shown_before_failing = 1, True  # and a model too.
    with pytest.raises(RuntimeError, match="clear"):
        owner.attempt()
    # As on `main`, the failed write is left to the retry: no data model is assigned, so a
    # setter that installs and then raises cannot leave cached nodes the tree does not own.
    assert owner._nodes is nodes and owner.tree.model.failures == 1
    book.handle(book.sheet("Delta")).readable = True
    owner.attempt()
    assert owner._nodes is nodes and owner._refresh_failures == 0 and owner.waits == [0.5]


def test_a_completed_write_whose_repaint_failed_leaves_only_the_picks_to_take() -> None:
    book = Book([*NAMES, "Delta"])
    owner = sheet_list(book)
    owner._select(["Bravo", "Charlie"], "Delta")  # The keyboard cursor is on an unpicked row.
    bravo, charlie = owner._selection.picked
    # Charlie's retained handle cannot be read for a moment, while the snapshot's own handles
    # prove every sheet: its pick drops with the proof intact, over rows that read the same.
    stale = Handle(book.sheet("Charlie"))
    stale.readable = False
    owner._selection.picked = [bravo, Ref("Charlie", stale, charlie.position)]
    invalidate = owner.peer.invalidate

    def refuse_then_fail_a_clear(flags: int) -> None:
        # The write has selected Bravo alone when the repaint fails, and the next clear fails.
        owner.peer.invalidate = invalidate
        owner.tree.failures = 1
        raise RuntimeError("the peer refused to invalidate")

    owner.peer.invalidate = refuse_then_fail_a_clear
    with pytest.raises(RuntimeError):
        owner.attempt()
    assert owner._proven == book.generation and owner._generation == 0
    owner.tree.failures = 0  # The tree is healthy again for the retry (#186).
    owner.attempt()
    owner.run_queue()
    assert [ref.name for ref in owner._current_picks()] == ["Bravo"], "An unpicked row was taken"
    assert owner.tree.shown() == ["Bravo"]


@pytest.mark.parametrize("held", [True, False], ids=["held press", "no press"])
def test_a_failed_replacement_offers_none_of_the_old_selection(held: bool) -> None:
    # The assignment fails before showing the new nodes. One that shows them and then raises
    # leaves cached nodes that the installed model does not own, which the retry's scroll read
    # passes to the tree, also on `main` (#257).
    book = Book([*NAMES, "Delta"])
    owner = sheet_list(book)
    if held:
        owner._press = HeldPress()
    owner.tree.assistive_select("Bravo")  # Awaiting intake, as through accessibility.
    book.replace("Bravo")  # The proof is lost, and a tab colour makes the rows differ: the
    book.sheet("Alfa").color = 0x993322  # nodes are replaced, which fails once.
    owner.tree.model.failures = 1
    with pytest.raises(RuntimeError, match="data model"):
        owner.attempt()
    # The retry (#186) finds only painted state changed since the failed refresh's proof, but
    # the old model's selection was made against the proof that refresh replaced: on `main`,
    # without a press, the retry showed it again over the new nodes and the intake took it.
    owner.attempt()
    owner.run_queue()
    assert owner.tree.data is not None
    assert owner.tree.data.root.children == owner._nodes, "The retry kept the old nodes"
    assert owner.rows == book.rows()
    assert owner.tree.shown() == []
    owner._press = None  # A drag or the release ends the press, then reads the picks.
    assert owner._current_picks() == [], "A selection made against the old model was taken"
