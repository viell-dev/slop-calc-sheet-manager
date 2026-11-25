"""Sequences of clicks and keys over the simulated tree, whose presses follow VCL's (#328).

At human speed, each input's work has run and VCL has painted before the next: the list must then
pick exactly what the gestures mean, with no notice, and the tree must show it. The inputs are
clicks on the labels, in the gutter and below the rows, with any button, selection keys, drags
dropped in place or cancelled, and renames by another window. That is checked against a plain model
of the gestures, for every pair of inputs and for random longer sequences. 0.0.11 cleared the
selection at a Shift+click that shrank or crossed a range, and no test saw it, because the simulated
Shift press selected its row alone (#349); after a drag, it cleared the selection at any click with
a modifier and took the row where the drag began at one in the gutter, because VCL's engine acted on
that click's release as on the drag's (#356); and other range presses were refused after another
window renamed a picked sheet (#321).

While LibreOffice is busy, the listeners and the list's posted work lag behind what the tree has
handled. The list may then refuse an input, with the notice unless there was nothing to clear, but
the picks, what the tree shows and what a command moves must agree once everything has run, and
without a refusal they must be those of a list that never lags. Beyond these draws, the result can
differ without one where the tree itself showed another selection for a moment, as after four
clicks in flight, or a range press handled before a rebuild on a list that has no anchor; the list
then shows what it picked. Assistive selections are not drawn: #323 and #334 record what they can
still do within one pass of the event queue.
"""

import itertools
import random
from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.unit.list_peer import (
    DOWN,
    END,
    HIT_X,
    HOME,
    LABEL_X,
    LEFT,
    MIDDLE,
    MOD1,
    RIGHT,
    SHIFT,
    SPACE,
    UP,
    A,
    Book,
    bind_drag,
    changed,
    drag,
    key,
    move_to_top,
    paint,
    picks,
    press,
    queued_click,
    record_activations,
    record_menus,
    release,
    sheet_list,
)

CTRL_SHIFT = MOD1 | SHIFT
CLICKS = (0, MOD1, SHIFT, CTRL_SHIFT)
KEYS = [
    *((code, modifiers) for code in (UP, DOWN) for modifiers in CLICKS),
    (HOME, 0),
    (END, SHIFT),
    (SPACE, MOD1),
    (A, MOD1),
]
# A row and the modifiers, or a key's code and its own. "cancel" is a drag that Esc ends.
Input = tuple[str, int, int]
# Clicks that leave the picks and the cursor as they are.
IDLE = ("below", "right", "middle")


def inputs(rows: int) -> list[Input]:
    return [
        *(
            (kind, row, modifiers)
            for kind in ("click", "gutter")
            for row in range(rows)
            for modifiers in CLICKS
        ),
        *(("below", rows, modifiers) for modifiers in CLICKS),
        *((kind, row, 0) for kind in ("double", "right", "middle") for row in range(rows)),
        *(("key", code, modifiers) for code, modifiers in KEYS),
        *(("rename", row, 0) for row in range(rows)),
        *((kind, row, 0) for kind in ("drag", "cancel") for row in range(rows)),
    ]


@dataclass
class Gestures:
    """What the gestures mean, one at a time, for sheets numbered in row order."""

    rows: int
    picked: set[int] = field(default_factory=set[int])
    cursor: int = 0
    anchor: int | None = None

    def give(self, kind: str, at: int, modifiers: int) -> None:
        if kind in IDLE:
            return
        if kind == "rename":
            # A renamed pick goes, and the next range starts at the cursor, which stays.
            if at in self.picked:
                self.picked.remove(at)
                self.anchor = None
            return
        if kind in ("drag", "cancel") and at in self.picked:
            self.cursor = self.anchor = at  # The picks stay, so that they are dragged together.
            return
        if kind == "key" and at == A:
            self.picked = set(range(self.rows))
            return
        if kind == "key" and at == SPACE:
            at, modifiers = self.cursor, MOD1
        elif kind == "key":
            at = {UP: self.cursor - 1, DOWN: self.cursor + 1, HOME: 0, END: self.rows - 1}[at]
            at = max(0, min(self.rows - 1, at))
            if modifiers == MOD1:
                self.cursor = self.anchor = at
                return
        if modifiers & SHIFT:
            self.anchor = self.cursor if self.anchor is None else self.anchor
            first, last = sorted((self.anchor, at))
            ranged = set(range(first, last + 1))
            self.picked = self.picked | ranged if modifiers & MOD1 else ranged
        else:
            self.anchor = at
            self.picked = self.picked ^ {at} if modifiers & MOD1 else {at}
        self.cursor = at


def opened(rows: int) -> Any:
    owner = sheet_list(Book([f"Sheet {row}" for row in range(rows)]))
    record_activations(owner)
    record_menus(owner)
    opened_menu = owner._open_menu

    def open_menu(*arguments: Any, **keywords: Any) -> None:
        opened_menu(*arguments, **keywords)
        owner._context_target = None  # As when the menu closes.

    owner._open_menu = open_menu
    bind_drag(owner)
    paint(owner)
    return owner


def give(owner: Any, kind: str, at: int, modifiers: int, lag: bool = False) -> None:
    """The input; with `lag`, a click whose release VCL handles before its press's listener runs,
    rather than after the press's work has, as a person's comes."""
    if kind in ("click", "gutter", "double", *IDLE):
        button = {"right": RIGHT, "middle": MIDDLE}.get(kind, LEFT)
        x = HIT_X - 1 if kind == "gutter" else LABEL_X
        for clicks in (1, 2) if kind == "double" else (1,):
            if lag:
                queued_click(owner, at, modifiers, clicks, button, x)
                continue
            press(owner, at, button, modifiers, clicks, x)
            owner.run_queue()
            release(owner, at, button)
            owner.run_queue()
    elif kind == "key":
        key(owner, at, modifiers)
    elif kind in ("drag", "cancel"):
        drag(owner, at, cancel=kind == "cancel")
    else:
        sheet = owner.book.sheets[at]
        owner.book.rename(sheet.name, sheet.name + "'")
        changed(owner)


def settle(owner: Any) -> None:
    """Run the posted work and the refresh that is due, and paint, as between two inputs of a
    person."""
    owner.run_queue()
    owner.retry()
    paint(owner)
    owner.run_queue()


def check_settled(sequence: tuple[Input, ...], rows: int, lag: bool = False) -> None:
    owner, wanted = opened(rows), Gestures(rows)
    for step, (kind, at, modifiers) in enumerate(sequence):
        give(owner, kind, at, modifiers, lag)
        settle(owner)
        wanted.give(kind, at, modifiers)
        names = [owner.book.names()[row] for row in sorted(wanted.picked)]
        given = sequence[: step + 1]
        assert picks(owner) == names == owner.tree.shown(), given
        assert owner.notices == [], given


def test_every_pair_of_inputs_at_human_speed_picks_what_it_means() -> None:
    for pair in itertools.product(inputs(4), repeat=2):
        check_settled(pair, 4)


def test_every_input_after_a_drag_of_picked_rows_acts_on_the_picks() -> None:
    """Two picked rows, a drag of either, and any input: VCL's engine still waits for the release
    that the drag took, and acts on the next one, whichever press that ends (#356)."""
    for first, second in itertools.permutations(range(3), 2):
        for how, source in itertools.product(("drag", "cancel"), (first, second)):
            start = (("click", first, 0), ("click", second, MOD1), (how, source, 0))
            for item in inputs(3):
                check_settled((*start, item), 3)


def test_every_range_corrected_by_shift_clicks_is_picked() -> None:
    """A click and two Shift+clicks: the second moves the range's end, also inwards and across
    its start (#349)."""
    for first, end, corrected in itertools.product(range(6), repeat=3):
        check_settled((("click", first, 0), ("click", end, SHIFT), ("click", corrected, SHIFT)), 6)


def test_every_range_after_a_rename_of_a_picked_sheet_is_picked() -> None:
    """A click, a Ctrl+click and a Ctrl+Shift+click, another window's rename of a sheet, and a
    Shift+click or Ctrl+Shift+click (#321)."""
    for first, second, end, renamed in itertools.product(range(5), repeat=4):
        start = (("click", first, 0), ("click", second, MOD1), ("click", end, CTRL_SHIFT))
        for modifiers in (SHIFT, CTRL_SHIFT):
            check_settled((*start, ("rename", renamed, 0), ("click", (end + 2) % 5, modifiers)), 5)


@pytest.mark.parametrize("seed", range(4))
def test_random_longer_sequences_at_human_speed_pick_what_they_mean(seed: int) -> None:
    draws = random.Random(seed)
    for _ in range(100):
        sequence = tuple(draws.choices(inputs(8), k=draws.randint(3, 9)))
        check_settled(sequence, 8)
        # Quick clicks, but not after a drag, whose effect on a later release (#356) the list then
        # cannot tell from that click's press: it refuses.
        check_settled(
            tuple(item for item in sequence if item[0] not in ("drag", "cancel")), 8, True
        )


def refusals(owner: Any) -> list[str]:
    """Record each time the list drops its picks or refuses a press or a key."""
    recorded: list[str] = []

    def record(name: str) -> None:
        method = getattr(owner, name)

        def recording(*arguments: Any, **keywords: Any) -> Any:
            recorded.append(name)
            return method(*arguments, **keywords)

        setattr(owner, name, recording)

    for name in ("_toggle_held_off", "_drop_picks", "_drop_all_picks"):
        record(name)
    return recorded


def run_some(owner: Any, draws: random.Random) -> None:
    """Run a few of the posted items, in order except that VCL can run the next listener early,
    in a callback event of the window still queued (`VCLXWindowImpl::callBackAsync`)."""
    for _ in range(draws.choice((0, 0, 1, 2, 3, 9))):
        listeners = [
            index
            for index, (_, where) in enumerate(owner.queue)
            if where in ("a mouse press", "a mouse release")
        ]
        if not owner.queue:
            return
        early = draws.random() < 0.3 and listeners
        work, _ = owner.queue.pop(listeners[0] if early else 0)
        work()
    if draws.random() < 0.3:
        paint(owner)


@pytest.mark.parametrize("seed", range(4))
def test_lagging_input_acts_as_at_human_speed_or_is_refused(seed: int) -> None:
    """After a click, so that the list has an anchor: clicks whose listeners and work lag, with
    refreshes that rebuild the rows between, and keys, which are typed once that work has run."""
    draws = random.Random(seed)
    for case in range(100):
        sequence = [
            draws.choice(inputs(8)) if draws.random() < 0.9 else ("recolour", draws.randrange(8), 0)
            for _ in range(draws.randint(2, 5))
        ]
        sequence = [item for item in sequence if item[0] not in ("rename", "drag", "cancel")]
        lagging, prompt = opened(8), opened(8)
        for owner in (lagging, prompt):
            give(owner, "click", 3, 0)
            settle(owner)
        refused = refusals(lagging)
        for kind, at, modifiers in sequence:
            for owner in (lagging, prompt):
                if kind == "recolour":
                    owner.book.sheets[at].color = (owner.book.sheets[at].color or 0) + 1
                    owner.post(owner.refresh, "refreshing the sheet list")
                    continue
                if kind == "key":
                    owner.run_queue()
                give(owner, kind, at, modifiers, lag=True)
            run_some(lagging, draws)
            settle(prompt)
        settle(lagging)
        where = (seed, case, sequence)
        assert picks(lagging) == lagging.tree.shown(), where
        assert refused or picks(lagging) == picks(prompt), where
        assert (move_to_top(lagging) or []) == picks(lagging), where
