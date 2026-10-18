"""The sheet list in a live office: contents, refresh, identity, clicks, the menu, and Show.

This feature suite runs in every integration session, on Linux and Windows, against the
packaged modules. LibreOffice's XToolkitRobot posts mouse and key events into VCL's own queue.
Robot key events bypass key handlers and robot input cannot carry a native drag, so the key
handler and drag and drop are covered by the real-input UI tests and the manual checklist.
Moving sheets is covered by ``test_reorder.py``.
"""

import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import uno
from com.sun.star.awt import KeyEvent, MouseEvent
from com.sun.star.beans import PropertyValue
from com.sun.star.table import CellRangeAddress
from sheet_list_view import (
    enabled_menu_items,
    labels,
    names,
    nodes,
    open_list,
    poll,
    row_point,
    selected_tabs,
    selection,
)

from sheet_manager import keys
from sheet_manager.sheet_list import SheetRow, row_label, tab_color
from sheet_manager.uno_reorder import snapshot
from sheet_manager.uno_show import show_sheets

# XToolkitRobot passes mouse buttons and modifiers to VCL unconverted.
VCL_LEFT, VCL_RIGHT, VCL_SHIFT, VCL_MOD1 = 1, 4, 0x1000, 0x2000
# LibreOffice's Python runs from the program directory on every platform.
PROGRAM = Path(sys.executable).resolve().parent
SIX = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]


def say(text):
    print("   ", text, flush=True)


class Robot:
    def __init__(self, context):
        self.toolkit = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.awt.Toolkit", context
        )

    def click(self, window, point, buttons=VCL_LEFT, modifiers=0):
        event = MouseEvent()
        event.Source = window
        event.Buttons, event.Modifiers, event.ClickCount = buttons, modifiers, 1
        event.X, event.Y = point
        self.toolkit.mouseMove(event)
        self.toolkit.mousePress(event)
        self.toolkit.mouseRelease(event)
        time.sleep(0.6)  # Keep the next click from becoming a double click.

    def key(self, window, code):
        event = KeyEvent()
        event.Source = window
        event.KeyCode = code
        self.toolkit.keyPress(event)
        self.toolkit.keyRelease(event)
        time.sleep(0.1)

    def dismiss(self, frame):
        """Close a message box over this frame, if one is open."""
        top = self.toolkit.getActiveTopWindow()
        if top is not None and top != frame.getContainerWindow():
            self.key(top, keys.RETURN)
            time.sleep(0.5)

    def choose(self, window, items, command):
        """Choose an entry of the open built-in menu by position."""
        self.key(window, keys.HOME)
        for _ in range(items.index(command)):
            self.key(window, keys.DOWN)
        self.key(window, keys.RETURN)


@contextmanager
def undo_capacity(context, steps):
    # The context belongs to the runner's private office and profile, never the user profile.
    provider = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", context
    )
    argument = PropertyValue()
    argument.Name, argument.Value = "nodepath", "/org.openoffice.Office.Common/Undo"
    access = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationUpdateAccess", (argument,)
    )
    original = access.getPropertyValue("Steps")
    try:
        access.setPropertyValue("Steps", steps)
        access.commitChanges()
        yield
    finally:
        access.setPropertyValue("Steps", original)
        access.commitChanges()
        access.dispose()


def make_workbook(desktop, sheet_names):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    document.getCurrentController().getFrame().activate()
    sheets = document.getSheets()
    sheets.getByIndex(0).setName(sheet_names[0])
    for index, name in enumerate(sheet_names[1:], start=1):
        sheets.insertNewByName(name, index)
    document.getCurrentController().setActiveSheet(sheets.getByIndex(0))
    document.getUndoManager().clear()
    return document


def replace(document, name):
    """Delete a sheet and insert a different one with the same name at the same place."""
    sheets = document.getSheets()
    index = list(sheets.getElementNames()).index(name)
    sheets.removeByName(name)
    sheets.insertNewByName(name, index)
    sheets.getByName(name).getCellRangeByName("A1").setString("replacement")


def expected_labels(document):
    active = document.getCurrentController().getActiveSheet().getName()
    sheets = document.getSheets()
    rows = []
    for index in range(sheets.getCount()):
        sheet = sheets.getByIndex(index)
        rows.append(
            row_label(
                SheetRow(
                    name=sheet.getName(),
                    visible=bool(sheet.IsVisible),
                    active=sheet.getName() == active,
                    protected=bool(sheet.isProtected()),
                    scenario=bool(sheet.getIsScenario()),
                    color=tab_color(sheet.TabColor),
                )
            )
        )
    return rows


def check_key_constants():
    for name in ("SHIFT", "MOD1", "MOD2", "MOD3"):
        assert getattr(keys, name) == uno.getConstantByName(f"com.sun.star.awt.KeyModifier.{name}")
    for name in (
        "A",
        "F1",
        "F2",
        "F6",
        "F10",
        "F26",
        "DOWN",
        "UP",
        "LEFT",
        "RIGHT",
        "HOME",
        "END",
        "PAGEUP",
        "PAGEDOWN",
        "RETURN",
        "ESCAPE",
        "TAB",
        "BACKSPACE",
        "SPACE",
        "INSERT",
        "DELETE",
        "CONTEXTMENU",
    ):
        assert getattr(keys, name) == uno.getConstantByName(f"com.sun.star.awt.Key.{name}"), name


def check_states_and_refresh(context, desktop):
    document = make_workbook(desktop, ["North", "South", "East", "West", "Base"])
    sheets = document.getSheets()
    sheets.getByName("South").protect("")
    sheets.getByName("East").TabColor = 0x2A6099
    sheets.getByName("West").IsVisible = False
    address = CellRangeAddress()
    address.Sheet, address.EndColumn, address.EndRow = 4, 1, 1
    sheets.getByName("Base").getScenarios().addNewByName("Case", (address,), "synthetic")
    _, tree = open_list(context, document)
    expected = expected_labels(document)
    poll(lambda: labels(tree) == expected, f"the labels {expected}")
    graphics = {node.DataValue: node.getNodeGraphicURL() for node in nodes(tree)}
    assert graphics["East"] and graphics["East"] != graphics["North"], graphics
    sheets.insertNewByName("Added", sheets.getCount())
    poll(lambda: names(tree)[-1:] == ["Added"], "an inserted sheet to appear")
    sheets.getByName("Added").setName("Renamed")
    poll(lambda: names(tree)[-1:] == ["Renamed"], "a renamed sheet to appear")
    sheets.removeByName("Renamed")
    poll(lambda: "Renamed" not in names(tree), "a removed sheet to disappear")
    controller = document.getCurrentController()
    controller.setActiveSheet(sheets.getByName("East"))
    order = list(sheets.getElementNames())
    poll(lambda: selection(tree, order) == ["East"], "the list to follow the active sheet")
    poll(lambda: labels(tree) == expected_labels(document), "the active marker to move")
    seen = labels(tree)
    document.close(True)
    return {"labels": seen, "graphics_differ": True}


def tabs_of(context, document):
    order = list(document.getSheets().getElementNames())
    return [order[index] for index in selected_tabs(context, document.getCurrentController())]


def check_selection_and_menu(context, desktop):
    sheet_names = ["One", "Two", "Three", "Four", "Five", "Six"]
    document = make_workbook(desktop, sheet_names)
    controller = document.getCurrentController()
    frame = controller.getFrame()
    sheets = document.getSheets()
    sheets.getByName("Six").IsVisible = False
    _, tree = open_list(context, document)
    poll(lambda: names(tree) == sheet_names, "every sheet in the list")
    robot = Robot(context)

    def tabs():
        return tabs_of(context, document)

    say("click, Ctrl+click, Shift+click, hidden row")
    robot.click(tree, row_point(tree, 2))
    poll(lambda: controller.getActiveSheet().getName() == "Three", "a click to activate")
    robot.click(tree, row_point(tree, 4), modifiers=VCL_MOD1)
    poll(lambda: selection(tree, sheet_names) == ["Three", "Five"], "Ctrl+click")
    robot.click(tree, row_point(tree, 0), modifiers=VCL_SHIFT)
    poll(lambda: len(selection(tree, sheet_names)) == 5, "Shift+click")
    shift = selection(tree, sheet_names)
    assert controller.getActiveSheet().getName() == "Three" and tabs() == ["Three"], tabs()
    robot.click(tree, row_point(tree, 5))
    poll(lambda: selection(tree, sheet_names) == ["Six"], "a click on a hidden row")
    assert controller.getActiveSheet().getName() == "Three", "A hidden row must not activate"

    say("menu: Calc's tabs are exactly the picked sheets, and Hide acts on them")
    robot.click(tree, row_point(tree, 1))
    robot.click(tree, row_point(tree, 3), modifiers=VCL_MOD1)
    poll(lambda: selection(tree, sheet_names) == ["Two", "Four"], "two rows for the menu")
    undo = document.getUndoManager()
    depth = len(undo.getAllUndoActionTitles())
    robot.click(tree, row_point(tree, 3), buttons=VCL_RIGHT)
    grouped = poll(lambda: tabs() if tabs() == ["Two", "Four"] else None, "grouped tabs")
    items = enabled_menu_items(context, frame, PROGRAM)
    robot.choose(tree, items, ".uno:Hide")

    def hidden():
        return [name for name in sheet_names if not sheets.getByName(name).IsVisible]

    poll(lambda: hidden() == ["Two", "Four", "Six"], "Hide to hide exactly the picked sheets")
    hid = hidden()
    while len(undo.getAllUndoActionTitles()) > depth:
        undo.undo()
    poll(lambda: hidden() == ["Six"], "undo to show the sheets again")

    say("a plain click after the menu leaves exactly one selected tab (#25)")
    robot.click(tree, row_point(tree, 1))
    robot.click(tree, row_point(tree, 3), modifiers=VCL_MOD1)
    robot.click(tree, row_point(tree, 3), buttons=VCL_RIGHT)
    poll(lambda: tabs() == ["Two", "Four"], "the menu to group the tabs")
    robot.key(tree, keys.ESCAPE)
    time.sleep(0.5)
    robot.click(tree, row_point(tree, 1))
    poll(lambda: tabs() == ["Two"], "a plain click to leave one selected tab")
    after_click = tabs()
    document.close(True)
    return {
        "shift_selection": shift,
        "calc_tabs_while_menu_open": grouped,
        "hidden_after_menu": hid,
        "tabs_after_plain_click": after_click,
    }


def check_identity(context, desktop):
    """A replaced or renamed sheet drops out of the selection and the menu (#28)."""
    document = make_workbook(desktop, SIX)
    controller = document.getCurrentController()
    frame = controller.getFrame()
    sheets = document.getSheets()
    _, tree = open_list(context, document)
    poll(lambda: names(tree) == SIX, "every sheet in the list")
    robot = Robot(context)
    order = SIX

    say("delete and recreate a selected sheet with the same name and place")
    robot.click(tree, row_point(tree, 0))
    robot.click(tree, row_point(tree, 1), modifiers=VCL_MOD1)
    poll(lambda: selection(tree, order) == ["Alfa", "Bravo"], "Alfa and Bravo selected")
    replace(document, "Bravo")
    poll(lambda: selection(tree, order) == ["Alfa"], "the replaced sheet to leave the selection")
    robot.click(tree, row_point(tree, 0), buttons=VCL_RIGHT)
    menu_tabs = poll(
        lambda: tabs_of(context, document) if tabs_of(context, document) == ["Alfa"] else None,
        "the menu to act only on Alfa",
    )
    robot.key(tree, keys.ESCAPE)
    time.sleep(0.5)

    say("rename a selected sheet and give its name to another")
    robot.click(tree, row_point(tree, 2))
    robot.click(tree, row_point(tree, 3), modifiers=VCL_MOD1)
    poll(lambda: selection(tree, order) == ["Charlie", "Delta"], "Charlie and Delta selected")
    sheets.getByName("Charlie").setName("Spare")
    sheets.getByName("Delta").setName("Charlie")
    renamed = ["Alfa", "Bravo", "Spare", "Charlie", "Echo", "Foxtrot"]
    poll(lambda: names(tree) == renamed, "the renamed rows")
    poll(lambda: selection(tree, renamed) == [], "the renamed sheets to leave the selection")

    say("replace a picked sheet while the built-in menu is open")
    robot.click(tree, row_point(tree, 4))
    robot.click(tree, row_point(tree, 5), modifiers=VCL_MOD1)
    poll(lambda: selection(tree, renamed) == ["Echo", "Foxtrot"], "Echo and Foxtrot selected")
    undo = document.getUndoManager()
    robot.click(tree, row_point(tree, 5), buttons=VCL_RIGHT)
    poll(lambda: tabs_of(context, document) == ["Echo", "Foxtrot"], "the menu to group the tabs")
    items = enabled_menu_items(context, frame, PROGRAM)
    replace(document, "Foxtrot")
    titles = list(undo.getAllUndoActionTitles())
    robot.choose(tree, items, ".uno:Hide")
    time.sleep(1.5)
    robot.dismiss(frame)  # The refusal message; a headless office cancels it by itself.
    shown = all(sheets.getByName(name).IsVisible for name in ("Echo", "Foxtrot"))
    assert shown and list(undo.getAllUndoActionTitles()) == titles, "A stale command ran"
    poll(lambda: "Foxtrot" not in selection(tree, renamed), "the replacement to stay unpicked")
    document.close(True)
    return {"menu_tabs_after_replacement": menu_tabs, "stale_menu_command_refused": True}


class _FailingHandle:
    """Forwards to a real sheet, but fails when asked to show it after `allowed` others."""

    def __init__(self, real, counter):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_counter", counter)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        if name == "IsVisible" and value:
            self._counter["shown"] += 1
            if self._counter["shown"] > self._counter["allowed"]:
                raise RuntimeError("injected failure")
        setattr(self._real, name, value)


class _FailingSheets:
    def __init__(self, real, counter):
        self._real, self._counter = real, counter

    def __getattr__(self, name):
        return getattr(self._real, name)

    def getByName(self, name):
        return _FailingHandle(self._real.getByName(name), self._counter)


class _FailingDocument:
    def __init__(self, real, allowed):
        self._real = real
        self._sheets = _FailingSheets(real.getSheets(), {"shown": 0, "allowed": allowed})

    def __getattr__(self, name):
        return getattr(self._real, name)

    def getSheets(self):
        return self._sheets


def hidden_workbook(desktop, hidden):
    document = make_workbook(desktop, SIX)
    for name in hidden:
        document.getSheets().getByName(name).IsVisible = False
    document.getUndoManager().clear()
    return document


def visible(document, sheet_names):
    return [name for name in sheet_names if document.getSheets().getByName(name).IsVisible]


def check_show(context, desktop):
    """Show is one undo step, refused without undo, and undone after a partial failure (#27)."""
    targets = ["Bravo", "Delta", "Echo"]
    results: dict[str, Any] = {}

    document = hidden_workbook(desktop, targets)
    undo = document.getUndoManager()
    result = show_sheets(context, document, snapshot(document), targets)
    assert result.status == "done" and visible(document, targets) == targets, result
    assert list(undo.getAllUndoActionTitles()) == ["Show Sheets"]
    undo.undo()
    assert visible(document, targets) == [], "One undo must hide all three again"
    results["one_undo_step"] = True

    undo.clear()
    undo.lock()
    try:
        result = show_sheets(context, document, snapshot(document), targets)
    finally:
        undo.unlock()
    assert result.status == "refused" and visible(document, targets) == [], result
    document.IsUndoEnabled = False
    try:
        result = show_sheets(context, document, snapshot(document), targets)
    finally:
        document.IsUndoEnabled = True
    assert result.status == "refused" and visible(document, targets) == [], result
    with undo_capacity(context, 0):
        result = show_sheets(context, document, snapshot(document), targets)
    assert result.status == "refused" and visible(document, targets) == [], result
    with undo_capacity(context, 2):
        result = show_sheets(context, document, snapshot(document), targets)
    assert result.status == "refused" and "3" in result.message, result
    results["refused_without_undo"] = True

    observed = snapshot(document)
    replace(document, "Delta")
    document.getSheets().getByName("Delta").IsVisible = False
    undo.clear()
    result = show_sheets(context, document, observed, targets)
    assert result.status == "refused" and visible(document, targets) == [], result
    results["refused_when_stale"] = True

    # The second case fills a two-step history, so that the group evicts the oldest action.
    for capacity, history, picked in ((100, 0, targets), (2, 2, targets[:2])):
        with undo_capacity(context, capacity):
            undo.clear()
            cell = document.getSheets().getByName("Alfa").getCellRangeByName("A1")
            for value in range(history):
                cell.setValue(value + 1)  # A full stack: the user's own last actions.
            before = list(undo.getAllUndoActionTitles())
            failing = _FailingDocument(document, allowed=1)
            result = show_sheets(context, failing, snapshot(failing), picked)
            assert result.status == "failed-restored", result
            assert visible(document, targets) == [], "A partial show must be undone"
            assert list(undo.getAllRedoActionTitles()) == []
            if history:
                assert cell.getValue() == history, "Recovery must keep the user's last edit"
                assert list(undo.getAllUndoActionTitles())[: history - 1] == before[: history - 1]
    results["partial_failure_restored"] = True
    document.close(True)
    return results


def measure_large_workbook(context, desktop, count):
    """Time the list's rebuild after an activation; recorded, not asserted (see #22)."""
    document = make_workbook(desktop, [f"Sheet {n:04}" for n in range(1, count + 1)])
    started = time.monotonic()
    _, tree = open_list(context, document)
    poll(lambda: len(names(tree)) == count, "every sheet in a large list", timeout=120)
    opened = time.monotonic() - started
    controller = document.getCurrentController()
    target = document.getSheets().getByIndex(count // 2)
    started = time.monotonic()
    controller.setActiveSheet(target)
    order = list(document.getSheets().getElementNames())
    poll(lambda: selection(tree, order) == [target.getName()], "a large list to follow", 120)
    followed = time.monotonic() - started
    document.close(True)
    return {"sheets": count, "open_seconds": round(opened, 2), "follow_seconds": round(followed, 2)}


def exercise(context, desktop, directory, output):
    results: dict[str, object] = {}
    for name, check in (
        ("key_constants", check_key_constants),
        ("states_and_refresh", lambda: check_states_and_refresh(context, desktop)),
        ("selection_and_menu", lambda: check_selection_and_menu(context, desktop)),
        ("identity", lambda: check_identity(context, desktop)),
        ("show", lambda: check_show(context, desktop)),
        ("large_workbook", lambda: measure_large_workbook(context, desktop, 1000)),
    ):
        print("sheet list check:", name, flush=True)
        results[name] = check() or True
    return results
