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
- the tree scrolls as `SvImpLBox` does (`MakeVisible`, `FillView` and `AdjustScrollBars`, read
  in 26.8.2.2) once a test sets how many rows fit (`Tree.visible`; by default every row fits and
  nothing scrolls): a new data model shows from its first row, `makeNodeVisible` leaves a row
  in view where it is and otherwise starts the view at that row, but no further down than the
  last rows fill the view, and a label longer than `Tree.wide` characters shows a horizontal
  scrollbar, which takes one row's height. `getNodeRect` gives a row's line in the view, and
  `Tree.scroll_to` scrolls as the user's wheel does;
- every native call can be made to fail (`Faults`), before it has any effect. `select` can also
  fail once it has deselected the rows ("select cleared") or selected its row ("select done"),
  `clearSelection` and `addSelection` after their effect ("... done"), and the data model
  assignment after installing its model. No native trigger is known for these failures (#257);
  they test the list's own state, not LibreOffice's behaviour;
- the toolkit's selection listener, which the list counts with (#294), is notified once per row
  whose selection changes, synchronously inside the call that changes it, whoever makes it: an
  assistive selection, the native part of a click, or the list's own tree calls. Every change
  of `Tree.selected` notifies, so a test or probe that sets it directly is a native change. A
  native Ctrl+Shift press adds the rows from the tree's anchor, its cursor when it has none, to
  the pressed row and removes none, and the second press of a double click changes nothing, as
  measured on #294.

Posted work runs on `run_queue`, and a failure there ends only that work and is recorded, as
LibreOffice's callback reports it. `queued_click` posts a click's mouse listeners there too, after
the tree has handled the press and behind all the work already posted, the latest place VCL gives
them (#269), so that work posted earlier, such as a refresh or the tab sample, runs between the
native press and the list's listener (#85, #288).
The refresh schedule's timers run on `retry`, which advances the fake clock. Move to Top runs
through `queue_move` and `_move_selection`; the reorder layer's `apply_order` is replaced by
`Book.apply`, which refuses a stale snapshot as `is_current` does and otherwise moves the planned
sheets.

The native checks are in `tests/integration` and `tests/ui`.
"""

import _thread
import ast
import functools
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any, cast

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
from sheet_manager.refresh_schedule import RefreshSchedule
from sheet_manager.reorder import Plan, plan_move
from sheet_manager.reorder import Sheet as Planned
from sheet_manager.selection import Ref, Selection, structure_kept
from sheet_manager.sheet_list import RowGeometry, SheetRow, list_name, ordered, row_label
from tests.unit import source_methods

SOURCE = "src/sheet_manager/uno_list.py"
LEFT, RIGHT = 1, 2  # Mouse buttons,
SHIFT, MOD1 = 1, 2  # and key modifiers, as UNO numbers them.
METHODS = (
    "names",
    "_ref",
    "refresh",
    "_refresh",
    "_identities_kept",
    "_prove",
    "_drop_all_picks",
    "_drop_picks",
    "_tell_dropped",
    "_hold_toggles",
    "_toggle_held",
    "_toggles_shown",
    "_toggle_held_off",
    "_hold_presses",
    "_release_presses",
    "_rebuild",
    "_show_native",
    "_name_viewed",
    "_select",
    "_apply_selection",
    "_show_selection",
    "_write_outside_refresh",
    "_take_tree_selection",
    "_settle_shown",
    "_current_picks",
    "_picks_at",
    "geometry",
    "_first_visible_name",  # Only revisions before the second read of the position (#293).
    "_hold_if_scrolled",
    "selected_names",
    "_focus_row",
    "_move_tree_cursor",
    "tree_key",
    "_queue_selection",
    "_flush_selection",
    "cursor_changed",
    "tree_selection_changed",
    "type_ahead",
    "_timed_refresh",
    "_run_refresh",
    "queue_move",
    "_move_selection",
    "mouse_pressed",
    "mouse_released",
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
                status="refused", message="The sheet list has changed. Refresh it and try again."
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
        self._tree.selected, self._tree.cursor = [], None
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
        self.anchor: Node | None = None  # The native range anchor, while it has one.
        self.cursor: Node | None = None
        self.model = ControlModel(self)
        self.focused = 0
        self.visible: int | None = None  # Rows that fit in the view; None: all of them.
        self.wide: int | None = None  # A longer label shows a horizontal scrollbar.
        self.start = 0  # The index of the first row in view.

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
        """Scroll as the user's wheel or scrollbar does, which no list call sees."""
        self.start = max(0, min(start, self._last_start()))

    def line(self, row: int) -> int:
        """The line in the view that shows the row at `row`, as a mouse event's position."""
        return row - self.start

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
        self.selected = []  # Every row is deselected before the node is looked up.
        self.anchor = None
        self.faults.check("select cleared")
        own = self._own(node, "select")
        self.selected, self.cursor = [own], own
        self.faults.check("select done")

    def addSelection(self, node: Any) -> None:
        self.faults.check("addSelection")
        own = self._own(node, "addSelection")
        if not any(own is item for item in self.selected):
            self.selected.append(own)
        self.faults.check("addSelection done")

    def clearSelection(self) -> None:
        self.faults.check("clearSelection")
        self.selected = []
        self.faults.check("clearSelection done")

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

    def getNodeRect(self, node: Any) -> Any:
        """A row's bounds: its line in the view, one unit high, as the list's geometry reads."""
        self.faults.check("getNodeRect")
        own = self._own(node, "getNodeRect")
        index = next(i for i, item in enumerate(self._installed()) if item is own)
        return SimpleNamespace(Y=self.line(index), Height=1)

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


def _load(source: str, node: ast.AST, namespace: dict[str, Any]) -> Any:
    module = ast.Module(body=[cast(ast.stmt, node)], type_ignores=[])
    exec(compile(module, source, "exec"), namespace)
    return namespace[cast(Any, node).name]


class _Owner(SimpleNamespace):
    @property
    def _cursor(self) -> str | None:
        """As `SheetList._cursor`: the keyboard cursor's name."""
        ref = cast(Any, self)._selection.cursor
        return ref.name if ref is not None else None


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
    }
    namespace["_Press"] = _load(source, others["_Press"], {"dataclass": dataclass, "Any": Any})
    namespace["_thread"] = _thread
    if "_OwnWrites" in others:  # A revision before #294 has none.
        namespace["_OwnWrites"] = _load(source, others["_OwnWrites"], {"_thread": _thread})
    if "_PressHold" in others:  # A revision before #293 has none.
        namespace["_PressHold"] = _load(source, others["_PressHold"], {"dataclass": dataclass})
    tree, peer = Tree(faults), Peer(faults)
    owner = _Owner(
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
        _deferred=None,
        _unowned=0,
        _accounted=0,
        _writing=0,
        _writer=None,
        _write_start=0,
        _presses_held=None,
        _presses_release=None,
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
    owner.namespace = namespace  # The methods' globals, for a sequence that binds its own.
    for name in METHODS:
        if name in methods:  # A method another revision lacks stays unbound.
            setattr(owner, name, _load(source, methods[name], dict(namespace)).__get__(owner))
    if "tree_selection_changed" in methods:  # `_Selections`, as `_initialize` registers it.
        tree.listener = lambda: owner.tree_selection_changed()
    owner.refresh()
    run_queue()
    return owner


def changed(owner: Any) -> None:
    """A document change, as the modify listener reports it: the schedule's timer refreshes."""
    owner._refreshes.changed()


def move_to_top(owner: Any) -> list[str] | str | None:
    """Press Move to Top: the sheets it moved, None if it refused, or "failed" if it did
    neither (a native failure ended it before its message)."""
    moves, errors = len(owner.book.moved), len(owner.errors)
    owner.queue_move("top")
    owner.run_queue()
    if len(owner.book.moved) > moves:
        return owner.book.moved[-1]
    return None if len(owner.errors) > errors else "failed"


def key(owner: Any, code: int, modifiers: int = 0) -> None:
    owner.tree_key(code, modifiers)
    owner.run_queue()


def _listen(owner: Any, handler: Callable[[Any], None], event: Any) -> None:
    """Run a mouse handler as the list's mouse listener does (`_Mouse._handle`)."""
    owner._pointer_depth += 1
    try:
        handler(event)
    finally:
        owner._pointer_depth -= 1
        if not owner._pointer_depth:
            owner._queue_selection()


def press(owner: Any, row: int, button: int = LEFT, modifiers: int = 0) -> None:
    """A press as the list's mouse listener runs it (`_Mouse._handle`), on the line that shows
    the row at `row` now."""
    line = owner.tree.line(row)
    event = SimpleNamespace(Buttons=button, X=0, Y=line, Modifiers=modifiers, ClickCount=1)
    _listen(owner, owner.mouse_pressed, event)


def release(owner: Any, row: int, button: int = LEFT) -> None:
    """The tree's native release selects the row under the pointer before the listener runs."""
    if button == LEFT:
        node = owner.tree._installed()[row]
        owner.tree.selected, owner.tree.cursor = [node], node
    event = SimpleNamespace(Buttons=button, X=0, Y=owner.tree.line(row), Modifiers=0, ClickCount=1)
    _listen(owner, owner.mouse_released, event)


def toggle_natively(owner: Any, row: int) -> None:
    """A Ctrl+press as the tree handles it: the row's selection is toggled and the cursor moved,
    and the range anchor goes (`SelectionEngine::SelMouseButtonDown`)."""
    node = owner.tree._installed()[row]
    if node in owner.tree.selected:
        owner.tree.selected = [item for item in owner.tree.selected if item is not node]
    else:
        owner.tree.selected = [*owner.tree.selected, node]
    owner.tree.cursor = node
    owner.tree.anchor = None


def extend_natively(owner: Any, row: int) -> None:
    """A Ctrl+Shift press as the tree handles it: the rows from the anchor, made at the cursor if
    there is none, to the pressed row are added, none removed, and the cursor moves there."""
    tree = owner.tree
    nodes = tree._installed()
    node = nodes[row]
    if tree.anchor is None:
        tree.anchor = tree.cursor if tree.cursor is not None else node
    start = next(index for index, item in enumerate(nodes) if item is tree.anchor)
    first, last = sorted((start, row))
    tree.selected = [
        *tree.selected,
        *(item for item in nodes[first : last + 1] if item not in tree.selected),
    ]
    tree.cursor = node


def queued_click(
    owner: Any, row: int, modifiers: int = MOD1, clicks: int = 1, button: int = LEFT
) -> None:
    """A click as LibreOffice delivers it (#85, #269, #288): the tree handles the press at once,
    and the press's and the release's listeners are queued behind all the work already posted,
    which `run_queue` then runs in order. That is the latest place VCL gives them. VCL can also
    run them earlier, in the place of a callback event of the window still queued, since it adds
    them to that event (`VCLXWindowImpl::callBackAsync`); this does not model that. With Ctrl
    alone the tree toggles the row, and the release changes no native selection; with Ctrl and
    Shift it adds the range from its anchor (`extend_natively`). Otherwise the row is selected
    alone, as a plain or Shift press on an unselected row selects it in the tree. `clicks` is the
    native click count, 2 for a double click's second click, which VCL's double-click path takes:
    with Ctrl it changes no native selection (#294); a plain one still selects its row alone, as
    the first click did. A right click changes no native selection (`SvImpLBox::MouseButtonDown`
    in 26.8). `row` is the pressed row's index as the tree shows it when the user presses; the
    events carry its line in the view, as VCL's carry a position."""
    if button == LEFT and modifiers & MOD1 and clicks % 2 == 0:
        pass
    elif button == LEFT and modifiers == MOD1:
        toggle_natively(owner, row)
    elif button == LEFT and modifiers == MOD1 | SHIFT:
        extend_natively(owner, row)
    elif button == LEFT:
        node = owner.tree._installed()[row]
        owner.tree.selected, owner.tree.cursor = [node], node
        owner.tree.anchor = None
    line = owner.tree.line(row)
    pressed = SimpleNamespace(Buttons=button, X=0, Y=line, Modifiers=modifiers, ClickCount=clicks)
    released = SimpleNamespace(Buttons=button, X=0, Y=line, Modifiers=modifiers, ClickCount=clicks)
    owner.post(lambda: _listen(owner, owner.mouse_pressed, pressed), "a mouse press")
    owner.post(lambda: _listen(owner, owner.mouse_released, released), "a mouse release")


def click(owner: Any, row: int) -> None:
    press(owner, row)
    owner.run_queue()
    release(owner, row)
    owner.run_queue()


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
