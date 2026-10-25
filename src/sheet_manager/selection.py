"""The sheet list's own selection and keyboard cursor, held as sheet identities.

The tree control knows its rows only by name, and a name can pass to another sheet: a sheet is
deleted and a new one inserted under its name, or renamed and its name reused. So the list keeps
each pick as a `Ref`: the name the sheet had when the user picked it and the sheet's retained
handle. The position is kept for diagnostics only: sheets move, and a moved sheet stays picked.

A retained handle is not an identity on its own. Measured in LibreOffice 26.2 and 26.8 (see
docs/reordering.md): handles follow their sheets through renames, moves, and insertions, but
when a sheet is deleted, its handle turns to the previous sheet (the next one at index 0) and
follows that sheet from then on. A rename can then make it report the deleted sheet's name
again. So a handle reporting the ref's name proves the ref's sheet only while no sheet has been
inserted or deleted since the ref was made.

Hence the rules. A ref is made only for the sheet a row showed at the moment of the user's
input, and never again from a name. The list proves its refs at every refresh against
`structure.StructureEvents`, whose generation moves whenever a sheet may have been inserted or
deleted, and checks as a second line that its retained handles still map one to one onto the
sheets (`structure_kept`). If either fails, every ref is dropped, since none can be proved;
otherwise each ref stays while its handle still reports its name, so a renamed pick drops out
and a moved one stays.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, eq=False)
class Ref:
    """A sheet as the list showed it: its name then, its position then, and its token."""

    name: str
    token: Any
    position: int = -1


class Selection:
    """Picks in row order and the keyboard cursor, as refs."""

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

    def choose(
        self,
        name: str,
        tokens: Mapping[str, Any],
        order: list[str],
        *,
        extend: bool = False,
        toggle: bool = False,
        preserve: bool = False,
    ) -> None:
        """Select a row or a range, keeping the range's starting sheet as an identity."""
        target = self.ref(name, tokens, order)
        if target is None:
            return
        if extend:
            anchor = self.anchor or self.cursor or target
            if not self._current(anchor) or anchor.name not in order:
                anchor = target
            self.anchor = anchor
            first, last = sorted((order.index(anchor.name), order.index(name)))
            names = set(order[first : last + 1])
            if toggle:
                names.update(self.names())
        else:
            self.anchor = target
            names = set(self.names())
            if toggle:
                names.symmetric_difference_update((name,))
            elif not preserve or name not in names:
                names = {name}
        self.take((item for item in order if item in names), tokens, order)
        self.cursor = target

    def revalidate(self) -> bool:
        """Drop every ref that no longer denotes its sheet under its name; True if any went."""
        picked = [ref for ref in self.picked if self._current(ref)]
        cursor = self.cursor if self.cursor is None or self._current(self.cursor) else None
        anchor = self.anchor if self.anchor is None or self._current(self.anchor) else None
        dropped = len(picked) != len(self.picked)
        dropped = dropped or cursor is not self.cursor or anchor is not self.anchor
        self.picked, self.cursor, self.anchor = picked, cursor, anchor
        return dropped

    def clear(self) -> bool:
        """Drop every ref; True if there was anything to drop."""
        had = bool(self.picked) or self.cursor is not None or self.anchor is not None
        self.picked, self.cursor, self.anchor = [], None, None
        return had


def structure_kept(
    recorded: Sequence[str], reported: Sequence[str | None], current: Sequence[str]
) -> bool:
    """Whether retained handles show the same sheets as when recorded, with at most one rename.

    `recorded` is the names of all sheets when their handles were taken, `reported` what those
    handles report now (None if one fails), and `current` the names of all sheets now. The
    sheets count as the same only if the counts match, the handles report distinct names that
    are exactly the current ones, and at most one handle reports a new name that no recorded
    sheet had, while no handle reports its old one.
    """
    if not len(recorded) == len(reported) == len(current):
        return False
    names = [name for name in reported if name is not None]
    if len(names) != len(reported) or len(set(names)) != len(names) or set(names) != set(current):
        return False
    renamed = [index for index, name in enumerate(names) if name != recorded[index]]
    if not renamed:
        return True
    if len(renamed) > 1:
        return False
    index = renamed[0]
    return recorded[index] not in names and names[index] not in recorded
