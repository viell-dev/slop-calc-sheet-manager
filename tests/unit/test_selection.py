"""The sheet list's selection model: picks, cursor, and anchor stay with their sheets.

The workbook here reproduces how LibreOffice behaves, as measured in 26.2 and 26.8
(docs/reordering.md). A retained handle follows its sheet through renames, moves, and
insertions; when its sheet is deleted it turns to the previous sheet (the next one at index 0)
and follows that sheet from then on. Notifications arrive as LibreOffice sends them, each with
the document's state at that moment: every recorded undo action as it happens, before its
modify notification; modify notifications per change, once when a `lockControllers` or
`addActionLock` batch ends, or not at all under `disableSetModified`; nothing for a change while
undo recording is off except its modify notification; an undo context's actions grouped into
one undo step; undo or redo as one action; and saves as modify notifications between save
events. Sheet ids are the ground truth the list never sees.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from sheet_manager.selection import Ref, Selection, structure_kept
from sheet_manager.structure import History, Quiet, StructureEvents


class Handle:
    """A retained sheet handle: it reports the name of the sheet it denotes now."""

    def __init__(self, book: "Book", sheet_id: int) -> None:
        self.book = book
        self.sheet_id = sheet_id
        book.handles.append(self)

    def name(self) -> str:
        return self.book.name_of(self.sheet_id)


Sheets = list[tuple[int, str]]


@dataclass
class Step:
    """One undo step: its title and the sheets and handle targets before it."""

    title: str
    sheets: Sheets
    targets: dict[int, int]
    stale: bool = False  # An unrecorded change came after it: the model does not undo it.
    received: bool = False  # For an open context: whether an action was recorded in it.


@dataclass
class Book:
    names_at_start: list[str]
    sheets: Sheets = field(default_factory=Sheets)
    handles: list[Handle] = field(default_factory=list[Handle])
    undo: list[Step] = field(default_factory=list[Step])
    contexts: list[Step] = field(default_factory=list[Step])
    listeners: list[Callable[[str, Quiet], None]] = field(
        default_factory=list[Callable[[str, Quiet], None]]
    )
    recording: bool = True  # IsUndoEnabled; off also locks the undo manager, as in Calc.
    lock: str | None = None  # "controllers" or "action": modify notifications wait.
    modify_off: bool = False  # disableSetModified.
    pending: bool = False  # A modify notification waiting for the lock to end.
    nested: Callable[[], None] | None = None  # Posted work LibreOffice runs during a save.
    next_id: int = 0

    def __post_init__(self) -> None:
        self.sheets = list(enumerate(self.names_at_start))
        self.next_id = len(self.sheets)

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
        return (len(self.undo), self.undo[-1].title if self.undo else None)

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def unused_name(self, rng: random.Random) -> str:
        while True:
            name = f"S{rng.randrange(1000)}"
            if name not in self.names():
                return name

    def quiet(self) -> Quiet:
        quiet = Quiet.NONE
        if not self.recording:
            quiet |= Quiet.UNDO_OFF | Quiet.UNDO_LOCKED
        if self.lock == "controllers":
            quiet |= Quiet.CONTROLLERS_LOCKED
        if self.lock == "action":
            quiet |= Quiet.ACTION_LOCKED
        if self.modify_off:
            quiet |= Quiet.MODIFY_OFF
        return quiet

    def notify(self, kind: str, quiet: Quiet | None = None) -> None:
        for listener in self.listeners:
            listener(kind, self.quiet() if quiet is None else quiet)

    def _state(self) -> tuple[Sheets, dict[int, int]]:
        return list(self.sheets), {id(h): h.sheet_id for h in self.handles}

    def _modify(self) -> None:
        if self.modify_off:
            return
        if self.lock:
            self.pending = True
        else:
            self.notify("modified")

    def _change(self, title: str, apply: Callable[[], None]) -> None:
        """One change as Calc makes it: recorded (if recording is on), then reported."""
        sheets, targets = self._state()
        apply()
        if self.recording:
            if self.contexts:
                self.contexts[-1].received = True
            else:
                self.undo.append(Step(title, sheets, targets))
            self.notify("added")
        else:
            for step in (*self.undo, *self.contexts):
                step.stale = True
        self._modify()

    # Wrappers, as a program calls them

    def begin_lock(self, kind: str) -> None:
        self.lock = kind

    def enter(self, title: str) -> None:
        self.notify("entered")
        sheets, targets = self._state()
        self.contexts.append(Step(title, sheets, targets))

    def leave(self) -> None:
        step = self.contexts.pop()
        if step.received:
            self.undo.append(step)
        self.notify("left")

    def undo_last(self) -> None:
        """Undo the last step: sheets and handles as before it, reported as one action."""
        if not self.undo or self.undo[-1].stale or self.lock or not self.recording:
            return
        step = self.undo.pop()
        positions = {sheet_id: index for index, (sheet_id, _) in enumerate(self.sheets)}
        self.sheets = step.sheets
        present = {sheet_id for sheet_id, _ in step.sheets}
        for handle in self.handles:
            target = step.targets.get(id(handle), handle.sheet_id)
            if target not in present:  # Its sheet was inserted by the undone step.
                index = min(positions.get(target, 0), len(step.sheets)) - 1
                target = step.sheets[max(index, 0)][0]
            handle.sheet_id = target
        # Measured: Calc turns undo recording off while it undoes.
        self.notify("modified", self.quiet() | Quiet.UNDO_OFF | Quiet.UNDO_LOCKED)
        self.notify("undone")

    def save(self) -> None:
        """Measured: five modify notifications and no undo action, between OnSave and
        OnSaveDone; LibreOffice may run posted work meanwhile, with modify notifications off."""
        self.notify("event:OnSave")
        for _ in range(3):
            self.notify("modified")
        if self.nested is not None:
            self.modify_off = True
            self.nested()
            self.modify_off = False
        for _ in range(2):
            self.notify("modified")
        self.notify("event:OnSaveDone")

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

    def colour(self) -> None:
        self._change("Color Tab", lambda: None)

    def typed_input(self) -> None:
        """A cell edit typed by the user (measured): context, action, modify, left, modify."""
        self.enter("Input")
        self._change("Input", lambda: None)
        self.leave()
        self._modify()


def end_lock(book: Book) -> None:
    """Release the lock as Calc does (measured): lockControllers clears its count before the
    waiting modify notification is sent; addActionLock still holds its lock then."""
    kind, waiting = book.lock, book.pending
    book.pending = False
    if kind == "controllers":
        book.lock = None
    if waiting and not book.modify_off:
        book.notify("modified")
    book.lock = None


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
    """The list's identity logic as uno_list.py and uno_structure.py run it.

    `sampled=False` is the monitor as it was before reading the document's state at each
    notification: the count alone, and every modify notification taken as explained.
    """

    def __init__(self, book: Book, careful: bool = True, sampled: bool = True) -> None:
        self.book = book
        self.careful = careful  # False: only per-ref name checks, as before round 6.
        self.sampled = sampled
        self.selection = Selection(lambda ref: ref.token.name() == ref.name)
        self.events = StructureEvents(count=len(book.sheets), history=book.history())
        book.listeners.append(self.notified)
        self.proven = self.events.generation
        self.rows: list[str] = []
        self.handles: list[Handle] = []
        self.refresh()

    def notified(self, kind: str, quiet: Quiet) -> None:
        count = len(self.book.sheets)  # Read while LibreOffice notifies, as is the state.
        events = self.events
        if not self.sampled:
            quiet = Quiet.NONE
            events.explained = True
        if kind == "modified":
            events.modified(count, quiet)
        elif kind == "added":
            events.action_added(count, quiet)
        elif kind == "entered":
            events.context_entered(count, quiet)
        elif kind == "left":
            events.context_left(count, quiet)
        elif kind in ("undone", "redone"):
            events.undone_or_redone(count)
        elif kind.startswith("event:"):
            events.document_event(kind.removeprefix("event:"))
        else:
            raise AssertionError(kind)

    def check(self) -> int:
        quiet = self.book.quiet() if self.sampled else Quiet.NONE
        return self.events.check(len(self.book.sheets), self.book.history(), quiet)

    def refresh(self) -> None:
        generation = self.check()
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

    def own_move(self, index: int, to: int) -> None:
        """The list's own move, as apply_order makes it: locked, in one undo context."""
        book = self.book
        if self.check() != self.proven or book.lock or not book.recording:
            return  # Refused, as the list and the reorder layer refuse.
        self.events.own_move_started(book.quiet() if self.sampled else Quiet.NONE)
        try:
            book.begin_lock("controllers")
            book.enter("Move Sheets")
            book.move(index, to)
            book.leave()
            end_lock(book)
        finally:
            self.events.own_move_finished()


DELIVERIES = (
    "each",
    "locked_controllers",
    "locked_action",
    "unmodified",
    "context",
    "undo",
    "unrecorded",
    "unrecorded_controllers_after",
    "unrecorded_controllers_before",
    "unrecorded_action_after",
    "unrecorded_action_before",
    "mixed_controllers",
    "mixed_action",
    "typed_input",
    "colour",
    "save",
    "properties",
    "held_controllers",
    "held_action",
)


def edit(book: Book, rng: random.Random, delivery: str) -> None:
    """One random edit, delivered as LibreOffice delivers it under one of the wrappers."""
    if delivery == "undo":
        book.undo_last()
        return
    if delivery == "typed_input":
        book.typed_input()
        return
    if delivery == "colour":
        book.colour()
        return
    if delivery == "save":
        book.save()
        return
    if delivery == "properties":  # Document properties: a modify notification only.
        book.notify("modified")
        return
    changes = random_changes(book, rng)
    if delivery == "silent":  # Out of scope: no undo recording, no modify notification.
        book.recording, book.modify_off = False, True
        for change in changes:
            change()
        book.recording, book.modify_off = True, False
        return
    if delivery == "camouflaged":  # Out of scope: see `structure`.
        book.enter("Input")
        book.colour()
        book.leave()
        delivery = "unrecorded_controllers_before"
    if delivery in ("each", "context", "unmodified", "unrecorded"):
        book.modify_off = delivery == "unmodified"
        book.recording = delivery != "unrecorded"
        if delivery == "context":
            book.enter("Batch")
        for change in changes:
            change()
        if delivery == "context":
            book.leave()
        book.recording, book.modify_off = True, False
        return
    kind = "controllers" if "controllers" in delivery else "action"
    if delivery.startswith("locked"):
        book.begin_lock(kind)
        for change in changes:
            change()
        end_lock(book)
        return
    if delivery.startswith("held"):
        # Unrecorded edits under a lock that stays held after recording comes back on: nothing
        # is reported until a later step releases it (`random_session`), and the list acts
        # meanwhile.
        book.begin_lock(kind)
        book.recording = False
        for change in changes:
            change()
        book.recording = True
        return
    after = delivery.endswith("after")  # Undo recording comes back on after the unlock.
    book.begin_lock(kind)
    book.recording = False
    for change in changes:
        change()
    if delivery.startswith("mixed"):
        book.recording = True
        book.colour()  # One recorded change under the same lock.
    if not after:
        book.recording = True
    end_lock(book)
    book.recording = True


def random_session(
    seed: int,
    careful: bool = True,
    deliveries: tuple[str, ...] = DELIVERIES,
    sampled: bool = True,
) -> list[str]:
    """Random edits, picks, own moves, and refreshes; the violations found after refreshes."""
    rng = random.Random(seed)
    book = Book([f"S{n}" for n in range(rng.randrange(1, 9))])
    sheet_list = List(book, careful, sampled)
    book.nested = sheet_list.refresh if rng.random() < 0.5 else None
    made_for: dict[int, tuple[Ref, int]] = {}  # id(ref) -> (ref, the sheet it was made for)
    violations: list[str] = []
    for _ in range(80):
        step = rng.random()
        if step < 0.35 and book.lock is not None:
            end_lock(book)  # A held batch's lock is released at last.
        elif step < 0.35:
            edit(book, rng, rng.choice(deliveries))
        elif step < 0.4:
            count = len(book.sheets)
            sheet_list.own_move(rng.randrange(count), rng.randrange(count))
        elif step < 0.6:
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

    The deliveries: edits one by one; in lockControllers or addActionLock batches with one
    modify notification; under disableSetModified with none; grouped in undo contexts; undone;
    made with undo recording off, one by one or in either lock with recording turned back on
    after or before the unlock; recorded and unrecorded under one lock; and among typed cell
    edits, tab colours, saves with and without posted work inside, document property changes,
    and the list's own moves.
    """
    violations = [found for seed in range(500) for found in random_session(seed)]
    assert violations == [], violations[:5]


def test_name_checks_alone_hand_picks_to_other_sheets():
    """The workbook reproduces the retargeting: per-ref name checks alone are fooled."""
    violations = [found for seed in range(500) for found in random_session(seed, careful=False)]
    assert violations, "The model should reproduce a deleted handle reporting a reused name"


def test_the_count_alone_misses_unrecorded_batches():
    """The model reproduces round 7's gap: without the state, an unrecorded batch passes."""
    unrecorded = ("unrecorded_controllers_after", "unrecorded_controllers_before", "each")
    violations = [
        found
        for seed in range(500)
        for found in random_session(seed, deliveries=unrecorded, sampled=False)
    ]
    assert violations, "Reading only the count should miss a batch made with undo off"


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


def test_camouflaged_batches_are_out_of_scope():
    """Documented limit: a batch built to report like typed input is not seen (`structure`).

    A recorded edit inside an undo context, then unrecorded structural edits inside a lock with
    recording back on before the unlock: the one modify notification follows an undo context
    that received an action, as typed input's second one does.
    """
    violations = [
        found for seed in range(500) for found in random_session(seed, deliveries=("camouflaged",))
    ]
    assert violations, "Camouflaged batches are expected to go unseen; see the docstring"


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


def batch(book: Book, kind: str, recording: str = "on", mixed: bool = False) -> None:
    """`cover` inside one lock; `recording` "on", or "off" until "after" or "before" unlock."""
    book.begin_lock(kind)
    book.recording = recording == "on"
    cover(book)
    if mixed:
        book.recording = True
        book.colour()
    if recording == "before":
        book.recording = True
    end_lock(book)
    book.recording = True


def test_actions_while_a_batch_is_open_find_nothing():
    """A lock still held may be holding back a whole batch's report: the list acts on nothing.

    The batch ran with undo recording off inside an inner lock, recording came back on, and only
    the inner lock was released, so LibreOffice has reported nothing yet (round 8's review).
    """
    for kind in ("controllers", "action"):
        book = Book(["Alfa", "Bravo", "Charlie"])
        sheet_list = picked_bravo(book)
        book.begin_lock(kind)
        book.recording = False
        cover(book)
        book.recording = True
        assert sheet_list.selection.picked[0].token.name() == "Bravo"  # The handle is fooled.
        assert sheet_list.check() != sheet_list.proven, kind  # Enter, a click, the menu refuse.
        sheet_list.refresh()
        assert sheet_list.selection.picked == [], kind
        end_lock(book)  # The report arrives at last.
        sheet_list.refresh()
        assert sheet_list.selection.picked == [], kind


def test_a_locked_batch_drops_the_pick():
    """lockControllers: one modify notification at the end, with the original count."""
    for kind in ("controllers", "action"):
        book = Book(["Alfa", "Bravo", "Charlie"])
        sheet_list = picked_bravo(book)
        batch(book, kind)
        sheet_list.refresh()
        assert sheet_list.selection.picked == [], kind


def test_unrecorded_batches_drop_the_pick():
    """Undo recording off inside either lock, back on after or before the unlock (#28)."""
    for kind in ("controllers", "action"):
        for recording in ("after", "before"):
            for mixed in (False, True):
                book = Book(["Alfa", "Bravo", "Charlie"])
                sheet_list = picked_bravo(book)
                batch(book, kind, recording, mixed)
                assert len(book.undo) == (1 if mixed else 0)
                sheet_list.refresh()
                assert sheet_list.selection.picked == [], (kind, recording, mixed)


def test_an_unmodified_batch_drops_the_pick():
    """disableSetModified: no modify notification; the undo notifications still come."""
    book = Book(["Alfa", "Bravo", "Charlie"])
    sheet_list = picked_bravo(book)
    book.modify_off = True
    cover(book)
    book.modify_off = False
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


def test_undoing_a_context_undoes_all_of_it():
    """A caller's undo context is one step: undoing it restores every sheet and handle."""
    book = Book(["Alfa", "Bravo", "Charlie"])
    sheet_list = picked_bravo(book)
    bravo = sheet_list.selection.picked[0]
    book.enter("Batch")
    cover(book)
    book.leave()
    assert [step.title for step in book.undo] == ["Batch"]
    book.undo_last()
    assert book.names() == ["Alfa", "Bravo", "Charlie"] and bravo.token.sheet_id == 1
    sheet_list.refresh()
    assert sheet_list.selection.picked == []  # Undo could have been anything.


def test_ordinary_changes_keep_the_picks():
    """Typed input, tab colours, saves, and the list's own moves keep the picks."""
    book = Book(["Alfa", "Bravo", "Charlie", "Delta"])
    sheet_list = List(book)
    sheet_list.selection.take(["Bravo", "Delta"], sheet_list.tokens(), sheet_list.rows)
    for change in (
        book.typed_input,
        book.colour,
        book.save,
        lambda: sheet_list.own_move(1, 3),
        lambda: book.move(0, 2),  # A recorded move by another program.
    ):
        change()
        sheet_list.refresh()
        assert sheet_list.selection.names() == ["Bravo", "Delta"], change
    book.nested = sheet_list.refresh  # A refresh inside the save, with modify notices off.
    book.save()
    sheet_list.refresh()
    assert sheet_list.selection.names() == ["Bravo", "Delta"]


def test_unexplained_modifications_drop_the_picks():
    """A modify notification no undo action explains, outside a save, could be anything."""
    book = Book(["Alfa", "Bravo", "Charlie"])
    sheet_list = picked_bravo(book)
    book.notify("modified")  # Document properties, or a batch released after undo came on.
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
    quiet = Quiet.NONE
    events = StructureEvents(count=3, history=(0, None))
    events.action_added(4, quiet)
    events.action_added(3, quiet)
    assert events.generation == 2  # Both count changes show, though the count came back.
    assert events.check(3, (2, "Rename Sheet"), quiet) == 2  # Explained by the notes.
    assert events.check(3, (3, "Input"), quiet) == 3  # History moved with no note.
    assert events.check(3, (3, "Input"), Quiet.UNDO_LOCKED) == 4  # Undo locked at a check.
    assert events.check(3, None, quiet) == 5  # The history could not be read.
    events.undone_or_redone(3)
    assert events.generation == 6
    events.action_added(3, quiet)
    events.modified(3, quiet)
    assert events.generation == 6  # Explained by the action.
    events.modified(3, quiet)
    assert events.generation == 7  # Not explained.
    events.action_added(3, Quiet.CONTROLLERS_LOCKED)
    assert events.generation == 8  # Recorded inside a lock.
    events.modified(3, None)
    assert events.generation == 9  # The state could not be read.
    events.check(3, (3, "Input"), Quiet.NONE)
    assert events.check(3, (3, "Input"), Quiet.CONTROLLERS_LOCKED) == 10  # A lock held now.
    assert events.check(3, (3, "Input"), Quiet.ACTION_LOCKED) == 11
    events.own_move_started(Quiet.NONE)
    assert events.check(3, (3, "Input"), Quiet.CONTROLLERS_LOCKED) == 11  # The list's own.
    events.own_move_finished()


def test_structure_events_save_windows():
    events = StructureEvents(count=3, history=(0, None))
    events.document_event("OnSave")
    events.modified(3, Quiet.NONE)
    assert events.check(3, (0, None), Quiet.MODIFY_OFF) == 0  # LibreOffice's own, mid-save.
    events.modified(3, Quiet.NONE)
    events.document_event("OnSaveDone")
    assert events.generation == 0
    events.modified(3, Quiet.NONE)
    assert events.generation == 1  # The window is closed.
    events.document_event("OnSaveAs")
    events.modified(3, Quiet.UNDO_OFF)
    assert events.generation == 2  # The state counts inside a window too.
    events.action_added(3, Quiet.NONE)  # A window left open ends at an undo notification.
    events.modified(3, Quiet.NONE)
    events.modified(3, Quiet.NONE)
    assert events.generation == 3


def test_structure_events_own_move():
    """The list's own move locks the controllers; someone else's lock still counts."""
    events = StructureEvents(count=3, history=(0, None))
    events.own_move_started(Quiet.NONE)
    events.context_entered(3, Quiet.CONTROLLERS_LOCKED)
    events.action_added(3, Quiet.CONTROLLERS_LOCKED)
    events.context_left(3, Quiet.CONTROLLERS_LOCKED)
    events.modified(3, Quiet.NONE)
    events.own_move_finished()
    assert events.generation == 0
    events.own_move_started(Quiet.ACTION_LOCKED)
    events.own_move_finished()
    assert events.generation == 1


def test_structure_events_contexts():
    """Typed input's second modify notification follows its context; an empty one explains none."""
    events = StructureEvents(count=3, history=(0, None))
    for report in (
        lambda: events.context_entered(3, Quiet.NONE),
        lambda: events.action_added(3, Quiet.NONE),
        lambda: events.modified(3, Quiet.NONE),
        lambda: events.context_left(3, Quiet.NONE),
        lambda: events.modified(3, Quiet.NONE),
    ):
        report()
    assert events.generation == 0
    events.context_entered(3, Quiet.NONE)
    events.context_left(3, Quiet.NONE)
    events.history_cleared(3, Quiet.NONE)
    events.modified(3, Quiet.NONE)
    assert events.generation == 1
