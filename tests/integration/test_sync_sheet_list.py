"""Observe each Calc view through the installed panel's public native controls."""

import time
from types import SimpleNamespace

import unohelper
from com.sun.star.container import NoSuchElementException
from com.sun.star.document import XDocumentEventListener
from main_thread import close_document
from sheet_list_view import (
    footer_text,
    labels,
    names,
    on_main_thread,
    poll,
    root,
    row_point,
    selection,
    tree_of,
)
from teardown import run_checks
from test_sheet_list import VCL_MOD1, Robot

from sheet_manager.uno_calc import dispatch, prop, select_tabs

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
_CREATED = []


class _Loaded(unohelper.Base, XDocumentEventListener):
    """Record native load completion without reading UNO from the notification."""

    def __init__(self):
        self.documents = []

    def documentEventOccured(self, Event):
        if Event.EventName == "OnLoad":
            self.documents.append(Event.Source)

    def disposing(self, Source):
        pass


def open_list(context, document):
    """Make this test's panel visible, including expansion persisted by an earlier test."""
    controller = document.getCurrentController()
    frame = controller.getFrame()
    frame.activate()
    dispatch(context, frame, ".uno:SidebarDeck.SheetManagerDeck")

    def opened():
        try:
            deck = controller.getSidebar().getDecks().getByName("SheetManagerDeck")
            if not deck.isActive():
                return None
            panel = deck.getPanels().getByName("SheetManagerPanel")
            panel.expand(False)
            window = panel.getDialog()
            tree = tree_of(window) if window is not None else None
            return (window, tree) if tree is not None else None
        except NoSuchElementException:
            return None  # Native sidebar context setup is asynchronous after reopening.

    return poll(opened, "the expanded sheet panel")


def workbook(desktop):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    _CREATED.append(document)
    sheets = document.getSheets()
    sheets.getByIndex(0).setName(NAMES[0])
    for index, name in enumerate(NAMES[1:], 1):
        sheets.insertNewByName(name, index)
    document.getCurrentController().setActiveSheet(sheets.getByIndex(0))
    document.getUndoManager().clear()
    return document


def status(panel):
    return footer_text(panel, "Cell edits affect").getText()


def check_tabs(context, desktop):
    document = workbook(desktop)
    controller = document.getCurrentController()
    frame = controller.getFrame()
    panel, tree = open_list(context, document)
    poll(lambda: names(tree) == NAMES, "the initial sheet rows")
    before = root(tree)
    select_tabs(context, frame, [0, 2])
    poll(lambda: selection(tree, NAMES) == ["Alfa", "Charlie"], "a same-active tab change")
    assert controller.getActiveSheet().getName() == "Alfa"
    assert status(panel) == "Edits affect 2 Calc tabs: Alfa, Charlie", status(panel)
    assert root(tree) == before, "A selection-only change rebuilt the rows"

    # This is actual native tree input, not a call to the list's Python methods.
    Robot(context).click(tree, row_point(tree, 1), modifiers=VCL_MOD1)
    wanted = ["Alfa", "Bravo", "Charlie"]
    poll(lambda: selection(tree, NAMES) == wanted, "independent list picks")
    time.sleep(0.8)
    assert selection(tree, NAMES) == wanted
    assert status(panel) == "Edits affect 2 Calc tabs: Alfa, Charlie"

    def reorder():
        # An external macro preserves the native view while changing its numeric indices.
        sheets = document.getSheets()
        active = controller.getActiveSheet()
        sheets.moveByName("Alfa", 5)
        controller.setActiveSheet(active)
        order = list(sheets.getElementNames())
        select_tabs(context, frame, [order.index(name) for name in ("Alfa", "Charlie")])

    on_main_thread(context, reorder)
    order = list(document.getSheets().getElementNames())
    poll(lambda: names(tree) == order, "reordered rows")
    time.sleep(0.8)
    assert set(selection(tree, order)) == set(wanted), selection(tree, order)
    assert status(panel) == "Edits affect 2 Calc tabs: Charlie, Alfa", status(panel)
    select_tabs(context, frame, [order.index(name) for name in ("Alfa", "Delta")])
    poll(
        lambda: set(selection(tree, order)) == {"Alfa", "Delta"},
        "a later distinct native selection",
    )
    document.getSheets().getByName("Alfa").getCellRangeByName("A1").setValue(42)
    before = root(tree)
    time.sleep(0.8)
    assert root(tree) == before, "An ordinary cell edit rebuilt the rows"
    return {"same_active": True, "independent_picks": True, "logical_membership": True}


def check_hidden(context, desktop, headless):
    document = workbook(desktop)
    controller = document.getCurrentController()
    frame = controller.getFrame()
    _, tree = open_list(context, document)
    poll(lambda: names(tree) == NAMES, "rows before hiding the panel")
    Robot(context).click(tree, row_point(tree, 0))
    poll(lambda: selection(tree, NAMES) == ["Alfa"], "a known pick before hiding")
    sidebar = controller.getSidebar()
    deck = sidebar.getDecks().getByName("SheetManagerDeck")
    native_panel = deck.getPanels().getByName("SheetManagerPanel")
    native_panel.collapse()
    time.sleep(0.5)
    select_tabs(context, frame, [0, 2])
    time.sleep(1.2)
    assert selection(tree, NAMES) == ["Alfa"], selection(tree, NAMES)
    native_panel.expand(False)
    poll(lambda: selection(tree, NAMES) == ["Alfa", "Charlie"], "resuming after collapse")

    other = next(
        name for name in sidebar.getDecks().getElementNames() if name != "SheetManagerDeck"
    )
    dispatch(context, frame, ".uno:SidebarDeck." + other)
    time.sleep(0.5)
    select_tabs(context, frame, [0, 3])
    time.sleep(1.2)
    assert selection(tree, NAMES) == ["Alfa", "Charlie"], selection(tree, NAMES)
    _, tree = open_list(context, document)
    poll(lambda: selection(tree, NAMES) == ["Alfa", "Delta"], "resuming after a deck switch")

    dispatch(context, frame, ".uno:Sidebar")
    poll(lambda: not sidebar.isVisible(), "a closed sidebar")
    select_tabs(context, frame, [0, 4])
    time.sleep(1.2)
    _, tree = open_list(context, document)  # Closing can replace the native panel window.
    poll(lambda: selection(tree, NAMES) == ["Alfa", "Echo"], "resuming after reopening")
    if not headless:
        window = frame.getContainerWindow()
        window.IsMinimized = True
        poll(lambda: window.IsMinimized, "the minimized document window")
        select_tabs(context, frame, [0, 5])
        time.sleep(1.2)
        assert selection(tree, NAMES) == ["Alfa", "Echo"]
        window.IsMinimized = False
        poll(lambda: selection(tree, NAMES) == ["Alfa", "Foxtrot"], "resuming after minimize")
    return {"collapse": True, "other_deck": True, "reopen": True, "minimize": not headless}


def check_views(context, desktop):
    document = workbook(desktop)
    first = document.getCurrentController()
    panel, tree = open_list(context, document)
    poll(lambda: names(tree) == NAMES, "the first window's rows")
    dispatch(context, first.getFrame(), ".uno:NewWindow")
    enumeration = document.getControllers()
    controllers = []
    while enumeration.hasMoreElements():
        controllers.append(enumeration.nextElement())
    second = next(controller for controller in controllers if controller != first)
    second.setActiveSheet(document.getSheets().getByName("Foxtrot"))
    other_panel, other_tree = open_list(
        context, SimpleNamespace(getCurrentController=lambda: second)
    )
    poll(lambda: names(other_tree) == NAMES, "the second window's rows")
    # New-window initialization can conservatively invalidate document proof. Establish
    # explicit user picks before testing subsequent changes in the two independent views.
    robot = Robot(context)
    robot.click(tree, row_point(tree, 0))
    robot.double_click(other_tree, row_point(other_tree, 5))
    select_tabs(context, first.getFrame(), [0, 2])
    select_tabs(context, second.getFrame(), [3, 5])
    poll(lambda: selection(tree, NAMES) == ["Alfa", "Charlie"], "the first view's group")
    poll(lambda: selection(other_tree, NAMES) == ["Delta", "Foxtrot"], "the second view's group")
    assert status(panel) == "Edits affect 2 Calc tabs: Alfa, Charlie"
    assert status(other_panel) == "Edits affect 2 Calc tabs: Delta, Foxtrot"
    assert labels(tree)[0] == "Alfa" and labels(other_tree)[5] == "Foxtrot"
    document.getSheets().getByName("Bravo").setName("Renamed")
    order = list(document.getSheets().getElementNames())
    poll(lambda: names(tree) == order and names(other_tree) == order, "both windows' renamed rows")
    # A different foreground document must not become either observer's controller.
    other_document = workbook(desktop)
    open_list(context, other_document)
    select_tabs(context, first.getFrame(), [0, 4])
    poll(lambda: selection(tree, order) == ["Alfa", "Echo"], "the retained first controller")
    assert second.getActiveSheet().getName() == "Foxtrot"
    return {"per_window_tabs": True, "per_window_active": True, "shared_properties": True}


def check_reload(context, desktop, directory):
    document = workbook(desktop)
    document.storeAsURL((directory / "sync-reload.ods").as_uri(), (prop("Overwrite", True),))
    old = document.getCurrentController()
    frame = old.getFrame()
    open_list(context, document)
    document.setModified(False)
    loaded = _Loaded()
    broadcaster = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.GlobalEventBroadcaster", context
    )
    broadcaster.addDocumentEventListener(loaded)
    try:
        dispatch(context, frame, ".uno:Reload")
        poll(lambda: frame.getController() != old, "a replacement controller after reload")
        current = frame.getController()
        replacement = current.getModel()
        _CREATED.remove(document)
        _CREATED.append(replacement)
        poll(lambda: replacement in loaded.documents, "the replacement document's OnLoad")
        # Rows can exist before first-paint page-break initialization. Its native timer
        # restores the clean flag, which Calc still reports as a modify notification (#88).
        # Drain queued work before reacquiring the panel and establishing the baseline below;
        # a click across its identity invalidation must remain fail-closed. Neither
        # dispatch completion nor OnLoadFinished guarantees this work has finished.
        toolkit = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.awt.Toolkit", context
        )
        on_main_thread(context, toolkit.processEventsToIdle)
    finally:
        broadcaster.removeDocumentEventListener(loaded)
    # Reacquire the panel after native sidebar context initialization.
    panel, tree = open_list(context, replacement)
    poll(lambda: names(tree) == NAMES, "the reloaded rows")
    select_tabs(context, frame, [0, 2])
    poll(
        lambda: status(panel) == "Edits affect 2 Calc tabs: Alfa, Charlie",
        "the replacement controller's group status",
    )
    # The settled replacement panel must observe later input and the replacement model.
    Robot(context).click(tree, row_point(tree, 0))
    try:
        poll(lambda: selection(tree, NAMES) == ["Alfa"], "an explicit pick after reload")
    except AssertionError as error:
        error.add_note(
            f"Reloaded rows={names(tree)!r}, picks={selection(tree, NAMES)!r}, "
            f"status={status(panel)!r}, focused={tree.hasFocus()!r}"
        )
        try:
            window = frame.getContainerWindow()
            error.add_note(
                f"Tree bounds={tree.getPosSize()!r}, visible={tree.isVisible()!r}, "
                f"enabled={tree.isEnabled()!r}, frame_active={frame.isActive()!r}, "
                f"frame_enabled={window.isEnabled()!r}, frame_visible={window.isVisible()!r}, "
                f"same_controller={frame.getController() == current!r}"
            )
        except Exception as diagnostic_error:
            error.add_note(f"Reload window diagnostics failed: {diagnostic_error!r}")
        raise
    select_tabs(context, frame, [0, 3])
    poll(lambda: selection(tree, NAMES) == ["Alfa", "Delta"], "the replacement observer")
    replacement.getSheets().getByName("Bravo").setName("AfterReload")
    expected = ["Alfa", "AfterReload", *NAMES[2:]]
    poll(lambda: names(tree) == expected, "a property change on the replacement model")
    return {"controller_replaced": True, "replacement_observer": True}


def exercise(context, desktop, directory, output, *, headless):
    checks = (
        ("tabs", lambda: check_tabs(context, desktop)),
        ("hidden", lambda: check_hidden(context, desktop, headless)),
        ("views", lambda: check_views(context, desktop)),
        ("reload", lambda: check_reload(context, desktop, directory)),
    )
    results = {}
    for check in checks:
        # Keep every window needed by one case, then release it before the next case.
        # Accumulating unrelated workbooks can exhaust native window resources (#45).
        results.update(
            run_checks(
                (check,),
                _CREATED,
                lambda document: close_document(context, document),
                label="view synchronization check",
            )
        )
    return results
