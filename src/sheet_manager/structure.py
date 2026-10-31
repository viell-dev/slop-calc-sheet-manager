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
- on every undo and redo, except a proved replay of one of the extension's own moves (below);
- at a modify notification that no undo action explains: none was added, nor an undo context
  that received one left, since the previous modify notification or check. Saves are the one
  measured exception, inside their save window;
- at a check, when the undo history changed without any undo notification, or when any of those
  states holds right then: a held lock may still be holding back the report of a whole batch,
  so the list acts on nothing until the lock is released and the report arrives. The exceptions
  are the extension's own move and, for modify notifications being off, a save window.

Over-clearing is the accepted cost: undo and redo, document property changes, and other changes
LibreOffice does not record for undo move the generation too, and so clear the list's picks.

The extension's own moves (#91). Undo and Redo report one action whatever it contained, so the
generation cannot tell an undone move from an undone insertion. The extension's own move group
therefore carries two marker actions of its own (`uno_reorder`), one before its first move and
one after its last, and each `OwnMove` here is the state they share. Measured with 26.8.1.1:
each move and each marker reports one undo action inside the group; Undo calls the last marker
first, with the undo manager locked and the view as it was before, then undoes the moves, calls
the first marker, and reports the undo; Redo calls the first marker first and the last one last.
Nothing else is reported in between. The generation stays where it is across such a replay only
when all of this holds:

- the move ended verified, with exactly its moves and two markers recorded inside its own move
  and the generation unchanged since it started (`own_recorded`);
- the replay's first marker finds the group where it was left, on the undo stack for Undo and on
  the redo stack for Redo, at the very generation and sheet count it was armed or last replayed
  at, with no history cleared, no redo history cleared for Redo, and no hidden undo context
  entered since (`epoch`, `redo_epoch`): a hidden context can add foreign actions to the top
  group;
- nothing at all is reported between the first marker and the last, and the undo or redo
  notification of the same direction comes next, with the same count.

Anything else revokes the group for good, and the undo or redo moves the generation as before.
An own move's replay can only move sheets, so the handles retained before it still denote their
sheets after it. `viewing_replay` and `replay_proven` let a view tell Calc's activations during a
proved replay, and the adapter's restoration of the view after it, from the user's own. The
restoration is posted work, so the view stops being the replay's `VIEW_RESTORE_LIMIT` seconds
after the proof whether or not the restoration has run: views never stay without following
Calc's activations and sampling its tabs for longer than that. This only ends a suppression;
it never trusts anything more.

The threat model, decided by the maintainer: everything LibreOffice reports must be caught. Out
of scope: a structural edit that LibreOffice does not report at all, because undo recording and
modify notifications were both off, or whose only report a save window absorbs. A program can
still make its report look like an ordinary edit's: if it records an edit inside an undo context
and, in the same main-thread call, makes unrecorded structural edits inside a lock and turns undo
recording back on before releasing the lock, the last modify notification follows an explaining
undo notification, exactly as typed input's does. That needs a sequence built to hide the edits,
and such a program could hide or delete any sheet directly anyway.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Flag, auto
from typing import Literal

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


@dataclass(eq=False)
class OwnMove:
    """One of the extension's own move groups in the undo history, as its two markers know it.

    `recording` until the move is verified, then `done` while the group is on the undo stack and
    `undone` while it is on the redo stack; `revoked`, for good, once continuity is not proved.
    """

    state: Literal["recording", "done", "undone", "revoked"] = "recording"
    generation: int = -1  # The generation its next replay must find.
    count: int | None = None  # The sheet count its next replay must find.
    epoch: int = -1  # `StructureEvents.epoch` when it was armed or last replayed.
    redo_epoch: int = -1  # `StructureEvents.redo_epoch` when it was last undone.


@dataclass(eq=False)
class Replay:
    """An own group's replay, from its first marker to its undo or redo notification."""

    move: OwnMove
    redo: bool
    serial: int
    complete: bool = False  # The last marker has run.


OUTCOMES_KEPT = 32  # Replay outcomes kept for views whose posted work runs after the replay.
VIEW_RESTORE_LIMIT = 5.0  # Seconds after its proof that a replay's view restoration may take.


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
    own_start: int = 0  # The generation when the outermost own move started.
    own_epoch: int = 0  # The epoch then.
    own_actions: int = 0  # Undo actions recorded during the own move.
    epoch: int = 0  # Moves when no own group can be trusted any more.
    redo_epoch: int = 0  # Moves when the redo history is cleared.
    replay: Replay | None = None
    serial: int = 0  # Numbers own replays.
    view_replay: int | None = None  # A running or proved own replay whose view is not restored.
    view_proved: float | None = None  # When `view_replay` was proved, by `clock`.
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    outcomes: dict[int, bool] = field(default_factory=dict[int, bool])

    def _bump(self) -> None:
        self.generation += 1

    def _settle(self, serial: int, proven: bool) -> None:
        self.outcomes[serial] = proven
        while len(self.outcomes) > OUTCOMES_KEPT:
            del self.outcomes[next(iter(self.outcomes))]
        if self.view_replay == serial:
            if proven:
                self.view_proved = self.clock()
            else:
                self.view_replay = None

    def _abort(self) -> None:
        """Anything reported during an own replay, other than its own steps, ends its proof."""
        replay, self.replay = self.replay, None
        if replay is not None:
            replay.move.state = "revoked"
            self._settle(replay.serial, False)

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
        self._abort()
        self._sample(count, quiet)
        if not self.explained and not self.saving:
            self._bump()
        self.explained = False

    def action_added(self, count: int | None, quiet: Quiet | None) -> None:
        self._abort()
        if self.own:
            self.own_actions += 1
        self._undo_noted()
        self._sample(count, quiet)
        self.explained = True
        if self.contexts:
            self.contexts[-1] = True

    def context_entered(self, count: int | None, quiet: Quiet | None, hidden: bool = False) -> None:
        """`hidden`: its actions join the top group, which may be an own one; trust none."""
        self._abort()
        if hidden:
            self.epoch += 1
        self._undo_noted()
        self._sample(count, quiet)
        self.contexts.append(False)

    def context_left(self, count: int | None, quiet: Quiet | None, cancelled: bool = False) -> None:
        self._abort()
        self._undo_noted()
        self._sample(count, quiet)
        received = self.contexts.pop() if self.contexts else False
        if received and not cancelled:
            self.explained = True
            if self.contexts:
                self.contexts[-1] = True

    def history_cleared(
        self, count: int | None, quiet: Quiet | None, reset: bool = False, redo: bool = False
    ) -> None:
        """The undo history, or only the redo history (`redo`), was cleared; nothing recorded."""
        self._abort()
        self.redo_epoch += 1
        if not redo:
            self.epoch += 1
        self._undo_noted()
        self._sample(count, quiet)
        if reset:
            self.contexts.clear()

    def undone_or_redone(self, count: int | None, redo: bool = False) -> bool:
        """Undo and redo report one action, whatever it contained: assume the worst, unless it
        ends the proved replay of an own move. True if it does."""
        replay, self.replay = self.replay, None
        self._undo_noted()
        self.explained = False
        proven = (
            replay is not None
            and replay.complete
            and replay.redo == redo
            and count is not None
            and count == self.count == replay.move.count
            and replay.move.generation == self.generation
        )
        if replay is not None and proven:
            move = replay.move
            move.state = "done" if redo else "undone"
            move.epoch, move.redo_epoch = self.epoch, self.redo_epoch
            self._settle(replay.serial, True)
            return True
        if replay is not None:
            replay.move.state = "revoked"
            self._settle(replay.serial, False)
        self._bump()
        self.count = count
        return False

    def own_recorded(self, move: OwnMove, actions: int, count: int | None) -> bool:
        """The own move ended verified, its controllers unlocked: arm its markers if provable.

        `actions` is how many undo actions the move itself recorded: one per sheet moved and
        one per marker. Anything else recorded meanwhile, or any generation change since the
        move started, leaves the group untrusted.
        """
        armed = (
            self.own > 0
            and move.state == "recording"
            and self.generation == self.own_start
            and self.epoch == self.own_epoch
            and self.own_actions == actions
            and count is not None
            and count == self.count
            and self.replay is None
        )
        if armed:
            move.state, move.generation, move.count = "done", self.generation, count
            move.epoch = self.epoch
        else:
            move.state = "revoked"
        return armed

    def replay_started(self, move: OwnMove, redo: bool, count: int | None) -> int | None:
        """The first marker of an own group's replay; its serial number if continuity holds.

        Undo calls the group's last marker first and Redo its first one. The group must be where
        its last transition left it, with nothing that could have changed its sheets since.
        """
        self._abort()
        trusted = (
            move.state == ("undone" if redo else "done")
            and move.generation == self.generation
            and count is not None
            and move.count == count == self.count
            and move.epoch == self.epoch
            and (not redo or move.redo_epoch == self.redo_epoch)
            and not self.own
            and not self.contexts
        )
        if not trusted:
            move.state = "revoked"
            return None
        self.serial += 1
        self.replay = Replay(move, redo, self.serial)
        self.view_replay, self.view_proved = self.serial, None
        return self.serial

    def replay_finished(self, move: OwnMove, redo: bool, count: int | None) -> None:
        """The last marker of the replay: nothing may have been reported since the first."""
        replay = self.replay
        if (
            replay is not None
            and replay.move is move
            and replay.redo == redo
            and not replay.complete
            and count is not None
            and count == move.count
        ):
            replay.complete = True
            return
        self._abort()
        move.state = "revoked"

    def revoke(self, move: OwnMove) -> None:
        """A marker could not follow its replay: the group is never trusted again."""
        if self.replay is not None and self.replay.move is move:
            self._abort()
        move.state = "revoked"

    def view_restored(self, serial: int) -> None:
        """The adapter is done with the view after this replay, restored or not."""
        if self.view_replay == serial:
            self.view_replay, self.view_proved = None, None

    def viewing_replay(self) -> int | None:
        """The replay whose view is still the adapter's: Calc's view is not the user's then.

        That is `view_replay` until the restoration is done, or until `VIEW_RESTORE_LIMIT`
        seconds after the proof, should the posted restoration never run or finish. A late
        restoration then finds the replay over and leaves Calc's view as it is.
        """
        serial, proved = self.view_replay, self.view_proved
        if serial is not None and proved is not None and self.clock() - proved > VIEW_RESTORE_LIMIT:
            self.view_restored(serial)
            return None
        return serial

    def replay_settled(self, serial: int) -> bool:
        """Whether that replay has ended, proved or not; posted work waits for it."""
        return serial in self.outcomes or serial < self.serial - OUTCOMES_KEPT

    def replay_proven(self, serial: int | None) -> bool:
        return serial is not None and self.outcomes.get(serial, False)

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
        self._abort()
        if quiet is None or quiet:
            self._bump()
        if not self.own:
            self.own_start, self.own_epoch, self.own_actions = self.generation, self.epoch, 0
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
        self._abort()
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
