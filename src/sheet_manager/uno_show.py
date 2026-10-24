"""Show hidden sheets as one undo step, with the reorder layer's safety rules.

This is the one document change the list's own short menu makes, for selections that Calc's tab
menu cannot represent (only hidden sheets). Like ``uno_reorder.apply_order`` it checks first
that the sheets are still the ones the list showed and that the change can be undone, groups the
change, verifies it, and on failure undoes its own group only and verifies the result. Call it
synchronously on the UI thread.
"""

from typing import Any

from sheet_manager.i18n import tr
from sheet_manager.uno_reorder import Result, Snapshot, is_current, undo_steps


def _title(count: int) -> str:
    return tr("Show Sheet") if count == 1 else tr("Show Sheets")


def _handles(observed: Snapshot) -> dict[str, Any]:
    return {
        sheet.name: handle for sheet, handle in zip(observed.sheets, observed.handles, strict=True)
    }


def hidden_targets(observed: Snapshot, names: list[str]) -> list[str]:
    """The picked sheets that are hidden now, in document order."""
    handles = _handles(observed)
    picked = set(names)
    return [
        sheet.name
        for sheet in observed.sheets
        if sheet.name in picked and not handles[sheet.name].IsVisible
    ]


def show_refusal(context: Any, document: Any, observed: Snapshot, targets: list[str]) -> str:
    """Why these hidden sheets cannot be shown now, or an empty string."""
    try:
        if not targets:
            return tr("None of these sheets is hidden.")
        if not is_current(document, observed) or not set(targets) <= _handles(observed).keys():
            return tr("The sheet list has changed. Refresh it and try again.")
        if document.isReadonly():
            return tr("This document is read-only.")
        if document.isProtected():
            return tr("The document's sheet structure is protected.")
        if document.getPropertyValue("RecordChanges"):
            return tr("Sheets cannot be shown while changes are being recorded.")
        undo = document.getUndoManager()
        capacity = undo_steps(context)
        if not document.getPropertyValue("IsUndoEnabled") or undo.isLocked() or capacity <= 0:
            return tr("Enable undo before showing sheets.")
        if len(targets) > capacity:
            # Calc trims a group to the undo limit and would lose the first changes (#16).
            return tr(
                "Increase undo history to at least {count} steps to show these sheets."
            ).format(count=len(targets))
        if undo.getAllUndoActionTitles() and not undo.isUndoPossible():
            return tr("Finish the current undo action before showing sheets.")
        controller = document.getCurrentController()
        if controller is None or not controller.getFrame().isActive():
            return tr("Activate this document's window before showing sheets.")
        return ""
    except Exception:
        return tr("Sheet Manager could not verify that this is safe.")


def show_sheets(context: Any, document: Any, observed: Snapshot, names: list[str]) -> Result:
    """Make the picked hidden sheets visible as one undo step, or change nothing."""
    try:
        targets = hidden_targets(observed, names)
    except Exception as error:
        return Result(
            "refused", tr("The sheet list has changed. Refresh it and try again."), 0, str(error)
        )
    reason = show_refusal(context, document, observed, targets)
    if reason:
        return Result("refused", reason)
    handles = _handles(observed)
    undo = document.getUndoManager()
    title = _title(len(targets))
    attempted = entered = left = False
    shown = 0

    def visible() -> list[str]:
        return [name for name in targets if handles[name].IsVisible]

    try:
        undo.enterUndoContext(title)
        entered = True
        try:
            for name in targets:
                attempted = True
                handles[name].IsVisible = True
                shown += 1
        finally:
            undo.leaveUndoContext()
            left = True
        if visible() != targets:
            raise RuntimeError("A sheet is still hidden")
        if not undo.isUndoPossible() or undo.getCurrentUndoActionTitle() != title:
            raise RuntimeError("Showing the sheets was not recorded as one undo action")
        return Result("done", tr("Sheets shown."), shown)
    except Exception as error:
        detail = str(error)
        try:
            if entered and not left:
                raise RuntimeError("The undo context could not be closed") from None
            # Undo only a change this call made; never the user's previous action.
            recorded = attempted and bool(visible())
            if recorded:
                if not document.getCurrentController().getFrame().isActive():
                    raise RuntimeError("Recovery needs the document's window active")
                if not undo.isUndoPossible() or undo.getCurrentUndoActionTitle() != title:
                    raise RuntimeError("The undo action for showing the sheets is unavailable")
                undo.undo()
            if visible():
                raise RuntimeError("A sheet is still visible after recovery")
            if recorded:
                if tuple(undo.getAllRedoActionTitles()) != (title,):
                    raise RuntimeError("Unexpected redo history after recovery")
                undo.clearRedo()
            return Result(
                "failed-restored",
                tr("Showing the sheets failed. They are hidden again."),
                shown,
                detail,
            )
        except Exception as recovery_error:
            return Result(
                "failed-not-restored",
                tr("Showing the sheets failed and could not be undone. Check the document."),
                shown,
                detail + "; " + str(recovery_error),
            )
