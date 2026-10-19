"""The sheet list: a flat TreeControl showing the document's sheets.

A single click on a row goes to that sheet and leaves it as Calc's only selected tab; Ctrl+click
and Shift+click only change the list's own selection. The selected sheets can be dragged to
another place in the list through the reorder layer (``uno_reorder``). The list's selection
follows Calc's whenever the active sheet changes, but the list groups Calc's tabs only to open
the sheet tab menu (see ``uno_menu``).

The list keeps the reorder layer's snapshot of the sheets it shows. A selected row survives a
refresh only while the sheet handle retained for it still has that row's name, so a sheet that
was deleted and recreated, or renamed and reused, drops out of the selection rather than passing
it to a different sheet. Drags, the menu, and Show check the same identity again when they run.

Every listener only records state or posts work to the main thread: LibreOffice calls some
of them from other threads or in the middle of a change.
"""

import contextlib
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, cast

import uno
import unohelper
from com.sun.star.awt import XFocusListener, XMouseListener, XPaintListener
from com.sun.star.datatransfer import DataFlavor, UnsupportedFlavorException, XTransferable
from com.sun.star.datatransfer.dnd import (
    XDragGestureListener,
    XDragSourceListener,
    XDropTargetListener,
)
from com.sun.star.sheet import XActivationEventListener
from com.sun.star.util import XModifyListener

from sheet_manager.i18n import tr
from sheet_manager.keys import (
    MOVING,
    PAGEDOWN,
    PAGEUP,
    TypeAhead,
    anchor_after,
    cursor_after,
    find_prefix,
    range_end,
)
from sheet_manager.reorder import plan_move
from sheet_manager.sheet_list import RowGeometry, SheetRow, ordered, row_label
from sheet_manager.uno_calc import (
    MainThread,
    dispatch,
    prop,
    read_rows,
    report,
    select_tabs,
    selected_tabs,
    show_error,
    swatch_url,
)
from sheet_manager.uno_keys import ListKeyHandler, Shortcuts
from sheet_manager.uno_menu import SHOW, SheetMenu
from sheet_manager.uno_reorder import Snapshot, apply_order, is_current, snapshot
from sheet_manager.uno_show import show_sheets

MULTI = uno.Enum("com.sun.star.view.SelectionType", "MULTI")
SINGLE = uno.Enum("com.sun.star.view.SelectionType", "SINGLE")
LEFT = cast(int, uno.getConstantByName("com.sun.star.awt.MouseButton.LEFT"))
RIGHT = cast(int, uno.getConstantByName("com.sun.star.awt.MouseButton.RIGHT"))
SHIFT = cast(int, uno.getConstantByName("com.sun.star.awt.KeyModifier.SHIFT"))
MOD1 = cast(int, uno.getConstantByName("com.sun.star.awt.KeyModifier.MOD1"))
POSSIZE = cast(int, uno.getConstantByName("com.sun.star.awt.PosSize.POSSIZE"))
ACTION_MOVE = cast(
    int, uno.getConstantByName("com.sun.star.datatransfer.dnd.DNDConstants.ACTION_MOVE")
)

# A private type: nothing outside this list accepts a sheet drag that leaves the panel.
MIME = "application/x-sheet-manager-sheets"
REFRESH_DELAY = 0.2  # Quiet time after a change before the list reads the sheets again.
REFRESH_COST_FACTOR = 4  # Wait at least this many times as long as the last refresh took.
REFRESH_MAX_WAIT = 2.0  # During continuous changes, refresh at least this often (scaled too).
SCROLL_INTERVAL = 0.1


def _guarded(where, function, *arguments):
    try:
        return function(*arguments)
    except Exception:
        report(where)
        return None


@dataclass(frozen=True)
class _Press:
    """A left button press on the list, kept until its release."""

    row: int | None
    modifiers: int
    name: str | None  # The sheet the pressed row showed,
    handle: Any  # and its handle at that moment: a refresh may put another sheet there.
    rebuilds: int  # How often the list had been rebuilt when the button went down.


@dataclass(frozen=True)
class _Drag:
    names: list[str]  # The dragged sheets, in document order.
    observed: Snapshot  # The sheets the list showed when the drag started.
    transferable: object


class _Transferable(unohelper.Base, XTransferable):
    def __init__(self, token: str):
        self.token = token
        self._flavor = DataFlavor(MIME, "Sheet Manager sheets", uno.getTypeByName("[]byte"))

    def getTransferData(self, flavor):
        if flavor.MimeType != MIME:
            raise UnsupportedFlavorException(flavor.MimeType, self)
        return uno.ByteSequence(self.token.encode("ascii"))

    def getTransferDataFlavors(self):
        return (self._flavor,)

    def isDataFlavorSupported(self, flavor):
        return flavor.MimeType == MIME


def _carries(transferable, drag: _Drag) -> bool:
    """Whether a dropped transferable is this list's current drag."""
    if transferable is drag.transferable:
        return True
    try:
        flavor = DataFlavor(MIME, "Sheet Manager sheets", uno.getTypeByName("[]byte"))
        data = transferable.getTransferData(flavor)
        token = getattr(drag.transferable, "token", None)
        return token is not None and bytes(data.value) == token.encode("ascii")
    except Exception:
        return False


class _Mouse(unohelper.Base, XMouseListener):
    def __init__(self, owner):
        self._owner = owner

    def mousePressed(self, event):
        _guarded("a mouse press", self._owner.mouse_pressed, event)

    def mouseReleased(self, event):
        _guarded("a mouse release", self._owner.mouse_released, event)

    def mouseEntered(self, event):
        pass

    def mouseExited(self, event):
        pass

    def disposing(self, event):
        pass


class _Focus(unohelper.Base, XFocusListener):
    def __init__(self, owner):
        self._owner = owner

    def focusGained(self, event):
        _guarded("gaining focus", self._owner.focus_changed, True)

    def focusLost(self, event):
        _guarded("losing focus", self._owner.focus_changed, False)

    def disposing(self, event):
        pass


class _Paint(unohelper.Base, XPaintListener):
    def __init__(self, owner):
        self._owner = owner

    def windowPaint(self, event):
        _guarded("drawing the insertion line", self._owner.draw_insertion_line)

    def disposing(self, event):
        pass


class _Gesture(unohelper.Base, XDragGestureListener):
    def __init__(self, owner):
        self._owner = owner

    def dragGestureRecognized(self, event):
        _guarded("starting a drag", self._owner.start_drag, event)

    def disposing(self, event):
        pass


class _Source(unohelper.Base, XDragSourceListener):
    def __init__(self, owner):
        self._owner = owner

    def dragEnter(self, event):
        pass

    def dragOver(self, event):
        pass

    def dragExit(self, event):
        pass

    def dropActionChanged(self, event):
        pass

    def dragDropEnd(self, event):
        # On Windows this arrives on the drag thread.
        self._owner.post(self._owner.end_drag, "ending a drag")

    def disposing(self, event):
        pass


class _Target(unohelper.Base, XDropTargetListener):
    def __init__(self, owner):
        self._owner = owner

    def dragEnter(self, event):
        flavors = event.SupportedDataFlavors
        _guarded(
            "a drag entering the list",
            self._owner.drag_over,
            event,
            any(flavor.MimeType == MIME for flavor in flavors),
        )

    def dragOver(self, event):
        _guarded("a drag over the list", self._owner.drag_over, event, True)

    def dragExit(self, event):
        _guarded("a drag leaving the list", self._owner.clear_drag_feedback)

    def dropActionChanged(self, event):
        _guarded("a drag action change", self._owner.drag_over, event, True)

    def drop(self, event):
        _guarded("a drop", self._owner.drop, event)

    def disposing(self, event):
        pass


class _Document(unohelper.Base, XModifyListener, XActivationEventListener):
    def __init__(self, owner):
        self._owner = owner

    def modified(self, event):
        _guarded("noticing a change", self._owner.document_modified)

    def activeSpreadsheetChanged(self, event):
        _guarded("noticing a sheet switch", self._owner.active_sheet_event)

    def disposing(self, event):
        pass


class SheetList:
    def __init__(self, context, frame, parent_window):
        self.context = context
        self.frame = frame
        self.controller = frame.getController()
        self.document = self.controller.getModel()
        self.toolkit = parent_window.getToolkit()
        self.rows: list[SheetRow] = []
        self._observed: Snapshot | None = None
        self._handles: dict[str, Any] = {}
        self._nodes: list[object] = []
        # The tree's keyboard cursor and Shift anchor, by sheet name: the tree has no API for them.
        self._cursor: str | None = None
        self._anchor: str | None = None
        self._disposed = False
        self._busy = False
        self._main = MainThread(context)
        self._menu = SheetMenu(
            context,
            frame,
            self.document,
            self.controller,
            lambda work: self.post(work, "releasing the menu guard"),
            lambda: self.post(self._command_refused, "refusing a stale command"),
        )
        self._keys = ListKeyHandler(self, Shortcuts(context, self.document))
        self._keys_registered = False
        self._refresh_timer: threading.Timer | None = None
        self._changed_at = 0.0  # The last document change.
        self._stale_since: float | None = None  # The first change not yet shown.
        self._refresh_cost = 0.0  # How long the last refresh took.
        self._refreshed_at = 0.0  # When it ended.
        # Counts the user's own input in the list, as the list's mouse and key handlers see
        # it. A request to follow Calc's selection remembers the count when Calc reported the
        # switch; newer input in the list wins over it.
        self._input = 0
        self._follow_input: int | None = None
        self._activating = False  # The list's own setActiveSheet call is running.
        self._press: _Press | None = None
        # Rebuilds so far, and the selection and cursor the last one established.
        self._rebuilds = 0
        self._rebuilt: tuple[list[str], str | None] = ([], None)
        self._drag: _Drag | None = None
        self._gap: int | None = None
        self._pointer_y = 0
        self._scroll = 0
        self._scroll_thread: threading.Thread | None = None
        self._scroll_pending = False
        self._type_ahead = TypeAhead()

        manager = context.ServiceManager
        model = manager.createInstanceWithContext("com.sun.star.awt.tree.TreeControlModel", context)
        model.SelectionType = MULTI
        model.RootDisplayed = False
        model.ShowsHandles = False
        model.ShowsRootHandles = False
        model.Editable = False
        model.HideInactiveSelection = False  # The list's selection stays visible in the sheet.
        model.Border = 0  # The sidebar draws the frame; this also makes the tree a direct child.
        self.tree = manager.createInstanceWithContext("com.sun.star.awt.tree.TreeControl", context)
        self.tree.setModel(model)
        self.tree.createPeer(self.toolkit, parent_window)
        self.peer = self.tree.getPeer()

        self._listeners = {
            "mouse": _Mouse(self),
            "focus": _Focus(self),
            "paint": _Paint(self),
            "gesture": _Gesture(self),
            "source": _Source(self),
            "target": _Target(self),
            "document": _Document(self),
        }
        self.tree.addMouseListener(self._listeners["mouse"])
        self.tree.addFocusListener(self._listeners["focus"])
        self.tree.addPaintListener(self._listeners["paint"])
        self._gestures = self.toolkit.getDragGestureRecognizer(self.peer)
        self._gestures.addDragGestureListener(self._listeners["gesture"])
        self._drag_source = self.toolkit.getDragSource(self.peer)
        self._drop_target = self.toolkit.getDropTarget(self.peer)
        self._drop_target.addDropTargetListener(self._listeners["target"])
        self._drop_target.setActive(True)
        self.document.addModifyListener(self._listeners["document"])
        self.controller.addActivationEventListener(self._listeners["document"])
        self.refresh()
        self.follow_calc_selection()

    # Life cycle and layout

    def post(self, function, where: str) -> None:
        if not self._disposed:
            self._main.post(function, where)

    def set_bounds(self, width: int, height: int) -> None:
        if not self._disposed:
            self.tree.setPosSize(0, 0, width, height, POSSIZE)

    def panel_hidden(self) -> None:
        self.focus_changed(False)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._main.closed = True
        self._scroll = 0
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
        self.focus_changed(False)
        for remove in (
            lambda: self.document.removeModifyListener(self._listeners["document"]),
            lambda: self.controller.removeActivationEventListener(self._listeners["document"]),
            lambda: self._drop_target.setActive(False),
            lambda: self._drop_target.removeDropTargetListener(self._listeners["target"]),
            lambda: self._gestures.removeDragGestureListener(self._listeners["gesture"]),
        ):
            with contextlib.suppress(Exception):  # The document or toolkit may be gone.
                remove()
        self.tree.dispose()

    # Rows and identity

    def names(self) -> list[str]:
        return [row.name for row in self.rows]

    def still_shown(self, name: str) -> bool:
        """Whether the sheet the list shows as `name` still exists under that name."""
        handle = self._handles.get(name)
        try:
            return handle is not None and handle.getName() == name
        except Exception:
            return False

    def refresh(self) -> None:
        """Read the sheets again; keep only selected rows whose sheets are still the same."""
        if self._disposed:
            return
        started = time.monotonic()
        try:
            self._refresh()
        finally:
            self._refreshed_at = time.monotonic()
            self._refresh_cost = self._refreshed_at - started
            self._stale_since = None

    def _refresh(self) -> None:
        observed = snapshot(self.document)
        rows = read_rows(self.controller, observed)
        names = {row.name for row in rows}
        picked = self.selected_names()
        kept = [name for name in picked if name in names and self.still_shown(name)]
        cursor = self._cursor
        if cursor is not None and (cursor not in names or not self.still_shown(cursor)):
            cursor = None
        anchor = self._anchor if self._anchor in names and self.still_shown(self._anchor) else None
        changed = rows != self.rows or not self._nodes
        invalidated = kept != picked or cursor != self._cursor or anchor != self._anchor
        self._observed = observed
        self._handles = dict(
            zip((sheet.name for sheet in observed.sheets), observed.handles, strict=True)
        )
        if changed or invalidated:
            self._rebuild(rows, kept, cursor)

    def _rebuild(self, rows: list[SheetRow], picked: list[str], cursor: str | None) -> None:
        """Replace the whole data model.

        With a hidden root, the tree control mishandles every change event of the data model:
        changing one node's text re-parents all rows under a newly shown root. So the list
        never changes nodes in place; it builds a new model and restores the selection, the
        scroll position, and the keyboard cursor. The tree's Shift anchor cannot be restored:
        the next Shift move starts a new range at the cursor.
        """
        top = self._first_visible_name()
        model = self.context.ServiceManager.createInstanceWithContext(
            "com.sun.star.awt.tree.MutableTreeDataModel", self.context
        )
        root = model.createNode("", False)
        model.setRoot(root)
        nodes: list[object] = []
        for row in rows:
            node = model.createNode(row_label(row), False)
            node.DataValue = row.name
            node.setNodeGraphicURL(swatch_url(self.context, row.color))
            root.appendChild(node)
            nodes.append(node)
        self.tree.getModel().DataModel = model
        self._nodes, self.rows = nodes, rows
        self._anchor = None
        names = self.names()
        if top in names and nodes:
            # Scroll to the end first, so that showing the old top row puts it at the top.
            self.tree.makeNodeVisible(nodes[-1])
            self.tree.makeNodeVisible(nodes[names.index(top)])
        self._select(picked, cursor)
        self._rebuilds += 1
        self._rebuilt = (list(picked), cursor)

    def _select(self, names: list[str], cursor: str | None = None) -> None:
        """Select these rows and put the keyboard cursor on `cursor`, or on the first of them."""
        wanted = set(names)
        indices = [index for index, row in enumerate(self.rows) if row.name in wanted]
        all_names = self.names()
        if cursor not in all_names:
            cursor = all_names[indices[0]] if indices else None
        if cursor is None:
            self.tree.clearSelection()
            self._cursor = None
            return
        self._focus_row(all_names.index(cursor), scroll=False)
        if cursor not in wanted:
            self.tree.clearSelection()  # Keeps the cursor where it is.
        for index in indices:
            if all_names[index] != cursor:
                self.tree.addSelection(self._nodes[index])

    def geometry(self) -> RowGeometry:
        if not self._nodes:
            return RowGeometry(0, 0, 0)
        rect = self.tree.getNodeRect(self._nodes[0])
        return RowGeometry(rect.Y, rect.Height, len(self._nodes))

    def _height(self) -> int:
        return self.peer.getOutputSize().Height

    def _first_visible_name(self) -> str | None:
        if not self._nodes:
            return None
        return self.rows[self.geometry().first_visible()].name

    # Selection, keyboard cursor, and activation

    def selected_names(self) -> list[str]:
        selection = self.tree.getSelection()
        if selection is None:
            return []
        nodes = selection if isinstance(selection, tuple) else (selection,)
        return ordered(self.names(), {node.DataValue for node in nodes})

    def _selected_indices(self) -> list[int]:
        picked = set(self.selected_names())
        return [index for index, row in enumerate(self.rows) if row.name in picked]

    def _focus_row(self, index: int, scroll: bool = True) -> None:
        """Select only this row and move the tree's keyboard cursor to it.

        The tree control has no cursor API, but in single selection mode selecting a row also
        moves the cursor, so arrow keys continue from the row selected here.
        """
        model = self.tree.getModel()
        model.SelectionType = SINGLE
        try:
            self.tree.select(self._nodes[index])
        finally:
            model.SelectionType = MULTI
        self._cursor = self.rows[index].name
        if scroll:
            self.tree.makeNodeVisible(self._nodes[index])

    def tree_key(self, code: int, modifiers: int) -> None:
        """Track the tree's cursor for a key that the tree is about to handle itself."""
        self._input += 1
        names = self.names()
        cursor = names.index(self._cursor) if self._cursor in names else None
        anchor = names.index(self._anchor) if self._anchor in names else None
        anchor = anchor_after(code, modifiers, cursor, anchor)
        self._anchor = names[anchor] if anchor is not None else None
        moved = cursor_after(code, cursor, len(names))
        if moved is not None:
            self._cursor = names[moved]
        elif code in (PAGEUP, PAGEDOWN):
            shift = bool(modifiers & SHIFT)
            self.post(lambda: self._cursor_from_selection(shift), "following the cursor")
        elif code in MOVING:
            self._cursor = None

    def _cursor_from_selection(self, shift: bool) -> None:
        """After Page Up or Page Down the selection shows where the cursor went."""
        selected = self._selected_indices()
        names = self.names()
        if not shift:
            self._cursor = names[selected[0]] if len(selected) == 1 else None
        elif self._anchor in names and names.index(self._anchor) in selected:
            self._cursor = names[range_end(selected, names.index(self._anchor))]
        else:
            self._cursor = None

    def follow_calc_selection(self) -> None:
        try:
            indices = selected_tabs(self.context, self.controller)
            active = self.controller.getActiveSheet().getName()
        except Exception:
            report("reading Calc's selected sheets")
            return
        names = self.names()
        self._select([names[index] for index in indices if 0 <= index < len(names)], active)

    def activate(self, name: str, handle: Any = None) -> None:
        """Go to the sheet and make it Calc's only selected tab, as a click on its tab does.

        `handle` is the sheet the user pointed at, by default the one the list shows as `name`.
        The sheet must still be that one, under that name, and visible at this moment: the
        list may not have been refreshed yet, and Calc would send the activation of a hidden
        sheet to another sheet (#43). Otherwise nothing changes except the list, which shows
        the sheets as they are. Calc keeps an existing group when the sheet is already part of
        it, which would make a cell edit change every grouped sheet, so the single selection
        is established and read back.
        """
        if handle is None:
            handle = self._handles.get(name)
        try:
            current = handle is not None and handle.getName() == name and bool(handle.IsVisible)
        except Exception:
            current = False
        if not current:
            self.post(self.refresh, "refreshing the sheet list")
            return
        controller = self.controller
        previous = controller.getActiveSheet()
        previous_name = previous.getName()
        previous_tabs = selected_tabs(self.context, controller)
        self._activating = True  # Calc reports the switch during the call.
        try:
            controller.setActiveSheet(handle)
        finally:
            self._activating = False
        if controller.getActiveSheet().getName() != name:
            # Calc went to another sheet after all: put the view back, and say whether it is.
            restored = self.restore_view(previous, previous_name, previous_tabs)
            self.post(self.refresh, "refreshing the sheet list")
            show_error(
                self.peer,
                tr("Sheet Manager"),
                tr("Calc could not go to this sheet. The view was left as it was.")
                if restored
                else tr(
                    "Calc could not go to this sheet, and the previous view could not be "
                    "restored. Check which sheets are active and selected before editing cells."
                ),
            )
            return
        index = list(self.document.getSheets().getElementNames()).index(name)
        if selected_tabs(self.context, controller) != [index]:
            dispatch(
                self.context, self.frame, ".uno:TableDeselectAll", (prop("SynchronMode", True),)
            )
        if (
            selected_tabs(self.context, controller) != [index]
            or controller.getActiveSheet().getName() != name
        ):
            show_error(
                self.peer,
                tr("Sheet Manager"),
                tr("Calc kept other sheets selected. Click the sheet's tab before editing cells."),
            )

    def restore_view(self, previous: Any, name: str, tabs: list[int]) -> bool:
        """Make `previous` active and `tabs` Calc's selection again; read back both (#46).

        Calc may send this activation elsewhere too, for example when the previous sheet was
        hidden meanwhile; then the view stays as Calc left it, and the caller says so.
        """
        controller = self.controller
        try:
            controller.setActiveSheet(previous)
            if selected_tabs(self.context, controller) != tabs:
                select_tabs(self.context, self.frame, tabs)
            return (
                controller.getActiveSheet().getName() == name
                and selected_tabs(self.context, controller) == tabs
            )
        except Exception:
            return False

    def activate_selection(self) -> None:
        picked = self.selected_names()
        if len(picked) == 1:
            self.activate(picked[0])

    def type_ahead(self, char: str) -> None:
        self._input += 1
        prefix = self._type_ahead.feed(char, time.monotonic())
        names = self.names()
        current = names.index(self._cursor) if self._cursor in names else None
        match = find_prefix(names, prefix, current)
        if match is not None:
            self._focus_row(match)

    # Events from Calc
    #
    # Reading the sheets and rebuilding the tree costs main-thread time that grows with the
    # number of sheets. Bulk changes, such as a macro or a 500-call move, send a change and
    # often an activation event for every step, so refreshes are rate-limited: one runs at once
    # when the list has been idle for several times its cost; otherwise the next waits until
    # changes pause, or at most a bounded time. Until then the rows may be out of date, so
    # every action checks the sheets it acts on when it runs.

    def _refresh_delay(self) -> float:
        return max(REFRESH_DELAY, REFRESH_COST_FACTOR * self._refresh_cost)

    def _rate_wait(self, now: float) -> float:
        """How long until another refresh may run without hogging the main thread."""
        return self._refreshed_at + REFRESH_COST_FACTOR * self._refresh_cost - now

    def _schedule(self, seconds: float) -> None:
        if self._refresh_timer is None and not self._disposed:
            self._refresh_timer = self._main.later(
                max(seconds, 0.05), self._timed_refresh, "refreshing the sheet list"
            )

    def _mark_stale(self, now: float) -> None:
        if self._stale_since is None:
            self._stale_since = now

    def document_modified(self) -> None:
        """Refresh once changes pause, or at the latest after a bounded wait."""
        if self._disposed:
            return
        now = time.monotonic()
        self._changed_at = now
        self._mark_stale(now)
        self._schedule(self._refresh_delay())

    def active_sheet_event(self) -> None:
        """Calc reports a sheet switch; the list handles it after the events already queued.

        Whether the list made the switch itself, and how much input the list had seen, are
        noted now, without calling back into Calc. The list's mouse handlers also run after
        the tree has handled the input, so a click's switch can be handled after a later click
        has reached the list; counting the input now keeps that click newer (#44).
        """
        seen = self._input
        own = self._activating
        self.post(lambda: self.active_sheet_changed(own, seen), "following a sheet switch")

    def active_sheet_changed(self, own: bool, seen: int) -> None:
        """Show the new active sheet, at once unless refreshes are being rate-limited.

        A switch the list made itself needs no following: the list already shows the sheet
        the user clicked or chose. Other switches make the list follow Calc's selection,
        unless the user has used the list since the switch (`seen`).
        """
        if self._disposed:
            return
        if not own:
            self._follow_input = seen
        now = time.monotonic()
        self._mark_stale(now)
        if self._refresh_timer is None and not self._busy and self._rate_wait(now) <= 0:
            self._run_refresh()
        else:
            self._schedule(self._rate_wait(now))

    def _timed_refresh(self) -> None:
        self._refresh_timer = None
        if self._disposed or self._stale_since is None:
            return
        now = time.monotonic()
        delay = self._refresh_delay()
        quiet = now - self._changed_at
        waited = now - self._stale_since
        settling = quiet < delay and waited < max(REFRESH_MAX_WAIT, delay * REFRESH_COST_FACTOR)
        if settling or self._rate_wait(now) > 0:
            self._schedule(max(delay - quiet if settling else 0.0, self._rate_wait(now)))
            return
        if not self._busy:  # A move refreshes the list itself when it ends.
            self._run_refresh()

    def _run_refresh(self) -> None:
        """Refresh, and follow Calc's tab selection if the user went to another sheet.

        Calc also reports activation when sheets move or the same sheet is selected again;
        then the list keeps its own selection. So does it when the user has changed the list's
        selection since the activation: a delayed refresh must not undo newer input (#44).
        """
        follow = self._follow_input is not None and self._follow_input == self._input
        self._follow_input = None
        before = next((row.name for row in self.rows if row.active), None)
        self.refresh()
        if follow and next((row.name for row in self.rows if row.active), None) != before:
            self.follow_calc_selection()

    # Keyboard

    def focus_changed(self, gained: bool) -> None:
        if gained and not self._keys_registered and not self._disposed:
            self.toolkit.addKeyHandler(self._keys)
            self._keys_registered = True
        elif not gained and self._keys_registered:
            self._keys_registered = False
            self.toolkit.removeKeyHandler(self._keys)

    def owns_keys(self) -> bool:
        """Whether the key being handled is for this list: its tree has the focus right now."""
        return not self._disposed and not self._menu.is_open and bool(self.peer.hasFocus())

    def run_command(self, command: str) -> None:
        self.post(lambda: dispatch(self.context, self.frame, command), "a shortcut")

    # Mouse and menu

    def mouse_pressed(self, event) -> None:
        self._input += 1
        if event.PopupTrigger:
            return
        row = self.geometry().row_at(event.Y)
        if event.Buttons & RIGHT:
            self._press = None
            if row is not None and self.rows[row].name not in self.selected_names():
                self._focus_row(row)
                self._anchor = None
        elif event.Buttons & LEFT:
            name = self.rows[row].name if row is not None else None
            handle = self._handles.get(name) if name is not None else None
            self._press = _Press(row, event.Modifiers, name, handle, self._rebuilds)
            if row is not None:
                # The tree has already handled the press: its cursor is on this row. Shift
                # keeps or starts the range at the old cursor; other clicks end it.
                if event.Modifiers & SHIFT:
                    self._anchor = self._anchor or self._cursor
                else:
                    self._anchor = None
                self._cursor = self.rows[row].name

    def mouse_released(self, event) -> None:
        if event.Buttons & RIGHT:
            # Open on release on every platform, so that the release cannot pick an item.
            x, y = event.X, event.Y
            self.post(lambda: self._open_menu(x, y), "the sheet tab menu")
            return
        press, self._press = self._press, None
        if not event.Buttons & LEFT or press is None or press.name is None:
            return
        if not self._pressed_sheet_in_place(press):
            # A refresh during the press moved the pressed sheet away or showed another sheet
            # under its name. The gesture then has no effect at all (#28): no activation, and
            # whatever the tree selected on release now sits in that row and was never
            # picked, so the selection the refresh established comes back.
            if press.rebuilds != self._rebuilds:
                self._select(*self._rebuilt)
            return
        row = press.row
        if row is None or press.modifiers & (SHIFT | MOD1):
            return
        if self.geometry().row_at(event.Y) != row:
            return
        self.activate(press.name, press.handle)

    def _pressed_sheet_in_place(self, press: _Press) -> bool:
        """Whether the pressed row still shows the pressed sheet, under the same name."""
        if press.row is None or press.row >= len(self.rows):
            return False
        if self.rows[press.row].name != press.name:
            return False
        try:
            return press.handle is not None and press.handle.getName() == press.name
        except Exception:
            return False

    def open_menu_for_keyboard(self) -> None:
        picked = self.selected_names()
        if not picked:
            return
        index = self.names().index(picked[0])
        self.tree.makeNodeVisible(self._nodes[index])
        geometry = self.geometry()
        self._open_menu(geometry.row_height, geometry.gap_y(index) + geometry.row_height // 2)

    def _open_menu(self, x: int, y: int) -> None:
        picked = self.selected_names()
        if self._disposed or self._busy or not picked or self._observed is None:
            return
        if not all(self.still_shown(name) for name in picked):
            self.refresh()  # A picked sheet was replaced or renamed: drop it, open nothing.
            return
        observed = self._observed
        chosen = self._menu.show(self.peer, x, y, observed, picked)
        if chosen == SHOW:
            result = show_sheets(self.context, self.document, observed, picked)
            self.refresh()
            if result.status != "done":
                show_error(self.peer, tr("Sheet Manager"), result.message)

    def _command_refused(self) -> None:
        self.refresh()
        show_error(
            self.peer,
            tr("Sheet Manager"),
            tr("The sheets changed while the menu was open. The command was not run."),
        )

    # Drag and drop

    def start_drag(self, event) -> None:
        self._press = None  # A drag is not a click.
        if self._busy or self._drag is not None or self._observed is None:
            return
        picked = self.selected_names()
        if not picked or self.document.isReadonly() or self.document.isProtected():
            return
        if not is_current(self.document, self._observed):
            self.refresh()
            return
        transferable = _Transferable(uuid.uuid4().hex)
        self._drag = _Drag(picked, self._observed, transferable)
        try:
            self._drag_source.startDrag(
                event, ACTION_MOVE, 0, 0, transferable, self._listeners["source"]
            )
        except Exception:
            self._drag = None
            raise

    def drag_over(self, event, ours: bool) -> None:
        if self._drag is None or not ours:
            event.Context.rejectDrag()
            return
        event.Context.acceptDrag(ACTION_MOVE)
        self._pointer_y = event.LocationY
        geometry = self.geometry()
        gap = geometry.gap_at(event.LocationY)
        if gap != self._gap:
            self._gap = gap
            self.peer.invalidate(0)
        edge = max(8, geometry.row_height)
        height = self._height()
        if event.LocationY < edge:
            self._set_scroll(-1)
        elif event.LocationY > height - edge:
            self._set_scroll(1)
        else:
            self._set_scroll(0)

    def drop(self, event) -> None:
        drag = self._drag
        if drag is None or not _carries(event.Transferable, drag):
            event.Context.rejectDrop()
            self.clear_drag_feedback()
            return
        event.Context.acceptDrop(ACTION_MOVE)
        gap = self.geometry().gap_at(event.LocationY)
        # Complete the drop first: on Windows the drag source waits on another thread.
        event.Context.dropComplete(True)
        self.clear_drag_feedback()
        self.post(lambda: self._move(drag, gap), "moving sheets")

    def end_drag(self) -> None:
        self._drag = None
        self.clear_drag_feedback()

    def clear_drag_feedback(self) -> None:
        self._scroll = 0
        if self._gap is not None:
            self._gap = None
            if not self._disposed:
                self.peer.invalidate(0)

    def draw_insertion_line(self) -> None:
        if self._gap is None or self._disposed:
            return
        y = self.geometry().gap_y(self._gap)
        width = self.peer.getOutputSize().Width
        color = self.peer.StyleSettings.HighlightColor
        graphics = self.peer.createGraphics()
        # The colours would otherwise stay set on the tree's device and outline its rows.
        graphics.push()
        try:
            graphics.setLineColor(color)
            graphics.setFillColor(color)
            graphics.drawRect(0, y - 1, width, 2)
        finally:
            graphics.pop()

    def _set_scroll(self, direction: int) -> None:
        self._scroll = direction
        if direction and (self._scroll_thread is None or not self._scroll_thread.is_alive()):
            self._scroll_thread = threading.Thread(
                target=self._scroll_loop, name="sheet-manager-autoscroll", daemon=True
            )
            self._scroll_thread.start()

    def _scroll_loop(self) -> None:
        # dragOver stops while the pointer rests, so a timer keeps scrolling at the edges.
        while self._scroll and self._drag is not None and not self._disposed:
            time.sleep(SCROLL_INTERVAL)
            if not self._scroll_pending:
                self._scroll_pending = True
                self.post(self._scroll_step, "auto-scroll")

    def _scroll_step(self) -> None:
        self._scroll_pending = False
        if not self._scroll or self._drag is None or not self._nodes:
            return
        geometry = self.geometry()
        first = geometry.first_visible()
        target = first - 1 if self._scroll < 0 else first + geometry.visible_rows(self._height())
        if 0 <= target < len(self._nodes):
            self.tree.makeNodeVisible(self._nodes[target])
            self._gap = self.geometry().gap_at(self._pointer_y)
            self.peer.invalidate(0)

    def _move(self, drag: _Drag, gap: int) -> None:
        """Move the dragged sheets through the reorder layer (docs/reordering.md).

        The plan uses the snapshot the list showed when the drag started; the layer refuses it
        if any sheet has changed since, and keeps the active sheet and Calc's tab selection.
        """
        if self._disposed:
            return
        try:
            plan = plan_move(drag.observed.sheets, drag.names, "drop", gap)
        except ValueError as error:
            show_error(self.peer, tr("Sheet Manager"), str(error))
            return
        if not plan.moves:
            return  # Dropped in place.
        self._busy = True
        try:
            if not self.frame.isActive():
                self.frame.activate()  # Calc's undo of sheet moves needs the active view.
            result = apply_order(self.context, self.document, drag.observed, plan)
        finally:
            self._busy = False
            self.refresh()
        if result.status != "done" or result.message != tr("Sheets moved."):
            # Refusals, failures, and a successful move whose view could not be restored.
            show_error(self.peer, tr("Sheet Manager"), result.message)
