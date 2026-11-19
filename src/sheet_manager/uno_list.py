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
of them from other threads, without its solar mutex (#269), or in the middle of a change. The
exceptions here are the drag gesture's own checks (#264) and the mouse handlers, which read the
tree, the sheet handles and the document, and write a refused release's picks back, through
calls that lock for themselves, so that a gesture is decided and shown at once (`SheetList`,
#269). Both run without the solar mutex, so they read the structure monitor's generation but
never check the monitor, whose update needs that mutex (#284).

The tree. The list is a borderless `TreeControl`, so that it is a direct child of the panel
window, with a hidden root. With a hidden root, the tree peer mishandles every data-model change
event and re-parents all rows under the root, so nodes are never changed in place: a refresh
builds a new data model and restores the selection, scroll position, and keyboard cursor.
`uno_rows` paints the rows.

Colours (#141). `uno_theme` reads Calc's resolved document background and applies a readable
palette to the tree's native labels and row decorations. The tab observer's visible-view sample
(`uno_tabs`) updates it behind the same input, lock and replay barriers; no colour listener or
timer is added.

Refresh. Refreshing reads every sheet and rebuilds the tree on the main thread, so it is
rate-limited and retried after a failure (`refresh_schedule`); only a successful refresh marks the
list current. Rows can therefore be out of date when the user acts on them, so every action checks
its sheets when it runs, never against the cached rows. A drop plans against the snapshot of the
drag's start through `apply_order`, which refuses stale state, and is refused when the generation
moved during the drag.

Failed tree writes (#257, #265). Writing the picks takes several native calls, and one can fail
after others changed the tree, which then shows part of the write, or before any did, which
leaves the tree without the picks the user just chose. From a write's first call until the tree
shows the picks, `_shown` is None, and a failure leaves it so; a rebuild's new model, which
shows nothing selected, starts that state while there are picks to write. While it is None the
queued intake takes no native selection and commands act on no picks. The next intake settles
it (`_settle_shown`): if the tree shows exactly the picks, the record is known again. Anything
else may be part of a write or a selection made since, such as through accessibility, which the
list cannot tell apart, so it drops the picks, with the clearing notice, and queues a write that
clears the tree: restoring the picks could replace the user's latest selection, and taking the
rows could act on a sheet nobody picked. A refresh writes after its tab baseline, and a write
outside a refresh is retried as a failed refresh is (`RefreshSchedule.failed`). A write that can
leave only the picks or an empty tree, a repeated write of the one pick the tree shows or a
clear of a tree that shows nothing, keeps `_shown`. A refresh that loses the identity proof
while the tree shows a native selection the intake has not taken treats it the same way, with
the clearing notice: it was made against rows whose handles no longer prove their sheets. So
does a refresh whose new model replaced such a selection and that fails before showing it again
in full: the picks it superseded are dropped, and a queued write clears the rows the tree still
shows, as settling does. Until a write shows the picks again, toggles are held (below). Rows,
their handles and their proof change together once a new data model is shown, so a row of a
refused model still maps to the handle it was read with; and a rebuild does not need the cached
nodes, which LibreOffice rejects after a setter installed its model and then failed, for its
scroll position. A failed `invalidate` after a complete write is not retried: the tree and
`_shown` agree, and the next write repaints. No native trigger for these failures is known;
LibreOffice's tree calls have failed only while the control was being disposed.

Toggles (#288). A Ctrl+click toggles its row in the tree as soon as LibreOffice handles the
press, and the list's mouse listener, which VCL runs later from its queue (#269), toggles the
same row in the picks; Ctrl+Space toggles the cursor's row as the user sees it. Each is right
only while the tree shows the picks. Dropping picks, which a refresh does without any failure
when it loses the identity proof or finds a picked sheet renamed by another window, or a write
that leaves `_shown` None, breaks that for every press handled natively until the tree shows
the picks again, and its listener may still be queued: toggling then against the dropped picks
picked the row the user had just deselected. The list cannot see when a press was handled, but
the queue bounds it: a listener runs before any work posted after its press. It may also run
before work posted earlier, since VCL adds a window's listener call to that window's callback
event while one is queued (`VCLXWindowImpl::callBackAsync`). So each such change holds toggles
(`_hold_toggles`), and only work posted once the tree shows exactly the picks ends the hold
(`_toggles_shown`): a complete write, a rebuild's new model while nothing is picked, an
intake's take, or a settled record. The listener of every press handled before then runs held,
and so may one that runs early, which costs a toggle but cannot invert one. While the hold
lasts, a Ctrl press without Shift and Space pick nothing and drop any picks left, with the
notice: those a failed write left, or that a press that does not toggle, or a key, picked after
the drop. Keeping them could keep a row the user saw selected and toggled off. They ask for the
write, and a press moves the cursor and the anchor to its row, as a toggle does. Rules on state
cannot do this: a refresh between the native toggle and its listener can drop the picks and
write the empty tree, leaving the record known before the listener runs, and settling over a
tree the toggle emptied knows it at once. A plain or Shift press sets the picks rather than
toggling a row, so a drop cannot invert it. Each hold is a new token, so that a release posted
for an earlier one does not end it. A hold adds no native call: it and its release are posted
work, and the write a held toggle asks for is the one any toggle asks for.

Pointer input. A left press picks at once and keeps the pressed sheet's handle. A plain press
on a picked row keeps the other picks, so that they can be dragged together; its release in the
same row narrows the picks to that sheet, and only the release of a double click's second press
activates it. Both act only on the pressed sheet, still in that row (#28). If a refresh during
the press moved the sheet or showed another under its name, the release has no effect at all:
the list writes its own refs back, whatever the tree selected on release, so a newer pick made
meanwhile, by following Calc or by keyboard, stays.
While a press is held, a refresh does not take the tree's selection as the user's; the press and
release handlers do. A selected row's native release can move the tree's cursor before the
queued mouse listener runs, so refusing that gesture also restores a surviving picked cursor,
preferring its original sheet, and keeps newer picks. An unpicked cursor moved during an invalid
held gesture is deliberately not kept, and the known-issues guide records that limit (#71): the
supported toolkit and controller interfaces offer no sidebar pre-release hook.

Rows under the pointer (#293). The tree handles a press on the rows it shows then, but the mouse
listener, which VCL runs later from its queue (#269), maps the event's position to a row as the
list shows it when the listener runs. A rebuild in between that changes a row's name, as a move,
an insertion, a deletion or a rename elsewhere does, or that may not keep the scroll position,
can put another sheet at that position: the listener then picked, toggled, activated or targeted
a menu at a sheet the user never pressed. By the queue order that toggles rely on (above), such a
rebuild holds presses (`_hold_presses`) from before it shows its model, and posts the end of the
hold as it returns (`_release_presses`): every listener whose press was handled before then runs
held, and so may one that VCL runs early, which costs that press. A held press counts as one
outside the rows: it reads no geometry, a left press picks nothing and drops the picks, which its
native effect superseded in the tree, with the notice, its release does nothing, and a right
press opens no menu. The list cannot tell a rename in place from another sheet moved into the row
without reading the handles again, so a rename holds presses too. A refresh that keeps each row's
name moves nothing under the pointer, even when it loses the identity proof: the press then acts
on the sheet under that name, as a press after the refresh would, and a drop of picks there holds
toggles (above).

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

Accessibility (#83). The tree's accessible name names the sheet Calc shows (`list_name`), from the
refreshed rows that paint the arrow and never from the picks. It is set through the toolkit's
`AccessibleName` window property only when it changes, which raises `NAME_CHANGED`. Rows keep
the plain name and textual states: measured with 26.8.1.1 and 26.8.2.2, UNO offers no per-row
description, state or relation setter, toolkit has no `AccessibleDescription`, and `HelpText` is
only a tooltip. Native selection made without an owned handler, such as through
`XAccessibleSelection`, waits for the queued intake; a refresh that rebuilds the rows first shows
that selection again (`_show_native`) under the proof, drop count and order the intake checks,
so the intake still decides, and one that keeps the rows does not write the picks over it. A
refresh that loses the proof clears it instead (#265, above), and one that fails before showing it
again drops the picks it replaced (#257, above). The panel window lists the move buttons, the tree
and the shown footer labels as its accessible children in creation order, which is their visual
order, so create them in that order (#133, `uno_panel`).

Following Calc's tabs and sidebar visibility (`uno_tabs`). The tab observer samples Calc's tab
selection, which has no reliable change notification, and the list follows a change only when no
newer list input or pending native pick exists. Owned input raises the list's input count and
calls `TabObserver.note_input`, which only posts the acknowledgement of Calc's preceding state.

Notices and focus. Clearing a pick the user made shows a panel notice for `NOTICE_SECONDS`
(`uno_status`); invalidating only the cursor, the anchor, or a press is silent. Never time out a
native infobar instead: its removal can move focus to the sheet. The notice uses the existing
main-thread timer, with a token rejecting a stale queued timeout after renewal or disposal. The
list moves Tab and Shift+Tab focus itself, between its controls and, past either end, to the
frame's component window: native sidebar traversal alone neither reaches these child peers nor
leaves them reliably. Posted focus requests are refused when focus or the active frame moved.

Window activation (#211). Calc's undo of the list's changes needs this window's view as its
current one (#108), which follows LibreOffice's frame activation. LibreOffice can leave the frame
of the focused window inactive: then real clicks in the list and Calc's own dialogs, such as Tab
Color, left it so (26.8.2.2 gtk3), and moves refused while their controls stayed disabled. Every
press, owned key and move request in the panel therefore posts one `claim_window`, which runs
ahead of the input's own posted work and activates the frame if it is inactive, as a window
activation does. Enablement does not depend on activation; the moves' preflight does.

Saving from the list (#23). With gtk3, a save moves the focus from every sidebar control to the
sheet while it stores, Calc's own panels included (measured with 26.8.1.1 and 26.8.2.2; gen keeps
it). A save or Save As forwarded from the list therefore runs synchronously, returning after any
dialog it opened has closed, and a posted request then focuses the panel's own window and the
control that had the focus. A focus request to the control alone has no effect after the save. The
request is dropped after newer list input, and while another window or a dialog is active; no
window is reported active until the document window has the focus again after a native gtk3 dialog,
and the request takes effect then.
`uno_moves` states the move buttons' rules, which `_update_moves` and `travel_focus` here, and
`uno_keys` and `keys.move_action`, carry out.
"""

import contextlib
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

import uno
import unohelper
from com.sun.star.accessibility import XAccessibleEventListener
from com.sun.star.awt import XFocusListener, XMouseListener, XPaintListener
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
    keeps_focus,
)
from sheet_manager.refresh_schedule import RefreshSchedule
from sheet_manager.rename import Batch
from sheet_manager.reorder import Action, plan_move
from sheet_manager.selection import Ref, Selection, structure_kept
from sheet_manager.sheet_list import RowGeometry, SheetRow, list_name, ordered, row_label
from sheet_manager.uno_calc import (
    Later,
    MainThread,
    dispatch,
    prop,
    query_command,
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
    REPLAY_WAIT,
    REPLAY_WAITS,
    Availability,
    Snapshot,
    apply_order,
    is_current,
    is_current_as_reported,
    move_availability,
    plan_availability,
    snapshot,
)
from sheet_manager.uno_rows import RowPaint
from sheet_manager.uno_show import show_sheets
from sheet_manager.uno_status import CalcStatus
from sheet_manager.uno_structure import monitor_for
from sheet_manager.uno_tabs import TabObserver
from sheet_manager.uno_theme import ListTheme

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
SCROLL_INTERVAL = 0.1
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
    """The coordinator of one panel's sheet list: its controls, picks, input and actions.

    Threads. Listener callbacks only record state or post work through `MainThread`, with the
    two exceptions below; everything else runs on LibreOffice's main thread, and posted work
    re-checks what it relies on. The modify listener reaches the refresh schedule on the
    notifying thread (`document_modified`, `RefreshSchedule.changed`), and toolkit listeners
    reach the tab observer only through `TabObserver.note_input`.

    VCL runs the mouse listeners on the main thread, from one user event it posts after its own
    input handling, but releases the solar mutex around them (`VCLXWindow`'s callback queue;
    measured with gtk3 and gen in 26.2.1.2 and 26.8.2.2). The mouse handlers still read the
    tree's geometry, the retained handles and the document, so that a release decides at once
    whether its gesture stands, and a refused release writes the picks back to the tree and
    buttons before later work reads them. Each of these calls locks for itself (checked in the
    26.8.2.2 sources). The tree's and buttons' toolkit methods, the handles' `getName` and, on a
    refused release, the permission getters in `uno_reorder.move_availability` take the mutex;
    the undo-steps setting that `move_availability` also reads is configuration, which has its
    own lock. Calc's tab getter takes no lock, so a double click posts its activation, as Enter
    does, with the generation its release verified (`_activate_pressed`, #269). Each call locks
    only itself, so another thread can change the document between them. The release therefore
    compares the press's generation with the structure monitor's `generation`, which every
    change's report moves, and never calls its `check()`, whose update relies on the mutex
    (`uno_structure`, #284). The work it posts, the selection flush and `_activate_pressed`,
    checks the monitor before anything acts on a handle.

    The drag gesture is the other exception: VCL calls its listener within its own mouse-move
    handling, rather than queued as the mouse listeners are, but also with the solar mutex
    released (`ImplHandleMouseEvent`'s `SolarMutexReleaser`, in the 26.2.1.2 and 26.8.2.2
    sources). `start_drag` starts the drag there, with the gesture's event as `startDrag`'s
    trigger. Before that it checks the picks (`_picks_at`), which can write the list's own tree
    and buttons as the mouse handlers do, the document's read-only and protection flags, and
    `uno_reorder.is_current_as_reported`, which reads the sheets and the retained handles. None
    of these reads Calc's view or tabs, and none checks the structure monitor: they compare its
    `generation` with the list's proof, as the release does (#284). What only a check finds,
    such as a lock held at that moment, the drop's posted `_move` finds before anything moves:
    it checks the monitor, and `apply_order` repeats the whole preflight. A drag on stale rows
    is refused and posts its refresh, whose tab sample must not run in the listener (#264).

    Collaborators, each owning its own state: `_refreshes` decides when to refresh
    (`refresh_schedule`), `_tabs` follows Calc's tabs and the sidebar (`uno_tabs`, for which this
    class is the `TabHost`), `_selection` holds the picks, cursor and anchor as identities
    (`selection`), and `_monitor` is the document's shared structure monitor (`uno_structure`).
    The menu, keys, move buttons, status line, palette and row painting have their own modules.

    Identity. `rows` and `_nodes` are the rows the tree shows and their nodes; `_handles` maps
    those rows' names to the handles they were read with, from the snapshot `_observed`. A
    rebuild changes them together once its data model is shown (`_prove`): a refused model leaves
    the old rows with the old handles and, after a lost proof, the old snapshot and proof, so that
    input on an old row never reaches the sheet that took its name since (#257). Actions check
    sheets again when they run. `_proven` is the structure generation the handles and picks were
    proved at; work that sees the monitor's generation elsewhere refreshes before trusting a
    handle. `_generation` counts the times the list dropped every pick, so that a drag or menu
    begun before a drop can tell.

    Input watermarks. `_input` counts owned input as the handlers see it; posted work captures it
    and yields to newer input. `_follow_input` is the count at which Calc reported a switch to
    follow, and `_activation_input` counts successful activations, which revoke older menu
    restoration.

    Barriers keep the list's own transient state from being taken as the user's. Each guards
    only the operations named here:

    - Native tree-selection intake (`_take_tree_selection`, also when a refresh or a tab sample
      defers it) waits while `_pointer_depth` (inside a mouse listener), `_press` (a held left
      press, voided by a drop of all picks), `_selection_write_pending` (a coalesced tree write
      is queued), `_context_target` (a right-click target) or `_menu_context` (an open or
      completing menu) holds. While `_shown` is None (the tree may show another selection than
      the picks: a write stopped partway, or a native selection outlived the identity proof it
      was made against), it takes nothing and settles the record instead (`_settle_shown`), at
      once even when deferring. Native cursor intake (`cursor_changed`) waits for the same, and
      also while `_restoring_cursor` (the list is writing the tree).
    - While `_shown` is still None after the intake, `_current_picks` returns no picks after
      writing them, and `queue_move` refuses: the user saw another selection. A refresh then
      writes the picks after its tab baseline, and `_write_outside_refresh` retries a write
      outside a refresh (#257). The pointer menu (`_open_menu` without refs) does not check
      `_shown`: the right press queues a write of the picks, which runs before the release opens
      the menu, so the menu targets the picks that write showed, or the pressed row. If that
      write fails partway, the menu still targets the picks, as before #257.
    - Toggles (`_toggles_held`, #288): from a drop of picks, or a failed write that leaves
      `_shown` None, until work posted once the tree shows exactly the picks has run, a Ctrl
      press's listener (`mouse_pressed`) and Ctrl+Space (`tree_key`) pick nothing, drop any
      picks left (`_toggle_held_off`) and ask for the write.
    - Presses (`_presses_held`, #293): from a rebuild that may show another sheet in a shown row
      until work posted as it returns has run, `mouse_pressed` maps no event to a row. A left
      press picks nothing and drops the picks, so its release does nothing, and a right press
      targets no menu.
    - Tab observation (`observation_paused`) waits while `_busy` (a move or rename runs),
      `_pointer_depth`, `_restoring_cursor`, `_press`, `_drag`, the menu's popup or
      `_menu_context` holds; the observer adds the document's locks and an own replay's view. A
      pending tree write alone does not pause it. Stamped input (input that raised `_input` and
      posted an acknowledgement through `TabObserver.note_input`) keeps a sample from following
      Calc state older than that input; a write queued without it, such as one after a mouse
      release with no retained press, has no such protection, so a changed tab selection can be
      followed while that write is pending.
    - `_activating` (the list's own `setActiveSheet`) makes Calc's report of that switch the
      list's own, so it is not followed. `_busy` also defers timed refreshes and refuses moves
      and drags.

    Disposal. `dispose` closes the posting queue, the refresh schedule and the tab observer
    first, then `_cleanup` releases the listeners and controls in reverse creation order.
    Closing the queue does not revoke work already queued, which runs after `dispose` or, if a
    native release dispatches events, during it; so each part checks its own disposal when such
    work runs. The list's own work then returns before it touches the document or a control, a
    menu command chosen before the close included (#282, #285). A shortcut forwarded from the
    list is the user's input to the window rather than the list's work: it still runs while the
    frame shows the list's view, and is dropped once the document has closed or reloaded
    (`_forward`). A failed construction disposes what it had created.
    """

    def __init__(self, context, frame, parent_window):
        self._disposed = False
        self._main = MainThread(context)
        self._refreshes = RefreshSchedule(self._main.later, self._timed_refresh)
        self._notice_timer: Later | None = None
        self._notice_token: object | None = None
        self._scroll = 0
        self._keys_registered = False
        self._restoring_cursor = False
        self._cleanup = contextlib.ExitStack()
        self._status: CalcStatus | None = None
        self._moves: MoveButtons | None = None
        self._theme: ListTheme | None = None
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
        self._panel_window = parent_window
        self.rows: list[SheetRow] = []
        self._observed: Snapshot | None = None
        self._handles: dict[str, Any] = {}
        self._nodes: list[object] = []
        # The list's own picks and keyboard cursor, as sheet identities (selection.py).
        # `_shown` is the selection last written to the tree or adopted from accessibility, or
        # None while the tree may show another (#257, #265; see Barriers in the class docstring).
        # Owned pointer and keyboard gestures share a retained range anchor.
        self._selection = Selection(_current)
        self._shown: tuple[str, ...] | None = ()
        # While set, toggles pick nothing: the tree may not have shown the picks when the user
        # toggled a row (#288; `_hold_toggles`). `_toggles_release` is the hold whose end is
        # posted.
        self._toggles_held: object | None = None
        self._toggles_release: object | None = None
        # While set, a mouse listener does not map its event to a row: a rebuild may have put
        # another sheet there since the tree handled the press (#293; `_hold_presses`).
        # `_presses_release` is the hold whose end is posted.
        self._presses_held: object | None = None
        self._presses_release: object | None = None
        # A sheet that may have been inserted or deleted since the picks were proved makes
        # every retained handle suspect (selection.py, structure.py), and the list then drops
        # its picks; `_generation` counts the drops, so that a drag or an open menu started
        # before one can tell.
        self._generation = 0
        self._user_picks = False  # Whether the picks came from the user rather than from Calc.
        self._busy = False
        self._claim_pending = False  # A posted activation of this window (`claim_window`).
        self._menu = SheetMenu(context, frame, self.document, self.controller)
        self._keys = ListKeyHandler(self, Shortcuts(context, self.document))
        # Counts the user's own input in the list, as the list's mouse and key handlers see
        # it. A request to follow Calc's selection remembers the count when Calc reported the
        # switch; newer input in the list wins over it.
        self._input = 0
        self._activation_input = 0  # A newer successful activation revokes old menu restoration.
        # Before any control or listener, so that all input finds it; `dispose` disposes it
        # before releasing them.
        self._tabs = TabObserver(
            self._main,
            frame,
            self.controller,
            self.document,
            self._monitor,
            selected_tabs_method(context),
            self,
            self._proven,
        )
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
        self._viewed_name: str | None = None  # The tree's accessible name, once set.
        self._drag: _Drag | None = None
        self._gap: int | None = None
        self._pointer_y = 0
        self._scroll = 0
        self._scrolling = False  # Whether the auto-scroll thread runs.
        self._scroll_pending = False
        self._type_ahead = TypeAhead()

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
        # The panel lists its children in creation order, which assistive technology follows:
        # the buttons above the list come first, the footer below it last (#133).
        self._moves = MoveButtons(
            context, parent_window, self.queue_move, self._listeners["focus"], self.note_input
        )
        self._release_with(self._moves.dispose)
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
        self._theme = ListTheme(context, frame, self.tree)
        self._row_paint = RowPaint(self.peer, self.tree)
        self._row_height = self._row_paint.row_height()
        model.RowHeight = self._row_height

        self._status = CalcStatus(context, parent_window)
        self._release_with(self._status.dispose)
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
        self._tabs.start()

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
        self._refreshes.close()
        # Before the native release below: if that dispatches events, a tick or acknowledgement
        # already queued runs, and closing the queue does not revoke it. A failed construction
        # may not have created the observer yet.
        if hasattr(self, "_tabs"):
            self._tabs.dispose()
        self._notice_token = None
        if self._notice_timer is not None:
            self._notice_timer.cancel()
        self._cleanup.close()
        self._theme = None

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
        # A failed refresh leaves its changes pending and retries (`refresh_schedule`, #186).
        self._refreshes.measure(lambda: self._refresh(renamed or {}))

    def _refresh(self, renamed: Mapping[str, str]) -> None:
        """Read the sheets, drop every pick that is no longer its sheet, and show the rest.

        Picks, cursor, and anchor are revalidated on every refresh, whether or not the rows
        change: a refresh that only renews the handles behind unchanged rows must still drop a
        pick whose sheet was replaced under the same name (#28).
        """
        # Let queued owned input run first. A native selection still waiting for that intake,
        # such as one made through accessibility, is shown again after a rebuild (`_show_native`).
        pending = (
            tuple(self.selected_names())
            if self._press is None and self._take_tree_selection(defer=True)
            else None
        )
        order, drops, proof = tuple(self.names()), self._generation, self._proven
        previous = self._observed
        observed = snapshot(self.document)
        rows = read_rows(self.controller, observed)
        generation = self._monitor.check()
        if previous is None or self._identities_kept(previous, observed, generation, renamed):
            had = len(self._selection.picked)
            dropped = self._selection.carry(renamed)
            if len(self._selection.picked) != had:
                # A pick whose sheet no longer has its name went, as after another window
                # renamed it: toggles are held, as at every drop (#288).
                self._hold_toggles()
            # The same sheets as before: a retry after a failed rebuild starts from these names.
            self._observed = observed
        else:
            dropped = self._drop_all_picks(pending)
            if pending is not None or self._press is not None:
                # The tree's native selection was made against rows whose handles no longer
                # prove their sheets: no one's pick now, though the rows may read the same (#265).
                self._shown = None
        changed = rows != self.rows or not self._nodes
        reshowing = False
        try:
            if changed:
                self._rebuild(rows, observed, generation)
            else:
                self._prove(observed, generation)
            self._name_viewed()
            self._update_moves()
            self._tabs.refreshed(generation)
            # The queued intake checks the same proof, drops and order before taking a native
            # selection that waits for it.
            waiting = (
                pending is not None
                and self._generation == drops
                and generation == proof
                and tuple(self.names()) == order
            )
            # Writes that change only the selection come after the tab baseline, so that one
            # failing, such as the clear a stale native selection needs, costs the refresh
            # nothing else (#257). Kept rows still show a waiting selection: writing the picks
            # over it, as a pick order that differs from the rows' asks for, would replace the
            # user's latest selection with older picks.
            if (
                not changed
                and not waiting
                and (dropped or tuple(self._selection.names()) != self._shown)
            ):
                self._apply_selection()
            # Only a rebuild replaced it. `waiting` already implies `pending is not None`; that
            # clause only narrows the type.
            if changed and waiting and pending is not None:
                reshowing = True
                self._show_native(pending)
        except BaseException:
            if (
                pending is not None
                and self.rows is rows  # The new model is shown: the native selection is gone,
                and self._generation == drops
                and (not reshowing or self._shown is None)  # and not shown again in full.
            ):
                # The user's latest selection superseded the picks, which must not return (#257).
                # Rows the tree may still show are cleared by a queued write, as settling does
                # (`_settle_shown`): a toggle on one would otherwise pick a dropped pick again.
                self._drop_picks(native=bool(pending))
                self._shown = None
                self._queue_selection()
            if self._shown is None:
                self._hold_toggles()  # The tree may show part of a write (#288).
            raise

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

    def _prove(self, observed: Snapshot, generation: int) -> None:
        """Make `observed` the snapshot of the rows the tree shows, proved at `generation`.

        Only then do those rows' names look up its handles: a row must map to the handle it was
        read with, not to the sheet that took its name since (#257).
        """
        self._proven = generation
        self._observed = observed
        self._handles = dict(
            zip((sheet.name for sheet in observed.sheets), observed.handles, strict=True)
        )

    def _drop_all_picks(self, pending: tuple[str, ...] | None = None) -> bool:
        """Drop every pick, the cursor, the anchor, and a held press: none can be proved now.

        `pending` is the tree's selection when it differed from the record and the intake had
        not taken it yet: one the user made in the tree, such as through accessibility, or a
        press's native toggle whose listener is still queued. Rows it shows are cleared too, so
        the notice tells of them. Toggles are held while picks or such a selection go (#288).
        """
        if self._selection.picked or pending is not None:
            self._hold_toggles()
        self._tell_dropped(bool(pending))
        had = self._selection.clear()
        self._user_picks = False
        self._generation += 1
        if self._press is not None:
            self._press = replace(self._press, voided=True)
        return had

    def _drop_picks(self, native: bool) -> None:
        """Drop the picks when the tree may show a newer selection than them (#257).

        The cursor still proves its sheet and stays, as an intake leaves it, and a range now
        starts there. `native` is a selection the tree shows that the next write clears; the
        notice tells of it, as of dropped picks the user made. Toggles are held (#288).
        """
        self._hold_toggles()
        self._tell_dropped(native)
        self._selection.picked = []
        self._selection.anchor = self._selection.cursor
        self._user_picks = False
        self._generation += 1

    def _tell_dropped(self, native: bool) -> None:
        """Show the selection notice for the picks about to be dropped, if the user sees them go.

        That is when the user made them, rather than the list following Calc's tabs, or when
        `native` is a selection the user made in the tree that goes with them.
        """
        if (self._user_picks and self._selection.picked) or native:
            self.post(self._show_cleared_notice, "telling that the selection was cleared")

    def _hold_toggles(self) -> None:
        """Hold toggles until work posted once the tree shows the picks again has run (#288).

        The module docstring's Toggles section gives the rule and the queue order it rests on.
        Until the release that `_toggles_shown` posts has run, `mouse_pressed` and `tree_key`
        pick nothing for a toggle, drop any picks left (`_toggle_held_off`) and ask for the
        write. Each hold is a new token: a release posted for an earlier one does not end it.
        """
        self._toggles_held = object()

    def _toggles_shown(self) -> None:
        """The tree shows exactly the picks, as the list just wrote or confirmed them: post the
        end of a toggle hold, to run after every listener already queued (`_hold_toggles`)."""
        held = self._toggles_held
        if held is None or self._toggles_release is held:
            return
        self._toggles_release = held

        def release() -> None:
            if self._toggles_held is held:
                self._toggles_held = None

        self.post(release, "accepting toggles again")

    def _hold_presses(self) -> None:
        """Hold presses: a rebuild may show another sheet in a row the user pressed (#293).

        The module docstring's Pointer input section gives the rule. Until the release that
        `_release_presses` posts has run, `mouse_pressed` maps no event to a row. Each hold is a
        new token, so that the release of an earlier one does not end it.
        """
        self._presses_held = object()

    def _release_presses(self) -> None:
        """The rebuild is done: post the end of a press hold, to run after every listener whose
        press LibreOffice handled before now (`_hold_presses`)."""
        held = self._presses_held
        if held is None or self._presses_release is held:
            return

        def release() -> None:
            if self._presses_held is held:
                self._presses_held = None

        self.post(release, "accepting presses again")
        self._presses_release = held  # Once posted: a failed post is tried again by the next.

    def _toggle_held_off(self) -> None:
        """A toggle while toggles are held: drop the picks, if any, with the notice (#288).

        The user toggled a row of a tree that may not have shown the picks. Toggling the row
        could pick one the user saw selected and deselected; keeping the picks could keep one
        the user saw and deselected. Picks are left after a failed write, and after a drop when
        the listener of a press that does not toggle, or a key, picked rows before this toggle's
        listener ran. The list drops them, as settling does for a tree it cannot read
        (`_settle_shown`), so that a command refuses rather than acting on a set the user may
        not have seen.
        """
        if self._selection.picked:
            self._drop_picks(native=False)

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

    def _rebuild(self, rows: list[SheetRow], observed: Snapshot, generation: int) -> None:
        """Replace the whole data model with `rows`, read from `observed` at `generation`.

        With a hidden root, the tree control mishandles every change event of the data model:
        changing one node's text re-parents all rows under a newly shown root. So the list
        never changes nodes in place; it builds a new model and restores the selection, the
        scroll position, and keyboard cursor. The range anchor belongs to the selection model
        and survives while its sheet identity remains valid.

        The rows, their handles and their proof change together when the new model is shown: a
        refused model leaves the old rows with what they were read with (#257). A setter can
        also show the new model and then fail, leaving cached nodes that LibreOffice's
        `getNodeRect` rejects; the retry then rebuilds without keeping the scroll position.

        Unless every sheet keeps its row and the scroll position is kept, presses are held from
        before the new model is shown until work posted when this returns has run (#293).
        """
        try:
            top = self._first_visible_name()
        except Exception:
            report("reading the sheet list's scroll position")
            top = None
        # A shown row may show another sheet once this model is.
        remapped = bool(self._nodes) and (top is None or [r.name for r in rows] != self.names())
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
            if remapped:
                self._hold_presses()
            # Replacing the model focuses intermediate rows before the old cursor comes back.
            self.tree.getModel().DataModel = model
            self._nodes, self.rows = nodes, rows
            self._prove(observed, generation)
            # The new model shows nothing selected, so the record is unknown until the picks
            # are written: a failed first call must not leave picks the tree does not show.
            # Without picks it shows exactly them already, which ends a toggle hold (#288).
            if self._selection.picked:
                self._shown = None
            else:
                self._shown = ()
                self._toggles_shown()
            names = self.names()
            if top in names and nodes:
                try:
                    # Scroll to the end first, so that showing the old top row puts it at the top.
                    self.tree.makeNodeVisible(nodes[-1])
                    self.tree.makeNodeVisible(nodes[names.index(top)])
                except BaseException:
                    self._hold_presses()  # The rows may now show at another scroll position.
                    raise
            self._apply_selection()
        finally:
            self._restoring_cursor = restoring
            self._release_presses()

    def _show_native(self, names: tuple[str, ...]) -> None:
        """Show a native selection that awaits intake again over rebuilt rows, keeping the cursor.

        Only the queued intake adopts it, after its own checks (`_take_tree_selection`). From
        the first call until that selection is shown, `_shown` is None, so a failure, even of
        the first read, leaves the record unknown: the tree then shows the list's picks or part
        of that selection, neither of them what the user selected last (`_refresh`).
        """
        restoring, shown, written = self._restoring_cursor, self._shown, False
        self._restoring_cursor, self._shown = True, None
        try:
            written = tuple(self.selected_names()) != names
            if written:
                self.tree.clearSelection()  # Keeps the cursor where it is.
                for index, name in enumerate(self.names()):
                    if name in names:
                        self.tree.addSelection(self._nodes[index])
            self._shown = shown
        finally:
            self._restoring_cursor = restoring
        if written:
            self.peer.invalidate(0)

    def _name_viewed(self) -> None:
        """Name the tree after the sheet Calc shows, which the painted arrow marks (#83)."""
        name = list_name(next((row.name for row in self.rows if row.active), None))
        if name != self._viewed_name:
            self._viewed_name = name
            self.peer.setProperty("AccessibleName", name)

    def _select(self, names: list[str], cursor: str | None = None) -> None:
        """Pick these rows as they show now and put the keyboard cursor on `cursor`."""
        self._selection.take(names, self._handles, self.names())
        self._selection.cursor = self._ref(cursor)
        self._selection.anchor = self._selection.cursor
        self._show_selection()

    def _show_selection(self) -> None:
        """Write the list's selection outside a refresh (`_apply_selection`)."""
        self._write_outside_refresh(self._apply_selection)

    def _write_outside_refresh(self, write: Callable[[], None]) -> None:
        """Run a selection write outside a refresh, retrying one that may have stopped partway.

        A failed write that left `_shown` None is retried as a failed refresh is, so that the
        tree does not wait for the next input to be written again (#257), and holds toggles
        until a write shows the picks (#288).
        """
        try:
            write()
        except BaseException:
            if self._shown is None:
                self._hold_toggles()
                self._refreshes.failed()
            raise

    def _apply_selection(self) -> None:
        """Write the list's own picks and cursor to the tree; the cursor falls back to a pick.

        The write takes several native calls, and one can fail after others changed the tree.
        From the first call to the last selection call `_shown` is None, so a failure leaves it
        None: the tree may show part of the write, or none of it, which the intake must not take
        (#257). A repeated write of the one pick the tree shows, and a clear of a tree that
        shows nothing, keep it: a failure there can leave only that pick or nothing.
        """
        names = self.names()
        cursor = self._selection.cursor
        if cursor is None or cursor.name not in names:
            cursor = self._selection.picked[0] if self._selection.picked else None
            self._selection.cursor = cursor
        wanted = {ref.name for ref in self._selection.picked}
        indices = [index for index, name in enumerate(names) if name in wanted]
        shown = tuple(names[index] for index in indices)
        self._update_moves()
        if cursor is None:
            if self._shown != ():
                self._shown = None  # A failed clear can leave rows that are no picks now.
            self.tree.clearSelection()
            self._shown = ()
            self._toggles_shown()
            return
        only = shown == (cursor.name,)  # Selecting the cursor's row then shows every pick.
        self._move_tree_cursor(
            names.index(cursor.name), scroll=False, shown=shown if only else None
        )
        if cursor.name not in wanted:
            self.tree.clearSelection()  # Keeps the cursor where it is.
        for index in indices:
            if names[index] != cursor.name:
                self.tree.addSelection(self._nodes[index])
        self._shown = shown
        self._toggles_shown()
        self.peer.invalidate(0)  # A failed repaint leaves a complete write: the next one paints.

    def _take_tree_selection(self, paint: bool = True, *, defer: bool = False) -> bool:
        """Take native picks, deferring observations until queued owned input has run.

        Nothing is taken while `_shown` is None: the list cannot tell which of the tree's
        selected rows the user chose, so it settles the record instead (#257, #265).
        """
        if (
            self._pointer_depth
            or self._selection_write_pending
            or self._press is not None
            or self._context_target is not None
            or self._menu_context
        ):
            return False
        names = self.selected_names()
        if self._shown is None:
            self._settle_shown(names)
            return False
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
            self._toggles_shown()  # The tree shows exactly the picks it just gave (#288).
            self._user_picks = True
            if paint:
                self.peer.invalidate(0)
                self._update_moves()
            return True
        return False

    def _settle_shown(self, names: list[str]) -> None:
        """Settle an unknown record (`_shown` is None) from the tree's selected rows `names`.

        If they are exactly the picks, the tree shows them and the record is known again.
        Anything else can be part of a write or a selection made since, such as through
        accessibility, and the list cannot tell the two apart: restoring the picks could replace
        the user's latest selection, and taking the rows could pick a sheet the user never
        chose. So the picks are dropped, with the notice (#257). A tree that then shows nothing
        shows exactly the picks. Rows it still shows are cleared by a queued write, as a key's
        is, rather than left until a later one: a Ctrl+click on such a row would otherwise pick
        the sheet the user saw selected and meant to deselect. The record stays unknown until
        that write. With no picks left, as after an earlier drop, only the write is due.
        """
        wanted = {ref.name for ref in self._selection.picked}
        if tuple(names) != tuple(name for name in self.names() if name in wanted):
            if self._selection.picked:
                self._drop_picks(native=bool(names))
            if names:
                self._queue_selection()
                return
        self._shown = tuple(names)
        self._toggles_shown()

    def _current_picks(self) -> list[Ref]:
        """The list's picks as they stand now, each still the sheet it was picked as.

        None while a sheet insertion or deletion has not been through a refresh yet: the
        refresh this asks for decides what can still be proved. None, too, while the tree may
        show another selection than the picks after the intake (`_shown` is None, as while a
        press is held): the user saw that, so this writes the picks and leaves them to the next
        command (#257).
        """
        return self._picks_at(self._monitor.check())

    def _picks_at(self, generation: int) -> list[Ref]:
        """`_current_picks`, with the structure generation its caller read.

        Posted work passes the monitor's `check()`. The drag gesture runs without the solar
        mutex that the check needs, so it passes the reported `generation` (#284).
        """
        if generation != self._proven:
            self.post(self.refresh, "refreshing the sheet list")
            return []
        if self._press is None:
            self._take_tree_selection()
        unknown = self._shown is None
        if self._selection.revalidate() or tuple(self._selection.names()) != self._shown:
            self._show_selection()
        return [] if unknown else list(self._selection.picked)

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
        name = self.rows[index].name
        ref = self._ref(name)
        self._selection.picked = [ref] if ref is not None else []
        self._selection.cursor = ref
        self._selection.anchor = ref
        self._user_picks = True
        self._write_outside_refresh(lambda: self._move_tree_cursor(index, scroll, shown=(name,)))

    def _move_tree_cursor(
        self, index: int, scroll: bool = True, shown: tuple[str, ...] | None = None
    ) -> None:
        """Select only this row in the tree, which moves its keyboard cursor there too.

        The tree control has no cursor setter, but in single selection mode selecting a row also
        moves the cursor, so arrow keys continue from the row selected here. From its first call
        on, `_shown` is None until the caller's write is complete (`_apply_selection`): even a
        failure that changed nothing leaves the tree without the picks the user just chose.
        `shown`, given when this row is the only pick, completes the write as soon as `select`
        returns (#257). If the tree already shows exactly `shown`, a failed call can leave only
        that row or none, neither of them another sheet, so `_shown` stays.
        """
        if shown is None or shown != self._shown:
            self._shown = None
        model = self.tree.getModel()
        model.SelectionType = SINGLE
        try:
            self.tree.select(self._nodes[index])
            if shown is not None:
                self._shown = shown
                self._toggles_shown()
        finally:
            model.SelectionType = MULTI
        if scroll:
            self.tree.makeNodeVisible(self._nodes[index])

    def tree_key(self, code: int, modifiers: int) -> None:
        """Record owned selection keys synchronously, so held keys accumulate before painting."""
        self._input += 1
        self._tabs.note_input()
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
            if self._toggles_held is not None:
                # The tree may not show the picks, as after a drop until its write, or after a
                # failed write. The user toggles what the tree shows, which the list cannot
                # tell: toggling the cursor's row on could pick a row the user saw selected and
                # meant to deselect, and keeping it could keep one (#257, #288). The key drops
                # any picks and asks for the write; a toggle after it acts on the tree it leaves.
                self._toggle_held_off()
                self._queue_selection(scroll=True)
                return
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
        if self._disposed:
            return  # Queued by a click or key; the tree is closed, the monitor maybe too (#285).
        if self._pointer_depth:
            self._selection_write_pending = False  # The listener posts again after its work.
            return
        try:
            if self._monitor.check() != self._proven:
                self.refresh()
            else:
                self._selection.revalidate()
                self._show_selection()
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
        self._tabs.remember(
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

        It reads Calc's tabs, so it runs only in posted work, which Enter and a double click
        queue, and does nothing once the list is disposed (#269).
        """
        if self._disposed:
            return
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
        self._tabs.note_input()

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
        """Activate the single pick: Enter's work, which `queue_input` posts (`uno_keys`)."""
        if self._disposed:
            return  # The picks' checks read the disposed tree and maybe a detached monitor (#282).
        picked = self._current_picks()
        if len(picked) == 1:
            self.activate(picked[0].name, picked[0].token)

    def type_ahead(self, char: str) -> None:
        if self._disposed:
            return  # Queued by a key; it writes the tree, which is closed now (#282).
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

    def document_modified(self) -> None:
        """Refresh once changes pause, or at the latest after a bounded wait.

        The structure monitor notes insertions and deletions itself, as they happen.
        """
        if not self._disposed:
            self._refreshes.changed()

    def active_sheet_event(self) -> None:
        """Calc reports a sheet switch; the list handles it after the events already queued.

        Whether the list made the switch itself, and how much input the list had seen, are
        noted now, without calling back into Calc. The list's mouse handlers also run after
        the tree has handled the input, so a click's switch can be handled after a later click
        has reached the list; counting the input now keeps that click newer (#44).
        """
        seen = self._input
        own = self._activating
        # Calc activates the sheets an Undo or Redo moves back; during an own move's replay and
        # the restoration after it, the switch belongs to the replay (`structure`, #91).
        replay = self._monitor.events.viewing_replay()
        self.post(lambda: self.active_sheet_changed(own, seen, replay), "following a sheet switch")

    def active_sheet_changed(
        self, own: bool, seen: int, replay: int | None = None, waits: int = 0
    ) -> None:
        """Show the new active sheet, at once unless refreshes are being rate-limited.

        A switch the list made itself needs no following: the list already shows the sheet
        the user clicked or chose. Neither does one made by a proved replay of an own move or
        by the restoration of the view after it, which puts back the sheet the user had. Other
        switches make the list follow Calc's selection, unless the user has used the list since
        the switch (`seen`).
        """
        if self._disposed:
            return
        events = self._monitor.events
        if replay is not None and not events.replay_settled(replay) and waits < REPLAY_WAITS:
            # Posted work can run before the replay's undo notification (`uno_reorder`).
            self._main.later(
                REPLAY_WAIT,
                lambda: self.active_sheet_changed(own, seen, replay, waits + 1),
                "following a sheet switch",
            )
            return
        if not own and not events.replay_proven(replay):
            self._follow_input = seen
        if self._refreshes.activated(self._busy):
            self._run_refresh()

    def _timed_refresh(self) -> None:
        """A scheduled refresh is due while changes are unshown (`RefreshSchedule`)."""
        if self._disposed:
            return
        if self._monitor.events.replay is not None:
            # The main loop can run during Calc's replay of an Undo; a check now would end an
            # own move's proof (#91). Refresh after it.
            self._refreshes.schedule(REPLAY_WAIT)
            return
        wait = self._refreshes.wait()
        if wait > 0:
            self._refreshes.schedule(wait)
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

    # Input stamps and the window claim

    def note_input(self) -> None:
        """Stamp native control input before its queued action can use the picks."""
        self._input += 1
        self._tabs.note_input()
        self.claim_window()

    def claim_window(self) -> None:
        """Post making this window Calc's active one, ahead of the input's own posted work.

        Input in the panel is the user working in this window. LibreOffice activates a frame
        when its window is activated, but after some window sequences it leaves the frame of a
        focused window inactive, and neither clicks in it nor Calc's own dialogs changed that
        (26.8.2.2 gtk3, #211). Calc's undo of the list's changes needs this frame's view
        (#108), so moves refuse an inactive frame; a drop already activates it.
        """
        if not self._claim_pending and not self._disposed:
            self._claim_pending = True
            self.post(self._activate_window, "activating the document's window")

    def _activate_window(self) -> None:
        self._claim_pending = False
        if self._disposed or self.frame.getController() != self.controller:
            return  # Reload replaced this controller; its panel owns the new one.
        if not self.frame.isActive():
            self.frame.activate()

    def queue_input(self, function, where: str) -> None:
        """Stamp a key's intent before an older observation can precede its queued action."""
        self.note_input()
        self.post(function, where)

    # Following Calc's tabs: the host side of `uno_tabs.TabHost`

    @property
    def input_count(self) -> int:
        return self._input

    @property
    def proven(self) -> int:
        return self._proven

    def observation_paused(self) -> bool:
        return (
            self._busy
            or bool(self._pointer_depth)
            or self._restoring_cursor
            or self._press is not None
            or self._drag is not None
            or self._menu.is_open
            or self._menu_context
        )

    def sheets_changed(self) -> None:
        if not self._refreshes.stale:
            self.document_modified()

    def pending_native_picks(self) -> bool:
        return self._take_tree_selection(paint=False, defer=True)

    def follow_tabs(self, tabs: list[str], active: str) -> None:
        self._select(tabs, active)
        self._user_picks = False

    def show_tabs(self, tabs: tuple[str, ...]) -> None:
        if self._status is not None and self._status.show_tabs(tabs):
            self.set_bounds(*self._bounds)

    def apply_palette(self) -> None:
        if self._theme is not None:
            self._theme.apply()

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
        self._tabs.note_input()
        self.claim_window()  # Also for activation without a press or key, such as through AT.
        # While the tree may show another selection than the picks (`_shown` is None), the user
        # saw that one: refuse, and let the refresh this asks for show the picks (#257).
        observed = self._observed if self._shown is not None else None
        picks, proof = tuple(self._selection.picked), self._proven
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
        if not keeps_focus(command):
            self.post(lambda: self._forward(command), "a shortcut")
            return
        # Called from the key handler: only note which control has the focus now.
        control = self.tree if self.owns_tree_keys() else self._focused_button()
        seen = self._input
        self.post(lambda: self._save_keeping_focus(command, control, seen), "a save shortcut")

    def _forward(self, command: str, arguments: tuple[Any, ...] = ()) -> bool:
        """Dispatch a shortcut typed in the list to the view it was typed in; True if it ran.

        The list may have closed since the key, and the shortcut still runs: it is the user's
        input to this window, which the list consumed. Once the frame shows another view or
        none, after the document closed or reloaded, it is dropped, as LibreOffice drops a
        shortcut it queued for a frame that closed meanwhile (`svt::AcceleratorExecute`,
        26.8.2.2). A closed frame has no controller and its `queryDispatch` raises
        `DisposedException`; a reloaded one resolves the command against the new document
        (measured with 26.8.1.1, #285).
        """
        try:
            if self.frame.getController() != self.controller:
                return False
            url, dispatcher = query_command(self.context, self.frame, command)
        except DisposedException:
            return False  # The frame is closing.
        if dispatcher is None:
            return False
        dispatcher.dispatch(url, arguments)
        return True

    def _focused_button(self):
        if self._moves is None:
            return None
        return next(
            (b for b in self._moves.buttons.values() if b.getPeer().hasFocus()),
            None,
        )

    def _save_keeping_focus(self, command: str, control, seen: int) -> None:
        """Save, then give the focus back to the control that had it (#23).

        Synchronous mode returns only when the save has finished, after any Save As, file
        format, or error dialog has closed. With the gtk3 interface, the save moves the focus
        from the panel to the sheet while it stores, as it does from Calc's own panels. The save
        runs as other forwarded shortcuts do, also after the list closed (`_forward`, #285);
        giving the focus back is the list's own work, which `post` refuses then.
        """
        if not self._forward(command, (prop("SynchronMode", True),)):
            return
        if control is not None:
            self.post(lambda: self._restore_focus(control, seen), "restoring focus after a save")

    def _restore_focus(self, control, seen: int) -> None:
        if self._disposed or self._input != seen or control.getPeer().hasFocus():
            return  # Newer list input decides where the focus goes.
        # After a native gtk3 dialog closes, no window is reported active until the document
        # window has the focus again; a focus request made meanwhile takes effect then.
        active = self.toolkit.getActiveTopWindow()
        if not self.frame.isActive() or active not in (None, self.frame.getContainerWindow()):
            return  # Another window or a dialog is active: leave it the focus.
        # With gtk3, the panel is a window of its own inside the sidebar: a control's focus
        # request alone has no effect after the save until that window has the focus again.
        self._panel_window.setFocus()
        if control is self.tree or control.getModel().Enabled:
            control.setFocus()
        else:
            self.tree.setFocus()

    # Mouse and menu

    def mouse_pressed(self, event) -> None:
        self._input += 1
        self._tabs.note_input()
        self.claim_window()
        # The tree handled this press before this listener runs (#269). While presses are held,
        # a rebuild since then may show another sheet at the event's position: the press is
        # taken as one outside the rows, which picks nothing and targets no menu (#293).
        held = self._presses_held is not None
        row = None if held else self.geometry().row_at(event.Y)
        if event.Buttons & RIGHT:
            self._press = None
            self._context_target = self._ref(self.rows[row].name) if row is not None else None
            self._context_generation = self._monitor.generation
            self._context_input = self._input
            self._queue_selection()
        elif event.Buttons & LEFT:
            self._context_target = None
            if held and self._selection.picked:
                # The press selected, toggled or extended rows of the tree as it showed them
                # then, which the list cannot read now. Keeping the picks could keep a row the
                # user deselected, as a held toggle could (#288): they go, with the notice.
                self._drop_picks(native=False)
                self._queue_selection()
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
                if self._toggles_held is not None and event.Modifiers & (SHIFT | MOD1) == MOD1:
                    # The tree toggled this row when the press happened, maybe against picks
                    # the list has dropped since or a tree that did not show them, so the list
                    # cannot tell which way (#288). It neither picks the row nor keeps picks
                    # the user may have toggled off: they go, with the notice. The cursor and
                    # the anchor move here, as a toggle's do, and the write shows the result.
                    self._toggle_held_off()
                    target = self._ref(name)
                    if target is not None:
                        self._selection.cursor = self._selection.anchor = target
                else:
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
        # Not `check()`: its update needs the solar mutex, which this listener runs without, and
        # the work posted below checks before anything acts on the pressed handle (#284).
        moved = press.generation != self._monitor.generation
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
            self._show_selection()
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
            # Activation reads Calc's tabs, which needs the lock this listener runs without (#269).
            name, handle, generation = press.name, press.handle, press.generation
            self.post(
                lambda: self._activate_pressed(name, handle, generation), "activating a sheet"
            )

    def _activate_pressed(self, name: str, handle: Any, generation: int) -> None:
        """Activate a double click's pressed sheet, posted by its release at `generation`.

        The release proved the pressed handle at that generation. `activate` alone compares the
        list's current proof, which work queued ahead of this one, such as the release's own
        selection flush, advances when it refreshes; meanwhile a deleted sheet's handle can have
        turned to another sheet that then took its name (#269).
        """
        if self._disposed:
            return  # The document's monitor may be detached too, and its check raises.
        if self._monitor.check() != generation:
            self.post(self.refresh, "refreshing the sheet list")
            return
        self.activate(name, handle)

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
        if self._disposed:
            return  # Queued by a key, as Enter's activation is (#282).
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
                # A list that closed after the popup runs no command, as one that closed during
                # it does (`uno_menu`, #63, #285); the menu's state still ends below.
                if not self._disposed:
                    self._menu_action(chosen, observed, refs, structure, unchanged)
            except DisposedException:
                self._tabs.stop()  # The view closed while its command ran.
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
            if not self._disposed and not self._tabs.stopped:
                # A command's result can still drop picks under the identity rules.
                self.refresh()
                self._selection.revalidate()
                self._show_selection()
        finally:
            self._activating = False
            self._menu_context = False
            self._context_target = None
            self._tabs.acknowledge()

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
            if not unchanged() or not is_current(self.document, observed):
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
        # Not `check()`: VCL fires the gesture without the solar mutex, which the check's update
        # needs. The drop's posted `_move` checks before anything moves (#284).
        proof = self._proven
        picked = [ref.name for ref in self._picks_at(self._monitor.generation)]
        if not picked or self.document.isReadonly() or self.document.isProtected():
            return
        if not is_current_as_reported(self.document, self._observed):
            # Refused. The refresh samples Calc's tabs, which never runs in a listener (#264).
            self.post(self.refresh, "refreshing the sheet list")
            return
        transferable = _Transferable(uuid.uuid4().hex)
        self._drag = _Drag(picked, self._observed, transferable, proof)
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
