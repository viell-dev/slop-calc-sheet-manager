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
  `addActionLock` batch, when the last lock is released, and not at all under
  `disableSetModified`. Each change LibreOffice records reports its undo action before its
  modify notification; typed input reports a second one after leaving its undo context.
- Undoing or redoing an action reports the action once, whatever it contained.
- Saving reports several modify notifications and no undo action, all between the document
  events `OnSave` and `OnSaveDone` (`OnSaveAs`, `OnSaveAsDone` for Save As). LibreOffice may run
  posted work during a save, and modify notifications are disabled meanwhile; copies, exports,
  and autosave's recovery file (`OnCopyTo` to `OnCopyToDone`) report no modification. A save
  window lasts from its start event to its `Done` or `Failed` event, or to the next undo
  notification, since a failed save may leave it open.

So the generation moves:

- when a notification shows a sheet count other than the last one;
- when, at a notification, undo recording is off or locked, the controllers are locked (except
  by the extension's own move), actions are locked, or modify notifications are off: a change
  then may go unrecorded, or its report may stand for a whole batch;
- on every undo and redo;
- at a modify notification that no undo action explains: none was added, nor an undo context
  that received one left, since the previous modify notification or check. Saves are the one
  measured exception, inside their save window;
- at a check, when the undo history changed without any undo notification, or when any of those
  states holds right then: a held lock may still be holding back the report of a whole batch,
  so the list acts on nothing until the lock is released and the report arrives. The exceptions
  are the extension's own move and, for modify notifications being off, a save window.

Over-clearing is the accepted cost: undo and redo, document property changes, and other changes
LibreOffice does not record for undo move the generation too, and so clear the list's picks.

The threat model, decided by the maintainer: everything LibreOffice reports must be caught. Out
of scope: a structural edit that LibreOffice does not report at all, because undo recording and
modify notifications were both off, or whose only report a save window absorbs. A program can
still make its report look like an ordinary edit's: if it records an edit inside an undo context
and, in the same main-thread call, makes unrecorded structural edits inside a lock and turns undo
recording back on before releasing the lock, the last modify notification follows an explaining
undo notification, exactly as typed input's does. That needs a sequence built to hide the edits,
and such a program could hide or delete any sheet directly anyway.
"""

from dataclasses import dataclass, field
from enum import Flag, auto

History = tuple[int, str | None]  # The undo history's depth and its top action's title.


class Quiet(Flag):
    """Document states in which a change may go unrecorded or be reported late."""

    NONE = 0
    UNDO_OFF = auto()  # The document's IsUndoEnabled is false.
    UNDO_LOCKED = auto()  # XUndoManager.isLocked().
    CONTROLLERS_LOCKED = auto()  # XModel.hasControllersLocked().
    ACTION_LOCKED = auto()  # XActionLockable.isActionLocked().
    MODIFY_OFF = auto()  # XModifiable2.isSetModifiedEnabled() is false.


# Document events that open a save window, and the events that close each one.
SAVE_WINDOWS = {
    "OnSave": ("OnSaveDone", "OnSaveFailed"),
    "OnSaveAs": ("OnSaveAsDone", "OnSaveAsFailed"),
    "OnCopyTo": ("OnCopyToDone", "OnCopyToFailed"),
}


@dataclass
class StructureEvents:
    count: int | None = None  # The sheet count at the last notification or check.
    history: History | None = None  # The undo history at the last check.
    generation: int = 0
    undo_notes: int = 0  # Undo notifications since the last check.
    explained: bool = False  # An undo action explains the next modify notification.
    contexts: list[bool] = field(default_factory=list[bool])  # Open contexts: received an action?
    saving: set[str] = field(default_factory=set[str])  # Open save windows, by their start event.
    own: int = 0  # Depth of the extension's own moves, which lock the controllers.

    def _bump(self) -> None:
        self.generation += 1

    def _sample(self, count: int | None, quiet: Quiet | None) -> None:
        """A notification's count and state, read at that moment; None if unreadable."""
        if count is None or count != self.count:
            self._bump()
        self.count = count
        if self.own and quiet is not None:
            quiet &= ~Quiet.CONTROLLERS_LOCKED
        if quiet is None or quiet:
            self._bump()

    def _undo_noted(self) -> None:
        self.undo_notes += 1
        # No undo action is recorded while saving; a window a failed save left open ends here.
        self.saving.clear()

    def modified(self, count: int | None, quiet: Quiet | None) -> None:
        """A modify notification."""
        self._sample(count, quiet)
        if not self.explained and not self.saving:
            self._bump()
        self.explained = False

    def action_added(self, count: int | None, quiet: Quiet | None) -> None:
        self._undo_noted()
        self._sample(count, quiet)
        self.explained = True
        if self.contexts:
            self.contexts[-1] = True

    def context_entered(self, count: int | None, quiet: Quiet | None) -> None:
        self._undo_noted()
        self._sample(count, quiet)
        self.contexts.append(False)

    def context_left(self, count: int | None, quiet: Quiet | None, cancelled: bool = False) -> None:
        self._undo_noted()
        self._sample(count, quiet)
        received = self.contexts.pop() if self.contexts else False
        if received and not cancelled:
            self.explained = True
            if self.contexts:
                self.contexts[-1] = True

    def history_cleared(self, count: int | None, quiet: Quiet | None, reset: bool = False) -> None:
        """The undo or redo history was cleared; nothing was recorded."""
        self._undo_noted()
        self._sample(count, quiet)
        if reset:
            self.contexts.clear()

    def undone_or_redone(self, count: int | None) -> None:
        """Undo and redo report one action, whatever it contained: assume the worst."""
        self._undo_noted()
        self._bump()
        self.count = count
        self.explained = False

    def document_event(self, name: str) -> None:
        if name in SAVE_WINDOWS:
            self.saving.add(name)
            return
        for start, ends in SAVE_WINDOWS.items():
            if name in ends:
                self.saving.discard(start)

    def own_move_started(self, quiet: Quiet | None) -> None:
        """The extension is about to lock the controllers for its own move.

        A lock or a quiet state someone else holds already is suspect: bump.
        """
        if quiet is None or quiet:
            self._bump()
        self.own += 1

    def own_move_finished(self) -> None:
        self.own = max(self.own - 1, 0)

    def check(self, count: int | None, history: History | None, quiet: Quiet | None) -> int:
        """Before acting on held handles; returns the generation to compare with.

        `quiet` is the document's state now. Any of its states moves the generation, as at a
        notification: a lock held now may be holding back the report of a batch made under it,
        which comes only when the lock is released. Inside a save window, LibreOffice itself
        turns modify notifications off while it may run posted work, such as a refresh; during
        the extension's own move, the controller lock is its own.
        """
        if count is None or count != self.count:
            self._bump()
        self.count = count
        if quiet is not None and self.saving:
            quiet &= ~Quiet.MODIFY_OFF
        if quiet is not None and self.own:
            quiet &= ~Quiet.CONTROLLERS_LOCKED
        unexplained = self.history is not None and history != self.history
        if quiet is None or quiet or history is None or unexplained and not self.undo_notes:
            self._bump()
        self.history = history
        self.undo_notes = 0
        self.explained = False
        return self.generation
