"""The sheet tab menu for the sheets selected in the list.

The outer movement menu leaves Calc's tabs unchanged. Choosing Sheet actions… groups its
visible targets and opens Calc's customized tab menu only after exact readback. Hidden or
mixed-visibility targets use safe extension actions instead. While the native menu is open,
a dispatch interceptor checks sheet identity and exact tab membership before every command.
"""

import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import cast

import unohelper
from com.sun.star.awt import Rectangle
from com.sun.star.frame import XDispatch, XDispatchProviderInterceptor
from com.sun.star.lang import DisposedException

from sheet_manager.i18n import tr
from sheet_manager.reorder import Action, plan_move
from sheet_manager.selection import Ref
from sheet_manager.uno_calc import MainThread, prop, select_tabs, selected_tabs
from sheet_manager.uno_reorder import Snapshot, move_availability, plan_availability
from sheet_manager.uno_show import hidden_targets, show_refusal

REPEAT_GUARD_SECONDS = 0.3  # gtk3 can deliver one menu request twice in a row.
SHOW = 1
ACTIONS = ("top", "up", "down", "bottom")
MOVE_IDS = {20001 + index: action for index, action in enumerate(ACTIONS)}
HELP = 20006
NATIVE = 20000
SELECT_COMMANDS = {".uno:TableSelectAll", ".uno:TableDeselectAll"}


@dataclass(frozen=True)
class MenuView:
    """The native view before temporary context targeting, as retained sheet identities."""

    active: Ref
    tabs: tuple[Ref, ...]
    visible: frozenset[str]


class _GuardedDispatch(unohelper.Base, XDispatch):
    """Runs a command only if the menu's targets are still exactly Calc's selected sheets."""

    def __init__(self, real, verify, refused, begin, end):
        self._real = real
        self._verify = verify
        self._refused = refused
        self._begin = begin
        self._end = end

    def dispatch(self, URL, Arguments):
        if self._verify():
            self._begin(URL.Complete)
            try:
                self._real.dispatch(URL, Arguments)
            finally:
                self._end()
        else:
            self._refused()

    def addStatusListener(self, Control, URL):
        self._real.addStatusListener(Control, URL)

    def removeStatusListener(self, Control, URL):
        self._real.removeStatusListener(Control, URL)


class _MenuGuard(unohelper.Base, XDispatchProviderInterceptor):
    """Registered on the frame only while the built-in menu is open."""

    def __init__(self, verify, refused, begin, end):
        self._verify = verify
        self._refused = refused
        self._begin = begin
        self._end = end
        self._slave = None
        self._master = None

    def queryDispatch(self, URL, TargetFrameName, SearchFlags):
        real = None
        if self._slave is not None:
            real = self._slave.queryDispatch(URL, TargetFrameName, SearchFlags)
        # The wrapper keeps checking even after the menu has closed: the menu dispatches its
        # command from a user event posted after it returns.
        return (
            None
            if real is None
            else _GuardedDispatch(real, self._verify, self._refused, self._begin, self._end)
        )

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
        self.command: str | None = None
        self._targeted_native = False
        self.view: MenuView | None = None
        self._dispatch_depth = 0
        self._completion: Callable[[], None] | None = None

    def defer_completion(self, work: Callable[[], None]) -> bool:
        """A native modal dialog can run queued callbacks before its command finishes."""
        if not self._dispatch_depth:
            return False
        self._completion = work
        return True

    def _begin_command(self, command: str) -> None:
        if self.command is None:
            self.command = command
        self._dispatch_depth += 1

    def _end_command(self) -> None:
        self._dispatch_depth -= 1
        if self._dispatch_depth == 0 and self._completion is not None:
            work, self._completion = self._completion, None
            self._post(work)

    def capture_view(self, observed: Snapshot) -> MenuView | None:
        names = [sheet.name for sheet in observed.sheets]
        active = self._controller.getActiveSheet().getName()
        tabs = selected_tabs(self._context, self._controller)
        if active not in names or any(index < 0 or index >= len(names) for index in tabs):
            return None
        refs = tuple(Ref(names[i], observed.handles[i], i) for i in tabs)
        visible = frozenset(ref.name for ref in refs if ref.token.IsVisible)
        return MenuView(
            Ref(active, observed.handles[names.index(active)], names.index(active)), refs, visible
        )

    def restore_view(self, view: MenuView, unchanged: Callable[[], bool]) -> None:
        """Restore only provable sheets with unchanged visibility; explicit selection wins."""
        if not self._targeted_native or self.command in SELECT_COMMANDS or not unchanged():
            return
        refs = (view.active, *view.tabs)
        if any(ref.token.getName() != ref.name for ref in refs):
            return
        if not view.active.token.IsVisible:
            return
        if frozenset(ref.name for ref in view.tabs if ref.token.IsVisible) != view.visible:
            return
        names = list(self._document.getSheets().getElementNames())
        if any(ref.name not in names for ref in refs):
            return
        if self._controller.getActiveSheet().getName() != view.active.name:
            self._controller.setActiveSheet(view.active.token)
        indices = sorted(names.index(ref.name) for ref in view.tabs)
        select_tabs(self._context, self._frame, indices)
        if (
            self._controller.getActiveSheet().getName() != view.active.name
            or selected_tabs(self._context, self._controller) != indices
        ):
            raise RuntimeError(tr("Calc could not restore the view after the sheet menu."))

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
        if self.is_open:
            return None
        # A refused reopen must not reuse the previous popup's transition state.
        self._targeted_native = False
        self.view = None
        self.command = None
        if time.monotonic() - self._closed_at < REPEAT_GUARD_SECONDS:
            return None
        self.is_open = True
        try:
            hidden = set(hidden_targets(observed, picked))
            if set(picked) - hidden:
                menu = self._popup()
                self._add_actions(menu, observed, picked)
                menu.insertSeparator(len(ACTIONS))
                menu.insertItem(NATIVE, tr("Sheet actions…"), 0, len(ACTIONS) + 1)
                chosen = menu.execute(peer, Rectangle(x, y, 1, 1), 0)
                if chosen != NATIVE:
                    return chosen if chosen in MOVE_IDS or chosen == HELP else None
                if not unchanged():
                    self._report_refusal()
                    return None
                if hidden_targets(observed, picked):
                    # Calc can report hidden indices as selected too. Do not mistake
                    # that for a visible tab context; keep mixed targets on safe actions.
                    return self._safe(peer, x, y, observed, picked)
                self.view = self.capture_view(observed)
                if self.view is None or not unchanged():
                    self._report_refusal()
                    return None
                self._targeted_native = True
                if self.group_calc_tabs(picked):
                    return self._native(peer, x, y, observed, picked, unchanged)
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

        guard = _MenuGuard(verify, self._report_refusal, self._begin_command, self._end_command)
        self._frame.registerDispatchProviderInterceptor(guard)
        controller = None
        executing = False
        try:
            popup = self._popup()
            controller = self._context.ServiceManager.createInstanceWithArgumentsAndContext(
                "com.sun.star.comp.framework.ResourceMenuController",
                (
                    prop("Value", "sheettab"),
                    prop("Frame", self._frame),
                    prop("IsContextMenu", True),
                ),
                self._context,
            )
            controller.setPopupMenu(popup)
            executing = True
            popup.execute(peer, Rectangle(x, y, 1, 1), 0)
            return None
        finally:
            try:
                if controller is not None:
                    controller.dispose()
            finally:

                def release():
                    # A closed frame no longer has dispatches to protect.
                    with suppress(DisposedException):
                        self._frame.releaseDispatchProviderInterceptor(guard)

                if executing:
                    # The native command is posted while its menu closes; release after it.
                    # Panel disposal closes the list's queue even inside this nested loop.
                    # Guard cleanup belongs to the surviving frame, not to the list lifetime.
                    try:
                        MainThread(self._context).post(release, "releasing the sheet menu guard")
                    except BaseException:
                        release()
                        raise
                else:
                    release()

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
        self._add_actions(popup, observed, picked)
        chosen = popup.execute(peer, Rectangle(x, y, 1, 1), 0)
        return (
            chosen
            if chosen in MOVE_IDS or chosen == HELP or chosen == SHOW and not reason
            else None
        )

    def _add_actions(self, popup, observed, picked):
        popup.hideDisabledEntries(False)
        labels = (
            tr("⤒  Move to top (Alt+Home)"),
            tr("↑  Move up (Alt+Up)"),
            tr("↓  Move down (Alt+Down)"),
            tr("⤓  Move to bottom (Alt+End)"),
        )
        permission = move_availability(self._context, self._document)
        for (item, action), label in zip(MOVE_IDS.items(), labels, strict=True):
            popup.insertItem(item, label, 0, popup.getItemCount())
            try:
                state = plan_availability(
                    permission, plan_move(observed.sheets, picked, cast(Action, action))
                )
            except ValueError as error:
                popup.enableItem(item, False)
                popup.setTipHelpText(item, str(error))
            else:
                popup.enableItem(item, state.allowed)
                popup.setTipHelpText(item, state.reason)
        popup.insertItem(HELP, tr("Sheet Manager Help"), 0, popup.getItemCount())
