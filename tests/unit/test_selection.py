"""The sheet list's selection model: picks, cursor, and anchor stay with their sheets.

The workbook here reproduces how LibreOffice's retained sheet handles behave, as measured in
26.2 and 26.8 (docs/reordering.md): a handle follows its sheet through renames, moves, and
insertions, and when its sheet is deleted it turns to the previous sheet (the next one at
index 0) and follows that sheet from then on. Sheet ids are the ground truth the list never
sees.
"""

import random
from collections.abc import Callable

from sheet_manager.selection import Ref, Selection, StructureWatch, structure_kept


class Handle:
    """A retained sheet handle: it reports the name of the sheet it denotes now."""

    def __init__(self, book: "Book", sheet_id: int) -> None:
        self.book = book
        self.sheet_id = sheet_id
        book.handles.append(self)

    def name(self) -> str:
        return self.book.name_of(self.sheet_id)


class Book:
    def __init__(self, names: list[str]) -> None:
        self.sheets: list[tuple[int, str]] = list(enumerate(names))
        self.next_id = len(names)
        self.handles: list[Handle] = []

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

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def unused_name(self, rng: random.Random) -> str:
        while True:
            name = f"S{rng.randrange(1000)}"
            if name not in self.names():
                return name

    # Each primitive below is one change as Calc reports it.

    def insert(self, index: int, name: str) -> None:
        self.sheets.insert(index, (self.new_id(), name))

    def delete(self, index: int) -> None:
        deleted, _ = self.sheets.pop(index)
        fallback = self.sheets[max(index - 1, 0)][0]  # Measured: the previous sheet.
        for handle in self.handles:
            if handle.sheet_id == deleted:
                handle.sheet_id = fallback

    def rename(self, index: int, name: str) -> None:
        self.sheets[index] = (self.sheets[index][0], name)

    def move(self, index: int, to: int) -> None:
        self.sheets.insert(to, self.sheets.pop(index))


Change = Callable[[], None]


def random_changes(book: Book, rng: random.Random) -> list[Change]:
    """One random edit, as the separate changes Calc reports for it."""
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
    if kind == "delete_rename" and index > 0:  # The reviewed sequence: the previous sheet
        previous = index - 1  # takes the deleted sheet's name.
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
    """The list's identity logic as uno_list.py runs it, against the workbook above."""

    def __init__(self, book: Book, careful: bool = True) -> None:
        self.book = book
        self.careful = careful  # False: only per-ref name checks, as before round 6.
        self.selection = Selection(lambda ref: ref.token.name() == ref.name)
        self.watch = StructureWatch()
        self.refresh()

    def refresh(self) -> None:
        if hasattr(self, "rows"):
            reported: list[str | None] = [handle.name() for handle in self.handles]
            proved = not self.watch.changed and structure_kept(
                self.rows, reported, self.book.names()
            )
            if self.careful and not proved:
                self.selection.clear()
            else:
                self.selection.revalidate()
        self.rows = self.book.names()
        self.handles = [self.book.handle(name) for name in self.rows]
        self.watch.settle(len(self.rows))

    def tokens(self) -> dict[str, Handle]:
        return dict(zip(self.rows, self.handles, strict=True))

    def changed(self) -> None:
        self.watch.note(len(self.book.sheets))


def random_session(seed: int, careful: bool = True) -> list[str]:
    """Random edits, picks, and refreshes; the violations found after refreshes."""
    rng = random.Random(seed)
    book = Book([f"S{n}" for n in range(rng.randrange(1, 9))])
    sheet_list = List(book, careful)
    made_for: dict[int, tuple[Ref, int]] = {}  # id(ref) -> (ref, the sheet it was made for)
    violations: list[str] = []
    for _ in range(80):
        step = rng.random()
        if step < 0.35:
            for change in random_changes(book, rng):
                change()
                sheet_list.changed()  # Calc reports each change as it happens.
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
    """Nothing the list holds after a refresh names a sheet it was not picked as."""
    violations = [found for seed in range(500) for found in random_session(seed)]
    assert violations == [], violations[:5]


def test_name_checks_alone_hand_picks_to_other_sheets():
    """The workbook reproduces the retargeting: per-ref name checks alone are fooled."""
    violations = [found for seed in range(500) for found in random_session(seed, careful=False)]
    assert violations, "The model should reproduce a deleted handle reporting a reused name"


def test_the_reviewed_sequence_drops_the_pick():
    """Only Bravo picked; Bravo deleted and Alfa renamed to Bravo (#28)."""
    book = Book(["Alfa", "Bravo", "Charlie", "Delta"])
    sheet_list = List(book)
    sheet_list.selection.take(["Bravo"], sheet_list.tokens(), sheet_list.rows)
    bravo = sheet_list.selection.picked[0]
    book.delete(1)
    sheet_list.changed()
    book.rename(0, "Bravo")
    sheet_list.changed()
    assert bravo.token.name() == "Bravo"  # The handle is fooled ...
    sheet_list.refresh()
    assert sheet_list.selection.picked == []  # ... the list is not.


def test_a_kept_count_still_drops_the_pick():
    """Insert before Bravo, delete Bravo, rename the newcomer to Bravo: the count is kept."""
    book = Book(["Alfa", "Bravo", "Charlie"])
    sheet_list = List(book)
    sheet_list.selection.take(["Bravo"], sheet_list.tokens(), sheet_list.rows)
    for change in (
        lambda: book.insert(1, "Newcomer"),
        lambda: book.delete(2),
        lambda: book.rename(1, "Bravo"),
    ):
        change()
        sheet_list.changed()
    rows, handles = sheet_list.rows, sheet_list.handles
    reported: list[str | None] = [handle.name() for handle in handles]
    assert structure_kept(rows, reported, book.names())  # The end state alone looks unchanged.
    sheet_list.refresh()
    assert sheet_list.selection.picked == []


def test_moves_and_one_rename_keep_the_other_picks():
    book = Book(["Alfa", "Bravo", "Charlie", "Delta"])
    sheet_list = List(book)
    sheet_list.selection.take(["Bravo", "Delta"], sheet_list.tokens(), sheet_list.rows)
    book.move(1, 3)
    sheet_list.changed()
    book.rename(book.names().index("Delta"), "Echo")
    sheet_list.changed()
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


def test_watch_sees_changes_that_cancel_out():
    watch = StructureWatch()
    watch.settle(3)
    watch.note(4)
    watch.note(3)
    assert watch.changed
    watch.settle(3)
    watch.note(3)
    assert not watch.changed
