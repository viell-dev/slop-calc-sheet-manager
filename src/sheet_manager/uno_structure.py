"""Feeds `structure.StructureEvents` from one document's modify, undo, and document events.

The sheet list and reorder snapshots share one monitor per document. Its listeners live until
the document is disposed, independently of any list view or snapshot.

The modify and undo listener methods read the sheet count and the document's state while
LibreOffice is still notifying: whether undo recording is enabled (the `IsUndoEnabled`
property) or locked (`XUndoManager.isLocked`), whether the controllers or actions are locked
(`hasControllersLocked`, `isActionLocked`), and whether modify notifications are enabled
(`isSetModifiedEnabled`). That is a narrow exception to the rule that listeners only note and
post. Each of these getters takes LibreOffice's main lock, which the notifying thread already
holds, and returns a count or a flag without UI work (checked in the 26.2.1.2 and 26.8.1.1
sources; `isLocked` also takes the undo manager's own recursive mutex). They have to be read
at that moment: a later read would miss an insertion and a deletion that cancel out, or a
state that a batch turns off and on again. Nothing else is called back from a listener here,
and the document event listener reads nothing.
"""

import contextlib
from collections.abc import Generator
from typing import Any
from weakref import WeakValueDictionary

import unohelper
from com.sun.star.document import XDocumentEventListener, XUndoManagerListener
from com.sun.star.util import XModifyListener

from sheet_manager.structure import History, Quiet, StructureEvents

_MONITORS: WeakValueDictionary[str, "StructureMonitor"] = WeakValueDictionary()


def monitor_for(document: Any) -> "StructureMonitor":
    """Get the document-owned monitor before retaining any sheet handles, on the UI thread."""
    key = str(document.RuntimeUID)
    monitor = _MONITORS.get(key)
    if monitor is None:
        monitor = StructureMonitor(document)
        _MONITORS[key] = monitor
    return monitor


class StructureMonitor(
    unohelper.Base, XModifyListener, XUndoManagerListener, XDocumentEventListener
):
    def __init__(self, document: Any):
        self._document_id = str(document.RuntimeUID)
        self._document: Any = document
        self._sheets: Any = document.getSheets()
        self._undo: Any = document.getUndoManager()
        self.events = StructureEvents(count=self._count(), history=self._history())
        self._attached = True
        try:
            document.addModifyListener(self)
            self._undo.addUndoManagerListener(self)
            document.addDocumentEventListener(self)
        except BaseException:
            self.dispose()
            raise

    @property
    def generation(self) -> int:
        return self.events.generation

    def check(self) -> int:
        """Bring the generation up to date before acting on handles; return it."""
        if not self._attached:
            raise RuntimeError("The sheet structure monitor has been disposed")
        return self.events.check(self._count(), self._history(), self._quiet())

    @contextlib.contextmanager
    def own_move(self) -> Generator[bool, None, None]:
        """Around the extension's own move, which locks the controllers while it records.

        Yields whether the move may go ahead: not if someone else's lock or quiet state is in
        place already, which moves the generation.
        """
        before = self.events.generation
        self.events.own_move_started(self._quiet())
        try:
            yield self.events.generation == before
        finally:
            self.events.own_move_finished()

    def dispose(self) -> None:
        if not self._attached:
            return
        self._attached = False
        for remove in (
            lambda: self._document.removeModifyListener(self),
            lambda: self._undo.removeUndoManagerListener(self),
            lambda: self._document.removeDocumentEventListener(self),
        ):
            with contextlib.suppress(Exception):  # The document may be gone already.
                remove()
        self._forget()

    def _forget(self) -> None:
        if _MONITORS.get(self._document_id) is self:
            del _MONITORS[self._document_id]
        # A held snapshot must not retain a closed document or silently regain continuity.
        self._document = self._sheets = self._undo = None

    def _count(self) -> int | None:
        try:
            return int(self._sheets.getCount())
        except Exception:
            return None

    def _history(self) -> History | None:
        try:
            titles = self._undo.getAllUndoActionTitles()
            return (len(titles), titles[0] if titles else None)
        except Exception:
            return None

    def _quiet(self) -> Quiet | None:
        try:
            document = self._document
            quiet = Quiet.NONE
            if not document.IsUndoEnabled:
                quiet |= Quiet.UNDO_OFF
            if self._undo.isLocked():
                quiet |= Quiet.UNDO_LOCKED
            if document.hasControllersLocked():
                quiet |= Quiet.CONTROLLERS_LOCKED
            if document.isActionLocked():
                quiet |= Quiet.ACTION_LOCKED
            if not document.isSetModifiedEnabled():
                quiet |= Quiet.MODIFY_OFF
            return quiet
        except Exception:
            return None

    # XModifyListener

    def modified(self, Source):
        self.events.modified(self._count(), self._quiet())

    # XUndoManagerListener

    def undoActionAdded(self, iEvent):
        self.events.action_added(self._count(), self._quiet())

    def actionUndone(self, iEvent):
        self.events.undone_or_redone(self._count())

    def actionRedone(self, iEvent):
        self.events.undone_or_redone(self._count())

    def allActionsCleared(self, iEvent):
        self.events.history_cleared(self._count(), self._quiet())

    def redoActionsCleared(self, iEvent):
        self.events.history_cleared(self._count(), self._quiet())

    def resetAll(self, iEvent):
        self.events.history_cleared(self._count(), self._quiet(), reset=True)

    def enteredContext(self, iEvent):
        self.events.context_entered(self._count(), self._quiet())

    def enteredHiddenContext(self, iEvent):
        self.events.context_entered(self._count(), self._quiet())

    def leftContext(self, iEvent):
        self.events.context_left(self._count(), self._quiet())

    def leftHiddenContext(self, iEvent):
        self.events.context_left(self._count(), self._quiet())

    def cancelledContext(self, iEvent):
        self.events.context_left(self._count(), self._quiet(), cancelled=True)

    # XDocumentEventListener

    def documentEventOccured(self, Event):
        self.events.document_event(str(Event.EventName))

    def disposing(self, Source):
        self._attached = False
        self._forget()
