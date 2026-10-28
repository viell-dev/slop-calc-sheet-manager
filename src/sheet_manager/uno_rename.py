"""Rename several sheets as one undo step, with the reorder layer's safety rules. UI thread only.

The list's Rename Sheets dialog plans its calls with `rename.plan_renames`; this adapter checks
and applies them. Like `uno_show.show_sheets`, it verifies the targets' identity and the
document's permissions and undo state again immediately before acting, groups its calls in one
undo context, verifies the result, and on failure undoes only its own group and verifies that.

- Calls go to the snapshot's retained handles, never by name, and never through a Calc command
  that acts on the viewed sheet. Every call is read back: Calc refuses a name silently, so a
  call returning normally proves nothing (#102).
- The result is verified as a whole: the complete order of names, every target handle's name,
  and that every final name looks up its own sheet. Calc accepts some names that its own lookup
  confuses with another sheet's (#113); snapshots read handles by name, so such a pair must never
  be created.
- Measured with 26.2.1.2 and 26.8.1.1: a flat undo context keeps every rename, whatever the undo
  steps setting (unlike moves, #16), so no nesting is needed. With 0 steps, entering a context does
  nothing and leaving it fails, so 0 steps are refused like undo that is off or locked.
- Calc's undo of a rename renames by sheet index and does not need a current view
  (`ScUndoRenameTab::DoChange`, checked in the 26.2.1.2 and 26.8.1.1 sources), so this adapter,
  unlike Show and moves, does not require the document's window to be active.
- Protected sheets are refused although the API renames them, because Calc's own Rename refuses
  them. Hidden sheets are allowed: nothing is viewed. Recording changes is allowed, as in Calc.
- A failure before any call changed a name never undoes anything: an empty context leaves no
  undo step, and the user's previous action stays on top. After a verified recovery, the failed
  group's redo entry is removed, so Redo cannot replay a partial batch.
"""

from typing import Any

from sheet_manager.i18n import tr
from sheet_manager.rename import Plan, plan_renames, quoted
from sheet_manager.uno_reorder import Result, Snapshot, is_current, undo_steps

TITLE = "Rename Sheets"


def _handles(observed: Snapshot) -> dict[str, Any]:
    return {
        sheet.name: handle for sheet, handle in zip(observed.sheets, observed.handles, strict=True)
    }


def _stale() -> str:
    return tr("The sheet list has changed. Refresh it and try again.")


def rename_refusal(context: Any, document: Any, observed: Snapshot, targets: list[str]) -> str:
    """Why these sheets cannot be renamed together now, or an empty string."""
    if len(set(targets)) < 2:
        return tr("Choose two or more sheets to rename them together.")
    return _refusal(context, document, observed, targets)


def _refusal(context: Any, document: Any, observed: Snapshot, targets: list[str]) -> str:
    # Permissions first, for the most useful reason: undo that is off or locked also makes the
    # snapshot unprovable. Every check is a read, and all of them must pass.
    try:
        handles = _handles(observed)
        if not set(targets) <= handles.keys():
            return _stale()
        if document.isReadonly():
            return tr("This document is read-only.")
        if document.isProtected():
            return tr("The document's sheet structure is protected.")
        undo = document.getUndoManager()
        if not document.getPropertyValue("IsUndoEnabled") or undo.isLocked():
            return tr("Enable undo before renaming sheets.")
        if undo_steps(context) <= 0:
            return tr("Enable undo before renaming sheets.")
        if undo.getAllUndoActionTitles() and not undo.isUndoPossible():
            return tr("Finish the current undo action before renaming sheets.")
        if not is_current(document, observed):
            return _stale()
        if any(handles[name].isProtected() for name in targets):
            return tr("Protected sheets cannot be renamed.")
        return ""
    except Exception:
        return tr("Sheet Manager could not verify that this is safe.")


def preflight(context: Any, document: Any, observed: Snapshot, plan: Plan) -> str:
    """Why this plan must not be applied now, or an empty string. Repeated by `apply_renames`.

    The plan must be the one `plan_renames` makes for the snapshot's names, so that its calls
    are tied to the whole namespace the user saw, not just to the renamed sheets.
    """
    names = tuple(sheet.name for sheet in observed.sheets)
    if plan.before != names:
        return _stale()
    try:
        if plan_renames(names, plan.renames) != plan:
            return tr("The rename plan is invalid. Refresh it and try again.")
    except ValueError as error:
        return str(error)
    if not plan.steps:
        return tr("No name has changed.")
    return _refusal(context, document, observed, [old for old, _ in plan.renames])


def _names(document: Any) -> tuple[str, ...]:
    return tuple(document.getSheets().getElementNames())


def _verify(document: Any, handles: dict[str, Any], expected: dict[str, str]) -> None:
    """The document has exactly the expected names, each on its own sheet, in the same order.

    `expected` maps each sheet's name before the batch to the name it must have now, in order.
    """
    if _names(document) != tuple(expected.values()):
        raise RuntimeError("The sheet names do not match the plan")
    for sheet, name in expected.items():
        if handles[sheet].getName() != name:
            raise RuntimeError("A sheet does not have its planned name")
    sheets = document.getSheets()
    for name in expected.values():
        if sheets.getByName(name).getName() != name:
            raise RuntimeError("A sheet name looks up another sheet")


def apply_renames(context: Any, document: Any, observed: Snapshot, plan: Plan) -> Result:
    """Give the planned sheets their new names as one undo step, or change nothing.

    `observed` is the snapshot whose handles the user chose; `moves` in the result counts the
    calls that completed.
    """
    reason = preflight(context, document, observed, plan)
    if reason:
        return Result("refused", reason)
    handles = _handles(observed)
    undo = document.getUndoManager()
    title = tr(TITLE)
    before = {name: name for name in plan.before}
    after = dict(zip(plan.before, plan.after, strict=True))
    attempted = entered = left = False
    completed = 0
    refused = None
    try:
        undo.enterUndoContext(title)
        entered = True
        try:
            for step in plan.steps:
                attempted = True
                handles[step.sheet].setName(step.new)
                if handles[step.sheet].getName() != step.new:
                    refused = step.new
                    raise RuntimeError("Calc refused a sheet name")
                completed += 1
        finally:
            undo.leaveUndoContext()
            left = True
        _verify(document, handles, after)
        if not undo.isUndoPossible() or undo.getCurrentUndoActionTitle() != title:
            raise RuntimeError("Renaming the sheets was not recorded as one undo action")
        return Result("done", tr("Sheets renamed."), completed)
    except Exception as error:
        detail = str(error)
        try:
            if entered and not left:
                raise RuntimeError("The undo context could not be closed") from None
            # Undo only a change this call made; never the user's previous action. Entering a
            # context at a full undo stack can drop its oldest step, so the titles prove nothing.
            recorded = attempted and any(
                handles[name].getName() != name for name in plan.before if name in handles
            )
            if recorded:
                if not undo.isUndoPossible() or undo.getCurrentUndoActionTitle() != title:
                    raise RuntimeError("The undo action for renaming the sheets is unavailable")
                undo.undo()
            _verify(document, handles, before)
            if recorded:
                if tuple(undo.getAllRedoActionTitles()) != (title,):
                    raise RuntimeError("Unexpected redo history after recovery")
                undo.clearRedo()
        except Exception as recovery_error:
            return Result(
                "failed-not-restored",
                tr("Renaming the sheets failed and could not be undone. Check the sheet names."),
                completed,
                detail + "; " + str(recovery_error),
            )
        if refused is not None:
            message = tr("Calc did not accept the name {name}. No sheet was renamed.").format(
                name=quoted(refused)
            )
        else:
            message = tr("Renaming the sheets failed. No sheet was renamed.")
        return Result("failed-restored", message, completed, detail)
