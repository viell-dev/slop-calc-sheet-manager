"""The sheet list: a flat TreeControl showing the document's sheets.

A single click selects a row; a double click or Enter goes to that sheet and leaves it as Calc's
only selected tab. Ctrl+click and Shift+click change the list's own selection. Picks can be dragged
to another place in the list through the reorder layer (``uno_reorder``). The list's selection
follows changes to this window's native tab selection, but the list groups Calc's tabs only to
run one of Calc's commands from its menu (see ``uno_menu``). A status line distinguishes that group
from list picks.

The list keeps the reorder layer's snapshot of the sheets it shows. A selected row survives a
refresh only while the sheet handle retained for it still has that row's name, so a sheet that
was deleted and recreated, or renamed and reused, drops out of the selection rather than passing
it to a different sheet. Drags, the menu, Show, and Rename Sheets check the same identity again
when they run. After its own verified batch rename, the list carries its picks, cursor, and
anchor to the new names through their retained handles (`selection.Selection.carry`); the
refresh counts only others' renames against its one-rename check.

Every listener only records state or posts work to the main thread: LibreOffice calls some
of them from other threads or in the middle of a change.

The tree. The list is a borderless `TreeControl`, so that it is a direct child of the panel
window, with a hidden root. With a hidden root, the tree peer mishandles every data-model change
event and re-parents all rows under the root, so nodes are never changed in place: a refresh
builds a new data model and restores the selection, scroll position, and keyboard cursor.
`uno_rows` paints the rows.

Refresh. Refreshing reads every sheet and rebuilds the tree on the main thread, so it is limited.
An activation refreshes at once only after the list has been idle for several times the last
refresh's cost; other changes wait for a pause, with a bounded wait. Bulk API changes, such as a
500-call move, send an event for each call, and refreshing on each one slowed such a move on
Windows from seconds to over a minute. Rows can therefore be out of date when the user acts on
them, so every action checks its sheets when it runs, never against the cached rows. A drop plans
against the snapshot of the drag's start through `apply_order`, which refuses stale state, and is
refused when the generation moved during the drag.

Pointer input. A left press keeps the pressed sheet's handle, and its release activates only that
sheet, still in that row (#28). If a refresh during the press moved the sheet or showed another
under its name, the release has no effect at all: the list writes its own refs back, whatever the
tree selected on release, so a newer pick made meanwhile, by following Calc or by keyboard, stays.
While a press is held, a refresh does not take the tree's selection as the user's; the press and
release handlers do. A selected row's native release can move the tree's cursor before the
queued mouse listener runs, so refusing that gesture also restores a surviving picked cursor,
preferring its original sheet, and keeps newer picks. An unpicked cursor moved during an invalid
held gesture is deliberately not kept, and the known-issues guide records that limit (#71): the
supported toolkit and controller interfaces offer no sidebar pre-release hook.

Activation. A double click or Enter makes the sheet Calc's only selected tab and reads that back,
because `setActiveSheet` keeps an existing group when the sheet belongs to it. Activation reads
the handle's current name and visibility first, because Calc sends the activation of a hidden
sheet to another sheet (#43); if Calc goes elsewhere anyway, the list restores the previous sheet
and tabs and reads both back before saying that the view is unchanged (#46). The mouse handlers
and the notice of a sheet switch both run after input already queued, so a switch is matched to
the list's input count when Calc reports it: newer clicks or keys in the list win over following
Calc's selection, and a switch the list made itself is not followed (#44).

Keyboard cursor. The list observes native cursor changes it did not make through
`ACTIVE_DESCENDANT_CHANGED` on the peer's accessible tree context. The event's row context has a
cached sibling index that maps directly to the flat rows; the callback reads only that index and
records a ref from the shown handles. Delivery is synchronous in the supported LibreOffice
versions. Intermediate focus events during model replacement and restoration are ignored, and
the listener is removed on failed setup and on disposal. A disposed event row supplies no new
position: catch only `DisposedException` from its getters and keep the last valid cursor; report
other errors. Selection keys are consumed before native handling, because forwarding a key can
deliver it more than once; never return a key unconsumed after updating the owned cursor.
Consumed key intent is recorded synchronously and the UI write coalesced, and native focus and
selection are ignored while that write or a pointer gesture is pending.

Following Calc's tabs. Calc sends no reliable notification for a tab selection that keeps the
same active sheet, so each list caches the reflected `getSelectedSheets` method and samples its
retained controller on the UI thread every `VIEW_INTERVAL`. Never run that getter in a timer
worker or a toolkit listener. Compare logical name membership, establish a fresh baseline after
a namespace or proof change, and never consume pending modify evidence through the structure
monitor's `check()` merely to observe tabs. List input acknowledges the preceding native state at
the listener boundary, so that queued Enter, menu, type-ahead, and move requests cannot have an
older sample replace their picks. Observation is skipped during a held tree press, a drag, the
menu, a move, a restoration, or a document lock. A token rejects a cancelled timer already posted
to the UI queue, so that timer chains cannot duplicate.

Sidebar visibility. A hidden panel checks its visibility every `HIDDEN_VIEW_INTERVAL` without
reading native tabs. Test the sidebar's visibility before calling `deck.isActive()`, which
dereferences its native controller, then the deck's activity and the panel's expansion; native
child-window visibility misses GTK hiding. Cached wrappers are dropped after the sidebar closes,
and observation stops on disposal or controller replacement. A panel wrapper is kept while the
panel is collapsed or inactive, because fresh `XPanel` discovery runs native deck layout: check
deck activity before a fresh discovery, and treat `NoSuchElementException` as a context that is
temporarily unavailable. Actual native panel disposal disposes the list too.

Notices and focus. Clearing a pick the user made shows a panel notice for `NOTICE_SECONDS`
(`uno_status`); invalidating only the cursor, the anchor, or a press is silent. Never time out a
native infobar instead: its removal can move focus to the sheet. The notice uses the existing
main-thread timer, with a token rejecting a stale queued timeout after renewal or disposal. The
list moves Tab and Shift+Tab focus itself, between its controls and, past either end, to the
frame's component window: native sidebar traversal alone neither reaches these child peers nor
leaves them reliably. Posted focus requests are refused when focus or the active frame moved.
`uno_moves` states the move buttons' rules, which `_update_moves` and `travel_focus` here, and
`uno_keys` and `keys.move_action`, carry out.
"""

import contextlib
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

import uno
import unohelper
from com.sun.star.accessibility import XAccessibleEventListener
from com.sun.star.awt import XFocusListener, XMouseListener, XPaintListener
from com.sun.star.container import NoSuchElementException
from com.sun.star.datatransfer import DataFlavor, UnsupportedFlavorException, XTransferable
from com.sun.star.datatransfer.dnd import (
    XDragGestureListener,
    XDragSourceListener,
    XDropTargetListener,
)
from com.sun.star.lang import DisposedException
from com.sun.star.sheet import XActivationEventListener
from com.sun.star.util import XModifyListener

from sheet_manager.i18n import tr
from sheet_manager.keys import (
    DOWN,
    END,
    HOME,
    PAGEDOWN,
    PAGEUP,
    SPACE,
    UP,
    A,
    TypeAhead,
    find_prefix,
)
from sheet_manager.rename import Batch
from sheet_manager.reorder import Action, plan_move
from sheet_manager.selection import Ref, Selection, structure_kept
from sheet_manager.sheet_list import RowGeometry, SheetRow, ordered, row_label
from sheet_manager.uno_calc import (
    Later,
    MainThread,
    dispatch,
    prop,
    read_rows,
    report,
    select_tabs,
    selected_tabs,
    selected_tabs_method,
    show_error,
    start_thread,
)
from sheet_manager.uno_keys import ListKeyHandler, Shortcuts
from sheet_manager.uno_menu import (
    ACTIONS,
    COMMANDS,
    HELP,
    MOVE_IDS,
    RENAME_SHEETS,
    SHOW,
    SheetMenu,
)
from sheet_manager.uno_moves import MoveButtons
from sheet_manager.uno_rename import apply_renames, preflight
from sheet_manager.uno_rename_dialog import RenameDialog
from sheet_manager.uno_reorder import (
    Availability,
    Snapshot,
    apply_order,
    is_current,
    move_availability,
    plan_availability,
    snapshot,
)
from sheet_manager.uno_rows import RowPaint
from sheet_manager.uno_show import show_sheets
from sheet_manager.uno_status import CalcStatus
from sheet_manager.uno_structure import monitor_for

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
VIEW_INTERVAL = 0.25
HIDDEN_VIEW_INTERVAL = 1.0
CURSOR_CHANGED = cast(
    int,
    uno.getConstantByName("com.sun.star.accessibility.AccessibleEventId.ACTIVE_DESCENDANT_CHANGED"),
)


NOTICE_SECONDS = 10.0


def _name_or_none(handle: Any) -> str | None:
    try:
        return handle.getName()
    except Exception:
        return None


def _current(ref: Ref) -> bool:
    """Whether the ref's retained handle still reports the ref's name (see selection.py)."""
    try:
        return ref.token is not None and ref.token.getName() == ref.name
    except Exception:
        return False


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
    generation: int  # The structure generation when the button went down.
    voided: bool = False  # The list dropped its picks while it was held.
    clicks: int = 1  # Native double-click count belongs to the press on some backends.


@dataclass(frozen=True)
class _Drag:
    names: list[str]  # The dragged sheets, in document order.
    observed: Snapshot  # The sheets the list showed when the drag started.
    transferable: object
    generation: int  # The structure generation when the drag started.


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
        self._handle("a mouse press", self._owner.mouse_pressed, event)

    def mouseReleased(self, event):
        self._handle("a mouse release", self._owner.mouse_released, event)

    def _handle(self, where, function, event):
        # Posting or reading UNO can let queued observation run before the handler returns.
        self._owner._pointer_depth += 1
        try:
            _guarded(where, function, event)
        finally:
            self._owner._pointer_depth -= 1
            if not self._owner._pointer_depth:
                self._owner._queue_selection()

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


class _Cursor(unohelper.Base, XAccessibleEventListener):
    def __init__(self, owner):
        self._owner = owner

    def notifyEvent(self, event):
        if event.EventId == CURSOR_CHANGED and event.NewValue is not None:
            _guarded("following the native tree cursor", self._owner.cursor_changed, event.NewValue)

    def disposing(self, event):
        pass


class _Paint(unohelper.Base, XPaintListener):
    def __init__(self, owner):
        self._owner = owner

    def windowPaint(self, event):
        _guarded("drawing sheet rows", self._owner.paint_rows)

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
        self._disposed = False
        self._main = MainThread(context)
        self._refresh_timer: Later | None = None
        self._view_timer: Later | None = None
        self._notice_timer: Later | None = None
        self._notice_token: object | None = None
        self._view_token: object | None = None
        self._view_stopped = False
        self._scroll = 0
        self._keys_registered = False
        self._restoring_cursor = False
        self._cleanup = contextlib.ExitStack()
        self._status: CalcStatus | None = None
        self._moves: MoveButtons | None = None
        self._bounds = (0, 0)
        try:
            self._initialize(context, frame, parent_window)
        except BaseException:
            self.dispose()
            raise

    def _release_with(self, work) -> None:
        self._cleanup.callback(_guarded, "disposing the sheet list", work)

    def _initialize(self, context, frame, parent_window):
        self.context = context
        self.frame = frame
        self.controller = frame.getController()
        self.document = self.controller.getModel()
        # Attached before the first snapshot, so that no structural change goes unnoticed.
        self._monitor = monitor_for(self.document)
        self._proven = self._monitor.generation  # The generation the picks were proved at.
        self.toolkit = parent_window.getToolkit()
        self.rows: list[SheetRow] = []
        self._observed: Snapshot | None = None
        self._handles: dict[str, Any] = {}
        self._nodes: list[object] = []
        # The list's own picks and keyboard cursor, as sheet identities (selection.py).
        # `_shown` is the selection last written to the tree or adopted from accessibility.
        # Owned pointer and keyboard gestures share a retained range anchor.
        self._selection = Selection(_current)
        self._shown: tuple[str, ...] = ()
        # A sheet that may have been inserted or deleted since the picks were proved makes
        # every retained handle suspect (selection.py, structure.py), and the list then drops
        # its picks; `_generation` counts the drops, so that a drag or an open menu started
        # before one can tell.
        self._generation = 0
        self._user_picks = False  # Whether the picks came from the user rather than from Calc.
        self._busy = False
        self._menu = SheetMenu(context, frame, self.document, self.controller)
        self._keys = ListKeyHandler(self, Shortcuts(context, self.document))
        self._changed_at = 0.0  # The last document change.
        self._stale_since: float | None = None  # The first change not yet shown.
        self._refresh_cost = 0.0  # How long the last refresh took.
        self._refreshed_at = 0.0  # When it ended.
        # Counts the user's own input in the list, as the list's mouse and key handlers see
        # it. A request to follow Calc's selection remembers the count when Calc reported the
        # switch; newer input in the list wins over it.
        self._input = 0
        self._activation_input = 0  # A newer successful activation revokes old menu restoration.
        self._view_input = 0
        self._view_ack_pending = False
        self._view_state: tuple[str, frozenset[str]] | None = None
        self._view_names: frozenset[str] = frozenset()
        self._view_generation = self._proven
        self._view_controls = None
        self._tabs_method = selected_tabs_method(context)
        self._follow_input: int | None = None
        self._activating = False  # The list's own setActiveSheet call is running.
        self._press: _Press | None = None
        self._pointer_depth = 0
        self._selection_write_pending = False
        self._selection_scroll = False
        self._context_target: Ref | None = None
        self._context_generation = self._proven
        self._context_input = 0
        self._menu_context = False
        self._page_rows = 10
        self._decoration_pending = False
        self._drag: _Drag | None = None
        self._gap: int | None = None
        self._pointer_y = 0
        self._scroll = 0
        self._scrolling = False  # Whether the auto-scroll thread runs.
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
        self._release_with(self.tree.dispose)
        self.tree.setModel(model)
        self.tree.createPeer(self.toolkit, parent_window)
        self.peer = self.tree.getPeer()
        self._row_paint = RowPaint(self.peer, self.tree)
        self._row_height = self._row_paint.row_height()
        model.RowHeight = self._row_height

        self._listeners = {
            "mouse": _Mouse(self),
            "focus": _Focus(self),
            "cursor": _Cursor(self),
            "paint": _Paint(self),
            "gesture": _Gesture(self),
            "source": _Source(self),
            "target": _Target(self),
            "document": _Document(self),
        }
        self._status = CalcStatus(context, parent_window)
        self._release_with(self._status.dispose)
        self._moves = MoveButtons(
            context, parent_window, self.queue_move, self._listeners["focus"], self.note_input
        )
        self._release_with(self._moves.dispose)
        self.tree.addMouseListener(self._listeners["mouse"])
        self.tree.addFocusListener(self._listeners["focus"])
        self.tree.addPaintListener(self._listeners["paint"])
        self._cursor_context = self.peer.getProperty("XAccessible").getAccessibleContext()
        self._cursor_context.addAccessibleEventListener(self._listeners["cursor"])
        self._release_with(
            lambda: self._cursor_context.removeAccessibleEventListener(self._listeners["cursor"])
        )
        self._gestures = self.toolkit.getDragGestureRecognizer(self.peer)
        self._gestures.addDragGestureListener(self._listeners["gesture"])
        self._release_with(
            lambda: self._gestures.removeDragGestureListener(self._listeners["gesture"])
        )
        self._drag_source = self.toolkit.getDragSource(self.peer)
        self._drop_target = self.toolkit.getDropTarget(self.peer)
        self._drop_target.addDropTargetListener(self._listeners["target"])
        self._release_with(
            lambda: self._drop_target.removeDropTargetListener(self._listeners["target"])
        )
        self._drop_target.setActive(True)
        self._release_with(lambda: self._drop_target.setActive(False))
        self.document.addModifyListener(self._listeners["document"])
        self._release_with(lambda: self.document.removeModifyListener(self._listeners["document"]))
        self.controller.addActivationEventListener(self._listeners["document"])
        self._release_with(
            lambda: self.controller.removeActivationEventListener(self._listeners["document"])
        )
        self._release_with(lambda: self.focus_changed(False))
        self.refresh()
        self.follow_calc_selection()
        self._schedule_view(VIEW_INTERVAL)

    # Life cycle and layout

    def post(self, function, where: str) -> None:
        if not self._disposed:
            self._main.post(function, where)

    def set_bounds(self, width: int, height: int) -> None:
        self._bounds = width, height
        if not self._disposed:
            toolbar = self._moves.height if self._moves is not None else 0
            if self._status is not None:
                self._status.set_bounds(width, height)
            footer = self._status.height if self._status is not None else 0
            if self._moves is not None:
                self._moves.set_bounds(width)
            self.tree.setPosSize(
                4, toolbar + 4, max(width - 8, 0), max(height - footer - toolbar - 8, 0), POSSIZE
            )
            row_height = self.geometry().row_height if self._nodes else self._row_height
            self._page_rows = max(1, (height - footer - toolbar - 8) // row_height - 1)

    @property
    def minimal_width(self) -> int:
        return max(150, self._moves.minimum_width if self._moves is not None else 0)

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
        self._view_token = None
        if self._view_timer is not None:
            self._view_timer.cancel()
        self._notice_token = None
        if self._notice_timer is not None:
            self._notice_timer.cancel()
        self._view_controls = None
        self._cleanup.close()

    # Rows and identity

    def names(self) -> list[str]:
        return [row.name for row in self.rows]

    @property
    def _cursor(self) -> str | None:
        cursor = self._selection.cursor
        return cursor.name if cursor is not None else None

    @_cursor.setter
    def _cursor(self, name: str | None) -> None:
        self._selection.cursor = self._ref(name)

    def _ref(self, name: str | None) -> Ref | None:
        """The sheet the row `name` shows now, reusing the list's ref for it if still current."""
        if name is None:
            return None
        return self._selection.ref(name, self._handles, self.names())

    def refresh(self, renamed: Mapping[str, str] | None = None) -> None:
        """Read the sheets again; keep only selected rows whose sheets are still the same.

        `renamed` is the list's own verified batch rename, old names to new, just made at the
        proven generation: refs of those sheets are carried to their new names (`_rename`).
        """
        if self._disposed:
            return
        started = time.monotonic()
        try:
            self._refresh(renamed or {})
        finally:
            self._refreshed_at = time.monotonic()
            self._refresh_cost = self._refreshed_at - started
            self._stale_since = None

    def _refresh(self, renamed: Mapping[str, str]) -> None:
        """Read the sheets, drop every pick that is no longer its sheet, and show the rest.

        Picks, cursor, and anchor are revalidated on every refresh, whether or not the rows
        change: a refresh that only renews the handles behind unchanged rows must still drop a
        pick whose sheet was replaced under the same name (#28).
        """
        if self._press is None:
            self._take_tree_selection(defer=True)  # Let queued owned input run first.
        previous = self._observed
        observed = snapshot(self.document)
        rows = read_rows(self.controller, observed)
        generation = self._monitor.check()
        if previous is not None and not self._identities_kept(
            previous, observed, generation, renamed
        ):
            dropped = self._drop_all_picks()
        else:
            dropped = self._selection.carry(renamed)
        self._proven = generation
        changed = rows != self.rows or not self._nodes
        self._observed = observed
        self._handles = dict(
            zip((sheet.name for sheet in observed.sheets), observed.handles, strict=True)
        )
        if changed:
            self._rebuild(rows)
        elif dropped or tuple(self._selection.names()) != self._shown:
            self._apply_selection()
        self._update_moves()

        if self._view_generation != generation or self._view_names != frozenset(self.names()):
            # Replacement or rename is not a request to pick the new sheet under an old name.
            self._view_state = None
            self._view_input = self._input
            if not self._view_stopped:
                # Establish the new baseline before the refreshed rows become usable. A tab
                # change after this return must not be mistaken for that first baseline.
                self._observe_view(True)

    def _identities_kept(
        self,
        previous: Snapshot,
        observed: Snapshot,
        generation: int,
        renamed: Mapping[str, str],
    ) -> bool:
        """Whether the handles of the last refresh still prove which sheet each one is.

        Not if a sheet may have been inserted or deleted since (the structure generation
        moved), nor if the handles no longer map one to one onto the sheets with at most one
        rename (`structure_kept`): a deleted sheet's handle turns to another sheet. The list's
        own verified batch rename counts as recorded under the new names, so only renames
        made by others count against that one.
        """
        if generation != self._proven:
            return False
        reported = [_name_or_none(handle) for handle in previous.handles]
        recorded = [renamed.get(sheet.name, sheet.name) for sheet in previous.sheets]
        return structure_kept(recorded, reported, [sheet.name for sheet in observed.sheets])

    def _drop_all_picks(self) -> bool:
        """Drop every pick, the cursor, the anchor, and a held press: none can be proved now."""
        told = self._user_picks and bool(self._selection.picked)
        had = self._selection.clear()
        self._user_picks = False
        self._generation += 1
        if self._press is not None:
            self._press = replace(self._press, voided=True)
        if told:
            self.post(self._show_cleared_notice, "telling that the selection was cleared")
        return had

    def _show_cleared_notice(self) -> None:
        """Explain clearing briefly in the panel, without Calc's focus-changing infobar."""
        if self._disposed or self._status is None:
            return
        self._status.show_notice(True)
        self.set_bounds(*self._bounds)
        if self._notice_timer is not None:
            self._notice_timer.cancel()
        token = self._notice_token = object()
        self._notice_timer = self._main.later(
            NOTICE_SECONDS,
            lambda: self._expire_cleared_notice(token),
            "clearing the selection notice",
        )

    def _expire_cleared_notice(self, token: object) -> None:
        # A cancelled timer can already be in the UI queue. It cannot hide a newer notice.
        if self._disposed or token is not self._notice_token:
            return
        self._notice_token = self._notice_timer = None
        if self._status is not None:
            self._status.show_notice(False)
            self.set_bounds(*self._bounds)

    def _rebuild(self, rows: list[SheetRow]) -> None:
        """Replace the whole data model.

        With a hidden root, the tree control mishandles every change event of the data model:
        changing one node's text re-parents all rows under a newly shown root. So the list
        never changes nodes in place; it builds a new model and restores the selection, the
        scroll position, and keyboard cursor. The range anchor belongs to the selection model
        and survives while its sheet identity remains valid.
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
            root.appendChild(node)
            nodes.append(node)
        restoring = self._restoring_cursor
        self._restoring_cursor = True
        try:
            # Replacing the model focuses intermediate rows before the old cursor comes back.
            self.tree.getModel().DataModel = model
            self._nodes, self.rows = nodes, rows
            self._shown = ()
            names = self.names()
            if top in names and nodes:
                # Scroll to the end first, so that showing the old top row puts it at the top.
                self.tree.makeNodeVisible(nodes[-1])
                self.tree.makeNodeVisible(nodes[names.index(top)])
            self._apply_selection()
        finally:
            self._restoring_cursor = restoring

    def _select(self, names: list[str], cursor: str | None = None) -> None:
        """Pick these rows as they show now and put the keyboard cursor on `cursor`."""
        self._selection.take(names, self._handles, self.names())
        self._selection.cursor = self._ref(cursor)
        self._selection.anchor = self._selection.cursor
        self._apply_selection()

    def _apply_selection(self) -> None:
        """Write the list's own picks and cursor to the tree; the cursor falls back to a pick."""
        names = self.names()
        cursor = self._selection.cursor
        if cursor is None or cursor.name not in names:
            cursor = self._selection.picked[0] if self._selection.picked else None
            self._selection.cursor = cursor
        wanted = {ref.name for ref in self._selection.picked}
        indices = [index for index, name in enumerate(names) if name in wanted]
        self._shown = tuple(names[index] for index in indices)
        self._update_moves()
        if cursor is None:
            self.tree.clearSelection()
            return
        self._move_tree_cursor(names.index(cursor.name), scroll=False)
        if cursor.name not in wanted:
            self.tree.clearSelection()  # Keeps the cursor where it is.
        for index in indices:
            if names[index] != cursor.name:
                self.tree.addSelection(self._nodes[index])
        self.peer.invalidate(0)

    def _take_tree_selection(self, paint: bool = True, *, defer: bool = False) -> bool:
        """Take native picks, deferring observations until queued owned input has run."""
        if (
            self._pointer_depth
            or self._selection_write_pending
            or self._press is not None
            or self._context_target is not None
            or self._menu_context
        ):
            return False
        names = self.selected_names()
        if tuple(names) != self._shown:
            if defer:
                seen, proof, generation = self._input, self._proven, self._generation
                order = tuple(self.names())

                def take() -> None:
                    if (
                        not self._disposed
                        and self._input == seen
                        and self._proven == self._monitor.generation == proof
                        and self._generation == generation
                        and tuple(self.names()) == order
                    ):
                        self._take_tree_selection()

                # Native selection can change before its queued mouse listener arrives.
                # Taking it now would apply the same Ctrl toggle again in that listener.
                self.post(take, "taking native list selection after queued input")
                return True
            self._selection.take(names, self._handles, self.names())
            self._selection.anchor = self._selection.cursor
            self._shown = tuple(names)
            self._user_picks = True
            if paint:
                self.peer.invalidate(0)
                self._update_moves()
            return True
        return False

    def _current_picks(self) -> list[Ref]:
        """The list's picks as they stand now, each still the sheet it was picked as.

        None while a sheet insertion or deletion has not been through a refresh yet: the
        refresh this asks for decides what can still be proved.
        """
        if self._monitor.check() != self._proven:
            self.post(self.refresh, "refreshing the sheet list")
            return []
        if self._press is None:
            self._take_tree_selection()
        if self._selection.revalidate() or tuple(self._selection.names()) != self._shown:
            self._apply_selection()
        return list(self._selection.picked)

    def geometry(self) -> RowGeometry:
        if not self._nodes:
            return RowGeometry(0, 0, 0)
        rect = self.tree.getNodeRect(self._nodes[0])
        # VCL can enlarge the requested RowHeight to fit its eventual font/DPI. Both hit
        # testing and painting must follow the actual entry bounds, including after scrolling.
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

    def _focus_row(self, index: int, scroll: bool = True) -> None:
        """Pick only this row, as it shows now, and move the keyboard cursor to it."""
        ref = self._ref(self.rows[index].name)
        self._selection.picked = [ref] if ref is not None else []
        self._selection.cursor = ref
        self._selection.anchor = ref
        self._user_picks = True
        self._move_tree_cursor(index, scroll)
        self._shown = (self.rows[index].name,)

    def _move_tree_cursor(self, index: int, scroll: bool = True) -> None:
        """Select only this row in the tree, which moves its keyboard cursor there too.

        The tree control has no cursor setter, but in single selection mode selecting a row also
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

    def tree_key(self, code: int, modifiers: int) -> None:
        """Record owned selection keys synchronously, so held keys accumulate before painting."""
        self._input += 1
        self._note_view_input()
        names = self.names()
        if not names or self._monitor.generation != self._proven:
            return
        self._selection.revalidate()
        cursor = self._selection.cursor
        current = names.index(cursor.name) if cursor is not None and cursor.name in names else 0
        if code == A and modifiers == MOD1:
            self._selection.take(names, self._handles, names)
            self._selection.cursor = cursor or self._ref(names[0])
        elif code == SPACE:
            self._selection.choose(names[current], self._handles, names, toggle=True)
        else:
            target = {
                UP: current - 1,
                DOWN: current + 1,
                HOME: 0,
                END: len(names) - 1,
                PAGEUP: current - self._page_rows,
                PAGEDOWN: current + self._page_rows,
            }.get(code)
            if target is None:
                return
            name = names[max(0, min(len(names) - 1, target))]
            if modifiers & MOD1 and not modifiers & SHIFT:
                self._selection.cursor = self._ref(name)
            else:
                self._selection.choose(
                    name,
                    self._handles,
                    names,
                    extend=bool(modifiers & SHIFT),
                    toggle=bool(modifiers & MOD1),
                )
        self._user_picks = True
        self._queue_selection(scroll=True)

    def _queue_selection(self, scroll: bool = False) -> None:
        self._selection_scroll = self._selection_scroll or scroll
        if not self._selection_write_pending:
            self._selection_write_pending = True
            self.post(self._flush_selection, "showing the selection")

    def _flush_selection(self) -> None:
        if self._pointer_depth:
            self._selection_write_pending = False  # The listener posts again after its work.
            return
        try:
            if self._monitor.check() != self._proven:
                self.refresh()
            else:
                self._selection.revalidate()
                self._apply_selection()
                cursor = self._selection.cursor
                if self._selection_scroll and cursor is not None and cursor.name in self.names():
                    self.tree.makeNodeVisible(self._nodes[self.names().index(cursor.name)])
        finally:
            self._selection_write_pending = False
            self._selection_scroll = False

    def cursor_changed(self, accessible: Any) -> None:
        """Record the row the native tree focused, even when it is outside the selection.

        These events are synchronous. The two getters return the entry's context and cached
        sibling index, without changing UI state (verified in LibreOffice 26.2.1 and 26.8).
        The hidden root is omitted, so the index maps directly onto the currently shown rows.
        """
        if (
            self._disposed
            or self._pointer_depth
            or self._restoring_cursor
            or self._selection_write_pending
            or self._press is not None
            or self._context_target is not None
            or self._menu_context
        ):
            return
        try:
            index = accessible.getAccessibleContext().getAccessibleIndexInParent()
        except DisposedException:
            # A cached event row may already belong to a discarded model. It supplies no
            # new position; preserve the last cursor proved against the displayed rows.
            return
        if 0 <= index < len(self.rows):
            name = self.rows[index].name
            self._selection.cursor = Ref(name, self._handles[name], index)

    def follow_calc_selection(self) -> None:
        try:
            indices = selected_tabs(self.context, self.controller)
            active = self.controller.getActiveSheet().getName()
        except Exception:
            report("reading Calc's selected sheets")
            return
        names = self.names()
        self._select([names[index] for index in indices if 0 <= index < len(names)], active)
        self._user_picks = False
        self._remember_view(
            active, tuple(names[index] for index in indices if 0 <= index < len(names))
        )

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
        if self._monitor.check() != self._proven:  # The handle may prove nothing now.
            self.post(self.refresh, "refreshing the sheet list")
            return
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
        self._activation_input += 1
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
        self._note_view_input()

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
        picked = self._current_picks()
        if len(picked) == 1:
            self.activate(picked[0].name, picked[0].token)

    def type_ahead(self, char: str) -> None:
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
        """Refresh once changes pause, or at the latest after a bounded wait.

        The structure monitor notes insertions and deletions itself, as they happen.
        """
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

    # Calc's tab selection has no reliable change notification. Observe this controller on
    # the UI thread, independently of property refreshes and the list's own picks.

    def _view_visible(self) -> bool:
        if self.frame.getController() != self.controller:
            self._view_stopped = True  # Reload replaced this controller; its panel owns disposal.
            self._view_controls = None
            return False
        if self.frame.getContainerWindow().IsMinimized:
            return False
        sidebar = self.controller.getSidebar()
        if not sidebar.isVisible():
            self._view_controls = None
            return False
        if self._view_controls is None:
            try:
                deck = sidebar.getDecks().getByName("SheetManagerDeck")
                if not deck.isActive():
                    return False
                panel = deck.getPanels().getByName("SheetManagerPanel")
            except NoSuchElementException:
                return False  # A reopened sidebar's native context may not be ready yet.
            self._view_controls = deck, panel
        deck, panel = self._view_controls
        # isActive dereferences the native sidebar controller: the visibility guard above
        # must precede it. Parent-window visibility alone misses GTK container hiding.
        # A fresh XPanel lookup lays out the native deck. Retain it while collapsed or
        # inactive; actual panel disposal synchronously disposes this list and its cache.
        return bool(deck.isActive() and panel.isExpanded())

    def _schedule_view(self, seconds: float) -> None:
        if self._disposed or self._view_stopped or self._view_timer is not None:
            return
        token = object()
        self._view_token = token
        self._view_timer = self._main.later(
            seconds, lambda: self._view_tick(token), "observing Calc's selected tabs"
        )

    def _view_tick(self, token: object) -> None:
        if self._disposed or token is not self._view_token:
            return  # A cancelled callback may already be in the native queue.
        self._view_timer, self._view_token = None, None
        visible = False
        try:
            visible = self._view_visible()
            if visible:
                self._observe_view(False)
        except DisposedException:
            self._view_stopped = True
        except Exception:
            self._view_stopped = True  # Report once rather than start a repeating error loop.
            raise
        finally:
            self._schedule_view(VIEW_INTERVAL if visible else HIDDEN_VIEW_INTERVAL)

    def _note_view_input(self) -> None:
        """Acknowledge preceding Calc state after this input, coalescing forwarded callbacks.

        Do not invoke the native selected-tabs getter from a toolkit listener. The watermark
        also protects a sample that runs before this acknowledgement reaches the UI queue.
        """
        if self._view_ack_pending:
            return
        self._view_ack_pending = True
        self.post(self._acknowledge_view, "noting the list's newer input")

    def note_input(self) -> None:
        """Stamp native control input before its queued action can use the picks."""
        self._input += 1
        self._note_view_input()

    def queue_input(self, function, where: str) -> None:
        """Stamp a key's intent before an older observation can precede its queued action."""
        self.note_input()
        self.post(function, where)

    def _acknowledge_view(self) -> None:
        self._view_ack_pending = False
        if not self._disposed and not self._view_stopped:
            try:
                if self._view_visible():
                    self._observe_view(True)
            except DisposedException:
                self._view_stopped = True
            except Exception:
                self._view_stopped = True
                raise

    def _remember_view(self, active: str, tabs: tuple[str, ...]) -> None:
        self._view_state = active, frozenset(tabs)
        self._view_names = frozenset(self.names())
        self._view_generation = self._proven
        self._view_input = self._input
        if self._status is not None and self._status.show_tabs(tabs):
            self.set_bounds(*self._bounds)

    def _observe_view(self, acknowledge: bool) -> None:
        if (
            self._busy
            or self._pointer_depth
            or self._restoring_cursor
            or self._press is not None
            or self._drag is not None
            or self._menu.is_open
            or self._menu_context
        ):
            return
        if self.document.hasControllersLocked() or self.document.isActionLocked():
            return
        generation = self._monitor.generation  # Never consume pending modify evidence (#66).
        if generation != self._proven:
            self._view_state = None
            if self._stale_since is None:
                self.document_modified()
            return
        names = tuple(self.document.getSheets().getElementNames())
        if names != tuple(self.names()):
            if self._stale_since is None:
                self.document_modified()
            return
        active = str(self.controller.getActiveSheet().getName())
        indices = self._tabs_method.invoke(self.controller, ())[0]
        if any(index < 0 or index >= len(names) for index in indices):
            return
        tabs = tuple(names[index] for index in sorted(indices))
        if self._monitor.generation != generation:
            return
        if self._view_generation != generation or self._view_names != frozenset(names):
            self._view_state = None  # A new namespace/proof establishes a baseline, not new picks.
        state = active, frozenset(tabs)
        changed = self._view_state is not None and state != self._view_state
        newer_input = self._input != self._view_input or self._view_ack_pending
        # Native input can precede its queued mouse listener. Do not follow Calc over it, or
        # adopt the native toggle before the owned listener has handled that same input.
        pending_picks = self._take_tree_selection(paint=False, defer=True)
        self._remember_view(active, tabs)
        if changed and not acknowledge and not newer_input and not pending_picks:
            self._select(list(tabs), active)
            self._user_picks = False

    # Keyboard

    def focus_changed(self, gained: bool) -> None:
        if gained and not self._keys_registered and not self._disposed:
            self.toolkit.addKeyHandler(self._keys)
            self._keys_registered = True
        elif not gained and self._keys_registered:
            self._keys_registered = False
            self.toolkit.removeKeyHandler(self._keys)

    def owns_keys(self) -> bool:
        return (
            not self._disposed
            and not self._menu.is_open
            and (self.owns_tree_keys() or self._moves is not None and self._moves.has_focus())
        )

    def owns_tree_keys(self) -> bool:
        return not self._disposed and bool(self.peer.hasFocus())

    def travel_focus(self, backwards: bool) -> bool:
        if not self.owns_keys():
            return False
        controls = [*(self._moves.buttons.values() if self._moves is not None else ()), self.tree]
        current = next(
            (index for index, control in enumerate(controls) if control.getPeer().hasFocus()), None
        )
        if current is None:
            return False
        seen = self._input
        step = -1 if backwards else 1
        for index in range(current + step, -1 if backwards else len(controls), step):
            control = controls[index]
            if control is self.tree or control.getModel().Enabled:
                self.post(
                    lambda target=control: self._focus_control(target, seen),
                    "moving focus within Sheet Manager",
                )
                return True
        self.post(lambda: self._focus_control(None, seen), "leaving Sheet Manager")
        return True

    def _focus_control(self, control, seen: int) -> None:
        if (
            self._disposed
            or self._input != seen
            or not self.frame.isActive()
            or not self.owns_keys()
        ):
            return
        if control is None:
            self.frame.getComponentWindow().setFocus()
        elif control is self.tree or control.getModel().Enabled:
            control.setFocus()
        else:
            self.tree.setFocus()

    # Movement commands

    def _update_moves(self) -> None:
        if self._moves is None or self._disposed:
            return
        reason = ""
        states = {}
        if self._busy:
            reason = tr("Wait for the current move to finish.")
        elif self._observed is None or not self._selection.picked:
            reason = tr("Select sheets to move.")
        else:
            permission = move_availability(self.context, self.document)
            if not permission.allowed:
                reason = permission.reason
            elif self._monitor.generation != self._proven:
                # Enablement must not consume pending undo/modify identity evidence (#66).
                reason = tr("The sheet list has changed. Refresh it and try again.")
            else:
                for action in ACTIONS:
                    try:
                        plan = plan_move(
                            self._observed.sheets, self._selection.names(), cast(Action, action)
                        )
                        states[action] = plan_availability(permission, plan)
                    except ValueError as error:
                        states[action] = Availability(False, str(error))
        if reason:
            states = {action: Availability(False, reason) for action in ACTIONS}
        self._moves.update(states)

    def queue_move(self, action: str) -> None:
        """Capture the shown selection now; queued work never adopts later picks or proof."""
        if self._disposed or self._busy or action not in ACTIONS:
            return
        if self._press is None:
            # Native navigation may already have changed the tree while its posted selection
            # callback is still queued. Read that selection without doing UI work here.
            self._take_tree_selection(paint=False)
        self._input += 1
        self._note_view_input()
        observed, picks, proof = self._observed, tuple(self._selection.picked), self._proven
        self.post(lambda: self._move_selection(action, observed, picks, proof), "moving sheets")

    def _move_selection(self, action, observed, picks, proof) -> None:
        if self._disposed or self._busy:
            return
        reason = ""
        if (
            observed is None
            or proof != self._monitor.check()
            or any(not _current(p) for p in picks)
        ):
            reason = tr("The sheet list has changed. Refresh it and try again.")
        elif not picks:
            reason = tr("Select sheets to move.")
        if reason or observed is None:
            self.refresh()
            show_error(self.peer, tr("Sheet Manager"), reason)
            return
        try:
            plan = plan_move(observed.sheets, [p.name for p in picks], action)
        except ValueError as error:
            show_error(self.peer, tr("Sheet Manager"), str(error))
            return
        self._busy = True
        try:
            self._update_moves()
            result = apply_order(self.context, self.document, observed, plan)
        finally:
            self._busy = False
            self.refresh()
        self.tree.setFocus()
        if result.status != "done" or result.message != tr("Sheets moved."):
            show_error(self.peer, tr("Sheet Manager"), result.message)

    def run_command(self, command: str) -> None:
        self.post(lambda: dispatch(self.context, self.frame, command), "a shortcut")

    # Mouse and menu

    def mouse_pressed(self, event) -> None:
        self._input += 1
        self._note_view_input()
        row = self.geometry().row_at(event.Y)
        if event.Buttons & RIGHT:
            self._press = None
            self._context_target = self._ref(self.rows[row].name) if row is not None else None
            self._context_generation = self._monitor.generation
            self._context_input = self._input
            self._queue_selection()
        elif event.Buttons & LEFT:
            self._context_target = None
            name = self.rows[row].name if row is not None else None
            handle = self._handles.get(name) if name is not None else None
            self._press = _Press(
                row,
                event.Modifiers,
                name,
                handle,
                self._monitor.generation,
                clicks=event.ClickCount,
            )
            if name is not None:
                self._selection.choose(
                    name,
                    self._handles,
                    self.names(),
                    extend=bool(event.Modifiers & SHIFT),
                    toggle=bool(event.Modifiers & MOD1),
                    preserve=not event.Modifiers & (SHIFT | MOD1),
                )
                self._user_picks = True
                self._queue_selection()

    def mouse_released(self, event) -> None:
        if event.Buttons & RIGHT:
            # Open on release on every platform, so that the release cannot pick an item.
            x, y, seen = event.X, event.Y, self._context_input
            self.post(lambda: self._open_menu(x, y, seen=seen), "the sheet tab menu")
            return
        press, self._press = self._press, None
        if not event.Buttons & LEFT or press is None or press.name is None:
            return
        moved = press.generation != self._monitor.check()
        if press.voided or moved or not self._pressed_sheet_in_place(press):
            # A refresh during the press moved the pressed sheet away or showed another sheet
            # under its name. The gesture then has no effect at all (#28): no activation, and
            # whatever the tree selected on release is undone. The list's own picks come back,
            # each still the sheet it was picked as, including any newer pick made meanwhile,
            # by following Calc or by keyboard.
            self._selection.revalidate()
            # The native selected-row release can move its cursor before this callback.
            # A refused gesture restores a surviving picked cursor, never that late row.
            picks = self._selection.picked
            self._selection.cursor = next(
                (ref for ref in picks if ref.name == press.name), picks[0] if picks else None
            )
            self._apply_selection()
            return
        row = press.row
        if row is None or press.modifiers & (SHIFT | MOD1):
            self._queue_selection()
            return
        if self.geometry().row_at(event.Y) != row:
            self._queue_selection()
            return
        self._selection.choose(press.name, self._handles, self.names())
        self._queue_selection()
        if press.clicks == 2:
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
        picked = self._current_picks()
        if not picked:
            return
        index = self.names().index(picked[0].name)
        self.tree.makeNodeVisible(self._nodes[index])
        geometry = self.geometry()
        self._open_menu(
            geometry.row_height, geometry.gap_y(index) + geometry.row_height // 2, picked
        )

    def _open_menu(
        self, x: int, y: int, refs: list[Ref] | None = None, seen: int | None = None
    ) -> None:
        """Open the sheet tab menu for the list's picks, each checked to be its sheet still.

        The menu gets a fresh snapshot whose handles are those sheets; it checks them again
        when the chosen command runs.
        """
        if seen is not None and seen != self._input:
            if self._context_input == seen:
                self._context_target = None  # Preserve a newer right-click's target, if any.
            return  # Newer input wins over an older context request still in the UI queue.
        if self._disposed or self._busy or self._menu_context or self._observed is None:
            self._context_target = None
            return
        if refs is None:
            target = self._context_target
            if target is None or self._context_generation != self._monitor.check():
                self._context_target = None
                self._queue_selection()
                return
            refs = (
                list(self._selection.picked) if target.name in self._selection.names() else [target]
            )
        if not refs:
            return
        generation, structure, activated = self._generation, self._proven, self._activation_input
        observed = snapshot(self.document)
        names = {sheet.name for sheet in observed.sheets}
        if not all(ref.name in names and _current(ref) for ref in refs):
            self._context_target = None
            self.refresh()  # A pick changed since this check began: open nothing.
            return
        picked = [ref.name for ref in refs]

        def unchanged() -> bool:
            return (
                self._monitor.check() == structure
                and self._generation == generation
                and self._activation_input == activated
            )

        if not unchanged():
            self._context_target = None
            self.refresh()
            return
        self._menu_context = True
        self._activating = True
        chosen = None

        def complete() -> None:
            try:
                self._menu_action(chosen, observed, refs, structure, unchanged)
            except DisposedException:
                self._view_stopped = True  # The view closed while its command ran.
            finally:
                self._finish_menu()

        try:
            chosen = self._menu.show(self.peer, x, y, observed, picked)
        finally:
            # Act once the popup has closed. A built-in command runs inside this completion,
            # after every check; its synchronous dialogs, such as Delete's confirmation, return
            # before the list refreshes.
            self.post(complete, "completing the sheet menu")

    def _menu_action(self, chosen, observed, refs, structure, unchanged) -> None:
        if chosen in MOVE_IDS:
            self._move_selection(MOVE_IDS[chosen], observed, refs, structure)
        elif chosen == HELP:
            shell = self.context.ServiceManager.createInstanceWithContext(
                "com.sun.star.system.SystemShellExecute", self.context
            )
            shell.execute("https://viell-dev.github.io/slop-calc-sheet-manager/", "", 2)
        elif chosen == RENAME_SHEETS:
            self._rename(observed, refs, unchanged)
        elif chosen == SHOW:
            if not unchanged():
                self._command_refused()
                return
            result = show_sheets(self.context, self.document, observed, [ref.name for ref in refs])
            self.refresh()
            if result.status != "done":
                show_error(self.peer, tr("Sheet Manager"), result.message)
        elif chosen in COMMANDS:
            message = self._menu.run(chosen, observed, [ref.name for ref in refs], unchanged)
            if message:
                self.refresh()
                show_error(self.peer, tr("Sheet Manager"), message)

    def _finish_menu(self) -> None:
        try:
            if not self._disposed and not self._view_stopped:
                # A command's result can still drop picks under the identity rules.
                self.refresh()
                self._selection.revalidate()
                self._apply_selection()
        finally:
            self._activating = False
            self._menu_context = False
            self._context_target = None
            self._acknowledge_view()

    def _rename(self, observed, refs, unchanged) -> None:
        """Rename the menu's targets together through the list's dialog, then carry the picks.

        The dialog checks the plan against `observed`, the menu's snapshot, before it closes;
        `apply_renames` checks everything again before it changes a name. After a verified
        rename at the generation the picks were proved at, the refresh carries every ref of a
        renamed sheet to its new name, through its retained handle (`Selection.carry`).
        """
        if not unchanged():
            self._command_refused()
            return
        changed = tr("The sheets changed while this dialog was open. Cancel and try again.")

        def check(plan) -> str:
            if not unchanged():
                return changed
            return preflight(self.context, self.document, observed, plan)

        batch = Batch([sheet.name for sheet in observed.sheets], [ref.name for ref in refs])
        plan = RenameDialog(self.context, self.frame.getContainerWindow(), batch, check).run()
        if plan is None:
            return  # Cancelled: nothing changed.
        if not unchanged():
            self._command_refused()
            return
        renamed = None
        self._busy = True
        try:
            self._update_moves()
            result = apply_renames(self.context, self.document, observed, plan)
            if result.status == "done":
                renamed = dict(plan.renames)
        finally:
            self._busy = False
            self.refresh(renamed)
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
        picked = [ref.name for ref in self._current_picks()]
        if not picked or self.document.isReadonly() or self.document.isProtected():
            return
        if not is_current(self.document, self._observed):
            self.refresh()
            return
        transferable = _Transferable(uuid.uuid4().hex)
        self._drag = _Drag(picked, self._observed, transferable, self._monitor.generation)
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

    def _drop_refused(self) -> None:
        """A sheet may have been inserted or deleted during the drag: its handles prove nothing."""
        self.refresh()
        show_error(
            self.peer,
            tr("Sheet Manager"),
            tr("Sheets may have been added or removed during the drag. Nothing was moved."),
        )

    def clear_drag_feedback(self) -> None:
        self._scroll = 0
        if self._gap is not None:
            self._gap = None
            if not self._disposed:
                self.peer.invalidate(0)

    def paint_rows(self) -> None:
        if self._disposed or self._restoring_cursor:
            return
        self._row_paint.draw(
            self.rows,
            self.geometry(),
            set(self._selection.names()),
        )
        if not self._decoration_pending:
            self._decoration_pending = True
            self.post(self._decorate_rows, "finishing sheet row borders")

    def _decorate_rows(self) -> None:
        try:
            if not self._disposed and not self._restoring_cursor:
                self._row_paint.decorate(self.geometry(), self._gap)
        finally:
            self._decoration_pending = False

    def _set_scroll(self, direction: int) -> None:
        self._scroll = direction
        if direction and not self._scrolling:
            self._scrolling = True
            start_thread(self._scroll_loop, "auto-scroll")

    def _scroll_loop(self) -> None:
        # dragOver stops while the pointer rests, so a timer keeps scrolling at the edges.
        try:
            while self._scroll and self._drag is not None and not self._disposed:
                time.sleep(SCROLL_INTERVAL)
                if not self._scroll_pending:
                    self._scroll_pending = True
                    self.post(self._scroll_step, "auto-scroll")
        finally:
            self._scrolling = False

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
        if drag.generation != self._monitor.check() or self._proven != drag.generation:
            self._drop_refused()
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
