"""The sheet list in a live office: contents, refresh, identity, clicks, the menu, and Show.

This feature suite runs in every integration session, on Linux and Windows, against the
packaged modules. LibreOffice's XToolkitRobot posts mouse and key events into VCL's own queue.
Robot key events bypass key handlers and robot input cannot carry a native drag, so the key
handler and drag and drop are covered by the real-input UI tests and the manual checklist.
Robot input reaches the sheet tab menu only where VCL draws it, in headless sessions; a painted
gtk3 session opens a native GTK menu, so there the suite skips its menu steps and the real-input
UI tests cover the menu. Moving sheets is covered by ``test_reorder.py``.
"""

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import uno
from com.sun.star.awt import KeyEvent, MouseEvent
from com.sun.star.beans import PropertyValue
from com.sun.star.table import CellRangeAddress
from main_thread import close_document
from sheet_list_view import (
    BATCHES,
    LOCKS,
    UNRECORDED,
    cover_batch,
    enabled_menu_items,
    held_batch,
    labels,
    names,
    on_main_thread,
    open_list,
    poll,
    release,
    root,
    row_point,
    selected_tabs,
    selection,
    unrecorded_batch,
)
from teardown import Configured, run_checks

from sheet_manager import keys, uno_list
from sheet_manager.sheet_list import SheetRow, row_label, tab_color
from sheet_manager.uno_calc import select_tabs
from sheet_manager.uno_reorder import snapshot
from sheet_manager.uno_show import show_sheets

# XToolkitRobot passes mouse buttons and modifiers to VCL unconverted.
VCL_LEFT, VCL_RIGHT, VCL_SHIFT, VCL_MOD1 = 1, 4, 0x1000, 0x2000
# LibreOffice's Python runs from the program directory on every platform.
PROGRAM = Path(sys.executable).resolve().parent
SIX = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
NATIVE_MENU = "menu steps skipped: robot input cannot reach a native gtk3 menu (see tests/ui)"
# Workbooks a check created and has not closed yet; a failed check leaves its own open, and a
# painted office would then ask whether to save them when the runner terminates it (#40).
_CREATED: list[Any] = []


def say(text):
    print("   ", text, flush=True)


class Robot:
    def __init__(self, context):
        self.toolkit = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.awt.Toolkit", context
        )

    def _event(self, window, point, buttons, modifiers):
        event = MouseEvent()
        event.Source = window
        event.Buttons, event.Modifiers, event.ClickCount = buttons, modifiers, 1
        event.X, event.Y = point
        return event

    def click(self, window, point, buttons=VCL_LEFT, modifiers=0, pause=0.6):
        """Click; the pause keeps the next click on the same row from becoming a double click.

        The robot only posts the events, so without a pause they are still queued when this
        returns, ahead of anything the list schedules later. The pointer moves with no button
        down, as a hand moves it between clicks: a move that reports a held button right after
        a press can start a drag.
        """
        event = self._event(window, point, buttons, modifiers)
        self.toolkit.mouseMove(self._event(window, point, 0, modifiers))
        self.toolkit.mousePress(event)
        self.toolkit.mouseRelease(event)
        time.sleep(pause)

    def press(self, window, point):
        self.toolkit.mouseMove(self._event(window, point, 0, 0))
        self.toolkit.mousePress(self._event(window, point, VCL_LEFT, 0))

    def double_click(self, window, point, pause=0.6):
        self.click(window, point, pause=0)
        event = self._event(window, point, VCL_LEFT, 0)
        event.ClickCount = 2
        self.toolkit.mousePress(event)
        self.toolkit.mouseRelease(event)
        time.sleep(pause)

    def release(self, window, point):
        self.toolkit.mouseRelease(self._event(window, point, VCL_LEFT, 0))

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
        self.key(window, keys.END)
        self.key(window, keys.UP)
        self.key(window, keys.RIGHT)
        self.key(window, keys.HOME)
        for _ in range(items.index(command)):
            self.key(window, keys.DOWN)
        self.key(window, keys.RETURN)


def undo_capacity(context, steps):
    """Set the undo limit for a `with` block; restored after it unless a callback stalled (#51)."""
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

    def set_steps(value):
        access.setPropertyValue("Steps", value)
        access.commitChanges()

    def restore():
        set_steps(original)
        access.dispose()

    return Configured(lambda: set_steps(steps), restore)


def make_workbook(desktop, sheet_names):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    _CREATED.append(document)
    document.getCurrentController().getFrame().activate()
    sheets = document.getSheets()
    sheets.getByIndex(0).setName(sheet_names[0])
    for index, name in enumerate(sheet_names[1:], start=1):
        sheets.insertNewByName(name, index)
    document.getCurrentController().setActiveSheet(sheets.getByIndex(0))
    document.getUndoManager().clear()
    return document


def close_workbook(context, document):
    """Close a workbook a check created; it then needs no clean-up."""
    close_document(context, document)
    _CREATED.remove(document)


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
    # Tab colours and the current marker are painted in the gutter; the text stays plain.
    assert sheets.getByName("East").TabColor != sheets.getByName("North").TabColor
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
    close_workbook(context, document)
    return {"labels": seen, "plain_labels": True}


def tabs_of(context, document):
    order = list(document.getSheets().getElementNames())
    return [order[index] for index in selected_tabs(context, document.getCurrentController())]


def check_selection_and_menu(context, desktop, menus):
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
    poll(lambda: selection(tree, sheet_names) == ["Three"], "a click to select")
    assert controller.getActiveSheet().getName() != "Three"
    robot.double_click(tree, row_point(tree, 2))
    poll(lambda: controller.getActiveSheet().getName() == "Three", "double-click activation")
    robot.click(tree, row_point(tree, 4), modifiers=VCL_MOD1)
    poll(lambda: selection(tree, sheet_names) == ["Three", "Five"], "Ctrl+click")
    robot.click(tree, row_point(tree, 0), modifiers=VCL_SHIFT)
    poll(lambda: len(selection(tree, sheet_names)) == 5, "Shift+click")
    shift = selection(tree, sheet_names)
    assert controller.getActiveSheet().getName() == "Three" and tabs() == ["Three"], tabs()
    robot.click(tree, row_point(tree, 5))
    poll(lambda: selection(tree, sheet_names) == ["Six"], "a click on a hidden row")
    assert controller.getActiveSheet().getName() == "Three", "A hidden row must not activate"
    if not menus:
        say(NATIVE_MENU)
        close_workbook(context, document)
        return {"shift_selection": shift, "menu": "skipped"}

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
    poll(lambda: labels(tree) == expected_labels(document), "the list to show them again")

    say("activation after the menu leaves exactly one selected tab (#25)")
    robot.click(tree, row_point(tree, 1))
    robot.click(tree, row_point(tree, 3), modifiers=VCL_MOD1)
    robot.click(tree, row_point(tree, 3), buttons=VCL_RIGHT)
    poll(lambda: tabs() == ["Two", "Four"], "the menu to group the tabs")
    robot.key(tree, keys.ESCAPE)
    time.sleep(0.5)
    robot.double_click(tree, row_point(tree, 1))
    poll(lambda: tabs() == ["Two"], "activation to leave one selected tab")
    after_click = tabs()
    close_workbook(context, document)
    return {
        "shift_selection": shift,
        "calc_tabs_while_menu_open": grouped,
        "hidden_after_menu": hid,
        "tabs_after_plain_click": after_click,
    }


def check_identity(context, desktop, menus):
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
    # A sheet was deleted and one inserted: no retained handle proves its sheet any more, so
    # every pick goes, not only the replaced one (#28).
    poll(lambda: selection(tree, order) == [], "the picks to be dropped")
    menu_tabs = None
    if menus:
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
    if not menus:
        say(NATIVE_MENU)
        close_workbook(context, document)
        return {"menu": "skipped"}

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
    close_workbook(context, document)
    return {"menu_tabs_after_replacement": menu_tabs, "stale_menu_command_refused": True}


def check_stale_clicks(context, desktop):
    """Clicks that meet rows the list has not refreshed yet (#28, #43, #44)."""
    document = make_workbook(desktop, SIX)
    controller = document.getCurrentController()
    sheets = document.getSheets()
    _, tree = open_list(context, document)
    robot = Robot(context)
    results: dict[str, Any] = {}

    def active():
        return controller.getActiveSheet().getName()

    def settled():
        poll(lambda: labels(tree) == expected_labels(document), "the list to show the workbook")

    def unchanged(what, picked=None):
        """Alfa is still active and Calc's only tab; the list selects `picked`, if given."""
        state = {"active": active(), "tabs": tabs_of(context, document)}
        expected = {"active": "Alfa", "tabs": ["Alfa"]}
        if picked is not None:
            state["selection"] = selection(tree, list(sheets.getElementNames()))
            expected["selection"] = picked
        assert state == expected, (what, state)
        return state

    settled()
    say("a press held while its sheet is replaced does not activate the replacement (#28)")
    point = row_point(tree, 1)
    robot.press(tree, point)
    poll(lambda: selection(tree, SIX) == ["Bravo"], "the press to select Bravo")
    replace(document, "Bravo")
    poll(lambda: selection(tree, SIX) == [], "the refresh to drop the replaced Bravo")
    robot.release(tree, point)
    time.sleep(1)
    results["press_then_replace"] = unchanged("press, replace, release", picked=[])

    say("a press held while its sheet moves does not activate the sheet now in its row (#28)")
    settled()
    point = row_point(tree, 1)
    robot.press(tree, point)
    poll(lambda: selection(tree, SIX) == ["Bravo"], "the press to select Bravo")
    sheets.moveByName("Bravo", len(SIX))
    moved = ["Alfa", "Charlie", "Delta", "Echo", "Foxtrot", "Bravo"]
    poll(lambda: names(tree) == moved, "the list to show the move")
    robot.release(tree, point)
    time.sleep(1)
    results["press_then_move"] = unchanged("press, move, release", picked=["Bravo"])
    sheets.moveByName("Bravo", 1)

    say("a voided press brings back the newer pick from following Calc")
    settled()
    point = row_point(tree, 1)
    robot.press(tree, point)
    poll(lambda: selection(tree, SIX) == ["Bravo"], "the press to select Bravo")
    controller.setActiveSheet(sheets.getByName("Delta"))
    poll(lambda: selection(tree, SIX) == ["Delta"], "the list to follow Delta")
    sheets.moveByName("Bravo", len(SIX))  # The pressed row now shows another sheet.
    time.sleep(2)
    robot.release(tree, point)
    time.sleep(1)
    order = list(sheets.getElementNames())
    followed = {"active": active(), "selection": selection(tree, order)}
    assert followed == {"active": "Delta", "selection": ["Delta"]}, followed
    results["follow_then_move"] = followed
    sheets.moveByName("Bravo", 1)
    controller.setActiveSheet(sheets.getByName("Alfa"))

    def pick_bravo_and_delta():
        """Pick Bravo and Delta with Delta active, once no refresh is pending any more."""
        time.sleep(1.5)  # A refresh after the last step's undo would drop the picks.
        robot.double_click(tree, row_point(tree, 3))  # Delta becomes active.
        robot.click(tree, row_point(tree, 1), modifiers=VCL_MOD1)
        poll(lambda: selection(tree, SIX) == ["Bravo", "Delta"], "Bravo and Delta picked")
        time.sleep(1.5)
        kept = selection(tree, SIX)
        assert kept == ["Bravo", "Delta"], ("the picks went before the change", kept)

    say("a deleted sheet's handle reporting its name again does not keep the pick (#28)")
    for case in ("delete, rename", "insert, delete, rename"):
        settled()
        pick_bravo_and_delta()
        steps = len(document.getUndoManager().getAllUndoActionTitles())
        if case == "insert, delete, rename":
            sheets.insertNewByName("Newcomer", 1)
        sheets.removeByName("Bravo")
        renamed = "Newcomer" if case == "insert, delete, rename" else "Alfa"
        sheets.getByName(renamed).setName("Bravo")
        poll(lambda: selection(tree, list(sheets.getElementNames())) == [], "the picks to go")
        results[case] = {
            "selection": [],
            "notice": bool(controller.hasInfobar(uno_list.NOTICE)),
        }
        undo = document.getUndoManager()
        while len(undo.getAllUndoActionTitles()) > steps:
            undo.undo()
        poll(lambda: list(sheets.getElementNames()) == SIX, "undo to restore the sheets")
        controller.setActiveSheet(sheets.getByName("Alfa"))

    say("batched or quiet edits on LibreOffice's main thread do not keep the pick (#28)")
    for wrapper in BATCHES:
        settled()
        pick_bravo_and_delta()
        steps = len(document.getUndoManager().getAllUndoActionTitles())
        on_main_thread(context, lambda w=wrapper: cover_batch(document, w))
        poll(lambda: selection(tree, list(sheets.getElementNames())) == [], "the picks to go")
        results[wrapper] = {"selection": [], "notice": bool(controller.hasInfobar(uno_list.NOTICE))}
        undo = document.getUndoManager()
        while len(undo.getAllUndoActionTitles()) > steps:
            undo.undo()
        poll(lambda: list(sheets.getElementNames()) == SIX, "undo to restore the sheets")
        controller.setActiveSheet(sheets.getByName("Alfa"))

    say("edits with undo recording off inside a lock do not keep the pick (#28)")
    for way in UNRECORDED:
        document.getUndoManager().clear()  # An empty history shows no difference either.
        settled()
        pick_bravo_and_delta()
        on_main_thread(context, lambda w=way: unrecorded_batch(document, w))
        poll(lambda: selection(tree, list(sheets.getElementNames())) == [], "the picks to go")
        replaced = sheets.getByName("Bravo").getCellRangeByName("A1").getString()
        assert replaced == "replacement", (way, replaced)
        results[way] = {"selection": [], "notice": bool(controller.hasInfobar(uno_list.NOTICE))}
        controller.setActiveSheet(sheets.getByName("Alfa"))

    say("a click while a batch's lock is still held activates nothing (#28)")
    for lock in LOCKS:
        document.getUndoManager().clear()
        settled()
        pick_bravo_and_delta()
        on_main_thread(context, lambda lk=lock: held_batch(document, lk))
        try:
            # LibreOffice has reported nothing yet; Bravo's row now holds the replacement.
            robot.click(tree, row_point(tree, 1))
            time.sleep(1)
            clicked = active()
        finally:
            on_main_thread(context, lambda lk=lock: release(document, lk))
        poll(lambda: selection(tree, list(sheets.getElementNames())) == [], "the picks to go")
        held = {"active_after_click": clicked, "selection": []}
        assert clicked == "Delta", (lock, held)
        results[f"held {lock}"] = held
        controller.setActiveSheet(sheets.getByName("Alfa"))

    say("out of scope: undo off and modify notifications off report nothing (documented)")
    document.getUndoManager().clear()
    settled()
    pick_bravo_and_delta()

    def silenced():
        document.IsUndoEnabled = False
        try:
            cover_batch(document, "disableSetModified")
        finally:
            document.IsUndoEnabled = True

    on_main_thread(context, silenced)
    time.sleep(2)
    # This documents the limit rather than a wanted outcome: with undo recording off and
    # modify notifications off, LibreOffice reports nothing, so the list keeps a pick that now
    # names the newcomer. The threat model excludes this case (docs/reordering.md). If this
    # starts failing, LibreOffice reports more than measured: update the documentation.
    silenced_state = {
        "selection": selection(tree, list(sheets.getElementNames())),
        "marker": sheets.getByName("Bravo").getCellRangeByName("A1").getString(),
    }
    assert silenced_state == {"selection": ["Bravo", "Delta"], "marker": "replacement"}, (
        silenced_state
    )
    results["silenced_out_of_scope"] = silenced_state
    sheets.removeByName("Bravo")
    sheets.insertNewByName("Bravo", 1)
    controller.setActiveSheet(sheets.getByName("Alfa"))
    poll(lambda: list(sheets.getElementNames()) == SIX, "Bravo back in place")

    say("a sheet hidden just before its row is clicked is not activated, nor another (#43)")
    settled()
    point = row_point(tree, 3)
    sheets.getByName("Delta").IsVisible = False
    robot.double_click(tree, point, pause=0)  # Queued before the list's refresh.
    poll(lambda: "(hidden)" in labels(tree)[3], "the list to show Delta hidden")
    time.sleep(1)
    results["click_hidden_before_refresh"] = unchanged("hide, click")
    sheets.getByName("Delta").IsVisible = True

    say("a delayed refresh keeps a Ctrl+click made after a plain click (#44)")
    settled()
    first, second = row_point(tree, 1), row_point(tree, 3)
    sheets.getByName("Foxtrot").TabColor = 0x2A6099  # Queues an ordinary delayed refresh.
    robot.double_click(tree, first, pause=0)
    robot.click(tree, second, modifiers=VCL_MOD1, pause=0)
    poll(lambda: active() == "Bravo", "the plain click to go to Bravo")
    settled()  # The delayed refresh has run: Bravo carries the active marker.
    time.sleep(1)
    kept = selection(tree, SIX)
    assert kept == ["Bravo", "Delta"], kept
    results["selection_after_delayed_refresh"] = kept
    close_workbook(context, document)
    return results


class _ActivationOwner:
    """What SheetList.activate() uses, around a real document; Calc does the work."""

    activate = uno_list.SheetList.activate
    restore_view = uno_list.SheetList.restore_view

    def __init__(self, context, document):
        self.context, self.document = context, document
        self.controller = document.getCurrentController()
        self.frame = self.controller.getFrame()
        self.peer = None
        self._activating = False
        self._handles: dict[str, Any] = {}
        self._monitor = SimpleNamespace(generation=0, check=lambda: 0)
        self._proven = 0

    def post(self, function, where):
        pass

    def refresh(self):
        pass

    def _note_view_input(self):
        pass  # This activation-only adapter has no list or periodic observer.


def redirected_activation(context, desktop, hidden):
    """Activate Bravo while Alfa and Delta are grouped, hiding `hidden` just before the switch.

    The sheets go between the moment activate() notes the view and its switch, which real input
    can only hit by chance: Calc then sends the switch, and maybe the restoration, elsewhere.
    """
    document = make_workbook(desktop, SIX)
    sheets = document.getSheets()
    owner = _ActivationOwner(context, document)
    uno_list.select_tabs(context, owner.frame, [0, 3])
    poll(lambda: tabs_of(context, document) == ["Alfa", "Delta"], "Alfa and Delta grouped")
    real_tabs = uno_list.selected_tabs
    calls = []
    messages = []

    def tabs_then_hide(ctx, controller):
        result = real_tabs(ctx, controller)
        calls.append(result)
        if len(calls) == 1:  # activate() has noted the view; now the sheets go.
            for name in hidden:
                sheets.getByName(name).IsVisible = False
        return result

    def captured(peer, title, message):
        messages.append(message)

    with (
        patch.object(uno_list, "selected_tabs", tabs_then_hide),
        patch.object(uno_list, "show_error", captured),
    ):
        owner.activate("Bravo", sheets.getByName("Bravo"))
    state = {
        "active": document.getCurrentController().getActiveSheet().getName(),
        "tabs": tabs_of(context, document),
        "messages": messages,
    }
    close_workbook(context, document)
    return state


def check_activation_fallback(context, desktop):
    """If Calc sends an activation elsewhere, the view is restored and read back (#46)."""
    say("Bravo hidden before the switch: the view is restored")
    restored = redirected_activation(context, desktop, ["Bravo"])
    assert restored["active"] == "Alfa" and restored["tabs"] == ["Alfa", "Delta"], restored
    assert len(restored["messages"]) == 1 and "left as it was" in restored["messages"][0]
    say("Bravo and Alfa hidden before the switch: the restoration fails and says so")
    failed = redirected_activation(context, desktop, ["Bravo", "Alfa"])
    assert failed["active"] != "Alfa", failed
    assert len(failed["messages"]) == 1, failed
    assert "could not be restored" in failed["messages"][0], failed
    return {"restored": restored, "not_restored": failed}


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

    say("one undo step")
    document = hidden_workbook(desktop, targets)
    undo = document.getUndoManager()
    result = show_sheets(context, document, snapshot(document), targets)
    assert result.status == "done" and visible(document, targets) == targets, result
    assert list(undo.getAllUndoActionTitles()) == ["Show Sheets"]
    undo.undo()
    assert visible(document, targets) == [], "One undo must hide all three again"
    results["one_undo_step"] = True

    say("refused with locked, disabled, zero, or too small undo")
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

    say("refused when a target was replaced")
    observed = snapshot(document)
    replace(document, "Delta")
    document.getSheets().getByName("Delta").IsVisible = False
    undo.clear()
    result = show_sheets(context, document, observed, targets)
    assert result.status == "refused" and visible(document, targets) == [], result
    results["refused_when_stale"] = True

    say("recovery after a partial failure")
    close_workbook(context, document)

    def partial_failure(picked, history):
        document = hidden_workbook(desktop, targets)
        undo = document.getUndoManager()
        cell = document.getSheets().getByName("Alfa").getCellRangeByName("A1")
        for value in range(history):
            cell.setValue(value + 1)  # The user's own last actions.
        before = list(undo.getAllUndoActionTitles())
        failing = _FailingDocument(document, allowed=1)
        result = show_sheets(context, failing, snapshot(failing), picked)
        assert result.status == "failed-restored", result
        assert visible(document, targets) == [], "A partial show must be undone"
        assert list(undo.getAllRedoActionTitles()) == []
        if history:
            assert cell.getValue() == history, "Recovery must keep the user's last edit"
            assert list(undo.getAllUndoActionTitles())[: history - 1] == before[: history - 1]
        close_workbook(context, document)

    say("  with room in the undo history")
    partial_failure(targets, 0)
    # A full two-step history: the group evicts the oldest action. Set the limit before the
    # document exists; lowering it for an open document makes Calc abort on undo (#37).
    say("  with a full undo history")
    with undo_capacity(context, 2):
        partial_failure(targets[:2], 2)
    results["partial_failure_restored"] = True
    return results


def measure_large_workbook(context, desktop, count):
    """Record wall-clock following/rebuild costs, with correctness assertions (see #22)."""
    document = make_workbook(desktop, [f"Sheet {n:04}" for n in range(1, count + 1)])
    started = time.monotonic()
    _, tree = open_list(context, document)
    poll(lambda: len(names(tree)) == count, "every sheet in a large list", timeout=120)
    opened = time.monotonic() - started
    controller = document.getCurrentController()
    target = document.getSheets().getByIndex(count // 2)
    started = time.monotonic()
    inactive_model = root(tree)
    controller.setActiveSheet(target)
    order = list(document.getSheets().getElementNames())
    poll(lambda: selection(tree, order) == [target.getName()], "a large list to follow", 120)

    def activation_painted():
        parent = root(tree)
        return (
            parent is not None
            and parent != inactive_model
            and parent.getChildCount() == count
            and parent.getChildAt(count // 2).getDisplayValue() == target.getName()
        )

    # The lightweight observer can follow the selection before the preceding activation's
    # rate-limited row repaint. Finish that repaint before isolating tab-only model retention.
    poll(activation_painted, "the active marker before tab-only timing", 120)
    followed = time.monotonic() - started
    before = root(tree)
    assert before is not None
    started = time.monotonic()
    select_tabs(context, controller.getFrame(), [count // 2, count - 1])
    expected = [order[count // 2], order[-1]]
    poll(lambda: selection(tree, order) == expected, "a large tab-only selection", 120)
    tab_followed = time.monotonic() - started
    assert root(tree) == before, "Tab-only following must retain the native model"
    document.getSheets().getByIndex(0).getCellRangeByName("A1").setValue(42)
    time.sleep(0.8)
    assert root(tree) == before, "An ordinary edit must retain the native model"
    repaints = []
    first = document.getSheets().getByIndex(0)
    for color in (0x2A6099, 0x993322, 0x228833):
        previous = root(tree)
        assert previous is not None
        started = time.monotonic()
        first.TabColor = color
        poll(
            lambda previous=previous: root(tree) not in (None, previous),
            "a large tab-colour repaint",
            120,
        )
        repaints.append(round(time.monotonic() - started, 4))
        current = root(tree)
        assert current is not None
        assert current.getChildCount() == count
        assert current.getChildAt(0).DataValue == order[0]
        assert current.getChildAt(count - 1).DataValue == order[-1]
    close_workbook(context, document)
    return {
        "sheets": count,
        "open_seconds": round(opened, 2),
        "follow_seconds": round(followed, 2),
        "tab_only_seconds": round(tab_followed, 4),
        "tab_only_same_model": True,
        "cell_edit_same_model": True,
        "tab_color_repaint_seconds": repaints,
        "method": "100ms polling; wall times include debounce/backpressure; no performance gate",
    }


def exercise(context, desktop, directory, output, *, headless):
    # Each check closes its own workbooks; the rest are closed after a failure, unless a
    # main-thread close timed out, which fails the suite in any case (#50).
    return run_checks(
        (
            ("key_constants", check_key_constants),
            ("states_and_refresh", lambda: check_states_and_refresh(context, desktop)),
            ("selection_and_menu", lambda: check_selection_and_menu(context, desktop, headless)),
            ("identity", lambda: check_identity(context, desktop, headless)),
            ("stale_clicks", lambda: check_stale_clicks(context, desktop)),
            ("activation_fallback", lambda: check_activation_fallback(context, desktop)),
            ("show", lambda: check_show(context, desktop)),
            ("large_workbook", lambda: measure_large_workbook(context, desktop, 1000)),
        ),
        _CREATED,
        lambda document: close_document(context, document),
        label="sheet list check",
    )
