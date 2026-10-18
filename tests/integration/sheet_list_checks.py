"""Headless checks of the sheet list: what it shows, how it follows Calc, robot clicks, the menu.

These run in every headless integration session, on Linux and Windows. LibreOffice's
XToolkitRobot posts mouse and key events into VCL's own queue. Robot key events bypass key
handlers and robot input cannot carry a native drag, so the key handler and drag and drop are
covered by the real-input UI tests under Xvfb and by the manual checklist.
"""

import sys
import time
from pathlib import Path

import uno
from com.sun.star.awt import KeyEvent, MouseEvent
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sheet_manager import keys  # noqa: E402
from sheet_manager.sheet_list import SheetRow, row_label, tab_color  # noqa: E402
from sheet_manager.temporary_move import move_block  # noqa: E402

# XToolkitRobot passes mouse buttons and modifiers to VCL unconverted.
VCL_LEFT, VCL_RIGHT, VCL_SHIFT, VCL_MOD1 = 1, 4, 0x1000, 0x2000


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


def say(text):
    print("  ", text, flush=True)


def expected_labels(document):
    controller = document.getCurrentController()
    active = controller.getActiveSheet().getName()
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


def make_workbook(desktop, sheet_names):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    sheets = document.getSheets()
    sheets.getByIndex(0).setName(sheet_names[0])
    for index, name in enumerate(sheet_names[1:], start=1):
        sheets.insertNewByName(name, index)
    document.getCurrentController().setActiveSheet(sheets.getByIndex(0))
    document.getUndoManager().clear()
    return document


def check_states_and_refresh(context, desktop):
    document = make_workbook(desktop, ["North", "South", "East", "West", "Base"])
    sheets = document.getSheets()
    sheets.getByName("South").protect("")
    sheets.getByName("East").TabColor = 0x2A6099
    sheets.getByName("West").IsVisible = False
    address = CellRangeAddress()
    address.Sheet, address.EndColumn, address.EndRow = 4, 1, 1
    sheets.getByName("Base").getScenarios().addNewByName("Case", (address,), "synthetic")
    say("_, tree = open_list")
    _, tree = open_list(context, document)
    expected = expected_labels(document)
    poll(lambda: labels(tree) == expected, f"the labels {expected}")
    graphics = {node.DataValue: node.getNodeGraphicURL() for node in nodes(tree)}
    assert graphics["East"] and graphics["East"] != graphics["North"], graphics
    say('sheets.insertNewByName("Added"')
    sheets.insertNewByName("Added", sheets.getCount())
    poll(lambda: names(tree)[-1:] == ["Added"], "an inserted sheet to appear")
    sheets.getByName("Added").setName("Renamed")
    poll(lambda: names(tree)[-1:] == ["Renamed"], "a renamed sheet to appear")
    sheets.removeByName("Renamed")
    poll(lambda: "Renamed" not in names(tree), "a removed sheet to disappear")
    controller = document.getCurrentController()
    say('controller.setActiveSheet(sheets.getByName("East"))')
    controller.setActiveSheet(sheets.getByName("East"))
    order = list(sheets.getElementNames())
    poll(lambda: selection(tree, order) == ["East"], "the list to follow the active sheet")
    poll(lambda: labels(tree) == expected_labels(document), "the active marker to move")
    # The temporary mover refuses workbooks with scenarios rather than split a base.
    refused = move_block(document, order, ["North"], len(order))
    assert refused.status == "refused" and list(sheets.getElementNames()) == order, refused
    labels_seen = labels(tree)
    document.close(True)
    return {"labels": labels_seen, "graphics_differ": True, "mover_refuses_scenarios": True}


def check_robot_selection_and_menu(context, desktop, program):
    sheet_names = ["One", "Two", "Three", "Four", "Five", "Six"]
    document = make_workbook(desktop, sheet_names)
    controller = document.getCurrentController()
    frame = controller.getFrame()
    sheets = document.getSheets()
    sheets.getByName("Six").IsVisible = False
    say("_, tree = open_list")
    _, tree = open_list(context, document)
    poll(lambda: names(tree) == sheet_names, "every sheet in the list")
    robot = Robot(context)

    def tabs():
        return [sheet_names[index] for index in selected_tabs(context, controller)]

    say("robot.click(")

    robot.click(tree, row_point(tree, 2))
    poll(lambda: controller.getActiveSheet().getName() == "Three", "a click to activate")
    say("robot.click(")
    robot.click(tree, row_point(tree, 4), modifiers=VCL_MOD1)
    poll(lambda: selection(tree, sheet_names) == ["Three", "Five"], "Ctrl+click")
    say("robot.click(")
    robot.click(tree, row_point(tree, 0), modifiers=VCL_SHIFT)
    poll(lambda: len(selection(tree, sheet_names)) == 5, "Shift+click")
    shift = selection(tree, sheet_names)
    assert controller.getActiveSheet().getName() == "Three" and tabs() == ["Three"], tabs()
    say("robot.click(")
    robot.click(tree, row_point(tree, 5))
    poll(lambda: selection(tree, sheet_names) == ["Six"], "a click on a hidden row")
    assert controller.getActiveSheet().getName() == "Three", "A hidden row must not activate"

    # The menu: Calc's tabs are set to exactly the picked sheets, and a command acts on them.
    say("robot.click(")
    robot.click(tree, row_point(tree, 1))
    say("robot.click(")
    robot.click(tree, row_point(tree, 3), modifiers=VCL_MOD1)
    poll(lambda: selection(tree, sheet_names) == ["Two", "Four"], "two rows for the menu")
    undo = document.getUndoManager()
    depth = len(undo.getAllUndoActionTitles())
    say("robot.click(")
    robot.click(tree, row_point(tree, 3), buttons=VCL_RIGHT)
    tabs_while_open = poll(lambda: tabs() if tabs() == ["Two", "Four"] else None, "grouped tabs")
    say("items = enabled_menu_items")
    items = enabled_menu_items(context, frame, program)
    say("robot.key(tree, keys.HOME)")
    robot.key(tree, keys.HOME)
    for _ in range(items.index(".uno:Hide")):
        robot.key(tree, keys.DOWN)
    robot.key(tree, keys.RETURN)

    def hidden():
        return [name for name in sheet_names if not sheets.getByName(name).IsVisible]

    poll(lambda: hidden() == ["Two", "Four", "Six"], "Hide to hide exactly the picked sheets")
    hid = hidden()
    while len(undo.getAllUndoActionTitles()) > depth:
        undo.undo()
    document.close(True)
    return {
        "shift_selection": shift,
        "calc_tabs_while_menu_open": tabs_while_open,
        "hidden_after_menu": hid,
    }


def check_temporary_mover(desktop):
    sheet_names = ["A1", "B2", "C3", "D4", "E5", "F6"]
    document = make_workbook(desktop, sheet_names)
    sheets = document.getSheets()
    undo = document.getUndoManager()
    result = move_block(document, sheet_names, ["B2", "D4"], 6)
    after = list(sheets.getElementNames())
    titles = list(undo.getAllUndoActionTitles())
    assert result.status == "moved" and after == ["A1", "C3", "E5", "F6", "B2", "D4"], after
    assert titles == ["Move Sheets"], titles
    undo.undo()
    assert list(sheets.getElementNames()) == sheet_names
    unchanged = move_block(document, sheet_names, ["C3", "D4"], 4)
    assert unchanged.status == "unchanged" and list(undo.getAllUndoActionTitles()) == []
    stale = move_block(document, list(reversed(sheet_names)), ["A1"], 6)
    assert stale.status == "refused" and list(sheets.getElementNames()) == sheet_names
    document.close(True)
    return {"moved": after, "undo_titles": titles, "unchanged": True, "stale_refused": True}


def measure_large_workbook(context, desktop, count):
    """Time the list's rebuild after an activation; recorded, not asserted (see #5)."""
    document = make_workbook(desktop, [f"Sheet {n:04}" for n in range(1, count + 1)])
    started = time.monotonic()
    say("_, tree = open_list")
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


def check_sheet_list(context, desktop, program):
    results: dict[str, object] = {}
    for name, check in (
        ("key_constants", check_key_constants),
        ("states_and_refresh", lambda: check_states_and_refresh(context, desktop)),
        ("temporary_mover", lambda: check_temporary_mover(desktop)),
        (
            "robot_selection_and_menu",
            lambda: check_robot_selection_and_menu(context, desktop, program),
        ),
        ("large_workbook", lambda: measure_large_workbook(context, desktop, 1000)),
    ):
        print("sheet list check:", name, flush=True)
        results[name] = check() or True
    return results
