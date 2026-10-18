"""TEMPORARY sheet mover for drag and drop, to be replaced by the reorder layer of issue #4.

It moves the dragged sheets, in their original order, as one block into the gap the user
dropped them on, with one ``moveByName`` call per sheet that is not already in place, inside
one undo context. It deliberately has no planner: #4 adds the fewest-moves planner, scenario
blocks, the full permission policy, and view-state handling. Until then this module refuses
workbooks with scenario sheets rather than risk moving a scenario away from its base.

The UNO objects are used through their methods only, so this module does not import ``uno``.
"""

from dataclasses import dataclass, field
from typing import Any

from sheet_manager.i18n import tr


def block_target(order: list[str], selected: list[str], gap: int) -> list[str]:
    """The order after moving the selected sheets as one block in front of position gap."""
    picked = set(selected)
    block = [name for name in order if name in picked]
    before = [name for name in order[:gap] if name not in picked]
    after = [name for name in order[gap:] if name not in picked]
    return before + block + after


def block_moves(order: list[str], selected: list[str], gap: int) -> list[tuple[str, int]]:
    """``moveByName(name, index)`` calls that produce block_target; index is the final position.

    Sheets left of the gap move right and are placed last first; sheets right of the gap move
    left and are placed first first. Each call then leaves the earlier placements in position.
    """
    picked = set(selected)
    block = [name for name in order if name in picked]
    left = [name for name in block if order.index(name) < gap]
    right = [name for name in block if order.index(name) >= gap]
    current = list(order)
    calls: list[tuple[str, int]] = []

    def move(name: str, index: int) -> None:
        if current.index(name) != index:
            current.remove(name)
            current.insert(index, name)
            calls.append((name, index))

    for offset, name in enumerate(reversed(left), start=1):
        move(name, gap - offset)
    for offset, name in enumerate(right):
        move(name, gap + offset)
    return calls


@dataclass
class MoveResult:
    status: str  # "moved", "unchanged", "refused", "failed-restored", or "failed-not-restored"
    message: str = ""
    order: list[str] = field(default_factory=list[str])


def refusal(document: Any) -> str:
    """A reason the workbook's sheets cannot be moved now, or an empty string."""
    if document.isReadonly():
        return tr("The document is read-only.")
    if document.isProtected():
        return tr("The workbook structure is protected.")
    if document.getPropertyValue("RecordChanges"):
        return tr("Changes are being recorded.")
    sheets = document.getSheets()
    if any(sheets.getByIndex(i).getIsScenario() for i in range(sheets.getCount())):
        return tr("Workbooks with scenarios cannot be reordered yet.")
    if document.getUndoManager().isLocked():
        return tr("Undo is not available.")
    return ""


def move_block(document: Any, expected: list[str], selected: list[str], gap: int) -> MoveResult:
    """Move the selected sheets to gap as one undo step, if the order is still `expected`."""
    sheets = document.getSheets()
    order = list(sheets.getElementNames())
    if order != expected or not set(selected) <= set(order):
        return MoveResult("refused", tr("The sheets changed; try again."), order)
    target = block_target(order, selected, gap)
    if target == order:
        return MoveResult("unchanged", "", order)
    reason = refusal(document)
    if reason:
        return MoveResult("refused", reason, order)
    undo = document.getUndoManager()
    title = tr("Move Sheets")
    depth = len(undo.getAllUndoActionTitles())
    error = ""
    undo.enterUndoContext(title)
    try:
        for name, index in block_moves(order, selected, gap):
            sheets.moveByName(name, index)
    except Exception as exception:  # A UNO error must not leave a half-done move behind.
        error = str(exception)
    finally:
        undo.leaveUndoContext()
    result = list(sheets.getElementNames())
    if not error and result == target:
        return MoveResult("moved", "", result)
    if len(undo.getAllUndoActionTitles()) > depth:
        undo.undo()
    restored = list(sheets.getElementNames())
    message = tr("The sheets could not be moved.") + (f" {error}" if error else "")
    if restored == order:
        return MoveResult("failed-restored", message, restored)
    return MoveResult(
        "failed-not-restored",
        message + " " + tr("Undo did not restore the previous order; check the workbook."),
        restored,
    )
