"""The sheet tab menu for the sheets selected in the list.

Calc's own sheet tab menu acts on Calc's selected tabs. Before it opens, the list selects
exactly its own picked sheets as Calc's tabs and reads the selection back; only if Calc holds
exactly those sheets does the built-in menu, with the user's customizations, open. While it is
open, a dispatch interceptor on the panel's frame wraps every command it dispatches: at the moment
a command runs, the picked sheets must still be the same sheets and still be Calc's whole tab
selection, or the command is not run. Calc cannot select only hidden sheets, so then, or if Calc
does not take the selection, a short menu offers what the extension can do safely itself.
"""

import time
from collections.abc import Callable

import unohelper
from com.sun.star.awt import Rectangle
from com.sun.star.frame import XDispatch, XDispatchProviderInterceptor

from sheet_manager.i18n import tr
from sheet_manager.uno_calc import prop, select_tabs, selected_tabs
from sheet_manager.uno_reorder import Snapshot
from sheet_manager.uno_show import hidden_targets, show_refusal

REPEAT_GUARD_SECONDS = 0.3  # gtk3 can deliver one menu request twice in a row.
SHOW = 1


class _GuardedDispatch(unohelper.Base, XDispatch):
    """Runs a command only if the menu's targets are still exactly Calc's selected sheets."""

    def __init__(self, real, verify: Callable[[], bool], refused: Callable[[], None]):
        self._real = real
        self._verify = verify
        self._refused = refused

    def dispatch(self, URL, Arguments):
        if self._verify():
            self._real.dispatch(URL, Arguments)
        else:
            self._refused()

    def addStatusListener(self, Control, URL):
        self._real.addStatusListener(Control, URL)

    def removeStatusListener(self, Control, URL):
        self._real.removeStatusListener(Control, URL)


class _MenuGuard(unohelper.Base, XDispatchProviderInterceptor):
    """Registered on the frame only while the built-in menu is open."""

    def __init__(self, verify: Callable[[], bool], refused: Callable[[], None]):
        self._verify = verify
        self._refused = refused
        self._slave = None
        self._master = None

    def queryDispatch(self, URL, TargetFrameName, SearchFlags):
        real = None
        if self._slave is not None:
            real = self._slave.queryDispatch(URL, TargetFrameName, SearchFlags)
        # The wrapper keeps checking even after the menu has closed: the menu dispatches its
        # command from a user event posted after it returns.
        return None if real is None else _GuardedDispatch(real, self._verify, self._refused)

    def queryDispatches(self, Requests):
        return tuple(
            self.queryDispatch(request.FeatureURL, request.FrameName, request.SearchFlags)
            for request in Requests
        )

    def getSlaveDispatchProvider(self):
        return self._slave

    def setSlaveDispatchProvider(self, NewDispatchProvider):
        self._slave = NewDispatchProvider

    def getMasterDispatchProvider(self):
        return self._master

    def setMasterDispatchProvider(self, NewSupplier):
        self._master = NewSupplier


class SheetMenu:
    def __init__(self, context, frame, document, controller, post, report_refusal):
        self._context = context
        self._frame = frame
        self._document = document
        self._controller = controller
        self._post = post  # Runs work later on the main thread.
        self._report_refusal = report_refusal
        self.is_open = False
        self._closed_at = 0.0

    def _tabs(self) -> list[str]:
        order = list(self._document.getSheets().getElementNames())
        return [order[index] for index in selected_tabs(self._context, self._controller)]

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

    def show(
        self,
        peer,
        x: int,
        y: int,
        observed: Snapshot,
        picked: list[str],
        unchanged: Callable[[], bool] = lambda: True,
    ) -> int | None:
        """Show the menu for the picked sheets; returns the chosen safe action, if any.

        The caller has checked that the picked sheets are still the ones `observed` holds;
        `unchanged` says whether that still holds as far as the caller can tell (no sheet was
        inserted or deleted since), and is checked again when a command runs.
        """
        if self.is_open or time.monotonic() - self._closed_at < REPEAT_GUARD_SECONDS:
            return None
        self.is_open = True
        try:
            hidden = set(hidden_targets(observed, picked))
            if set(picked) - hidden and self.group_calc_tabs(picked):
                self._native(peer, x, y, observed, picked, unchanged)
                return None
            return self._safe(peer, x, y, observed, picked)
        finally:
            self.is_open = False
            self._closed_at = time.monotonic()

    def _popup(self):
        manager = self._context.ServiceManager
        return manager.createInstanceWithContext("com.sun.star.awt.PopupMenu", self._context)

    def _native(self, peer, x, y, observed, picked, unchanged):
        handles = dict(
            zip((sheet.name for sheet in observed.sheets), observed.handles, strict=True)
        )

        def verify() -> bool:
            try:
                same = unchanged() and all(handles[name].getName() == name for name in picked)
                return same and sorted(self._tabs()) == sorted(picked)
            except Exception:
                return False

        guard = _MenuGuard(verify, self._report_refusal)
        self._frame.registerDispatchProviderInterceptor(guard)
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
            # The chosen command was posted while the menu closed; release the interceptor
            # after it, so that no other window's dispatches go through it.
            self._post(lambda: self._frame.releaseDispatchProviderInterceptor(guard))

    def _safe(self, peer, x, y, observed, picked):
        targets = hidden_targets(observed, picked)
        popup = self._popup()
        popup.insertItem(SHOW, tr("Show Sheet") if len(targets) <= 1 else tr("Show Sheets"), 0, 0)
        reason = show_refusal(self._context, self._document, observed, targets)
        if not targets:
            # Calc did not take exactly these sheets, and none of them is hidden.
            reason = tr("Calc could not select exactly these sheets.")
        if reason:
            popup.enableItem(SHOW, False)
            popup.setTipHelpText(SHOW, reason)
        chosen = popup.execute(peer, Rectangle(x, y, 1, 1), 0)
        return chosen if chosen == SHOW and not reason else None
