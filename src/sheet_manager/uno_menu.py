"""The sheet tab menu for the sheets selected in the list.

The menu offers a few of Calc's sheet commands directly (Insert, Delete, Rename and Hide), the
list's own Show, Rename Sheets and moves, and Help. Opening or dismissing it leaves Calc's view
and tabs unchanged. A chosen built-in command is checked again when it runs, whatever the menu
showed: its targets' identity and permissions; then Calc's selected tabs are set to exactly those
targets, and Calc's own state for the command is read. Grouping and that query can run other code,
so every check is repeated after them, with only reads before the dispatch. Calc stays on its
targets afterwards: its dialogs can outlive the dispatch and act on the viewed sheet when
confirmed (#100). A refusal after grouping restores the previous view.

This module owns context targeting, native tab grouping and restoration, and move enablement.

- A right click retains a transient row ref without changing the picks. The menu opens only for
  refs checked just before, with a fresh snapshot. Show takes Hide's place for hidden targets, and
  the list's Rename Sheets (`uno_rename`) takes Rename's place for two or more targets: Calc's
  Rename acts on the one viewed sheet.
- GTK can activate cascading menus while preparing them, so never group from a menu callback;
  only `SheetMenu.run` groups.
- `command_refusal` applies Calc's state rules to the targets, because Calc's command state
  describes its current tabs. Insert's "after" uses the last selected tab.
- Duplicate Sheet and Move or Copy Sheet stay off the menu: the supported 26.8.0 and 26.8.1 copy
  formulas wrongly (tdf#173608, fixed in 26.8.2; #33), and the list moves sheets itself (#3).
- `run` repeats every check in the list's posted completion: the generation, the targets'
  identity, and `command_refusal`. It sets and reads back exactly the targets, queries the
  dispatcher, and reads Calc's command state for that group. Grouping runs Calc's activation
  listeners and the query runs the frame's interceptors, either of which can move, rename, hide or
  protect a sheet, so after both it repeats the generation, `command_refusal`, and an exact tab
  readback (a single target viewed). It then dispatches through the dispatcher already found,
  without arguments, as Calc's menu does; only reads run in between.
- A refusal after grouping, including a failed grouping or a UNO error before the dispatch,
  restores the saved view against fresh indices, retained identities, proof, and the original
  visibility, never by raw indices. An error raised by the dispatch itself is different: Calc may
  already have opened the command's dialog or acted, so the view stays on the targets and the
  message says the outcome is uncertain; restoring could send a Rename or Insert dialog to another
  sheet (#100). `DisposedException` propagates: the view is gone.
- A dispatched command keeps Calc on its targets, because Calc's asynchronous dialogs outlive the
  dispatch, and Insert and Rename act on the sheet viewed at confirmation (#100). The document's
  `OnModeChanged` reports dialog lifetime for VCL and gtk3 dialogs, but native Qt dialogs never
  report it, so no restoration may wait for it or for a delay. Synchronous dialogs, such as
  Delete's confirmation, run inside the list's completion, which refreshes after the dispatch
  returns.
- Panel disposal can close the list's queue inside the popup's nested loop (#63): the completion
  is then dropped, and nothing else outlives the popup.
- A move captures the observed snapshot, refs and proof before it is posted, and uses the common
  permission and plan checks and the full `apply_order` preflight.
- The sidebar's native panel header generates its own help ID, for a topic that does not exist
  (#81). The menu's Help links to the guide instead, without intercepting global help or changing
  the installed help system.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from com.sun.star.awt import Rectangle
from com.sun.star.lang import DisposedException

from sheet_manager.i18n import tr
from sheet_manager.reorder import Action, plan_move
from sheet_manager.selection import Ref
from sheet_manager.uno_calc import (
    command_label,
    command_state,
    query_command,
    report,
    select_tabs,
    selected_tabs,
)
from sheet_manager.uno_rename import rename_refusal
from sheet_manager.uno_reorder import Snapshot, move_availability, plan_availability
from sheet_manager.uno_show import hidden_targets, show_refusal

REPEAT_GUARD_SECONDS = 0.3  # gtk3 can deliver one menu request twice in a row.
SHOW = 1
INSERT, DELETE, RENAME, HIDE = 2, 3, 4, 5
RENAME_SHEETS = 6  # The list's own Rename Sheets, in Rename's place for two or more targets.
# Calc's commands offered directly. Duplicate Sheet and Move or Copy Sheet are left to Calc's tab
# bar: they copy formulas wrongly in 26.8.0 and 26.8.1 (tdf#173608, fixed in 26.8.2; #33), and
# the list moves sheets itself (#3).
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
        """Select exactly the picked sheets as Calc's tabs and confirm Calc did so.

        The caller restores the previous view otherwise, through retained sheet identities:
        selecting runs Calc's activation listeners, which can move sheets, so the indices of
        the earlier selection may no longer name its sheets.
        """
        order = list(self._document.getSheets().getElementNames())
        if not picked or not set(picked) <= set(order):
            return False
        indices = sorted(order.index(name) for name in picked)
        select_tabs(self._context, self._frame, indices)
        order = list(self._document.getSheets().getElementNames())
        return set(picked) <= set(order) and selected_tabs(self._context, self._controller) == (
            sorted(order.index(name) for name in picked)
        )

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
        # Grouping activates a target, and querying the command runs the frame's interceptors:
        # either can run other code, which can move, rename, hide or protect a sheet. So after
        # both, every check is made again, and only reads run between them and the dispatch.
        dispatcher = url = None
        try:
            if not self.group_calc_tabs(picked):
                reason = tr("Calc could not select exactly these sheets.")
            else:
                url, dispatcher = query_command(self._context, self._frame, COMMANDS[item])
                if dispatcher is None or not command_state(dispatcher, url):
                    reason = tr("Calc does not allow this command for these sheets now.")
                else:
                    reason = self._dispatch_refusal(item, observed, picked, unchanged)
        except DisposedException:
            raise  # The window closed; there is no view left to restore.
        except Exception:
            # Nothing was dispatched yet, so restoring the earlier view is safe.
            report("checking a sheet command before running it")
            reason = tr("Sheet Manager could not verify that this is safe.")
        if not reason and dispatcher is not None:
            try:
                dispatcher.dispatch(url, ())
            except DisposedException:
                raise
            except Exception:
                # Calc may already have opened the command's dialog or acted. Restoring the
                # earlier view could send that dialog to another sheet (#100): stay on the
                # targets and say that the outcome is uncertain.
                report("running a sheet command")
                return tr(
                    "Calc reported an error while running the command, which may have started. "
                    "Calc stays on the targeted sheets; check them before editing."
                )
            return ""
        try:
            self.restore_view(view, unchanged)
        except DisposedException:
            raise
        except Exception:
            report("restoring the view after a refused command")
            reason += " " + tr(
                "Calc's previous viewed sheet and selected tabs could not be restored. "
                "Check them before editing."
            )
        return reason

    def _dispatch_refusal(self, item: int, observed: Snapshot, picked: list[str], unchanged) -> str:
        """Why the grouped command must not be dispatched now, or an empty string."""
        if not unchanged():
            return _stale()
        reason = command_refusal(self._document, observed, item, picked)
        if reason:
            return reason
        order = list(self._document.getSheets().getElementNames())
        indices = sorted(order.index(name) for name in picked)
        if selected_tabs(self._context, self._controller) != indices:
            return tr("Calc could not select exactly these sheets.")
        # Insert and Rename act on the viewed sheet when their dialogs are confirmed.
        if len(picked) == 1 and self._controller.getActiveSheet().getName() != picked[0]:
            return tr("Calc could not select exactly these sheets.")
        return ""

    def _popup(self):
        manager = self._context.ServiceManager
        return manager.createInstanceWithContext("com.sun.star.awt.PopupMenu", self._context)

    def _add_commands(self, popup, observed, picked) -> set[int]:
        """Add Calc's commands, Show in place of Hide for hidden targets, and Rename Sheets in
        place of Rename for two or more targets."""
        popup.hideDisabledEntries(False)
        hidden = hidden_targets(observed, picked)
        labels = _labels()
        enabled: set[int] = set()
        rename = RENAME_SHEETS if len(set(picked)) > 1 else RENAME
        for item in (INSERT, DELETE, rename, SHOW if hidden else HIDE):
            if item == SHOW:
                label = tr("Show Sheet") if len(hidden) == 1 else tr("Show Sheets")
                reason = show_refusal(self._context, self._document, observed, hidden)
            elif item == RENAME_SHEETS:
                label = tr("Rename Sheets...")
                reason = rename_refusal(self._context, self._document, observed, picked)
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
