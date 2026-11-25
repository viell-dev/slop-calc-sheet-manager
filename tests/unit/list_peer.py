"""The real `SheetList` refreshes, tree writes, intake, keys and Move to Top over a simulated peer.

The list's methods are loaded from `uno_list.py`'s source (`source_methods`) and run unchanged
without LibreOffice, together with the real `Selection`, `RefreshSchedule` and reorder planner.
The workbook, the tree, its peer and the posted-work queue are simulated, following what the list
relies on from Calc and the tree control:

- a deleted sheet's handle turns to the previous sheet (the next one at index 0) and follows it,
  and an insertion or a deletion moves the structure generation (`selection.py`), while a rename
  or a move does not;
- assigning a data model shows its nodes with nothing selected; `select` in single selection
  mode deselects every row and then selects that node, moving the cursor there, so a node
  outside the installed model raises with nothing selected (`TreeControlPeer::select` in
  26.8.2.2); `addSelection` and an assistive selection add a node without moving the cursor;
  `clearSelection` keeps the cursor; `getNodeRect` refuses a node outside the installed model,
  as LibreOffice documents;
- the tree handles presses and releases as VCL's selection engine does (`Tree.press` and
  `Tree.release`; `SelectionEngine::SelMouseButtonDown` and `SelMouseButtonUp`,
  `SvImpLBox::MouseButtonDown`, `SetCursor` and `SetAnchorSelection`, read in 26.8.3.1; add mode,
  the click counts and the range measured on #294). A plain press on a selected row changes
  nothing; its release, unless a drag began, then selects that row alone, at the press's position
  wherever the pointer is. A plain press on another row selects it alone, and no other release
  changes a selection. A Shift press without an anchor deselects every row, makes the anchor at
  the cursor and selects the range from there, and one with an anchor moves the range's end. A
  Ctrl press drops the anchor and toggles its row, or in add mode only moves the cursor to an
  unselected one. A Ctrl+Shift press starts add mode and moves the end of the range from the
  anchor, made at the cursor if there is none. Without a cursor, a press first puts it on the
  first row in view, as a paint does. The cursor's moves are announced inside the call that makes
  them, so the list hears of a press's before its listener runs, except in add mode, where a press
  that only moves the cursor announces nothing (heard with real input on #321). Deselecting every
  row, by `clearSelection`, by `select` before it selects or by a press, drops the anchor only if
  a row was selected (`SvImpLBox::SelAllDestrAnch`); assistive selections keep it. A model
  replaced while the engine has an anchor leaves the engine believing that it still does
  (`Tree.anchored`; `SvImpLBox::Clear`);
- the tree scrolls as `SvImpLBox` does (`MakeVisible`, `FillView` and `AdjustScrollBars`, read
  in 26.8.2.2) once a test sets how many rows fit (`Tree.visible`; by default every row fits and
  nothing scrolls): a new data model shows from its first row, `makeNodeVisible` leaves a row
  in view where it is and otherwise starts the view at that row, but no further down than the
  last rows fill the view, and a label longer than `Tree.wide` characters shows a horizontal
  scrollbar, which takes one row's height. `getNodeRect` gives a row's line in the view, in units
  of `Tree.height`, and `Tree.scroll_to` scrolls with no list call seeing it. By reading the same
  sources, the wheel and the scroll bar paint within their own handling (`DoScroll`,
  `ScrollUpDownHdl`, then `PaintImmediately`), so `wheel` runs the list's paint listener,
  `paint_rows`, at once; `MakeVisible`, `FillView` and a resize only invalidate, and VCL paints
  later, so `resize` and `scroll_unseen` do not paint and a test paints where VCL would (`paint`);
- every native call can be made to fail (`Faults`), before it has any effect. `select` can also
  fail once it has deselected the rows ("select cleared") or selected its row ("select done"),
  `clearSelection` and `addSelection` after their effect ("... done"), and the data model
  assignment after installing its model. No native trigger is known for these failures (#257);
  they test the list's own state, not LibreOffice's behaviour;
- the toolkit's selection listener, which the list counts with (#294), is notified once per row
  whose selection changes, synchronously inside the call that changes it, whoever makes it: an
  assistive selection, the native part of a click, or the list's own tree calls. Every change
  of `Tree.selected` notifies, so a test or probe that sets it directly is a native change. The
  second press of a double click changes nothing, as measured on #294.

Posted work runs on `run_queue`, and a failure there ends only that work and is recorded, as
LibreOffice's callback reports it. `queued_click` posts a click's mouse listeners there too, after
the tree has handled the press and behind all the work already posted, the latest place VCL gives
them (#269), so that work posted earlier, such as a refresh or the tab sample, runs between the
native press and the list's listener (#85, #288). `bind_drag` binds the real `start_drag`, with
the document's checks stubbed, so that a test can recognize a drag gesture between a press, which
`native_press` handles, and its listener, as VCL can within its handling of the motion (#264).
The refresh schedule's timers run on `retry`, which advances the fake clock. Move to Top runs
through `queue_move` and `_move_selection`; the reorder layer's `apply_order` is replaced by
`Book.apply`, which refuses a stale snapshot as `is_current` does and otherwise moves the planned
sheets.

The mouse handlers run through the list's own mouse listener, `_Mouse`, which is loaded from the
source with its guard, `_guarded` (`listen`). As in LibreOffice, a failure inside a handler ends
only that handler, and the listener still queues the selection write as it returns (#312), and
leaves a failed press undecided (#318). The
failure is recorded where `run_queue` records one, under the listener's name. So do the keys and
Move to Top: `key` and `type_key` run the list's key handler, `ListKeyHandler.keyPressed`, and
`move_to_top` its button's action listener, `MoveButtons.actionPerformed`, each loaded with its
guard from the current `uno_keys.py` and `uno_moves.py`, also for another revision of the list; a
failure there is recorded as "the key handler" or "a move button" (#320). Each guard records only
a simulated native failure: any other exception is a defect of the list or of a test, which
LibreOffice would report too, and it is raised.

The native checks are in `tests/integration` and `tests/ui`.
"""

import _thread
import ast
import enum
import functools
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import CodeType, SimpleNamespace
from typing import Any, cast

from sheet_manager.keys import (
    DOWN,
    END,
    HOME,
    PAGEDOWN,
    PAGEUP,
    SPACE,
    TAB,
    UP,
    A,
    KeyRoute,
    TypeAhead,
    button_route,
    find_prefix,
    move_action,
    route_key,
    unbound_route,
)
from sheet_manager.refresh_schedule import RefreshSchedule
from sheet_manager.reorder import Plan, plan_move
from sheet_manager.reorder import Sheet as Planned
from sheet_manager.selection import Ref, Selection, structure_kept
from sheet_manager.sheet_list import RowGeometry, SheetRow, list_name, ordered, row_label
from tests.unit import source_methods

SOURCE = "src/sheet_manager/uno_list.py"
# The key handler and the move buttons, always from these sources, also for another revision of
# the list.
KEYS = "src/sheet_manager/uno_keys.py"
MOVES = "src/sheet_manager/uno_moves.py"
LEFT, RIGHT, MIDDLE = 1, 2, 4  # Mouse buttons,
SHIFT, MOD1, MOD2 = 1, 2, 4  # and key modifiers, as UNO numbers them.
HIT_X, LABEL_X = 22, 40  # Where the rows' native hit area starts, and a point on the labels.
METHODS = (
    "names",
    "_ref",
    "refresh",
    "_refresh",
    "_renames_elsewhere",  # From #321's fix on; before it, the next one.
    "_identities_kept",
    "_prove",
    "_drop_all_picks",
    "_drop_picks",
    "_tell_dropped",
    "_hold_toggles",
    "_toggle_held",
    "_toggles_shown",
    "_toggle_held_off",
    "_hold_ranges",  # From #313's fix on, as is the next.
    "_ranges_shown",
    "_account_write",  # From #310's third round on, as are the next two.
    "_account",
    "_follow_engine",
    "_hold_presses",
    "_release_presses",
    "_rebuild",
    "_show_native",
    "_name_viewed",
    "_select",
    "_fallback_cursor",  # Only revisions from #71's fix until #327's.
    "_apply_selection",
    "_show_selection",
    "_write_outside_refresh",
    "_take_tree_selection",
    "_settle_shown",
    "_current_picks",
    "_picks_at",
    "geometry",
    "_first_visible_name",  # Only revisions before the second read of the position (#293).
    "_hold_if_scrolled",  # The second read of the position until #299 renamed it.
    "_note_rebuilt_position",  # From #299 on, as are the next four.
    "_hold_every_row",
    "_saw_position",
    "_note_position",
    "_show_row",
    "paint_rows",
    "open_menu_for_keyboard",
    "selected_names",
    "_focus_row",
    "_move_tree_cursor",
    "tree_key",
    "note_input",  # For the key handler, as is the next one.
    "queue_input",
    "_queue_selection",
    "_flush_selection",
    "_overtaken",  # From #307 on, as are the next three.
    "_read_tree",
    "_take_overtaken",
    "_unread",
    "cursor_changed",
    "tree_selection_changed",
    "type_ahead",
    "_timed_refresh",
    "_run_refresh",
    "queue_move",
    "_move_selection",
    "mouse_pressed",
    "mouse_released",
    "press_failed",  # From #318 on.
    "_pressed_sheet_in_place",
    "follow_tabs",
)


class NativeFailure(RuntimeError):
    """A native call that a test made fail."""


class Faults:
    """Native calls by name, each counted; `fail` makes one fail."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.armed: dict[
            str, list[int]
        ] = {}  # A call's name: [calls that succeed first, failures].
        self.nth: int | None = None  # Fail the native call with this index in `calls`, if set.
        self.failed: list[str] = []

    def fail(self, call: str, after: int = 0, times: int = 1) -> None:
        self.armed[call] = [after, times]

    def check(self, call: str) -> None:
        index = len(self.calls)
        self.calls.append(call)
        if self.nth == index:
            self.nth = None
            self.failed.append(call)
            raise NativeFailure(call)
        armed = self.armed.get(call)
        if armed is None:
            return
        if armed[0] > 0:
            armed[0] -= 1
            return
        armed[1] -= 1
        if not armed[1]:
            del self.armed[call]
        self.failed.append(call)
        raise NativeFailure(call)


@dataclass(eq=False)
class Sheet:
    name: str
    color: int | None = None
    protected: bool = False


class Handle:
    """A retained sheet handle: it follows its sheet, and turns to another when it is deleted."""

    def __init__(self, sheet: Sheet):
        self.sheet = sheet
        self.readable = True

    def getName(self) -> str:
        if not self.readable:
            raise NativeFailure("the handle could not be read")
        return self.sheet.name

    def getIsScenario(self) -> bool:
        return False


class Book:
    """A workbook's sheets, Calc's viewed sheet, the structure generation and the moves made."""

    RuntimeUID = "synthetic-book"

    def __init__(self, names: list[str]):
        self.sheets = [Sheet(name) for name in names]
        self._own = {id(sheet): Handle(sheet) for sheet in self.sheets}
        self._retained = list(self._own.values())
        self.active = self.sheets[0]
        self.generation = 0
        self.planned: list[str] = []  # The sheets the last planned move was asked to move,
        self.moved: list[list[str]] = []  # and those of each move made, in order.

    def names(self) -> list[str]:
        return [sheet.name for sheet in self.sheets]

    def handle(self, sheet: Sheet) -> Handle:
        return self._own[id(sheet)]

    def sheet(self, name: str) -> Sheet:
        return next(sheet for sheet in self.sheets if sheet.name == name)

    def rename(self, name: str, new: str) -> None:
        self.sheet(name).name = new

    def move(self, name: str, index: int) -> None:
        sheet = self.sheet(name)
        self.sheets.remove(sheet)
        self.sheets.insert(index, sheet)

    def delete(self, name: str) -> int:
        """Delete the sheet and return its index; Calc then shows the sheet its handle turned to."""
        index = self.sheets.index(self.sheet(name))
        deleted = self.sheets.pop(index)
        turned = self.sheets[index - 1] if index > 0 else self.sheets[0]
        for handle in self._retained:
            if handle.sheet is deleted:
                handle.sheet = turned
        del self._own[id(deleted)]
        if self.active is deleted:
            self.active = turned
        self.generation += 1
        return index

    def insert(self, name: str, index: int) -> Sheet:
        """Insert a new sheet at `index`; an insertion moves the structure generation."""
        inserted = Sheet(name)
        self.sheets.insert(index, inserted)
        self._own[id(inserted)] = Handle(inserted)
        self._retained.append(self._own[id(inserted)])
        self.generation += 1
        return inserted

    def replace(self, name: str) -> Sheet:
        """Delete the sheet and insert a different one under its name at the same place."""
        shown = self.active is self.sheet(name)
        index = self.delete(name)
        inserted = Sheet(name)
        self.sheets.insert(index, inserted)
        self._own[id(inserted)] = Handle(inserted)
        self._retained.append(self._own[id(inserted)])
        if shown:
            self.active = inserted
        self.generation += 1  # The insertion, after the deletion's.
        return inserted

    def snapshot(self) -> Any:
        return SimpleNamespace(
            sheets=tuple(Planned(sheet.name) for sheet in self.sheets),
            handles=tuple(self.handle(sheet) for sheet in self.sheets),
            generation=self.generation,
        )

    def rows(self) -> list[SheetRow]:
        return [
            SheetRow(
                sheet.name,
                active=sheet is self.active,
                protected=sheet.protected,
                color=sheet.color,
            )
            for sheet in self.sheets
        ]

    def apply(self, context: object, document: object, observed: Any, plan: Plan) -> Any:
        """Move as `uno_reorder.apply_order` does, refusing a snapshot `is_current` would."""
        current = (
            observed.generation == self.generation
            and [sheet.name for sheet in observed.sheets] == self.names()
            and all(
                handle.getName() == sheet.name
                for handle, sheet in zip(observed.handles, observed.sheets, strict=True)
            )
        )
        if not current:
            return SimpleNamespace(
                status="refused", message="The sheet list has changed. Check it and try again."
            )
        for move in plan.moves:
            self.move(move.name, move.index)
        self.moved.append(list(self.planned))
        return SimpleNamespace(status="done", message="Sheets moved.")

    def plan(self, sheets: Any, selected: Any, action: Any, gap: int | None = None) -> Plan:
        """The real planner, recording which sheets the command asked it to move."""
        self.planned = list(selected)
        return plan_move(sheets, self.planned, action, gap)


class Node:
    def __init__(self, faults: Faults, label: str):
        self._faults = faults
        self.label = label
        self._value: str | None = None
        self.children: list[Node] = []

    @property
    def DataValue(self) -> str | None:
        return self._value

    @DataValue.setter
    def DataValue(self, value: str) -> None:
        self._faults.check("DataValue")
        self._value = value

    def appendChild(self, node: "Node") -> None:
        self._faults.check("appendChild")
        self.children.append(node)


class NodeModel:
    """A `MutableTreeDataModel`."""

    def __init__(self, faults: Faults):
        self._faults = faults
        self.root: Node | None = None

    def createNode(self, label: str, expandable: bool) -> Node:
        self._faults.check("createNode")
        return Node(self._faults, label)

    def setRoot(self, root: Node) -> None:
        self._faults.check("setRoot")
        self.root = root


class ControlModel:
    """The tree control's model. Assigning `DataModel` shows the new nodes, none selected.

    A failure armed as "DataModel" refuses the model; one armed as "DataModel installed" shows it
    first and then fails, as a setter that installs and then raises would (#257, case 4).
    """

    def __init__(self, tree: "Tree"):
        self._tree = tree
        self._type = "MULTI"

    @property
    def SelectionType(self) -> str:
        return self._type

    @SelectionType.setter
    def SelectionType(self, value: str) -> None:
        self._tree.faults.check("SelectionType")
        self._type = value

    @property
    def DataModel(self) -> NodeModel | None:
        return self._tree.data

    @DataModel.setter
    def DataModel(self, data: NodeModel) -> None:
        faults = self._tree.faults
        faults.check("DataModel")
        self._tree.data = data
        # `SvImpLBox::Clear`; the selection engine is not told (`anchored`).
        self._tree.selected, self._tree.cursor, self._tree.anchor = [], None, None
        self._tree.start = 0  # `SvImpLBox::Clear`: the new rows show from the first.
        faults.check("DataModel installed")


class Selected(list[Node]):
    """The tree's selected nodes: adding one notifies the tree's selection listener."""

    def __init__(self, tree: "Tree", nodes: Any = ()) -> None:
        super().__init__(nodes)
        self._tree = tree

    def append(self, node: Node) -> None:
        if not any(node is item for item in self):
            super().append(node)
            self._tree.notify(1)


class Tree:
    def __init__(self, faults: Faults) -> None:
        self.faults = faults
        self.data: NodeModel | None = None
        # The toolkit's selection listener (`XSelectionChangeListener`), and how many times it
        # was notified.
        self.listener: Callable[[], None] | None = None
        self.notified = 0
        self._selected = Selected(self)
        self.anchor: Node | None = None  # The native range anchor (`SvImpLBox::m_pAnchor`),
        self.anchored = False  # and whether the selection engine made one (`HAS_ANCH`).
        # Whether VCL's selection engine is in add mode: after a Ctrl+Shift press, until a plain
        # or a Shift press (`SelectionEngine::SelMouseButtonDown`).
        self.add_mode = False
        # The line of a plain press on a selected row, which the engine leaves to its release
        # (`WAIT_UPEVT`).
        self.waiting: int | None = None
        self.cursor: Node | None = None
        # `ACTIVE_DESCENDANT_CHANGED`, which the list observes.
        self.cursor_listener: Callable[[int], None] | None = None
        self.model = ControlModel(self)
        self.focused = 0
        self.visible: int | None = None  # Rows that fit in the view; None: all of them.
        self.wide: int | None = None  # A longer label shows a horizontal scrollbar.
        self.start = 0  # The index of the first row in view.
        self.height = 1  # A row's height, as VCL fits it to the font and the display.

    @property
    def selected(self) -> Selected:
        return self._selected

    @selected.setter
    def selected(self, nodes: list[Node]) -> None:
        """Select exactly `nodes`: the listener hears once per row whose selection changed."""
        old = self._selected
        changed = sum(1 for node in nodes if not any(node is item for item in old))
        changed += sum(1 for node in old if not any(node is item for item in nodes))
        self._selected = Selected(self, nodes)
        self.notify(changed)

    def notify(self, changes: int) -> None:
        """Notify the selection listener once per changed row, inside the changing call."""
        for _ in range(changes):
            self.notified += 1
            if self.listener is not None:
                self.listener()

    def _installed(self) -> list[Node]:
        root = self.data.root if self.data is not None else None
        return root.children if root is not None else []

    def _in_view(self) -> int | None:
        """How many rows fit, one fewer under a horizontal scrollbar; None if all of them do."""
        if self.visible is None:
            return None
        nodes = self._installed()
        wide = self.wide is not None and any(len(node.label) > self.wide for node in nodes)
        return self.visible - 1 if wide else self.visible

    def _last_start(self) -> int:
        """The first row in view when the last rows fill the view (`SvImpLBox::FillView`)."""
        fit = self._in_view()
        return 0 if fit is None else max(0, len(self._installed()) - fit)

    def scroll_to(self, start: int) -> None:
        """Start the view at `start`, as far as the rows allow; no list call sees this."""
        self.start = max(0, min(start, self._last_start()))

    def fill_view(self) -> None:
        """`SvImpLBox::FillView` after a resize: the view starts no further down than the last
        rows fill it."""
        self.start = min(self.start, self._last_start())

    def line(self, row: int) -> int:
        """The position in the view of the row at `row`, as a mouse event's position."""
        return (row - self.start) * self.height

    def first_in_view(self) -> Node | None:
        nodes = self._installed()
        return nodes[self.start] if nodes else None

    def _own(self, node: Any, call: str) -> Node:
        if not any(node is item for item in self._installed()):
            raise NativeFailure(f"{call}: the node is not in the installed model")
        return cast(Node, node)

    def getModel(self) -> ControlModel:
        self.faults.check("getModel")
        return self.model

    def getSelection(self) -> tuple[Node, ...] | Node | None:
        self.faults.check("getSelection")
        if len(self.selected) == 1:
            return self.selected[0]  # As PyUNO returns a single selected node.
        return tuple(self.selected) or None

    def select(self, node: Any) -> None:
        self.faults.check("select")
        assert self.model.SelectionType == "SINGLE", "Only the cursor write selects one row"
        self.deselect_all()  # Every row is deselected before the node is looked up.
        self.faults.check("select cleared")
        own = self._own(node, "select")
        self._mark(own, True)
        if own is not self.cursor:  # `SvImpLBox::EntrySelected` in single selection mode.
            old, self.cursor = self.cursor, own
            self._announce_cursor()
            self._move_range(old, own)
        self.faults.check("select done")

    def addSelection(self, node: Any) -> None:
        self.faults.check("addSelection")
        own = self._own(node, "addSelection")
        if not any(own is item for item in self.selected):
            self.selected.append(own)
        self.faults.check("addSelection done")

    def clearSelection(self) -> None:
        self.faults.check("clearSelection")
        self.deselect_all()
        self.faults.check("clearSelection done")

    def deselect_all(self, engine: bool = False) -> None:
        """`SvImpLBox::SelAllDestrAnch`: nothing, if nothing is selected; otherwise the anchor goes
        too. The selection engine's own call (`engine`) leaves it to the engine to note that."""
        if not self.selected:
            return
        self.selected, self.anchor = [], None
        self.anchored = self.anchored and engine

    def _is_selected(self, node: Node) -> bool:
        return any(node is item for item in self.selected)

    def _mark(self, node: Node, select: bool) -> None:
        """`SvTreeListBox::Select`: the row's selection, which the listener hears of if it
        changes."""
        if self._is_selected(node) != select:
            kept = [item for item in self.selected if item is not node]
            self.selected = [*kept, node] if select else kept

    def _set_cursor(self, node: Node, select: bool = True) -> None:
        """`SvImpLBox::SetCursor` in multiple selection mode, as the selection engine calls it:
        the cursor moves, its row is selected unless the engine is in add mode, and the range
        from the anchor, if any, follows it."""
        if node is self.cursor and self._is_selected(node):
            return
        old, self.cursor = self.cursor, node
        if select and not self.add_mode:
            self._mark(node, True)
        if not (select and self.add_mode):
            self._announce_cursor()
        self._move_range(old, node)

    def _announce_cursor(self) -> None:
        """Tell accessibility of the row the cursor is on (`ListboxTreeFocus`), inside the call
        that moved it: nothing for a press in add mode that only moves the cursor."""
        if self.cursor_listener is not None and self.cursor is not None:
            index = next(i for i, item in enumerate(self._installed()) if item is self.cursor)
            self.cursor_listener(index)

    def paint_cursor(self) -> None:
        """`SvImpLBox::Paint` puts the cursor of a tree that has none on its first row in view
        (measured on #327 with 26.8.2.2)."""
        if self.cursor is None:
            self.cursor = self.first_in_view()
            self._announce_cursor()

    def _move_range(self, old_cursor: Node | None, new_cursor: Node) -> None:
        """`SvImpLBox::SetAnchorSelection`: move the end of the range that starts at the anchor
        from the old cursor to the new one, a row at a time as VCL selects and deselects them."""
        if self.anchor is None or old_cursor is None:
            return
        nodes = self._installed()

        def mark(first: int, last: int, select: bool = True) -> None:
            for node in nodes[first : last + 1]:
                self._mark(node, select)

        anchor, old, new = (
            next(i for i, item in enumerate(nodes) if item is node)
            for node in (self.anchor, old_cursor, new_cursor)
        )
        if old > anchor or (old == anchor and new > anchor):
            if new > old:
                mark(old, new)
            elif new < anchor:
                mark(anchor, old, False)
                mark(new, anchor)
            elif new < old:
                mark(new + 1, old, False)
        elif new < old:
            mark(new, old)
        elif new > anchor:
            mark(old, anchor, False)
            mark(anchor, new)
        elif new > old:
            mark(old, new - 1, False)

    def press(self, line: int, modifiers: int = 0, clicks: int = 1, button: int = LEFT) -> None:
        """A press on the labels at `line` as the tree handles it, before the list's listener runs
        (`SvImpLBox::MouseButtonDown`, `SelectionEngine::SelMouseButtonDown`).

        The tree ignores a middle press and gives the engine a left one alone (measured on #328
        with 26.8.3.1), which returns at once for a click count above 1 or with Alt (measured on
        #294 with 26.8.2.2). A press outside the rows is not modelled: callers press rows.
        """
        if button not in (LEFT, RIGHT):
            return
        self.waiting = None
        index, nodes = line // self.height + self.start, self._installed()
        node = nodes[index]
        if self.cursor is None:
            self.cursor = self.first_in_view()
        if button == RIGHT or modifiers & MOD2 or clicks > 1:
            return
        keys = modifiers & (SHIFT | MOD1)
        if keys == SHIFT | MOD1:
            self.add_mode = True
        elif keys != MOD1:
            self.add_mode = False
        if keys == MOD1:
            self.anchor, self.anchored = (None, False) if self.anchored else (self.anchor, False)
            toggled_off = self._is_selected(node)
            if toggled_off:
                self._mark(node, False)
            self._set_cursor(node, select=not toggled_off)
            return
        if keys:
            if not self.anchored:
                if not self.add_mode:
                    self.deselect_all(engine=True)
                self.anchor, self.anchored = self.cursor, True
        elif self._is_selected(node):
            self.waiting = line
            return
        else:
            self.deselect_all(engine=True)
            self.anchored = False
        self._set_cursor(node)

    def release(self) -> None:
        """The release of the latest press as the tree handles it (`SelMouseButtonUp`): after a
        plain press on a selected row, the row at that press's position is selected alone."""
        line, self.waiting = self.waiting, None
        if line is None:
            return
        index, nodes = line // self.height + self.start, self._installed()
        self.deselect_all(engine=True)
        self.anchored = False
        if index < len(nodes):
            self._set_cursor(nodes[index])

    def makeNodeVisible(self, node: Any) -> None:
        """`SvImpLBox::MakeVisible`: a row in view stays where it is (`IsEntryInView`); any
        other row starts the view, which `FillView` then moves up until the view is full."""
        self.faults.check("makeNodeVisible")
        own = self._own(node, "makeNodeVisible")
        fit = self._in_view()
        if fit is None:
            return
        index = next(i for i, item in enumerate(self._installed()) if item is own)
        if not self.start <= index < self.start + fit:
            self.start = min(index, self._last_start())

    def getClosestNodeForLocation(self, x: int, y: int) -> Node | None:
        """The row that the native hit test finds: none in the gutter left of `HIT_X` (measured on
        gtk3 and gen with 26.8.3.1, #342), and none off the rows."""
        self.faults.check("getClosestNodeForLocation")
        index, nodes = y // self.height + self.start, self._installed()
        return nodes[index] if x >= HIT_X and 0 <= index < len(nodes) else None

    def getNodeRect(self, node: Any) -> Any:
        """A row's bounds: its position in the view and its height, as the list's geometry reads."""
        self.faults.check("getNodeRect")
        own = self._own(node, "getNodeRect")
        index = next(i for i, item in enumerate(self._installed()) if item is own)
        return SimpleNamespace(Y=self.line(index), Height=self.height)

    def setFocus(self) -> None:
        self.focused += 1

    def node(self, name: str) -> Node:
        return next(node for node in self._installed() if node.DataValue == name)

    def assistive_select(self, name: str) -> None:
        """Select a row as `XAccessibleSelection` does: no owned handler sees it, and only the
        toolkit's selection listener hears it."""
        node = self.node(name)
        if not any(node is item for item in self.selected):
            self.selected.append(node)

    def assistive_only(self, name: str) -> None:
        """Select only this row through accessibility, as clearing and selecting it does."""
        self.selected = [self.node(name)]

    def assistive_clear(self) -> None:
        self.selected = []

    def shown(self) -> list[str]:
        """The selected rows' names, in row order."""
        return [str(node.DataValue) for node in self._installed() if node in self.selected]


class Peer:
    def __init__(self, faults: Faults) -> None:
        self._faults = faults
        self.invalidations = 0
        self.properties: dict[str, object] = {}

    def invalidate(self, flags: int) -> None:
        self._faults.check("invalidate")
        self.invalidations += 1

    def setProperty(self, name: str, value: object) -> None:
        self._faults.check("setProperty")
        self.properties[name] = value


class Tabs:
    """The tab observer's side of a refresh: it records each baseline the list asks for."""

    def __init__(self) -> None:
        self.baselines: list[int] = []
        self.inputs = 0
        self.stopped = False

    def refreshed(self, generation: int) -> None:
        self.baselines.append(generation)

    def note_input(self) -> None:
        self.inputs += 1

    def acknowledge(self) -> None:
        pass


class Monitor:
    def __init__(self, book: Book):
        self._book = book
        self.events = SimpleNamespace(replay=None, viewing_replay=self.no_replay)

    def no_replay(self) -> None:
        return None  # No own move is being replayed.

    @property
    def generation(self) -> int:
        return self._book.generation

    def check(self) -> int:
        return self._book.generation


@dataclass
class Timer:
    seconds: float
    work: Callable[[], None]
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


Definitions = dict[str, ast.FunctionDef | ast.ClassDef]


@functools.cache
def _parsed(source: str) -> tuple[dict[str, ast.FunctionDef], Definitions]:
    """`SheetList`'s methods and the module's other definitions in `source`, parsed once."""
    tree = ast.parse((source_methods.ROOT / source).read_text(encoding="utf-8"))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SheetList")
    methods = {node.name: node for node in owner.body if isinstance(node, ast.FunctionDef)}
    others = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.ClassDef) and node.name != "SheetList"
    }
    return methods, others


@functools.cache
def _class_methods(source: str, name: str) -> dict[str, ast.FunctionDef]:
    """The methods of the module-level class `name` in `source`, parsed once."""
    tree = ast.parse((source_methods.ROOT / source).read_text(encoding="utf-8"))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    return {node.name: node for node in owner.body if isinstance(node, ast.FunctionDef)}


@functools.cache
def _compiled(source: str, node: ast.AST) -> CodeType:
    return compile(ast.Module(body=[cast(ast.stmt, node)], type_ignores=[]), source, "exec")


def _load(source: str, node: ast.AST, namespace: dict[str, Any]) -> Any:
    exec(_compiled(source, node), namespace)
    return namespace[cast(Any, node).name]


class _Owner(SimpleNamespace):
    @property
    def _cursor(self) -> str | None:
        """As `SheetList._cursor`: the keyboard cursor's name."""
        ref = cast(Any, self)._selection.cursor
        return ref.name if ref is not None else None


def _draw_nothing(rows: object, geometry: object, picked: object) -> None:
    """`RowPaint.draw`: the peer draws nothing."""


class _UnoBase:
    """`unohelper.Base`, which the list's listeners derive from."""


class _MouseListener:
    """`XMouseListener`, which `_Mouse` implements."""


def sheet_list(book: Book, source: str = SOURCE) -> Any:
    """A list over `book` with the real methods of `source` bound, after its first refresh."""
    faults = Faults()
    clock = SimpleNamespace(now=100.0)
    timers: list[Timer] = []
    reports: list[str] = []
    errors: list[str] = []

    def later(seconds: float, work: Callable[[], None], where: str) -> Timer:
        timer = Timer(seconds, work)
        timers.append(timer)
        return timer

    def read_rows(controller: object, observed: object) -> list[SheetRow]:
        return book.rows()

    def snapshot(document: object) -> Any:
        return book.snapshot()

    def create(service: str, context: object) -> NodeModel:
        faults.check("createInstanceWithContext")
        return NodeModel(faults)

    def show_error(peer: object, title: str, message: str) -> None:
        errors.append(message)

    def _current(ref: Ref) -> bool:  # As `uno_list._current`.
        try:
            return ref.token is not None and ref.token.getName() == ref.name
        except Exception:
            return False

    methods, others = _parsed(source)
    namespace: dict[str, Any] = {
        "Any": Any,  # Annotations are evaluated when the methods are defined.
        "Callable": Callable,
        "Mapping": Mapping,
        "SheetRow": SheetRow,
        "RowGeometry": RowGeometry,
        "Snapshot": object,
        "MULTI": "MULTI",
        "SINGLE": "SINGLE",
        "Ref": Ref,
        "list_name": list_name,
        "ordered": ordered,
        "read_rows": read_rows,
        "replace": replace,
        "report": reports.append,
        "row_label": row_label,
        "snapshot": snapshot,
        "structure_kept": structure_kept,
        "time": time,
        "DisposedException": type("DisposedException", (Exception,), {}),
        "REPLAY_WAIT": 0.05,
        "REPLAY_WAITS": 3,
        "ACTIONS": ("top", "up", "down", "bottom"),
        "plan_move": book.plan,
        "apply_order": book.apply,
        "show_error": show_error,
        "tr": str,
        "cast": cast,
        "Action": str,
        "_current": _current,
        "_name_or_none": _load(source, others["_name_or_none"], {"Any": Any}),
        "find_prefix": find_prefix,
        "A": A,
        "SPACE": SPACE,
        "UP": UP,
        "DOWN": DOWN,
        "HOME": HOME,
        "END": END,
        "PAGEUP": PAGEUP,
        "PAGEDOWN": PAGEDOWN,
        "LEFT": LEFT,
        "RIGHT": RIGHT,
        "SHIFT": SHIFT,
        "MOD1": MOD1,
        "MOD2": MOD2,
    }
    namespace["_Press"] = _load(source, others["_Press"], {"dataclass": dataclass, "Any": Any})
    namespace["_thread"] = _thread
    if "_OwnWrites" in others:  # A revision before #294 has none.
        namespace["_OwnWrites"] = _load(source, others["_OwnWrites"], {"_thread": _thread})
    if "_PressHold" in others:  # A revision before #293 has none.
        namespace["_PressHold"] = _load(source, others["_PressHold"], {"dataclass": dataclass})
    if "_Intake" in others:  # A revision before #307 has none.
        namespace["_Intake"] = _load(source, others["_Intake"], {"enum": enum})
    tree, peer = Tree(faults), Peer(faults)
    owner = _Owner(
        source=source,
        book=book,
        tree=tree,
        peer=peer,
        faults=faults,
        clock=clock,
        timers=timers,
        reports=reports,
        errors=errors,
        failures=[],  # Where a failure ended posted work.
        queue=[],
        context=SimpleNamespace(ServiceManager=SimpleNamespace(createInstanceWithContext=create)),
        document=book,
        controller=book,
        _disposed=False,
        _busy=False,
        _move_queued=False,
        _monitor=Monitor(book),
        _proven=book.generation,
        _generation=0,
        _observed=None,
        _handles={},
        _nodes=[],
        rows=[],
        _shown=(),
        _toggles_held=None,
        _toggles_release=None,
        _toggles_keys=True,
        _ranges_held=None,
        _range_start=None,
        _ranges_release=None,
        _deferred=None,
        _unowned=0,
        _accounted=0,
        _writing=0,
        _writer=None,
        _write_start=0,
        _shown_at=0,
        _quiet=None,
        _erased=None,
        _input_seen=0,
        _unclaimed=False,
        _intake=namespace["_Intake"].CHANGES if "_Intake" in namespace else None,
        _add_mode=False,
        _presses_held=None,
        _presses_release=None,
        _position=None,
        _row_paint=SimpleNamespace(draw=_draw_nothing),
        _decoration_pending=False,
        _selection=Selection(_current),
        _user_picks=False,
        _press=None,
        _pointer_depth=0,
        _selection_write_pending=False,
        _selection_scroll=False,
        _context_target=None,
        _context_generation=book.generation,
        _context_input=0,
        _menu_context=False,
        _restoring_cursor=False,
        _input=0,
        _follow_input=None,
        _viewed_name=None,
        _page_rows=3,
        _tabs=Tabs(),
        claim_window=lambda: None,
        _update_moves=lambda: None,
        notices=[],
    )
    owner._refreshes = RefreshSchedule(later, lambda: owner._timed_refresh(), lambda: clock.now)
    owner._show_cleared_notice = lambda: owner.notices.append(clock.now)
    owner._type_ahead = TypeAhead()

    def decorate_rows() -> None:  # The borders `paint_rows` posts; nothing to draw here.
        owner._decoration_pending = False

    owner._decorate_rows = decorate_rows

    def post(work: Callable[[], None], where: str) -> None:
        owner.queue.append((work, where))

    def run_queue() -> None:
        """Run the posted main-thread work, as LibreOffice's queue would next."""
        while owner.queue:
            work, where = owner.queue.pop(0)
            try:
                work()
            except NativeFailure:
                owner.failures.append(where)

    def retry(limit: int = 12) -> int:
        """Run the refresh schedule's timers, as they come due, until none is pending."""
        ran = 0
        while ran < limit:
            pending = [timer for timer in timers if not timer.cancelled]
            if not pending:
                break
            timer = pending[0]
            timers.remove(timer)
            clock.now += timer.seconds
            post(timer.work, "refreshing the sheet list")
            run_queue()
            ran += 1
        return ran

    owner.post, owner.run_queue, owner.retry = post, run_queue, retry

    def contain(where: str) -> None:
        """`report` as a guard below calls it, while it handles a failure: a simulated native
        failure is recorded where `run_queue` records one, and anything else is raised again."""
        failure = sys.exception()
        if isinstance(failure, NativeFailure):
            owner.failures.append(where)
        elif failure is not None:
            raise failure

    guarded = _load(source, others["_guarded"], {"report": contain})
    listener = {
        "unohelper": SimpleNamespace(Base=_UnoBase),
        "XMouseListener": _MouseListener,
        "_guarded": guarded,
    }
    owner.mouse = _load(source, others["_Mouse"], listener)(owner)  # `_listeners["mouse"]`.
    owner.namespace = namespace  # The methods' globals, for a sequence that binds its own.
    for name in METHODS:
        if name in methods:  # A method another revision lacks stays unbound.
            setattr(owner, name, _load(source, methods[name], dict(namespace)).__get__(owner))
    if "tree_selection_changed" in methods:  # `_Selections`, as `_initialize` registers it.
        tree.listener = lambda: owner.tree_selection_changed()

    def cursor_moved(index: int) -> None:  # `_Cursor`, as `_initialize` registers it.
        focus_event(owner, index)

    tree.cursor_listener = cursor_moved
    # The key handler that the list registers while it has the focus, which it always has here,
    # and the move buttons' action listener, which requests a move as `_initialize` passes it.
    owner.owns_keys = owner.owns_tree_keys = lambda: True
    handler = owner.key_handler = SimpleNamespace(_list=owner, _shortcuts=None, _consumed={})
    routing = {
        "route_key": route_key,
        "button_route": button_route,
        "move_action": move_action,
        "unbound_route": unbound_route,
        "KeyRoute": KeyRoute,
        "TAB": TAB,
        "SHIFT": SHIFT,
        "SPACE": SPACE,
        "report": contain,
    }
    pressed = _class_methods(KEYS, "ListKeyHandler")["keyPressed"]
    handler.keyPressed = _load(KEYS, pressed, routing).__get__(handler)

    def request(action: str) -> None:  # `queue_move`, looked up when the button is pressed.
        owner.queue_move(action)

    buttons = owner.move_buttons = SimpleNamespace(_request=request)
    performed = _class_methods(MOVES, "MoveButtons")["actionPerformed"]
    buttons.actionPerformed = _load(MOVES, performed, {"report": contain}).__get__(buttons)
    owner.refresh()
    run_queue()
    return owner


def changed(owner: Any) -> None:
    """A document change, as the modify listener reports it: the schedule's timer refreshes."""
    owner._refreshes.changed()


def move_to_top(owner: Any) -> list[str] | str | None:
    """Press Move to Top, through the button's action listener (`MoveButtons.actionPerformed`),
    then the work it queued: the sheets it moved, None if it refused, or "failed" if it did
    neither, as when a native failure ended it before its message. A failure before the move is
    queued ends only that press, recorded as "a move button"."""
    moves, errors = len(owner.book.moved), len(owner.errors)
    owner.move_buttons.actionPerformed(SimpleNamespace(ActionCommand="top"))
    owner.run_queue()
    if len(owner.book.moved) > moves:
        return owner.book.moved[-1]
    return None if len(owner.errors) > errors else "failed"


def key(owner: Any, code: int, modifiers: int = 0) -> None:
    """A selection key in the list, through the list's key handler (`ListKeyHandler.keyPressed`),
    then the work it queued. Only a key that the handler gives the tree (`tree_key`) is accepted:
    another would mean something else there, or nothing. A native failure while the handler runs
    ends only that key, recorded as "the key handler", and the key is still consumed: the
    handler's `_consumed`, which consumes the key's release, says so."""
    assert route_key(code, modifiers) is KeyRoute.TREE, (code, modifiers, "is not a tree key")
    owner.key_handler.keyPressed(SimpleNamespace(KeyCode=code, Modifiers=modifiers, KeyChar=""))
    owner.run_queue()


def type_key(owner: Any, char: str) -> None:
    """A character typed in the list, through the list's key handler, which queues type-ahead
    for it (`queue_input`), then that work: a native failure in type-ahead ends only that work,
    recorded as "type-ahead"."""
    assert route_key(0, 0, char) is KeyRoute.TYPE_AHEAD, (char, "is not typed ahead")
    letter = char.isascii() and char.isalpha()
    code = A + ord(char.lower()) - ord("a") if letter else 0  # UNO's key codes A to Z.
    owner.key_handler.keyPressed(SimpleNamespace(KeyCode=code, Modifiers=0, KeyChar=char))
    owner.run_queue()


def listen(owner: Any, handler: Callable[[Any], None], event: Any) -> None:
    """Run a mouse handler through the list's own mouse listener (`_Mouse.mousePressed` or
    `mouseReleased`), as LibreOffice calls it: inside the pointer depth, guarded, and queueing the
    selection write as it returns. A native failure in the handler ends only the handler and is
    recorded once in `failures`, under the listener's name ("a mouse press" or "a mouse
    release"), and a failed press is left undecided (`press_failed`, #318); the call returns.
    `handler` is the list's handler as the listener finds it, a wrapper a sequence installed
    included."""
    name = handler.__name__
    assert handler == getattr(owner, name), (name, "is not the list's own handler")
    {"mouse_pressed": owner.mouse.mousePressed, "mouse_released": owner.mouse.mouseReleased}[name](
        event
    )


def press(owner: Any, row: int, button: int = LEFT, modifiers: int = 0) -> None:
    """A press as the list's mouse listener runs it (`_Mouse.mousePressed`), on the line that shows
    the row at `row` now, at once after the tree handled it."""
    line = owner.tree.line(row)
    owner.tree.press(line, modifiers, button=button)
    event = SimpleNamespace(Buttons=button, X=LABEL_X, Y=line, Modifiers=modifiers, ClickCount=1)
    listen(owner, owner.mouse_pressed, event)


def release(owner: Any, row: int, button: int = LEFT) -> None:
    """The release of the latest press, with the pointer over the row at `row`: the tree handles
    it before the listener runs (`Tree.release`)."""
    if button == LEFT:
        owner.tree.release()
    event = SimpleNamespace(
        Buttons=button, X=LABEL_X, Y=owner.tree.line(row), Modifiers=0, ClickCount=1
    )
    listen(owner, owner.mouse_released, event)


def queued_click(
    owner: Any,
    row: int,
    modifiers: int = MOD1,
    clicks: int = 1,
    button: int = LEFT,
    x: int = LABEL_X,
) -> None:
    """A click as LibreOffice delivers it (#85, #269, #288): the tree handles the press and the
    release at once (`Tree.press`, `Tree.release`), and their listeners are queued behind all the
    work already posted, which `run_queue` then runs in order. That is the latest place VCL gives
    them. VCL can also run them earlier, in the place of a callback event of the window still
    queued, since it adds them to that event (`VCLXWindowImpl::callBackAsync`); this does not
    model that. `clicks` is the native click count: above 1, as for a double or triple click's
    later clicks, the engine returns at once and changes nothing (#310's review; measured on #294
    with 26.8.2.2). `row` is the pressed row's index as the tree shows it when the user presses;
    the events carry its line in the view, as VCL's carry a position. `x` left of `HIT_X` is in
    the gutter, where the tree changes nothing (#342)."""
    line = owner.tree.line(row)
    if owner.tree.getClosestNodeForLocation(x, line) is not None:
        owner.tree.press(line, modifiers, clicks, button)
        if button == LEFT:
            owner.tree.release()
    pressed = SimpleNamespace(Buttons=button, X=x, Y=line, Modifiers=modifiers, ClickCount=clicks)
    released = SimpleNamespace(Buttons=button, X=x, Y=line, Modifiers=modifiers, ClickCount=clicks)
    owner.post(lambda: listen(owner, owner.mouse_pressed, pressed), "a mouse press")
    owner.post(lambda: listen(owner, owner.mouse_released, released), "a mouse release")


def click(owner: Any, row: int) -> None:
    press(owner, row)
    owner.run_queue()
    release(owner, row)
    owner.run_queue()


def record_activations(owner: Any) -> list[str]:
    """The sheets a double click's posted activation is asked to activate (`_activate_pressed`)."""
    activated: list[str] = []

    def activate_pressed(name: str, handle: Any, generation: int) -> None:
        activated.append(handle.getName())

    owner._activate_pressed = activate_pressed
    return activated


def record_menus(owner: Any) -> list[str | None]:
    """The target of each sheet tab menu that a right click's release asks for (`_open_menu`)."""
    targets: list[str | None] = []

    def open_menu(x: int, y: int, refs: Any = None, seen: int | None = None) -> None:
        target = owner._context_target
        targets.append(None if target is None else target.token.getName())

    owner._open_menu = open_menu
    return targets


def paint(owner: Any) -> None:
    """VCL paints the tree, as after it scrolled or changed: the list's paint listener runs. The
    paint gives a tree without a cursor one (`Tree.paint_cursor`)."""
    owner.tree.paint_cursor()
    owner.paint_rows()


def wheel(owner: Any, start: int) -> None:
    """The user's wheel or the scroll bar scrolls the view to start at `start`, which no list call
    sees. VCL paints the scrolled rows within its handling of the scroll, so the list's paint
    listener runs at once."""
    owner.tree.scroll_to(start)
    paint(owner)


def resize(owner: Any, visible: int) -> None:
    """The panel's height changes so that `visible` rows fit, as when the selection notice shows
    or goes (`SheetList.set_bounds`). A taller view of a list scrolled to its end scrolls up
    (`FillView`). VCL only invalidates, so the scrolled rows are painted later (`paint`)."""
    owner.tree.visible = visible
    owner.tree.fill_view()


def scroll_unseen(owner: Any, start: int) -> None:
    """Another UNO client's `makeNodeVisible` scrolls the view to start at `start`. `MakeVisible`
    only invalidates, so the scrolled rows are painted later (`paint`)."""
    owner.tree.scroll_to(start)


def bind_drag(owner: Any) -> list[list[str]]:
    """Bind the real `start_drag`, with the document's checks stubbed to pass: it is writable and
    unprotected, and `is_current_as_reported` finds the rows current. Returns the sheets of each
    drag started, in order."""
    methods, _ = _parsed(owner.source)
    namespace = dict(owner.namespace)

    def current(document: object, observed: object) -> bool:
        return True

    def transferable(token: str) -> Any:
        return SimpleNamespace(token=token)

    def drag(names: list[str], observed: object, transferable: object, generation: int) -> Any:
        return SimpleNamespace(names=names)

    namespace.update(
        is_current_as_reported=current,
        _Transferable=transferable,
        _Drag=drag,
        uuid=SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="token")),
        ACTION_MOVE=2,
    )
    owner.start_drag = _load(owner.source, methods["start_drag"], namespace).__get__(owner)
    dragged: list[list[str]] = []

    def start(*arguments: object) -> None:
        dragged.append(list(owner._drag.names))

    owner._drag, owner._listeners = None, {"source": None}
    owner._drag_source = SimpleNamespace(startDrag=start)
    owner.book.isReadonly = owner.book.isProtected = lambda: False
    return dragged


def native_press(owner: Any, row: int) -> None:
    """A plain press as the tree handles it at once, its listener queued behind the work already
    posted (`queued_click` without the release, which waits while the button is held)."""
    line = owner.tree.line(row)
    owner.tree.press(line)
    event = SimpleNamespace(Buttons=LEFT, X=LABEL_X, Y=line, Modifiers=0, ClickCount=1)
    owner.post(lambda: listen(owner, owner.mouse_pressed, event), "a mouse press")


def focus_event(owner: Any, index: int) -> None:
    """An accessible focus event for the row at `index`, as the tree raises it."""
    row = SimpleNamespace(
        getAccessibleContext=lambda: SimpleNamespace(getAccessibleIndexInParent=lambda: index)
    )
    owner.cursor_changed(row)


def picks(owner: Any) -> list[str]:
    return owner._selection.names()


def cursor(owner: Any) -> str | None:
    ref = owner._selection.cursor
    return ref.name if ref is not None else None
