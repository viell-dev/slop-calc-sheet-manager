"""The sheet list: a flat TreeControl showing the document's sheets.

A single click on a row goes to that sheet; Ctrl+click and Shift+click only change the list's
own selection. The selected sheets can be dragged to another place in the list. The list's
selection follows Calc's whenever the active sheet changes, but the list groups Calc's tabs
only to open the sheet tab menu (see ``uno_menu``).

Every listener only records state or posts work to the main thread: LibreOffice calls some
of them from other threads or in the middle of a change.
"""

import threading
import time
import uuid
from dataclasses import dataclass

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
from sheet_manager.keys import TypeAhead, find_prefix
from sheet_manager.sheet_list import RowGeometry, SheetRow, ordered, row_label
from sheet_manager.temporary_move import move_block, refusal
from sheet_manager.uno_calc import (
    MainThread,
    dispatch,
    read_rows,
    report,
    select_tabs,
    selected_tabs,
    show_error,
    swatch_url,
)
from sheet_manager.uno_keys import ListKeyHandler, Shortcuts
from sheet_manager.uno_menu import SHOW, SheetMenu, show_sheets

MULTI = uno.Enum("com.sun.star.view.SelectionType", "MULTI")
SINGLE = uno.Enum("com.sun.star.view.SelectionType", "SINGLE")
LEFT = uno.getConstantByName("com.sun.star.awt.MouseButton.LEFT")
RIGHT = uno.getConstantByName("com.sun.star.awt.MouseButton.RIGHT")
SHIFT = uno.getConstantByName("com.sun.star.awt.KeyModifier.SHIFT")
MOD1 = uno.getConstantByName("com.sun.star.awt.KeyModifier.MOD1")
POSSIZE = uno.getConstantByName("com.sun.star.awt.PosSize.POSSIZE")
ACTION_MOVE = uno.getConstantByName("com.sun.star.datatransfer.dnd.DNDConstants.ACTION_MOVE")

# A private type: nothing outside this list accepts a sheet drag that leaves the panel.
MIME = "application/x-sheet-manager-sheets"
REFRESH_DELAY = 0.2
SCROLL_INTERVAL = 0.1


def _guarded(where, function, *arguments):
    try:
        return function(*arguments)
    except Exception:
        report(where)
        return None


@dataclass(frozen=True)
class _Drag:
    names: list[str]  # The dragged sheets, in document order.
    order: list[str]  # The document's order when the drag started.
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
        self._owner.post(self._owner.active_sheet_changed, "following the active sheet")

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
        self._nodes: list[object] = []
        self._disposed = False
        self._busy = False
        self._main = MainThread(context)
        self._menu = SheetMenu(context, frame, self.document, self.controller)
        self._keys = ListKeyHandler(self, Shortcuts(context, self.document))
        self._keys_registered = False
        self._refresh_timer: threading.Timer | None = None
        self._press: tuple[int | None, int] | None = None
        self._drag: _Drag | None = None
        self._gap: int | None = None
        self._pointer_y = 0
        self._scroll = 0
        self._scroll_thread: threading.Thread | None = None
        self._scroll_pending = False
        self._type_ahead = TypeAhead()

        manager = context.ServiceManager
        model = manager.createInstanceWithContext(
            "com.sun.star.awt.tree.TreeControlModel", context
        )
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
            try:
                remove()
            except Exception:
                pass  # The document or toolkit may already be gone.
        self.tree.dispose()

    # Rows

    def names(self) -> list[str]:
        return [row.name for row in self.rows]

    def refresh(self) -> None:
        if self._disposed:
            return
        rows = read_rows(self.document, self.controller)
        if rows != self.rows or not self._nodes:
            self._rebuild(rows)

    def _rebuild(self, rows: list[SheetRow]) -> None:
        """Replace the whole data model.

        With a hidden root, the tree control mishandles every change event of the data model:
        changing one node's text re-parents all rows under a newly shown root. So the list
        never changes nodes in place; it builds a new model and restores selection and scroll.
        """
        picked = self.selected_names()
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
        names = self.names()
        if top in names and nodes:
            # Scroll to the end first, so that showing the old top row puts it at the top.
            self.tree.makeNodeVisible(nodes[-1])
            self.tree.makeNodeVisible(nodes[names.index(top)])
        self._select(picked)

    def _select(self, names: list[str]) -> None:
        """Select these rows; the keyboard cursor goes to the first, so arrows continue there."""
        wanted = set(names)
        indices = [index for index, row in enumerate(self.rows) if row.name in wanted]
        if not indices:
            self.tree.clearSelection()
            return
        self._focus_row(indices[0], scroll=False)
        for index in indices[1:]:
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

    # Selection and activation

    def selected_names(self) -> list[str]:
        selection = self.tree.getSelection()
        if selection is None:
            return []
        nodes = selection if isinstance(selection, tuple) else (selection,)
        return ordered(self.names(), {node.DataValue for node in nodes})

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
        if scroll:
            self.tree.makeNodeVisible(self._nodes[index])

    def follow_calc_selection(self) -> None:
        try:
            indices = selected_tabs(self.context, self.controller)
        except Exception:
            report("reading Calc's selected sheets")
            return
        names = self.names()
        self._select([names[index] for index in indices if 0 <= index < len(names)])

    def activate(self, name: str) -> None:
        """Go to the sheet, unless it is hidden: Calc cannot show a hidden sheet."""
        row = next((row for row in self.rows if row.name == name), None)
        sheets = self.document.getSheets()
        if row is not None and row.visible and sheets.hasByName(name):
            self.controller.setActiveSheet(sheets.getByName(name))

    def activate_selection(self) -> None:
        picked = self.selected_names()
        if len(picked) == 1:
            self.activate(picked[0])

    def type_ahead(self, char: str) -> None:
        prefix = self._type_ahead.feed(char, time.monotonic())
        names = self.names()
        picked = self.selected_names()
        current = names.index(picked[0]) if picked else None
        match = find_prefix(names, prefix, current)
        if match is not None:
            self._focus_row(match)

    # Events from Calc

    def document_modified(self) -> None:
        if self._disposed or self._refresh_timer is not None:
            return
        self._refresh_timer = self._main.later(
            REFRESH_DELAY, self._timed_refresh, "refreshing the sheet list"
        )

    def _timed_refresh(self) -> None:
        self._refresh_timer = None
        if not self._busy:  # A move refreshes the list itself when it ends.
            self.refresh()

    def active_sheet_changed(self) -> None:
        """Follow Calc's tab selection when the user went to another sheet.

        Calc also reports activation when sheets move or the same sheet is selected again;
        then the list keeps its own selection.
        """
        if self._disposed or self._busy:
            return
        before = next((row.name for row in self.rows if row.active), None)
        self.refresh()
        if next((row.name for row in self.rows if row.active), None) != before:
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
        if event.PopupTrigger:
            return
        row = self.geometry().row_at(event.Y)
        if event.Buttons & RIGHT:
            self._press = None
            if row is not None and self.rows[row].name not in self.selected_names():
                self._focus_row(row)
        elif event.Buttons & LEFT:
            self._press = (row, event.Modifiers)

    def mouse_released(self, event) -> None:
        if event.Buttons & RIGHT:
            # Open on release on every platform, so that the release cannot pick an item.
            x, y = event.X, event.Y
            self.post(lambda: self._open_menu(x, y), "the sheet tab menu")
            return
        press, self._press = self._press, None
        if not event.Buttons & LEFT or press is None:
            return
        row, modifiers = press
        if row is None or modifiers & (SHIFT | MOD1) or self.geometry().row_at(event.Y) != row:
            return
        self.activate(self.rows[row].name)

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
        if self._disposed or self._busy or not picked:
            return
        hidden = {row.name for row in self.rows if not row.visible}
        chosen = self._menu.show(self.peer, x, y, picked, hidden)
        if chosen == SHOW:
            if not show_sheets(self.document, picked):
                show_error(self.peer, tr("Sheet Manager"), tr("The sheets changed; try again."))
            self.refresh()

    # Drag and drop

    def start_drag(self, event) -> None:
        self._press = None  # A drag is not a click.
        if self._busy or self._drag is not None:
            return
        picked = self.selected_names()
        order = self.names()
        if not picked or refusal(self.document):
            return
        if list(self.document.getSheets().getElementNames()) != order:
            self.refresh()
            return
        transferable = _Transferable(uuid.uuid4().hex)
        self._drag = _Drag(picked, order, transferable)
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
        if self._disposed:
            return
        self._busy = True
        try:
            if not self.frame.isActive():
                self.frame.activate()  # Calc's undo of sheet moves needs the active view.
            active = self.controller.getActiveSheet().getName()
            names = self.names()
            tabs = [names[index] for index in selected_tabs(self.context, self.controller)]
            result = move_block(self.document, drag.order, drag.names, gap)
            if result.status == "moved":
                self._restore_view(active, tabs)
        finally:
            self._busy = False
        self.refresh()
        if set(drag.names) <= set(self.names()):
            self._select(drag.names)
        if result.message:
            show_error(self.peer, tr("Sheet Manager"), result.message)

    def _restore_view(self, active: str, tabs: list[str]) -> None:
        """Keep the active sheet and Calc's tab selection as they were before the move."""
        sheets = self.document.getSheets()
        if self.controller.getActiveSheet().getName() != active and sheets.hasByName(active):
            self.controller.setActiveSheet(sheets.getByName(active))
        order = list(sheets.getElementNames())
        wanted = sorted(order.index(name) for name in tabs if name in order)
        if wanted and selected_tabs(self.context, self.controller) != wanted:
            select_tabs(self.context, self.frame, wanted)
