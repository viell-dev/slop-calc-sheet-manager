"""The sheet tab menu for the sheets selected in the list.

Calc's own sheet tab menu acts on Calc's selected tabs. Before it opens, the list selects
exactly its own picked sheets as Calc's tabs and reads the selection back; only if Calc holds
exactly those sheets does the built-in menu, with the user's customizations, open. Calc cannot
select only hidden sheets, so then, or if the check fails, a short menu offers what the
extension can do safely itself.
"""

import time

from com.sun.star.awt import Rectangle

from sheet_manager.i18n import tr
from sheet_manager.uno_calc import prop, select_tabs, selected_tabs

REPEAT_GUARD_SECONDS = 0.3  # gtk3 can deliver one menu request twice in a row.
SHOW = 1


def show_refusal(document) -> str:
    if document.isReadonly():
        return tr("The document is read-only.")
    if document.isProtected():
        return tr("The workbook structure is protected.")
    return ""


class SheetMenu:
    def __init__(self, context, frame, document, controller):
        self._context = context
        self._frame = frame
        self._document = document
        self._controller = controller
        self.is_open = False
        self._closed_at = 0.0

    def group_calc_tabs(self, picked: list[str]) -> bool:
        """Select exactly the picked sheets as Calc's tabs and confirm Calc did so."""
        order = list(self._document.getSheets().getElementNames())
        if not picked or not set(picked) <= set(order):
            return False
        indices = sorted(order.index(name) for name in picked)
        active = self._controller.getActiveSheet().getName()
        before = selected_tabs(self._context, self._controller)
        select_tabs(self._context, self._frame, indices)
        if selected_tabs(self._context, self._controller) == indices:
            return True
        # Calc did not take exactly these sheets: leave its selection as the user had it.
        if self._controller.getActiveSheet().getName() != active:
            self._controller.setActiveSheet(self._document.getSheets().getByName(active))
        if selected_tabs(self._context, self._controller) != before:
            select_tabs(self._context, self._frame, before)
        return False

    def show(self, peer, x: int, y: int, picked: list[str], hidden: set[str]) -> int | None:
        """Show the menu for the picked sheets; returns the chosen safe action, if any."""
        if self.is_open or time.monotonic() - self._closed_at < REPEAT_GUARD_SECONDS:
            return None
        self.is_open = True
        try:
            if set(picked) - hidden and self.group_calc_tabs(picked):
                self._native(peer, x, y)
                return None
            return self._safe(peer, x, y, picked, bool(set(picked) & hidden))
        finally:
            self.is_open = False
            self._closed_at = time.monotonic()

    def _popup(self):
        manager = self._context.ServiceManager
        return manager.createInstanceWithContext("com.sun.star.awt.PopupMenu", self._context)

    def _native(self, peer, x, y):
        popup = self._popup()
        # The arguments SfxDispatcher passes for the tab bar; the controller fills and runs it.
        controller = self._context.ServiceManager.createInstanceWithArgumentsAndContext(
            "com.sun.star.comp.framework.ResourceMenuController",
            (prop("Value", "sheettab"), prop("Frame", self._frame), prop("IsContextMenu", True)),
            self._context,
        )
        try:
            controller.setPopupMenu(popup)
            popup.execute(peer, Rectangle(x, y, 1, 1), 0)
        finally:
            controller.dispose()

    def _safe(self, peer, x, y, picked, any_hidden):
        popup = self._popup()
        popup.insertItem(SHOW, tr("Show Sheet") if len(picked) == 1 else tr("Show Sheets"), 0, 0)
        reason = show_refusal(self._document)
        if not any_hidden:
            # Calc did not select exactly these sheets, and none of them is hidden.
            reason = tr("Calc could not select exactly these sheets.")
        if reason:
            popup.enableItem(SHOW, False)
            popup.setTipHelpText(SHOW, reason)
        chosen = popup.execute(peer, Rectangle(x, y, 1, 1), 0)
        return chosen if chosen == SHOW and not reason else None


def show_sheets(document, names: list[str]) -> bool:
    """Make the named sheets visible as one undo step; False if any of them is gone."""
    sheets = document.getSheets()
    if show_refusal(document) or not all(sheets.hasByName(name) for name in names):
        return False
    hidden = [sheets.getByName(name) for name in names]
    hidden = [sheet for sheet in hidden if not sheet.IsVisible]
    if not hidden:
        return True
    undo = document.getUndoManager()
    undo.enterUndoContext(tr("Show Sheet") if len(hidden) == 1 else tr("Show Sheets"))
    try:
        for sheet in hidden:
            sheet.IsVisible = True
    finally:
        undo.leaveUndoContext()
    return True
