"""What ordinary gestures in the sheet list mean: the reference the random walk compares with.

The selection rules are `tests/unit/test_input_sequences.py`'s `Gestures` (repository commit
9b2658f), ported from row numbers to sheet names so that the picks, the keyboard cursor and the
range anchor follow their sheets when sheets move. Extensions, from `docs/reordering.md` and the
user guide `docs/guide/use.md`:

- A move (Top, Up, Down, Bottom by button or Alt+key, or a drop at a gap) sets the order to
  `reorder.target_order` of the picks and keeps the picks; a plan that changes nothing changes
  nothing and adds no undo step. The cursor and the anchor stay on their sheets, which the list
  holds as references (`uno_list`, `Selection.cursor`).
- Undo (Ctrl+Z) of the list's own move puts the previous order back and keeps the picks and the
  view. The walk gives Ctrl+Z only while the newest undo step is a list move that nothing has
  followed.
- A double click picks its row alone, as a plain click, and makes its sheet the viewed one.
- Wheel scrolling, right clicks closed with Esc, middle clicks and clicks below the rows change
  nothing.
- A rename by another window drops a renamed pick and the anchor (`Gestures.give("rename")`); the
  cursor stays on its row under the new name.
"""

from sheet_manager.reorder import Sheet, target_order

SHIFT, MOD1 = 1, 2  # com.sun.star.awt.KeyModifier, as in tests/unit/list_peer.py.
KEY_CODES = ("Up", "Down", "Home", "End", "space", "a")


class Model:
    def __init__(self, order, active):
        self.order = list(order)
        self.picked = set()
        self.cursor = self.order[0]
        self.anchor = None
        self.active = active
        # ("move", order before) for each list move still undoable by the walk, ("blocked",)
        # once anything else came after it.
        self.undo = []

    # Reading

    def row(self, name):
        return self.order.index(name)

    def picks(self):
        return [name for name in self.order if name in self.picked]

    def state(self):
        return {
            "picks": self.picks(),
            "cursor": self.cursor,
            "anchor": self.anchor,
            "active": self.active,
        }

    def can_undo(self):
        return bool(self.undo) and self.undo[-1][0] == "move"

    def target(self, action, gap=None):
        return list(target_order([Sheet(name) for name in self.order], self.picks(), action, gap))

    # Gestures

    def select(self, at, modifiers):
        """A click on row `at` with `modifiers`, or a key that resolved to that row."""
        if modifiers & SHIFT:
            if self.anchor is None:
                self.anchor = self.cursor
            first, last = sorted((self.row(self.anchor), at))
            ranged = set(self.order[first : last + 1])
            self.picked = self.picked | ranged if modifiers & MOD1 else ranged
        else:
            name = self.order[at]
            self.anchor = name
            self.picked = self.picked ^ {name} if modifiers & MOD1 else {name}
        self.cursor = self.order[at]

    def click(self, at, modifiers):
        self.select(at, modifiers)

    def double(self, at):
        self.select(at, 0)
        self.active = self.order[at]

    def key(self, code, modifiers):
        if code == "a":  # Ctrl+A
            self.picked = set(self.order)
            return
        if code == "space":  # Ctrl+Space
            self.select(self.row(self.cursor), MOD1)
            return
        cursor = self.row(self.cursor)
        at = {"Up": cursor - 1, "Down": cursor + 1, "Home": 0, "End": len(self.order) - 1}[code]
        at = max(0, min(len(self.order) - 1, at))
        if modifiers == MOD1:
            self.cursor = self.anchor = self.order[at]
            return
        self.select(at, modifiers)

    def press_drag(self, at):
        """The press that starts a drag: picks stay when the row is picked."""
        name = self.order[at]
        if name in self.picked:
            self.cursor = self.anchor = name
        else:
            self.select(at, 0)

    def move(self, action, gap=None):
        """Apply a move; True if it changed the order (one undo step)."""
        before = list(self.order)
        target = self.target(action, gap)
        if target == before:
            return False
        self.order = target
        self.undo.append(("move", before))
        return True

    def undo_move(self):
        _, before = self.undo.pop()
        self.order = list(before)

    def rename(self, at, new):
        old = self.order[at]
        self.order[at] = new
        if old in self.picked:
            self.picked.discard(old)
            self.anchor = None
        if self.cursor == old:
            self.cursor = new
        if self.anchor == old:
            self.anchor = new
        if self.active == old:
            self.active = new
        self.undo.append(("blocked",))

    def resync(self, order, active, block_undo=True):
        """After a mismatch: take the document's order and view as the new baseline."""
        self.order = list(order)
        self.active = active
        self.picked &= set(order)
        if self.cursor not in order:
            self.cursor = order[0]
        if self.anchor not in order:
            self.anchor = None
        if block_undo:
            self.undo.append(("blocked",))
