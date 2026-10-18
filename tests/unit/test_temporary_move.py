"""The temporary drag-and-drop mover: block targets, final-index moves, one undo step."""

from itertools import combinations
from typing import Any

import pytest

from sheet_manager.temporary_move import block_moves, block_target, move_block


def apply(order: list[str], calls: list[tuple[str, int]]) -> list[str]:
    """XSpreadsheets.moveByName semantics: the sheet ends at the given final index."""
    result = list(order)
    for name, index in calls:
        result.remove(name)
        result.insert(index, name)
    return result


def test_block_target() -> None:
    order = list("ABCDEFG")
    assert block_target(order, ["B", "E"], 6) == list("ACDFBEG")
    assert block_target(order, ["E", "B"], 0) == list("BEACDFG")
    assert block_target(order, ["B", "E"], 3) == list("ACBEDFG")
    assert block_target(order, ["C", "D"], 3) == order  # Dropped in place.
    assert block_target(order, ["C", "D"], 2) == order
    assert block_target(order, ["C", "D"], 4) == order


def test_block_moves_reach_every_target_moving_only_selected_sheets() -> None:
    for size in range(1, 7):
        order = [chr(ord("A") + index) for index in range(size)]
        for count in range(1, size + 1):
            for selected in combinations(order, count):
                for gap in range(size + 1):
                    calls = block_moves(order, list(selected), gap)
                    target = block_target(order, list(selected), gap)
                    assert apply(order, calls) == target, (order, selected, gap, calls)
                    assert {name for name, _ in calls} <= set(selected)
                    assert len(calls) <= count
                    if target == order:
                        assert calls == []


class Sheet:
    def __init__(self, scenario: bool = False) -> None:
        self.scenario = scenario

    def getIsScenario(self) -> bool:
        return self.scenario


class Sheets:
    def __init__(self, names: list[str], scenarios: set[str], fail_after: int | None) -> None:
        self.names = list(names)
        self.scenarios = scenarios
        self.fail_after = fail_after
        self.calls = 0

    def getElementNames(self) -> tuple[str, ...]:
        return tuple(self.names)

    def getCount(self) -> int:
        return len(self.names)

    def getByIndex(self, index: int) -> Sheet:
        return Sheet(self.names[index] in self.scenarios)

    def moveByName(self, name: str, index: int) -> None:
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise RuntimeError("injected failure")
        self.calls += 1
        self.names.remove(name)
        self.names.insert(index, name)


class Undo:
    """Records one action per outermost context; undo restores that context's snapshot."""

    def __init__(self, sheets: Sheets, restores: bool) -> None:
        self.sheets = sheets
        self.restores = restores
        self.titles: list[str] = []
        self.snapshots: list[list[str]] = []
        self.locked = False
        self.depth = 0
        self.pending: tuple[str, list[str]] = ("", [])

    def isLocked(self) -> bool:
        return self.locked

    def getAllUndoActionTitles(self) -> tuple[str, ...]:
        return tuple(self.titles)

    def enterUndoContext(self, title: str) -> None:
        self.depth += 1
        self.pending = (title, list(self.sheets.names))

    def leaveUndoContext(self) -> None:
        self.depth -= 1
        title, snapshot = self.pending
        if self.sheets.names != snapshot:
            self.titles.insert(0, title)
            self.snapshots.insert(0, snapshot)

    def undo(self) -> None:
        self.titles.pop(0)
        snapshot = self.snapshots.pop(0)
        if self.restores:
            self.sheets.names = snapshot


class Document:
    def __init__(
        self,
        names: str = "ABCDEF",
        *,
        readonly: bool = False,
        protected: bool = False,
        recording: bool = False,
        scenarios: str = "",
        fail_after: int | None = None,
        undo_restores: bool = True,
    ) -> None:
        self.sheets = Sheets(list(names), set(scenarios), fail_after)
        self.undo = Undo(self.sheets, undo_restores)
        self.readonly, self.protected, self.recording = readonly, protected, recording

    def getSheets(self) -> Sheets:
        return self.sheets

    def getUndoManager(self) -> Undo:
        return self.undo

    def isReadonly(self) -> bool:
        return self.readonly

    def isProtected(self) -> bool:
        return self.protected

    def getPropertyValue(self, name: str) -> Any:
        assert name == "RecordChanges"
        return self.recording


def test_moves_as_one_undo_step() -> None:
    document = Document()
    result = move_block(document, list("ABCDEF"), ["B", "D"], 6)
    assert result.status == "moved" and result.order == list("ACEFBD")
    assert document.undo.titles == ["Move Sheets"]
    document.undo.undo()
    assert document.sheets.names == list("ABCDEF")


def test_dropping_in_place_changes_nothing() -> None:
    document = Document()
    result = move_block(document, list("ABCDEF"), ["C", "D"], 4)
    assert result.status == "unchanged" and document.undo.titles == []


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (Document(readonly=True), "read-only"),
        (Document(protected=True), "protected"),
        (Document(recording=True), "recorded"),
        (Document(scenarios="F"), "scenarios"),
    ],
)
def test_refuses_what_it_cannot_do_safely(document: Document, message: str) -> None:
    result = move_block(document, list("ABCDEF"), ["A"], 6)
    assert result.status == "refused" and message in result.message
    assert document.sheets.names == list("ABCDEF") and document.undo.titles == []


def test_refuses_a_stale_order() -> None:
    document = Document()
    result = move_block(document, list("ABCDFE"), ["A"], 6)
    assert result.status == "refused" and document.sheets.calls == 0
    result = move_block(document, list("ABCDEF"), ["Z"], 6)
    assert result.status == "refused"


def test_refuses_when_undo_is_locked() -> None:
    document = Document()
    document.undo.locked = True
    assert move_block(document, list("ABCDEF"), ["A"], 6).status == "refused"


def test_a_failure_is_undone() -> None:
    document = Document(fail_after=1)
    result = move_block(document, list("ABCDEF"), ["A", "C"], 6)
    assert result.status == "failed-restored" and "injected failure" in result.message
    assert document.sheets.names == list("ABCDEF") and document.undo.titles == []


def test_a_failed_undo_is_reported() -> None:
    document = Document(fail_after=1, undo_restores=False)
    result = move_block(document, list("ABCDEF"), ["A", "C"], 6)
    assert result.status == "failed-not-restored" and "check the workbook" in result.message
