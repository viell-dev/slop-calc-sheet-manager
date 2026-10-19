"""The sheet list's selection model: picks, cursor, and anchor stay with their sheets."""

import random

from sheet_manager.selection import Ref, Selection

Sheets = list[tuple[int, str]]


class Book:
    """A workbook in miniature: sheets with stable ids, ordered, each with a unique name.

    A sheet's id plays the part of the retained handle: it always denotes the sheet it was
    taken from, which is the property the list relies on (see selection.py).
    """

    def __init__(self, names: list[str]) -> None:
        self.sheets: Sheets = [(index, name) for index, name in enumerate(names)]
        self.next_id = len(names)

    def names(self) -> list[str]:
        return [name for _, name in self.sheets]

    def tokens(self) -> dict[str, int]:
        return {name: sheet_id for sheet_id, name in self.sheets}

    def name_of(self, sheet_id: int) -> str | None:
        return next((name for known, name in self.sheets if known == sheet_id), None)

    def current(self, ref: Ref) -> bool:
        return self.name_of(ref.token) == ref.name

    def unused_name(self, rng: random.Random) -> str:
        while True:
            name = f"S{rng.randrange(1000)}"
            if name not in self.names():
                return name

    def change(self, rng: random.Random) -> str:
        """One random change of the kinds a user, macro, or other window makes."""
        kind = rng.choice(["rename", "move", "delete", "insert", "replace", "reuse"])
        if kind == "insert" or not self.sheets:
            place = rng.randrange(len(self.sheets) + 1)
            self.sheets.insert(place, (self.new_id(), self.unused_name(rng)))
            return kind
        index = rng.randrange(len(self.sheets))
        sheet_id, name = self.sheets[index]
        if kind == "rename":
            self.sheets[index] = (sheet_id, self.unused_name(rng))
        elif kind == "move":
            self.sheets.pop(index)
            self.sheets.insert(rng.randrange(len(self.sheets) + 1), (sheet_id, name))
        elif kind == "delete" and len(self.sheets) > 1:
            self.sheets.pop(index)
        elif kind == "replace":
            # Delete a sheet and insert a different one with the same name at the same place.
            self.sheets[index] = (self.new_id(), name)
        elif kind == "reuse" and len(self.sheets) > 1:
            # Rename a sheet and give its name to another.
            other = rng.choice([i for i in range(len(self.sheets)) if i != index])
            other_id, _ = self.sheets[other]
            self.sheets[index] = (sheet_id, self.unused_name(rng))
            self.sheets[other] = (other_id, name)
        return kind

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id


def resolves_to_own_sheet(book: Book, ref: Ref) -> bool:
    """The sheet the list would act on for this ref, by name, is the sheet the ref was made for."""
    return book.tokens().get(ref.name) == ref.token


def test_picks_never_pass_to_another_sheet():
    """Random edits, picks, and refreshes: nothing held ever resolves to another sheet.

    Each ref is recorded with the sheet its row showed when the user's input created it. The
    list resolves a held ref by its name only after revalidating it, at a refresh or right
    before an action; at those points every held ref must be one created by a pick, and its
    name must lead to that same sheet.
    """
    for seed in range(400):
        random_session(seed)


def random_session(seed: int) -> None:
    rng = random.Random(seed)
    book = Book([f"S{n}" for n in range(rng.randrange(1, 9))])
    selection = Selection(book.current)
    made_for: dict[int, tuple[Ref, int]] = {}  # id(ref) -> (ref, the sheet it was made for)
    shown_names, shown_tokens = book.names(), book.tokens()  # What the rows show.
    for _ in range(60):
        step = rng.random()
        if step < 0.35:
            book.change(rng)  # The document changes; the rows show it only at a refresh.
        elif step < 0.55:
            selection.revalidate()  # A refresh, or the check before an action.
            for ref in held(selection):
                assert id(ref) in made_for, (seed, "a ref no pick created", ref)
                assert book.tokens().get(ref.name) == made_for[id(ref)][1], (seed, ref)
            shown_names, shown_tokens = book.names(), book.tokens()
        elif step < 0.8 and shown_names:
            # The user picks rows as they show, possibly before a refresh.
            picked = sorted(rng.sample(shown_names, rng.randrange(len(shown_names) + 1)))
            selection.take(picked, shown_tokens, shown_names)
            record(selection, made_for, shown_tokens)
        elif shown_names:
            name = rng.choice(shown_names)
            target = "cursor" if rng.random() < 0.5 else "anchor"
            setattr(selection, target, selection.ref(name, shown_tokens, shown_names))
            record(selection, made_for, shown_tokens)


def record(
    selection: Selection, made_for: dict[int, tuple[Ref, int]], shown: dict[str, int]
) -> None:
    """Note the sheet each newly created ref was made for: the one its row showed."""
    for ref in held(selection):
        if id(ref) not in made_for:
            made_for[id(ref)] = (ref, shown[ref.name])


def held(selection: Selection) -> list[Ref]:
    return [ref for ref in (*selection.picked, selection.cursor, selection.anchor) if ref]


def test_current_picks_survive_a_refresh():
    for seed in range(200):
        rng = random.Random(seed)
        book = Book([f"S{n}" for n in range(6)])
        selection = Selection(book.current)
        selection.take(sorted(rng.sample(book.names(), 3)), book.tokens(), book.names())
        before = list(selection.picked)
        for _ in range(rng.randrange(4)):
            book.change(rng)
        selection.revalidate()
        assert selection.picked == [ref for ref in before if book.current(ref)], seed


def test_follow_then_replace_keeps_the_newer_pick():
    """Hold Bravo, Calc goes to Delta and the list follows, Bravo is replaced (#28)."""
    book = Book(["Alfa", "Bravo", "Charlie", "Delta"])
    selection = Selection(book.current)
    selection.take(["Bravo"], book.tokens(), book.names())  # The press.
    selection.take(["Delta"], book.tokens(), book.names())  # Following Calc.
    index = book.names().index("Bravo")
    book.sheets[index] = (book.new_id(), "Bravo")  # The replacement.
    selection.revalidate()
    assert selection.names() == ["Delta"]
    # Restoring after the voided release writes these picks back: never the replacement.
    assert all(resolves_to_own_sheet(book, ref) for ref in selection.picked)


def test_keyboard_pick_then_replace_keeps_the_keyboard_pick():
    """Hold Bravo, move it, type to pick Delta, replace Bravo (#28)."""
    book = Book(["Alfa", "Bravo", "Charlie", "Delta", "Echo"])
    selection = Selection(book.current)
    selection.take(["Bravo"], book.tokens(), book.names())  # The press.
    bravo = book.sheets.pop(1)
    book.sheets.insert(4, bravo)  # The move; the refresh keeps Bravo picked.
    selection.revalidate()
    assert selection.names() == ["Bravo"]
    delta = selection.ref("Delta", book.tokens(), book.names())  # Type-ahead.
    selection.picked, selection.cursor = [delta] if delta else [], delta
    index = book.names().index("Bravo")
    book.sheets[index] = (book.new_id(), "Bravo")
    selection.revalidate()
    assert selection.names() == ["Delta"] and selection.cursor is delta


def test_a_stale_held_ref_is_not_renewed_for_a_replacement():
    book = Book(["Alfa", "Bravo"])
    selection = Selection(book.current)
    selection.take(["Bravo"], book.tokens(), book.names())
    old = selection.picked[0]
    book.sheets[1] = (book.new_id(), "Bravo")
    # The rows still show the old Bravo: a take before the refresh keeps the stale ref ...
    selection.take(["Bravo"], {"Alfa": 0, "Bravo": old.token}, ["Alfa", "Bravo"])
    assert selection.picked[0].token == old.token
    # ... and the refresh drops it rather than handing the pick to the replacement.
    assert selection.revalidate() and selection.picked == []
