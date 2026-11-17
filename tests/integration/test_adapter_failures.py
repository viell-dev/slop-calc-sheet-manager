"""Failure paths at the list's UNO boundary, using the installed package and private office."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import unohelper
from com.sun.star.awt import KeyEvent
from com.sun.star.lang import XEventListener
from main_thread import close_after
from sheet_list_view import labels, poll

from sheet_manager import uno_panel
from sheet_manager.keys import MOD1
from sheet_manager.uno_calc import select_tabs, selected_tabs
from sheet_manager.uno_keys import ListKeyHandler
from sheet_manager.uno_list import SheetList
from sheet_manager.uno_menu import SheetMenu
from sheet_manager.uno_reorder import snapshot
from sheet_manager.uno_show import show_sheets
from sheet_manager.uno_structure import StructureMonitor, monitor_for


class Tracked:
    """Forward real UNO calls, retaining only listener registration evidence."""

    def __init__(self, real):
        self.real = real
        self.attached = set()

    def __getattr__(self, name) -> Any:
        value = getattr(self.real, name)
        if name.startswith(("add", "remove")) and name.endswith("Listener"):

            def registration(listener):
                value(listener)
                key = (name.removeprefix("add").removeprefix("remove"), id(listener))
                if name.startswith("add"):
                    self.attached.add(key)
                else:
                    self.attached.discard(key)

            return registration
        return value


def check_failed_list(context, document):
    undo = Tracked(document.getUndoManager())
    model: Any = Tracked(document)
    model.getUndoManager = lambda: undo
    controller: Any = Tracked(document.getCurrentController())
    controller.getModel = lambda: model
    frame: Any = Tracked(document.getCurrentController().getFrame())
    frame.getController = lambda: controller
    # The shared document monitor deliberately outlives a failed or disposed list view.
    monitor = monitor_for(model)
    model_before, undo_before = set(model.attached), set(undo.attached)
    disposed = []
    cursors = []

    class FailingList(SheetList):
        def __setattr__(self, name, value):
            if name == "_cursor_context":
                value = Tracked(value)
                cursors.append(value)
            super().__setattr__(name, value)

        def refresh(self, renamed=None):
            # This is after every listener is attached. It must unwind even though the
            # SheetPanel assignment never receives the partly constructed list.
            disposed.append(self)
            raise RuntimeError("injected first refresh failure")

    try:
        FailingList(context, frame, frame.getContainerWindow())
    except RuntimeError as error:
        assert "injected first refresh" in str(error), error
    else:
        raise AssertionError("The initialization failure did not propagate")
    assert (
        model.attached == model_before and undo.attached == undo_before and not controller.attached
    ), (
        model.attached,
        undo.attached,
        controller.attached,
    )
    assert disposed and disposed[0]._disposed
    assert cursors and all(not cursor.attached for cursor in cursors)
    assert monitor_for(model) is monitor

    def fail_registration(listener):
        raise RuntimeError("injected document-event registration failure")

    model.addDocumentEventListener = fail_registration
    try:
        StructureMonitor(model)
    except RuntimeError as error:
        assert "injected document-event" in str(error), error
    else:
        raise AssertionError("The monitor registration failure did not propagate")
    assert model.attached == model_before and undo.attached == undo_before


def check_failed_menu(context, document):
    """A popup that fails to open leaves the menu closed and Calc's view as it was."""
    controller = document.getCurrentController()
    frame = controller.getFrame()
    sheets = document.getSheets()
    sheets.insertNewByName("Sheet2", 1)
    select_tabs(context, frame, [0, 1])
    before = controller.getActiveSheet().getName(), selected_tabs(context, controller)
    menu: Any = SheetMenu(context, frame, document, controller)
    observed = snapshot(document)

    def fail_popup():
        raise RuntimeError("injected popup failure")

    with patch.object(menu, "_popup", fail_popup):
        try:
            menu.show(frame.getContainerWindow(), 0, 0, observed, ["Sheet2"])
        except RuntimeError as error:
            assert "injected popup" in str(error), error
        else:
            raise AssertionError("The menu setup failure did not propagate")
    assert not menu.is_open, "A failed menu stayed open"
    after = controller.getActiveSheet().getName(), selected_tabs(context, controller)
    assert after == before, ("A failed menu changed Calc's view", before, after)


def check_key_failure():
    def fail_command(command):
        raise RuntimeError("injected shortcut failure")

    owner = SimpleNamespace(
        owns_keys=lambda: True,
        owns_tree_keys=lambda: True,
        claim_window=lambda: None,  # So that the injected failure is the shortcut's own.
        run_command=fail_command,
    )
    shortcuts = cast(Any, SimpleNamespace(command=lambda code, modifiers: ".uno:Save"))
    handler = ListKeyHandler(owner, shortcuts)
    event = KeyEvent()
    event.KeyCode, event.Modifiers, event.KeyChar = 530, MOD1, "s"
    assert handler.keyPressed(event), "A failed handler passed its owned key to Calc"
    assert handler.keyReleased(event), "The corresponding release must be consumed too"
    owner.owns_keys = lambda: False
    assert not handler.keyPressed(event), "Another window's keys must remain untouched"


class Disposed(unohelper.Base, XEventListener):
    def __init__(self):
        self.heard = False

    def disposing(self, Source):
        self.heard = True


def check_failed_panel(context, document):
    """A list that cannot be created leaves a message naming only the error type (#188).

    The panel completes, disposes every window it made, and the next panel opens normally.
    """
    frame = document.getCurrentController().getFrame()
    arguments = {"Frame": frame, "ParentWindow": frame.getContainerWindow()}
    late = []
    secret = "Synthetic private sheet"

    class EarlyFailure(SheetList):
        def __init__(self, *args):
            raise RuntimeError(f"{secret} is unreadable")

    class LateFailure(SheetList):
        def set_bounds(self, width, height):
            late.append(self)
            raise RuntimeError(f"{secret} could not be laid out")

    shown = {}
    for name, failing in (("early", EarlyFailure), ("late", LateFailure)):
        with patch.object(uno_panel, "SheetList", failing):
            panel = uno_panel.SheetPanel(context, uno_panel.RESOURCE_URL, arguments)
        closed = Disposed()
        panel.Window.addEventListener(closed)
        try:
            assert panel.list is None, name
            window: Any = panel.Window
            texts = [
                child.getText()
                for child in window.getWindows()
                if "com.sun.star.awt.XFixedText" in [kind.typeName for kind in child.getTypes()]
            ]
            message = [text for text in texts if "could not open its sheet list" in text]
            assert len(message) == 1 and "(RuntimeError)" in message[0], texts
            assert secret not in message[0], "The message must not repeat the error's text"
            assert panel.getMinimalWidth() == 150
            shown[name] = message[0]
        finally:
            panel.dispose()
        assert closed.heard, f"The {name} failure's panel window was not disposed"
    assert late and late[0]._disposed, "The late failure's list was not disposed"
    panel = uno_panel.SheetPanel(context, uno_panel.RESOURCE_URL, arguments)
    try:
        reopened = panel.list
        assert reopened is not None, "The next panel did not open its list"
        poll(lambda: labels(reopened.tree) == ["Sheet1"], "the reopened list")
    finally:
        panel.dispose()
    return shown


def check_failed_refresh(context, document):
    """A failed refresh stays pending and is retried until the list shows the change (#186).

    Hiding a sheet changes neither the names nor the structure generation, so nothing else
    asks for that refresh again.
    """
    frame = document.getCurrentController().getFrame()
    sheets = document.getSheets()
    sheets.insertNewByName("Second", 1)
    rebuilds = []

    class FlakyList(SheetList):
        def _rebuild(self, rows):
            rebuilds.append([row.name for row in rows])
            if len(rebuilds) == 2:
                raise RuntimeError("injected rebuild failure")
            super()._rebuild(rows)

    sheet_list = FlakyList(context, frame, frame.getContainerWindow())
    try:
        assert labels(sheet_list.tree) == ["Sheet1", "Second"]
        sheets.getByIndex(1).IsVisible = False
        poll(
            lambda: labels(sheet_list.tree) == ["Sheet1", "Second (hidden)"],
            "the retried refresh to show the hidden sheet",
        )
        assert len(rebuilds) == 3, rebuilds
    finally:
        sheet_list.dispose()


def check_recorded_show(context, document):
    sheets = document.getSheets()
    sheets.insertNewByName("Hidden", 1)
    sheets.getByName("Hidden").IsVisible = False
    undo = document.getUndoManager()
    undo.clear()
    document.RecordChanges = True
    try:
        result = show_sheets(context, document, snapshot(document), ["Hidden"])
        assert result.status == "refused", result
        assert "recorded" in result.message, result
        assert not sheets.getByName("Hidden").IsVisible
        assert not undo.isUndoPossible(), "Refusing Show must record no undo action"
    finally:
        document.RecordChanges = False


def exercise(context, desktop, directory, output):
    results = {}
    failures = []
    for name, check in (
        ("failed_list_cleanup", lambda book: check_failed_list(context, book)),
        ("failed_menu_cleanup", lambda book: check_failed_menu(context, book)),
        ("owned_key_failure", lambda book: check_key_failure()),
        ("show_while_recording", lambda book: check_recorded_show(context, book)),
        ("failed_panel_message", lambda book: check_failed_panel(context, book)),
        ("failed_refresh_retried", lambda book: check_failed_refresh(context, book)),
    ):
        book = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
        book.getCurrentController().getFrame().activate()
        try:
            check(book)
            results[name] = True
        except Exception as error:
            results[name] = str(error)
            failures.append(name)
        finally:
            close_after(context, book)
    if failures:
        raise AssertionError(f"Adapter failure regressions: {results}")
    return results
