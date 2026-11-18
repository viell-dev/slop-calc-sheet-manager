"""The real `SheetList` refresh, selection writes and intake over a simulated tree peer.

The methods are loaded from `uno_list.py`'s source (`source_methods`), so they run unchanged
without LibreOffice, together with the real `Selection`. The simulated workbook and tree follow
what the list relies on from Calc and from the tree control for these calls:

- a deleted sheet's handle turns to the previous sheet (the next one at index 0), and every
  insertion or deletion moves the structure generation (`selection.py`), while a rename does
  not, and a handle can fail to read;
- assigning a data model shows its nodes with nothing selected, `select` in single selection
  mode selects only that node and moves the cursor to it, `addSelection` and an assistive
  selection add a node without moving the cursor, and `clearSelection` keeps the cursor;
- `clearSelection` and `invalidate` can be made to fail, as a peer call can during a refresh
  (#186).

It models those calls and is not evidence of LibreOffice's behaviour: the native checks are in
`tests/integration` and `tests/ui`.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

from sheet_manager.selection import Ref, Selection, structure_kept
from sheet_manager.sheet_list import SheetRow, list_name, node_text, ordered, row_label
from tests.unit.source_methods import function, method

SOURCE = "src/sheet_manager/uno_list.py"
METHODS = (
    "names",
    "_ref",
    "_refresh",
    "_identities_kept",
    "_drop_all_picks",
    "_rebuild",
    "_show_native",
    "_name_viewed",
    "_select",
    "_apply_selection",
    "_repaint",
    "_take_tree_selection",
    "_current_picks",
    "selected_names",
    "_move_tree_cursor",
)


@dataclass
class Sheet:
    name: str
    color: int | None = None


class Handle:
    """A retained sheet handle: it follows its sheet, and turns to another when it is deleted."""

    def __init__(self, sheet: Sheet):
        self.sheet = sheet
        self.readable = True

    def getName(self) -> str:
        if not self.readable:
            raise RuntimeError("the handle could not be read")
        return self.sheet.name


class Book:
    """A workbook's sheets, Calc's viewed sheet and the structure generation."""

    def __init__(self, names: list[str]):
        self.sheets = [Sheet(name) for name in names]
        self._own = {id(sheet): Handle(sheet) for sheet in self.sheets}
        self._retained = list(self._own.values())
        self.active = self.sheets[0]
        self.generation = 0

    def handle(self, sheet: Sheet) -> Handle:
        """The handle Calc gives for this sheet now."""
        return self._own[id(sheet)]

    def sheet(self, name: str) -> Sheet:
        return next(sheet for sheet in self.sheets if sheet.name == name)

    def rename(self, name: str, new: str) -> None:
        """Rename the sheet: its handles follow it, and the generation stays."""
        self.sheet(name).name = new

    def replace(self, name: str) -> None:
        """Delete the sheet and insert a different one under its name at the same place."""
        index = self.sheets.index(self.sheet(name))
        deleted = self.sheets.pop(index)
        turned = self.sheets[index - 1] if index > 0 else self.sheets[0]
        for handle in self._retained:
            if handle.sheet is deleted:
                handle.sheet = turned
        del self._own[id(deleted)]
        inserted = Sheet(name)
        self.sheets.insert(index, inserted)
        self._own[id(inserted)] = Handle(inserted)
        self._retained.append(self._own[id(inserted)])
        self.generation += 2  # One deletion and one insertion.

    def snapshot(self) -> Any:
        return SimpleNamespace(
            sheets=tuple(SimpleNamespace(name=sheet.name) for sheet in self.sheets),
            handles=tuple(self.handle(sheet) for sheet in self.sheets),
        )

    def rows(self) -> list[SheetRow]:
        return [
            SheetRow(sheet.name, active=sheet is self.active, color=sheet.color)
            for sheet in self.sheets
        ]


class Node:
    def __init__(self, label: str):
        self.label = label
        self.DataValue: str | None = None
        self.children: list[Node] = []

    def appendChild(self, node: "Node") -> None:
        self.children.append(node)


class NodeModel:
    """A `MutableTreeDataModel`."""

    def createNode(self, label: str, expandable: bool) -> Node:
        return Node(label)

    def setRoot(self, root: Node) -> None:
        self.root = root


class ControlModel:
    """The tree control's model: assigning `DataModel` shows the new nodes, none selected."""

    def __init__(self, tree: "Tree"):
        self._tree = tree
        self.SelectionType = "MULTI"

    @property
    def DataModel(self) -> "NodeModel | None":
        return self._tree.data

    @DataModel.setter
    def DataModel(self, data: "NodeModel") -> None:
        self._tree.data = data
        self._tree.selected, self._tree.cursor = [], None


class Tree:
    def __init__(self) -> None:
        self.data: NodeModel | None = None
        self.selected: list[Node] = []
        self.cursor: Node | None = None
        self.model = ControlModel(self)
        self.failures = 0  # How many of the next `clearSelection` calls fail.

    def getModel(self) -> ControlModel:
        return self.model

    def getSelection(self) -> tuple[Node, ...] | None:
        return tuple(self.selected) or None

    def select(self, node: Node) -> None:
        assert self.model.SelectionType == "SINGLE", "Only the cursor write selects one row"
        self.selected, self.cursor = [node], node

    def addSelection(self, node: Node) -> None:
        if node not in self.selected:
            self.selected.append(node)

    def clearSelection(self) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("the tree refused to clear its selection")
        self.selected = []

    def makeNodeVisible(self, node: Node) -> None:
        pass

    def assistive_select(self, name: str) -> None:
        """Select a row as `XAccessibleSelection` does: no owned handler sees it."""
        assert self.data is not None
        self.addSelection(next(node for node in self.data.root.children if node.DataValue == name))

    def shown(self) -> list[str]:
        return [str(node.DataValue) for node in self.selected]


class Peer:
    def __init__(self) -> None:
        self.invalidations = 0
        self.failures = 0  # How many of the next invalidations fail.
        self.properties: dict[str, object] = {}

    def invalidate(self, flags: int) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("the peer refused to invalidate")
        self.invalidations += 1

    def setProperty(self, name: str, value: object) -> None:
        self.properties[name] = value


class Monitor:
    def __init__(self, book: Book):
        self._book = book

    @property
    def generation(self) -> int:
        return self._book.generation

    def check(self) -> int:
        return self._book.generation


def sheet_list(book: Book) -> Any:
    """A list over `book` with the real methods bound, after its first refresh."""

    def read_rows(controller: object, observed: object) -> list[SheetRow]:
        return book.rows()

    def snapshot(document: object) -> Any:
        return book.snapshot()

    def create(service: str, context: object) -> NodeModel:
        return NodeModel()

    namespace: dict[str, Any] = {
        "Any": Any,  # Annotations are evaluated when the methods are defined.
        "Mapping": Mapping,
        "SheetRow": SheetRow,
        "Snapshot": object,
        "MULTI": "MULTI",
        "SINGLE": "SINGLE",
        "Ref": Ref,
        "list_name": list_name,
        "node_text": node_text,
        "ordered": ordered,
        "read_rows": read_rows,
        "replace": replace,
        "row_label": row_label,
        "snapshot": snapshot,
        "structure_kept": structure_kept,
        "_name_or_none": function(SOURCE, "_name_or_none", {"Any": Any}),
    }
    tree, peer = Tree(), Peer()
    factory = SimpleNamespace(createInstanceWithContext=create)
    owner = SimpleNamespace(
        book=book,
        tree=tree,
        peer=peer,
        queue=[],
        context=SimpleNamespace(ServiceManager=factory),
        document=book,
        controller=book,
        _disposed=False,
        _monitor=Monitor(book),
        _proven=book.generation,
        _generation=0,
        _observed=None,
        _handles={},
        _nodes=[],
        rows=[],
        _shown=(),
        _repaint_pending=False,
        _selection=Selection(function(SOURCE, "_current", {"Ref": Ref})),
        _user_picks=False,
        _press=None,
        _pointer_depth=0,
        _selection_write_pending=False,
        _context_target=None,
        _menu_context=False,
        _restoring_cursor=False,
        _input=0,
        _viewed_name=None,
        _view_generation=book.generation,
        _view_names=frozenset(),
        _view_input=0,
        _view_state=None,
        _view_stopped=True,
        _first_visible_name=lambda: None,
        _update_moves=lambda: None,
        _show_cleared_notice=lambda: None,
    )

    def post(work: Callable[[], None], where: str) -> None:
        owner.queue.append(work)

    def run_queue() -> None:
        """Run the posted main-thread work, as LibreOffice's queue would next."""
        while owner.queue:
            owner.queue.pop(0)()

    def refresh() -> None:
        """A refresh the list asks for. Tests run `_refresh` themselves, as its timer would."""
        owner.refreshes_asked += 1

    owner.post, owner.run_queue, owner.refresh = post, run_queue, refresh
    owner.refreshes_asked = 0
    for name in METHODS:
        loaded = method(SOURCE, "SheetList", name, dict(namespace))
        setattr(owner, name, loaded.__get__(owner))
    owner._refresh({})
    run_queue()
    return owner
