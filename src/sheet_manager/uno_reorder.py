"""Guarded UNO adapter for the pure reorder planner. Call synchronously on the UI thread.

`reorder` plans the target order and the fewest individual moves without UNO. This adapter takes
snapshots, checks permissions and stale handles, applies a plan as one undo step, and verifies
the result or its recovery. docs/reordering.md is the contract the panel relies on.

- The panel stays busy and defers refresh while a plan is applied: consecutive individual moves
  of a scenario block split it in between.
- Never pass an interior scenario gap through as a raw move destination, and never use Calc's
  native multi-sheet Move.
- Keep balanced nested undo contexts. Calc limits the current context to the configured undo
  steps, so a flat context silently loses the earliest moves above that capacity (#16). The tests
  cover a capacity of two.
- Snapshots carry the shared `uno_structure` monitor's identity and generation, and
  `is_current`, `preflight` and `apply_order` check both. Undo and Redo invalidate a held
  snapshot even when they restore the original order, so recovery tests take fresh ones.
"""

from dataclasses import dataclass
from typing import Any, Literal, cast

import uno
from com.sun.star.beans import PropertyValue

from sheet_manager.i18n import tr
from sheet_manager.reorder import Move, Plan, Sheet, ordered_blocks, plan_order
from sheet_manager.uno_structure import StructureMonitor, monitor_for


@dataclass(frozen=True)
class Snapshot:
    sheets: tuple[Sheet, ...]
    document_id: str
    monitor: StructureMonitor
    generation: int
    # A second line of checking; these are not stable sheet identities.
    handles: tuple[Any, ...]


@dataclass(frozen=True)
class Availability:
    allowed: bool
    reason: str = ""
    detail: str = ""
    undo_steps: int = 0


@dataclass(frozen=True)
class Result:
    status: Literal["done", "refused", "failed-restored", "failed-not-restored"]
    message: str
    moves: int = 0
    detail: str = ""  # Diagnostic text; the UI presents the translated message.


def snapshot(document: Any) -> Snapshot:
    """Read fresh physical ordering, including hidden and scenario sheets."""
    monitor = monitor_for(document)
    generation = monitor.check()
    sheets, handles = _read_sheets(document)
    return Snapshot(sheets, str(document.RuntimeUID), monitor, generation, handles)


def _read_sheets(document: Any) -> tuple[tuple[Sheet, ...], tuple[Any, ...]]:
    """Read physical state without consuming the monitor's pending notification evidence."""
    collection = document.getSheets()
    names = tuple(collection.getElementNames())
    handles = tuple(collection.getByName(name) for name in names)
    return (
        tuple(
            Sheet(name, bool(handle.getIsScenario()))
            for name, handle in zip(names, handles, strict=True)
        ),
        handles,
    )


def is_current(document: Any, observed: Snapshot) -> bool:
    """Check structural continuity, physical order, scenario flags, and retained handle names."""
    if str(document.RuntimeUID) != observed.document_id:
        return False
    if observed.monitor.check() != observed.generation:
        return False
    fresh = snapshot(document)
    return (
        fresh.monitor is observed.monitor
        and fresh.generation == observed.generation
        and (
            fresh.sheets == observed.sheets
            and all(
                handle.getName() == sheet.name
                for handle, sheet in zip(observed.handles, observed.sheets, strict=True)
            )
            and observed.monitor.check() == observed.generation
        )
    )


def undo_steps(context: Any) -> int:
    """The configured undo capacity, read without changing it."""
    return _undo_steps(context)


def _undo_steps(context: Any) -> int:
    provider = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", context
    )
    argument = PropertyValue()
    argument.Name, argument.Value = "nodepath", "/org.openoffice.Office.Common/Undo"
    access = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationAccess", (argument,)
    )
    try:
        return int(access.getPropertyValue("Steps"))
    finally:
        access.dispose()


def preflight(context: Any, document: Any, observed: Snapshot, plan: Plan) -> Availability:
    """Return an enablement reason, and repeat this check immediately before applying.

    Treat an unreadable safety condition as a refusal. A plan is tied to the whole
    observed order and retained sheet handles, not just the selected names.
    """
    try:
        if plan.before != observed.sheets or not is_current(document, observed):
            return Availability(False, tr("The sheet list has changed. Refresh it and try again."))
        # Validate against the canonical (cached) plan, including indices and scenario blocks.
        if plan_order(observed.sheets, plan.target) != plan:
            return Availability(False, tr("The move plan is invalid. Refresh it and try again."))
        return plan_availability(move_availability(context, document), plan)
    except Exception as error:
        return Availability(
            False, tr("Sheet Manager could not verify that this move is safe."), str(error)
        )


def move_availability(context: Any, document: Any) -> Availability:
    """Shared document permissions for enablement; execution still needs full preflight."""
    try:
        if document.isReadonly():
            return Availability(False, tr("This document is read-only."))
        if document.isProtected():
            return Availability(False, tr("The document's sheet structure is protected."))
        if document.getPropertyValue("RecordChanges"):
            return Availability(False, tr("Sheets cannot move while changes are being recorded."))
        undo = document.getUndoManager()
        capacity = _undo_steps(context)
        if not document.getPropertyValue("IsUndoEnabled") or undo.isLocked() or capacity <= 0:
            return Availability(False, tr("Enable undo before moving sheets."))
        # An open context is listed in the stack, but cannot be undone until
        # closed. An empty top-level stack instead has no titles at all.
        if undo.getAllUndoActionTitles() and not undo.isUndoPossible():
            return Availability(False, tr("Finish the current undo action before moving sheets."))
        controller = document.getCurrentController()
        if controller is None or not controller.getFrame().isActive():
            return Availability(False, tr("Activate this document's window before moving sheets."))
        return Availability(True, undo_steps=capacity)
    except Exception as error:
        return Availability(
            False, tr("Sheet Manager could not verify that this move is safe."), str(error)
        )


def plan_availability(permission: Availability, plan: Plan) -> Availability:
    """Add plan-specific enablement without rereading the document or configuration."""
    if not permission.allowed:
        return permission
    if permission.undo_steps == 1 and len(plan.moves) > 1:
        return Availability(
            False, tr("Increase undo history to at least two steps before moving these sheets.")
        )
    if not plan.moves:
        return Availability(False, tr("The sheets are already in that position."))
    return permission


def _selected_names(context: Any, controller: Any, names: tuple[str, ...]) -> tuple[str, ...]:
    reflection = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.reflection.CoreReflection", context
    )
    method = reflection.forName("com.sun.star.sheet.XSelectedSheetsSupplier").getMethod(
        "getSelectedSheets"
    )
    return tuple(names[int(index)] for index in method.invoke(controller, ())[0])


def _restore_view(context: Any, controller: Any, active: str, selected: tuple[str, ...]) -> None:
    sheets = controller.getModel().getSheets()
    if controller.getActiveSheet().getName() != active:
        controller.setActiveSheet(sheets.getByName(active))
    names = tuple(sheets.getElementNames())
    if set(_selected_names(context, controller, names)) != set(selected):
        argument = PropertyValue()
        argument.Name = "Tables"
        argument.Value = cast(Any, uno).Any("[]long", tuple(names.index(name) for name in selected))
        dispatch = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.DispatchHelper", context
        )
        dispatch.executeDispatch(controller.getFrame(), ".uno:SelectTables", "", 0, (argument,))
    if controller.getActiveSheet().getName() != active or set(
        _selected_names(context, controller, names)
    ) != set(selected):
        raise RuntimeError("The active sheet or tab selection could not be restored")


def _verify(document: Any, target: tuple[str, ...], original: Snapshot) -> None:
    # A check here would consume the undo evidence explaining the modify notification at
    # unlockControllers, falsely invalidating picks after our own successful move.
    sheets, _ = _read_sheets(document)
    if tuple(sheet.name for sheet in sheets) != target:
        raise RuntimeError("The sheet order does not match the plan")
    expected_flags = {sheet.name: sheet.scenario for sheet in original.sheets}
    if any(sheet.scenario != expected_flags[sheet.name] for sheet in sheets):
        raise RuntimeError("Scenario sheet identities changed")
    # Also checks scenario adjacency/ownership against the original blocks.
    ordered_blocks(original.sheets, target)


def apply_order(context: Any, document: Any, observed: Snapshot, plan: Plan) -> Result:
    """Apply one plan, preserving this view's active sheet and native tab selection.

    The panel must stay busy until this returns; modify listeners must defer refresh.
    Scenario blocks require consecutive individual calls, so intermediate ordering
    inside the undo context is private to this operation. Never dispatch Calc's
    multi-sheet Move, copy/delete sheets, save, or clear/lock the user's undo stack.
    """
    permission = preflight(context, document, observed, plan)
    if not permission.allowed:
        return Result("refused", permission.reason, detail=permission.detail)
    # All callers get the own-move exception, including callers without a sheet-list view.
    # It covers unlock notifications too, and excludes pre-existing locks/quiet states.
    with observed.monitor.own_move() as clear:
        if not clear:
            return Result("refused", tr("The sheet list has changed. Refresh it and try again."))
        return _apply_order(context, document, observed, plan, permission)


def _apply_order(
    context: Any, document: Any, observed: Snapshot, plan: Plan, permission: Availability
) -> Result:
    controller = document.getCurrentController()
    undo = document.getUndoManager()
    title = tr("Move Sheets")
    attempted = False
    completed = 0
    entered = False
    left = False
    locked = False
    depth = 0
    try:
        active = str(controller.getActiveSheet().getName())
        selected = _selected_names(context, controller, tuple(s.name for s in observed.sheets))
        capacity = permission.undo_steps
    except Exception as error:
        return Result(
            "refused", tr("The current sheet selection could not be read."), detail=str(error)
        )

    def execute(moves: tuple[Move, ...]) -> None:
        nonlocal attempted, completed, depth
        if len(moves) > capacity:
            # Calc limits the current undo array to configured Steps during
            # native moves. A flat group silently loses early actions (#16):
            # https://github.com/viell-dev/slop-calc-sheet-manager/issues/16
            # Balanced subgroups keep every level within that limit (>= 2).
            middle = len(moves) // 2
            for portion in (moves[:middle], moves[middle:]):
                undo.enterUndoContext(title)
                depth += 1
                try:
                    execute(portion)
                finally:
                    undo.leaveUndoContext()
                    depth -= 1
            return
        for move in moves:
            if not controller.getFrame().isActive():
                raise RuntimeError("The document's window is no longer active")
            attempted = True
            document.getSheets().moveByName(move.name, move.index)
            completed += 1

    try:
        document.lockControllers()
        locked = True
        undo.enterUndoContext(title)
        entered = True
        depth += 1
        try:
            execute(plan.moves)
        finally:
            undo.leaveUndoContext()
            depth -= 1
            left = True
        _verify(document, plan.target, observed)
        if not undo.isUndoPossible() or undo.getCurrentUndoActionTitle() != title:
            raise RuntimeError("The move was not recorded as one undo action")
        # Restore both success and rollback views under lock to avoid an intermediate repaint.
        return _finish_view(
            context, controller, active, selected, Result("done", tr("Sheets moved."), completed)
        )
    except Exception as error:
        detail = str(error)
        try:
            if depth or (entered and not left):
                # Context closure failed: undo could consume unrelated history.
                raise RuntimeError("The move undo context could not be closed")
            changed = tuple(document.getSheets().getElementNames()) != tuple(
                sheet.name for sheet in observed.sheets
            )
            # A throwing API call may already have mutated the document. Conversely,
            # failure before the first mutation must never undo the user's last edit.
            # Entering an empty group can evict the oldest full-stack entry;
            # title changes alone therefore do not prove a mutation. A minimal
            # plan never returns to the original order after any of its moves.
            recorded = attempted and changed
            if recorded:
                if not controller.getFrame().isActive():
                    raise RuntimeError("Rollback needs the document's window active")
                if not undo.isUndoPossible() or undo.getCurrentUndoActionTitle() != title:
                    raise RuntimeError("The move undo action is unavailable")
                undo.undo()
            _verify(document, tuple(sheet.name for sheet in observed.sheets), observed)
            if recorded:
                # The mutation discarded prior redo history. The only redo entry
                # must now be our failed group; do not let Redo replay a partial
                # scenario block move after reporting successful recovery.
                if tuple(undo.getAllRedoActionTitles()) != (title,):
                    raise RuntimeError("Unexpected redo history after move recovery")
                undo.clearRedo()
            restored = Result(
                "failed-restored",
                tr("The move failed. The original order was restored."),
                completed,
                detail,
            )
        except Exception as rollback_error:
            return Result(
                "failed-not-restored",
                tr(
                    "The move failed and the original order could not be restored. "
                    "Check the document."
                ),
                completed,
                detail + "; " + str(rollback_error),
            )
        return _finish_view(context, controller, active, selected, restored)
    finally:
        if locked:
            document.unlockControllers()


def _finish_view(
    context: Any, controller: Any, active: str, selected: tuple[str, ...], result: Result
) -> Result:
    # The order has been verified. A view warning must never undo a correct move
    # or misreport a verified rollback as a document-order recovery failure.
    try:
        _restore_view(context, controller, active, selected)
        return result
    except Exception as error:
        return Result(
            result.status,
            result.message + " " + tr("The active sheet or tab selection could not be restored."),
            result.moves,
            "; ".join(part for part in (result.detail, str(error)) if part),
        )
