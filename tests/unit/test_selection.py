"""The sheet list's selection model: picks, cursor, and anchor stay with their sheets.

The workbook here reproduces how LibreOffice behaves, as measured in 26.2 and 26.8
(docs/reordering.md). A retained handle follows its sheet through renames, moves, and
insertions; when its sheet is deleted it turns to the previous sheet (the next one at index 0)
and follows that sheet from then on. Notifications arrive as LibreOffice sends them: every
recorded undo action as it happens, modify notifications per change, once per batch under
`lockControllers`, or not at all under `disableSetModified`, and undo or redo as one action.
Sheet ids are the ground truth the list never sees.
"""

import random
from collections.abc import Callable

from sheet_manager.selection import Ref, Selection, structure_kept
from sheet_manager.structure import History, StructureEvents


class Handle:
    """A retained sheet handle: it reports the name of the sheet it denotes now."""

    def __init__(self, book: "Book", sheet_id: int) -> None:
        self.book = book
        self.sheet_id = sheet_id
        book.handles.append(self)

    def name(self) -> str:
        return self.book.name_of(self.sheet_id)


Sheets = list[tuple[int, str]]


class Book:
    def __init__(self, names: list[str]) -> None:
        self.sheets: Sheets = list(enumerate(names))
        self.next_id = len(names)
        self.handles: list[Handle] = []
        self.undo: list[tuple[str, Sheets, dict[int, int]]] = []  # Title, state before.
        self.listeners: list[Callable[[str], None]] = []
        self.recording = True  # Undo recording; off for the out-of-scope case.
        self.modify_mode = "each"  # "each", "batch" (once at the end), or "none".
        self.modify_pending = False

    def names(self) -> list[str]:
        return [name for _, name in self.sheets]

    def name_of(self, sheet_id: int) -> str:
        return next(name for known, name in self.sheets if known == sheet_id)

    def id_named(self, name: str) -> int | None:
        return next((known for known, other in self.sheets if other == name), None)

    def handle(self, name: str) -> Handle:
        sheet_id = self.id_named(name)
        assert sheet_id is not None
        return Handle(self, sheet_id)

    def history(self) -> History:
        return (len(self.undo), self.undo[-1][0] if self.undo else None)

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def unused_name(self, rng: random.Random) -> str:
        while True:
            name = f"S{rng.randrange(1000)}"
            if name not in self.names():
                return name

    def notify(self, kind: str) -> None:
        for listener in self.listeners:
            listener(kind)

    def _change(self, title: str, apply: Callable[[], None]) -> None:
        """One change as Calc makes it: recorded, then reported."""
        before = (list(self.sheets), {id(h): h.sheet_id for h in self.handles})
        apply()
        if self.recording:
            self.undo.append((title, before[0], before[1]))
            self.notify("undoActionAdded")
        if self.modify_mode == "each":
            self.notify("modified")
        elif self.modify_mode == "batch":
            self.modify_pending = True

    def end_batch(self) -> None:
        if self.modify_pending:
            self.notify("modified")
        self.modify_pending = False
        self.modify_mode = "each"
        self.recording = True

    def undo_last(self) -> None:
        """Undo the last action: sheets and handles as before it, reported as one action."""
        if not self.undo:
            return
        _, sheets, targets = self.undo.pop()
        positions = {sheet_id: index for index, (sheet_id, _) in enumerate(self.sheets)}
        self.sheets = sheets
        present = {sheet_id for sheet_id, _ in sheets}
        for handle in self.handles:
            target = targets.get(id(handle), handle.sheet_id)
            if target not in present:  # Its sheet was inserted by the undone action.
                index = min(positions.get(target, 0), len(sheets)) - 1
                target = sheets[max(index, 0)][0]
            handle.sheet_id = target
        self.notify("modified")
        self.notify("actionUndone")

    # Primitives

    def insert(self, index: int, name: str) -> None:
        self._change("Insert Sheet", lambda: self.sheets.insert(index, (self.new_id(), name)))

    def delete(self, index: int) -> None:
        def apply() -> None:
            deleted, _ = self.sheets.pop(index)
            fallback = self.sheets[max(index - 1, 0)][0]  # Measured: the previous sheet.
            for handle in self.handles:
                if handle.sheet_id == deleted:
                    handle.sheet_id = fallback

        self._change("Delete Sheets", apply)

    def rename(self, index: int, name: str) -> None:
        def apply() -> None:
            self.sheets[index] = (self.sheets[index][0], name)

        self._change("Rename Sheet", apply)

    def move(self, index: int, to: int) -> None:
        self._change("Move Sheets", lambda: self.sheets.insert(to, self.sheets.pop(index)))


Change = Callable[[], None]


def random_changes(book: Book, rng: random.Random) -> list[Change]:
    """One random edit, as the separate changes Calc makes for it."""
    count = len(book.sheets)
    index = rng.randrange(count)
    name = book.names()[index]
    kind = rng.choice(
        ["insert", "delete", "rename", "move", "replace", "delete_rename", "cover", "reuse"]
    )
    if kind == "insert":
        new = book.unused_name(rng)
        return [lambda: book.insert(rng.randrange(count + 1), new)]
    if kind == "rename":
        new = book.unused_name(rng)
        return [lambda: book.rename(index, new)]
    if kind == "move":
        return [lambda: book.move(index, rng.randrange(count))]
    if count < 2:
        return []
    if kind == "delete":
        return [lambda: book.delete(index)]
    if kind == "replace":  # Delete a sheet and insert another under its name, in its place.
        return [lambda: book.delete(index), lambda: book.insert(index, name)]
    if kind == "delete_rename" and index > 0:  # The previous sheet takes the deleted name.
        previous = index - 1
        return [lambda: book.delete(index), lambda: book.rename(previous, name)]
    if kind == "cover":  # Insert before, delete, rename the newcomer: the count is kept.
        newcomer = book.unused_name(rng)
        return [
            lambda: book.insert(index, newcomer),
            lambda: book.delete(index + 1),
            lambda: book.rename(index, name),
        ]
    if kind == "reuse":  # Rename a sheet and give its name to another.
        other = rng.choice([i for i in range(count) if i != index])
        spare = book.unused_name(rng)
        return [lambda: book.rename(index, spare), lambda: book.rename(other, name)]
    return []


class List:
    """The list's identity logic as uno_list.py and uno_structure.py run it."""

    def __init__(self, book: Book, careful: bool = True) -> None:
        self.book = book
        self.careful = careful  # False: only per-ref name checks, as before round 6.
        self.selection = Selection(lambda ref: ref.token.name() == ref.name)
        self.events = StructureEvents(count=len(book.sheets), history=book.history())
        book.listeners.append(self.notified)
        self.proven = self.events.generation
        self.rows: list[str] = []
        self.handles: list[Handle] = []
        self.refresh()

    def notified(self, kind: str) -> None:
        count = len(self.book.sheets)  # Read while LibreOffice notifies.
        if kind == "modified":
            self.events.notified(count)
        elif kind in ("actionUndone", "actionRedone"):
            self.events.undone_or_redone(count)
        else:
            self.events.undo_notified(count)

    def refresh(self) -> None:
        generation = self.events.check(len(self.book.sheets), self.book.history(), quiet=False)
        if self.rows:
            reported: list[str | None] = [handle.name() for handle in self.handles]
            proved = generation == self.proven and structure_kept(
                self.rows, reported, self.book.names()
            )
            if self.careful and not proved:
                self.selection.clear()
            else:
                self.selection.revalidate()
        self.proven = generation
        self.rows = self.book.names()
        self.handles = [self.book.handle(name) for name in self.rows]

    def tokens(self) -> dict[str, Handle]:
        return dict(zip(self.rows, self.handles, strict=True))


DELIVERIES = ("each", "locked", "unmodified", "context", "undo")


def edit(book: Book, rng: random.Random, delivery: str) -> None:
    """One random edit, delivered as LibreOffice delivers it under one of the wrappers."""
    if delivery == "undo":
        book.undo_last()
        return
    if delivery == "silent":  # Out of scope: no undo recording, no modify notification.
        book.recording = False
        book.modify_mode = "none"
    elif delivery == "locked":  # lockControllers or addActionLock: one modify at the end.
        book.modify_mode = "batch"
    elif delivery == "unmodified":  # disableSetModified: none.
        book.modify_mode = "none"
    elif delivery == "context":  # A caller's undo context: reported as entered and left.
        book.notify("enteredContext")
    for change in random_changes(book, rng):
        change()
    if delivery == "context":
        book.notify("leftContext")
    book.end_batch()


def random_session(
    seed: int, careful: bool = True, deliveries: tuple[str, ...] = DELIVERIES
) -> list[str]:
    """Random edits, picks, and refreshes; the violations found after refreshes."""
    rng = random.Random(seed)
    book = Book([f"S{n}" for n in range(rng.randrange(1, 9))])
    sheet_list = List(book, careful)
    made_for: dict[int, tuple[Ref, int]] = {}  # id(ref) -> (ref, the sheet it was made for)
    violations: list[str] = []
    for _ in range(80):
        step = rng.random()
        if step < 0.35:
            edit(book, rng, rng.choice(deliveries))
        elif step < 0.55:
            sheet_list.refresh()
            for ref in held(sheet_list.selection):
                if id(ref) not in made_for:
                    violations.append(f"seed {seed}: {ref.name} was made by no pick")
                elif book.id_named(ref.name) != made_for[id(ref)][1]:
                    violations.append(f"seed {seed}: {ref.name} now names another sheet")
        elif step < 0.8:
            # The user picks rows as they show, possibly before a refresh.
            rows = sheet_list.rows
            picked = sorted(rng.sample(rows, rng.randrange(len(rows) + 1)))
            sheet_list.selection.take(picked, sheet_list.tokens(), rows)
            record(sheet_list.selection, made_for)
        else:
            name = rng.choice(sheet_list.rows)
            target = "cursor" if rng.random() < 0.5 else "anchor"
            ref = sheet_list.selection.ref(name, sheet_list.tokens(), sheet_list.rows)
            setattr(sheet_list.selection, target, ref)
            record(sheet_list.selection, made_for)
    return violations


def held(selection: Selection) -> list[Ref]:
    return [ref for ref in (*selection.picked, selection.cursor, selection.anchor) if ref]


def record(selection: Selection, made_for: dict[int, tuple[Ref, int]]) -> None:
    """Note the sheet each newly made ref was made for: the one its handle denotes now."""
    for ref in held(selection):
        if id(ref) not in made_for:
            made_for[id(ref)] = (ref, ref.token.sheet_id)


def test_picks_never_pass_to_another_sheet():
    """However LibreOffice delivers the changes, nothing held names a sheet it was not picked as.

    Edits arrive one by one, in lockControllers batches with one modify notification, under
    disableSetModified with none, inside undo contexts, and as undo of earlier edits.
    """
    violations = [found for seed in range(500) for found in random_session(seed)]
    assert violations == [], violations[:5]


def test_name_checks_alone_hand_picks_to_other_sheets():
    """The workbook reproduces the retargeting: per-ref name checks alone are fooled."""
    violations = [found for seed in range(500) for found in random_session(seed, careful=False)]
    assert violations, "The model should reproduce a deleted handle reporting a reused name"


def test_silenced_edits_are_out_of_scope():
    """Documented limit: with undo recording off and modify notifications off, nothing is seen.

    LibreOffice then reports nothing at all (measured), so a program that silences both channels
    around structural edits can hand a pick to another sheet. Such a program can hide or delete
    any sheet directly anyway; this is outside the threat model (docs/reordering.md).
    """
    violations = [
        found for seed in range(500) for found in random_session(seed, deliveries=("silent",))
    ]
    assert violations, "Silenced edits are expected to go unseen; see the docstring"


def cover(book: Book) -> None:
    """Insert a sheet before Bravo, delete Bravo, rename the newcomer to Bravo."""
    index = book.names().index("Bravo")
    book.insert(index, "Newcomer")
    book.delete(index + 1)
    book.rename(index, "Bravo")


def picked_bravo(book: Book) -> List:
    sheet_list = List(book)
    sheet_list.selection.take(["Bravo"], sheet_list.tokens(), sheet_list.rows)
    return sheet_list


def test_a_locked_batch_drops_the_pick():
    """lockControllers: one modify notification at the end, with the original count."""
    book = Book(["Alfa", "Bravo", "Charlie"])
    sheet_list = picked_bravo(book)
    book.modify_mode = "batch"
    cover(book)
    book.end_batch()
    sheet_list.refresh()
    assert sheet_list.selection.picked == []


def test_an_unmodified_batch_drops_the_pick():
    """disableSetModified: no modify notification; the undo notifications still come."""
    book = Book(["Alfa", "Bravo", "Charlie"])
    sheet_list = picked_bravo(book)
    book.modify_mode = "none"
    cover(book)
    book.end_batch()
    sheet_list.refresh()
    assert sheet_list.selection.picked == []


def test_undo_drops_the_pick():
    book = Book(["Alfa", "Bravo", "Charlie"])
    sheet_list = picked_bravo(book)
    book.rename(0, "Zulu")  # Not structural: Bravo's pick stays ...
    sheet_list.refresh()
    assert sheet_list.selection.names() == ["Bravo"]
    book.undo_last()  # ... but an undo could have been anything.
    sheet_list.refresh()
    assert sheet_list.selection.picked == []


def test_the_reviewed_sequence_drops_the_pick():
    """Only Bravo picked; Bravo deleted and Alfa renamed to Bravo (#28)."""
    book = Book(["Alfa", "Bravo", "Charlie", "Delta"])
    sheet_list = picked_bravo(book)
    bravo = sheet_list.selection.picked[0]
    book.delete(1)
    book.rename(0, "Bravo")
    assert bravo.token.name() == "Bravo"  # The handle is fooled ...
    sheet_list.refresh()
    assert sheet_list.selection.picked == []  # ... the list is not.


def test_moves_and_one_rename_keep_the_other_picks():
    book = Book(["Alfa", "Bravo", "Charlie", "Delta"])
    sheet_list = List(book)
    sheet_list.selection.take(["Bravo", "Delta"], sheet_list.tokens(), sheet_list.rows)
    book.move(1, 3)
    book.rename(book.names().index("Delta"), "Echo")
    sheet_list.refresh()
    assert sheet_list.selection.names() == ["Bravo"]


def test_structure_kept():
    assert structure_kept(["A", "B"], ["A", "B"], ["B", "A"])  # A move: handles follow.
    assert not structure_kept(["A", "B"], ["B", "A"], ["B", "A"])  # Names swapped.
    assert structure_kept(["A", "B"], ["A", "X"], ["A", "X"])  # One rename.
    assert not structure_kept(["A", "B"], ["A", "A"], ["A"])  # A deleted handle turned to A.
    assert not structure_kept(["A", "B"], ["X", "A"], ["X", "A"])  # B renamed to A's old name.
    assert not structure_kept(["A", "B"], ["X", "Y"], ["X", "Y"])  # Two renames.
    assert not structure_kept(["A", "B"], ["A", None], ["A", "B"])  # A handle failed.
    assert not structure_kept(["A", "B"], ["A", "B"], ["A", "B", "C"])  # A sheet appeared.


def test_structure_events():
    events = StructureEvents(count=3, history=(0, None))
    events.undo_notified(4)
    events.undo_notified(3)
    assert events.generation == 2  # Both count changes show, though the count came back.
    assert events.check(3, (2, "Rename Sheet"), quiet=False) == 2  # Explained by the notes.
    assert events.check(3, (3, "Input"), quiet=False) == 3  # History moved with no note.
    assert events.check(3, (3, "Input"), quiet=True) == 4  # Undo locked or notices off.
    assert events.check(3, None, quiet=False) == 5  # The history could not be read.
    events.undone_or_redone(3)
    assert events.generation == 6
