"""The sheet list's own selection, keyboard cursor, and Shift anchor, held as sheet identities.

The tree control knows its rows only by name, and a name can pass to another sheet: a sheet is
deleted and a new one inserted under its name, or renamed and its name reused. So the list keeps
each pick as a `Ref`: the name the sheet had when the user picked it and a token that follows
that sheet. In LibreOffice the token is the sheet's retained handle, and a ref is current while
the handle still reports the ref's name (the check `uno_reorder.is_current` makes per sheet; see
docs/reordering.md for why it is empirical). The position is kept for diagnostics only: sheets
move, and a moved sheet stays picked.

The rules: a ref is created only for the sheet a row showed at the moment of the user's input,
from the row tokens of that moment; it is never re-created from a name later. Every refresh
drops refs that are no longer current, whether or not the rows change, so a pick never passes to
a replacement. What the list writes back to the tree comes from these refs.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, eq=False)
class Ref:
    """A sheet as the list showed it: its name then, its position then, and its token."""

    name: str
    token: Any
    position: int = -1


class Selection:
    """Picks in row order, the keyboard cursor, and the Shift anchor, as refs."""

    def __init__(self, current: Callable[[Ref], bool]):
        self._current = current  # Whether the ref's token still denotes a sheet of that name.
        self.picked: list[Ref] = []
        self.cursor: Ref | None = None
        self.anchor: Ref | None = None

    def names(self) -> list[str]:
        return [ref.name for ref in self.picked]

    def take(self, names: Iterable[str], tokens: Mapping[str, Any], order: list[str]) -> None:
        """Take the picks the user just made, as the rows showed them (`tokens` by name).

        A name already picked keeps its ref while that ref is current, so a pick made before a
        same-name replacement is not silently renewed for the replacement.
        """
        held = {ref.name: ref for ref in self.picked if self._current(ref)}
        picked: list[Ref] = []
        for name in names:
            if name in held:
                picked.append(held[name])
            elif name in tokens:
                position = order.index(name) if name in order else -1
                picked.append(Ref(name, tokens[name], position))
        self.picked = picked

    def ref(self, name: str, tokens: Mapping[str, Any], order: list[str]) -> Ref | None:
        """A ref for the row now showing `name`, reusing a current one for the same sheet."""
        for held in (*self.picked, self.cursor, self.anchor):
            if held is not None and held.name == name and self._current(held):
                return held
        if name not in tokens:
            return None
        return Ref(name, tokens[name], order.index(name) if name in order else -1)

    def revalidate(self) -> bool:
        """Drop every ref that no longer denotes its sheet under its name; True if any went."""
        picked = [ref for ref in self.picked if self._current(ref)]
        cursor = self.cursor if self.cursor is None or self._current(self.cursor) else None
        anchor = self.anchor if self.anchor is None or self._current(self.anchor) else None
        dropped = len(picked) != len(self.picked)
        dropped = dropped or cursor is not self.cursor or anchor is not self.anchor
        self.picked, self.cursor, self.anchor = picked, cursor, anchor
        return dropped
