"""Feeds `structure.StructureEvents` from one document's modify and undo notifications.

The sheet list keeps one monitor per list. The reorder layer (`uno_reorder`) is meant to share
this module so that a snapshot can record the generation it was taken at (#19).

The listener methods read the sheet count with `getCount()` while LibreOffice is still
notifying. That is a narrow exception to the rule that listeners only note and post: the getter
takes LibreOffice's main lock and returns the number of sheets, without UI work, and it has to
be read at that moment, since a later read would miss an insertion and a deletion that cancel
out. Nothing else is called back from a listener here.
"""

import contextlib
from typing import Any

import unohelper
from com.sun.star.document import XUndoManagerListener
from com.sun.star.util import XModifyListener

from sheet_manager.structure import History, StructureEvents


class StructureMonitor(unohelper.Base, XModifyListener, XUndoManagerListener):
    def __init__(self, document: Any):
        self._document = document
        self._sheets = document.getSheets()
        self._undo = document.getUndoManager()
        self.events = StructureEvents(count=self._count(), history=self._history())
        document.addModifyListener(self)
        self._undo.addUndoManagerListener(self)
        self._attached = True

    @property
    def generation(self) -> int:
        return self.events.generation

    def check(self) -> int:
        """Bring the generation up to date before acting on handles; return it."""
        return self.events.check(self._count(), self._history(), self._quiet())

    def dispose(self) -> None:
        if not self._attached:
            return
        self._attached = False
        for remove in (
            lambda: self._document.removeModifyListener(self),
            lambda: self._undo.removeUndoManagerListener(self),
        ):
            with contextlib.suppress(Exception):  # The document may be gone already.
                remove()

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

    def _quiet(self) -> bool:
        try:
            return (
                bool(self._undo.isLocked())
                or not self._document.IsUndoEnabled
                or not self._document.isSetModifiedEnabled()
            )
        except Exception:
            return True

    # XModifyListener

    def modified(self, Source):
        self.events.notified(self._count())

    # XUndoManagerListener

    def undoActionAdded(self, iEvent):
        self.events.undo_notified(self._count())

    def actionUndone(self, iEvent):
        self.events.undone_or_redone(self._count())

    def actionRedone(self, iEvent):
        self.events.undone_or_redone(self._count())

    def allActionsCleared(self, iEvent):
        self.events.undo_notified(self._count())

    def redoActionsCleared(self, iEvent):
        self.events.undo_notified(self._count())

    def resetAll(self, iEvent):
        self.events.undo_notified(self._count())

    def enteredContext(self, iEvent):
        self.events.undo_notified(self._count())

    def enteredHiddenContext(self, iEvent):
        self.events.undo_notified(self._count())

    def leftContext(self, iEvent):
        self.events.undo_notified(self._count())

    def leftHiddenContext(self, iEvent):
        self.events.undo_notified(self._count())

    def cancelledContext(self, iEvent):
        self.events.undo_notified(self._count())

    def disposing(self, Source):
        self._attached = False
