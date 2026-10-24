"""Failure paths at the list's UNO boundary, using the installed package and private office."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from com.sun.star.awt import KeyEvent
from main_thread import close_after

from sheet_manager.keys import MOD1
from sheet_manager.uno_keys import ListKeyHandler
from sheet_manager.uno_list import SheetList
from sheet_manager.uno_menu import SheetMenu
from sheet_manager.uno_reorder import snapshot
from sheet_manager.uno_show import show_sheets
from sheet_manager.uno_structure import StructureMonitor, monitor_for


class Tracked:
    """Forward real UNO calls, retaining only listener/interceptor registration evidence."""

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

    class FailingList(SheetList):
        def refresh(self):
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
    real_frame = document.getCurrentController().getFrame()
    registered = []
    frame: Any = Tracked(real_frame)

    def register(guard):
        real_frame.registerDispatchProviderInterceptor(guard)
        registered.append(guard)

    def release(guard):
        real_frame.releaseDispatchProviderInterceptor(guard)
        registered.remove(guard)

    frame.registerDispatchProviderInterceptor = register
    frame.releaseDispatchProviderInterceptor = release
    posted = []
    menu: Any = SheetMenu(
        context, frame, document, document.getCurrentController(), posted.append, lambda: None
    )
    observed = snapshot(document)

    def fail_popup():
        raise RuntimeError("injected popup failure")

    try:
        with patch.object(menu, "_popup", fail_popup):
            try:
                menu._native(frame.getContainerWindow(), 0, 0, observed, ["Sheet1"], lambda: True)
            except RuntimeError as error:
                assert "injected popup" in str(error), error
            else:
                raise AssertionError("The menu setup failure did not propagate")
        assert not registered, "A failed menu left its interceptor registered"
        assert not posted, "No command was posted; setup failure must release immediately"
    finally:
        # Keep a failed baseline probe from contaminating later checks in this private office.
        for guard in list(registered):
            release(guard)


def check_key_failure():
    def fail_command(command):
        raise RuntimeError("injected shortcut failure")

    owner = SimpleNamespace(owns_keys=lambda: True, run_command=fail_command)
    shortcuts = cast(Any, SimpleNamespace(command=lambda code, modifiers: ".uno:Save"))
    handler = ListKeyHandler(owner, shortcuts)
    event = KeyEvent()
    event.KeyCode, event.Modifiers, event.KeyChar = 530, MOD1, "s"
    assert handler.keyPressed(event), "A failed handler passed its owned key to Calc"
    assert handler.keyReleased(event), "The corresponding release must be consumed too"
    owner.owns_keys = lambda: False
    assert not handler.keyPressed(event), "Another window's keys must remain untouched"


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
