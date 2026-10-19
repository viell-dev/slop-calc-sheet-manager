"""Whether a document's sheets may have been inserted or deleted: a generation counter.

LibreOffice offers no stable sheet identity: a deleted sheet's retained handle turns to another
sheet and can report the deleted sheet's name again (docs/reordering.md). So whatever holds
handles across user time needs to know whether any sheet was inserted or deleted meanwhile, and
the generation here moves whenever that may have happened. `uno_structure.StructureMonitor`
feeds it from the document's notifications; this module only decides.

What LibreOffice reports (measured with 26.2.1.2 and 26.8.1.1; docs/reordering.md):

- Every recorded undo action, also inside `lockControllers`, `addActionLock`,
  `disableSetModified`, and a caller's own undo context, reaches undo listeners as it happens,
  and the sheet count read then shows each insertion and deletion.
- Modify notifications come once per change, but only once for a whole `lockControllers` or
  `addActionLock` batch, and not at all under `disableSetModified`.
- Undoing or redoing an action reports the action once, whatever it contained.

So the generation moves when a notification shows a sheet count other than the last one,
when an action is undone or redone, and, at a check, when the undo history changed without any
undo notification, or when the undo manager is locked or disabled or modification
notifications are off (a batch may be running unseen). Out of scope: a program that both turns
off or locks undo recording and batches or suppresses modification notifications around
structural edits. Nothing is reported then, and such a program could hide or delete any sheet
directly anyway.
"""

from dataclasses import dataclass

History = tuple[int, str | None]  # The undo history's depth and its top action's title.


@dataclass
class StructureEvents:
    count: int | None = None  # The sheet count at the last notification or check.
    history: History | None = None  # The undo history at the last check.
    generation: int = 0
    undo_notes: int = 0  # Undo notifications since the last check.

    def notified(self, count: int | None) -> None:
        """A modify or undo notification, with the sheet count read at that moment."""
        if count is None or count != self.count:
            self.generation += 1
        self.count = count

    def undo_notified(self, count: int | None) -> None:
        """An undo action added, a context entered or left, or the history cleared."""
        self.undo_notes += 1
        self.notified(count)

    def undone_or_redone(self, count: int | None) -> None:
        """Undo and redo report one action, whatever it contained: assume the worst."""
        self.undo_notes += 1
        self.generation += 1
        self.count = count

    def check(self, count: int | None, history: History | None, quiet: bool) -> int:
        """Before acting on held handles; returns the generation to compare with.

        `quiet` is whether undo recording is locked or off, or modification notifications are
        off, right now.
        """
        self.notified(count)
        unexplained = history != self.history and self.undo_notes == 0
        if history is None or quiet or (self.history is not None and unexplained):
            self.generation += 1
        self.history = history
        self.undo_notes = 0
        return self.generation
