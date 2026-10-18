"""Guarded UNO adapter for the pure reorder planner. Call synchronously on the UI thread."""

from dataclasses import dataclass
from typing import Any, Literal, cast

import uno
from com.sun.star.beans import PropertyValue

from sheet_manager.i18n import tr
from sheet_manager.reorder import Move, Plan, Sheet, ordered_blocks, plan_order


@dataclass(frozen=True)
class Snapshot:
    sheets: tuple[Sheet, ...]
    document_id: str
    # Deleted handles can alias index zero; same-name recreation there is undetectable.
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
    collection = document.getSheets()
    names = tuple(collection.getElementNames())
    handles = tuple(collection.getByName(name) for name in names)
    return Snapshot(
        tuple(
            Sheet(name, bool(handle.getIsScenario()))
            for name, handle in zip(names, handles, strict=True)
        ),
        str(document.RuntimeUID),
        handles,
    )


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
        if str(document.RuntimeUID) != observed.document_id or plan.before != observed.sheets:
            return Availability(False, tr("The sheet list has changed. Refresh it and try again."))
        fresh = snapshot(document)
        if fresh.sheets != observed.sheets or any(
            handle.getName() != sheet.name
            for handle, sheet in zip(observed.handles, observed.sheets, strict=True)
        ):
            return Availability(False, tr("The sheet list has changed. Refresh it and try again."))
        # Recompute: callers cannot smuggle stale indices or a split scenario block in a Plan.
        if plan_order(observed.sheets, plan.target) != plan:
            return Availability(False, tr("The move plan is invalid. Refresh it and try again."))
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
        if capacity == 1 and len(plan.moves) > 1:
            return Availability(
                False, tr("Increase undo history to at least two steps before moving these sheets.")
            )
        # An open context is listed in the stack, but cannot be undone until
        # closed. An empty top-level stack instead has no titles at all.
        if undo.getAllUndoActionTitles() and not undo.isUndoPossible():
            return Availability(False, tr("Finish the current undo action before moving sheets."))
        controller = document.getCurrentController()
        if controller is None or not controller.getFrame().isActive():
            return Availability(False, tr("Activate this document's window before moving sheets."))
        if not plan.moves:
            return Availability(False, tr("The sheets are already in that position."))
        return Availability(True, undo_steps=capacity)
    except Exception as error:
        return Availability(
            False, tr("Sheet Manager could not verify that this move is safe."), str(error)
        )


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
    fresh = snapshot(document)
    if tuple(sheet.name for sheet in fresh.sheets) != target:
        raise RuntimeError("The sheet order does not match the plan")
    expected_flags = {sheet.name: sheet.scenario for sheet in original.sheets}
    if any(sheet.scenario != expected_flags[sheet.name] for sheet in fresh.sheets):
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
    return _finish_view(
        context, controller, active, selected, Result("done", tr("Sheets moved."), completed)
    )


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
