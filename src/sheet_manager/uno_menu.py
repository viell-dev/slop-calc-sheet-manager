"""The sheet tab menu for the sheets selected in the list.

The menu offers a few of Calc's sheet commands directly (Insert, Delete, Rename and Hide), the
list's own Show and moves, and Help. Opening or dismissing it leaves Calc's view and tabs
unchanged. A chosen built-in command is checked again when it runs, whatever the menu showed:
its targets' identity and permissions; then Calc's selected tabs are set to exactly those targets
and read back, and Calc's own state for the command is read. Only then is the command dispatched,
and Calc stays on its targets afterwards: its dialogs can outlive the dispatch and act on the
viewed sheet when confirmed (#100). A refusal after grouping restores the previous view.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from com.sun.star.awt import Rectangle

from sheet_manager.i18n import tr
from sheet_manager.reorder import Action, plan_move
from sheet_manager.selection import Ref
from sheet_manager.uno_calc import (
    command_enabled,
    command_label,
    dispatch,
    report,
    select_tabs,
    selected_tabs,
)
from sheet_manager.uno_reorder import Snapshot, move_availability, plan_availability
from sheet_manager.uno_show import hidden_targets, show_refusal

REPEAT_GUARD_SECONDS = 0.3  # gtk3 can deliver one menu request twice in a row.
SHOW = 1
INSERT, DELETE, RENAME, HIDE = 2, 3, 4, 5
# Calc's commands offered directly. Duplicate Sheet and Move or Copy Sheet are left to Calc's tab
# bar: they copy formulas wrongly in 26.8.0 and 26.8.1 (tdf#173608, #33), and the list moves
# sheets itself (#3).
COMMANDS = {
    INSERT: ".uno:Insert",
    DELETE: ".uno:Remove",
    RENAME: ".uno:RenameTable",
    HIDE: ".uno:Hide",
}
ACTIONS = ("top", "up", "down", "bottom")
MOVE_IDS = {20001 + index: action for index, action in enumerate(ACTIONS)}
HELP = 20006


def _stale() -> str:
    return tr("The sheets changed while the menu was open. The command was not run.")


def _labels() -> dict[int, str]:
    return {
        INSERT: tr("Insert Sheet..."),
        DELETE: tr("Delete Sheet..."),
        RENAME: tr("Rename Sheet..."),
        HIDE: tr("Hide Sheet"),
    }


def command_refusal(document, observed: Snapshot, item: int, picked: list[str]) -> str:
    """Why Calc's command cannot run on exactly these sheets now, or an empty string.

    Calc's own command state describes its current tabs, not these targets, so this applies its
    state rules (`ScTabViewShell::GetStateTable`) to the targets. It also refuses where Calc's
    command would act on other sheets than these: Insert and Rename anchor on one viewed sheet,
    Calc cannot view a hidden sheet (#43), and Delete skips protected sheets.
    """
    try:
        names = (sheet.name for sheet in observed.sheets)
        handles = dict(zip(names, observed.handles, strict=True))
        targets = set(picked)
        if not targets or not targets <= handles.keys():
            return _stale()
        if any(handles[name].getName() != name for name in targets):
            return _stale()
        if item == INSERT and len(targets) != 1:
            return tr("Choose one sheet to insert a sheet next to it.")
        if item == RENAME and len(targets) != 1:
            return tr("Choose one sheet to rename it.")
        if any(not handles[name].IsVisible for name in targets):
            return tr("Show the hidden sheets first.")
        if document.isReadonly():
            return tr("This document is read-only.")
        if document.isProtected():
            return tr("The document's sheet structure is protected.")
        if item == RENAME and handles[picked[0]].isProtected():
            return tr("This sheet is protected.")
        if item == DELETE:
            if document.getPropertyValue("RecordChanges"):
                return tr("Sheets cannot be deleted while changes are being recorded.")
            if any(handles[name].isProtected() for name in targets):
                return tr("Protected sheets cannot be deleted.")
        if item in (DELETE, HIDE) and not any(
            handle.IsVisible for name, handle in handles.items() if name not in targets
        ):
            return tr("At least one other sheet must stay visible.")
        return ""
    except Exception:
        return tr("Sheet Manager could not verify that this is safe.")


@dataclass(frozen=True)
class MenuView:
    """The native view before a command's targeting, as retained sheet identities."""

    active: Ref
    tabs: tuple[Ref, ...]
    visible: frozenset[str]


class SheetMenu:
    def __init__(self, context, frame, document, controller):
        self._context = context
        self._frame = frame
        self._document = document
        self._controller = controller
        self.is_open = False
        self._closed_at = 0.0

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
        """Restore the view from before a refused command, to provable sheets only."""
        if not unchanged():
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

    def show(self, peer, x: int, y: int, observed: Snapshot, picked: list[str]) -> int | None:
        """Show the menu for the picked sheets; returns the chosen enabled entry, if any.

        The caller has checked that the picked sheets are still the ones `observed` holds. The
        menu changes nothing itself; a chosen built-in command runs through `run`.
        """
        if self.is_open or time.monotonic() - self._closed_at < REPEAT_GUARD_SECONDS:
            return None
        self.is_open = True
        try:
            popup, enabled = self.build(observed, picked)
            chosen = popup.execute(peer, Rectangle(x, y, 1, 1), 0)
            return chosen if chosen in enabled else None
        finally:
            self.is_open = False
            self._closed_at = time.monotonic()

    def build(self, observed: Snapshot, picked: list[str]):
        """The popup for these targets, and its enabled entries."""
        popup = self._popup()
        enabled = self._add_commands(popup, observed, picked)
        popup.insertSeparator(popup.getItemCount())
        enabled |= self._add_actions(popup, observed, picked)
        popup.insertSeparator(popup.getItemCount())
        popup.insertItem(HELP, tr("Sheet Manager Help"), 0, popup.getItemCount())
        return popup, enabled | {HELP}

    def run(self, item: int, observed: Snapshot, picked: list[str], unchanged) -> str:
        """Run Calc's command on exactly the picked sheets; returns why it did not run, or ''.

        `unchanged` says whether the picked sheets are still the ones `observed` holds, as far
        as the caller can tell (no sheet was inserted or deleted since). Call on the UI thread.
        """
        if not unchanged():
            return _stale()
        reason = command_refusal(self._document, observed, item, picked)
        if reason:
            return reason
        view = self.capture_view(observed)
        if view is None:
            return _stale()
        if not self.group_calc_tabs(picked):
            return tr("Calc could not select exactly these sheets.")
        # Insert and Rename act on the viewed sheet when their dialogs are confirmed.
        if len(picked) == 1 and self._controller.getActiveSheet().getName() != picked[0]:
            reason = tr("Calc could not select exactly these sheets.")
        elif not unchanged():
            reason = _stale()
        elif not command_enabled(self._context, self._frame, COMMANDS[item]):
            reason = tr("Calc does not allow this command for these sheets now.")
        elif dispatch(self._context, self._frame, COMMANDS[item]):
            return ""
        else:
            reason = tr("Calc does not allow this command for these sheets now.")
        try:
            self.restore_view(view, unchanged)
        except RuntimeError:
            report("restoring the view after a refused command")
            reason += " " + tr(
                "Calc's previous viewed sheet and selected tabs could not be restored. "
                "Check them before editing."
            )
        return reason

    def _popup(self):
        manager = self._context.ServiceManager
        return manager.createInstanceWithContext("com.sun.star.awt.PopupMenu", self._context)

    def _add_commands(self, popup, observed, picked) -> set[int]:
        """Add Calc's commands, and Show in place of Hide for hidden targets."""
        popup.hideDisabledEntries(False)
        hidden = hidden_targets(observed, picked)
        labels = _labels()
        enabled: set[int] = set()
        for item in (INSERT, DELETE, RENAME, SHOW if hidden else HIDE):
            if item == SHOW:
                label = tr("Show Sheet") if len(hidden) == 1 else tr("Show Sheets")
                reason = show_refusal(self._context, self._document, observed, hidden)
            else:
                label = command_label(self._context, COMMANDS[item], labels[item])
                reason = command_refusal(self._document, observed, item, picked)
            popup.insertItem(item, label, 0, popup.getItemCount())
            popup.enableItem(item, not reason)
            popup.setTipHelpText(item, reason)
            if not reason:
                enabled.add(item)
        return enabled

    def _add_actions(self, popup, observed, picked) -> set[int]:
        popup.hideDisabledEntries(False)
        labels = (
            tr("⤒  Move to top (Alt+Home)"),
            tr("↑  Move up (Alt+Up)"),
            tr("↓  Move down (Alt+Down)"),
            tr("⤓  Move to bottom (Alt+End)"),
        )
        permission = move_availability(self._context, self._document)
        enabled: set[int] = set()
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
                if state.allowed:
                    enabled.add(item)
        return enabled
