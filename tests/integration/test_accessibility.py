"""What assistive technology reads from the sheet list, through public UNO accessibility (#83).

This feature suite reads the tree's `XAccessibleContext`, its rows, their states, and the
`NAME_CHANGED` events a screen reader's bridge receives, in every integration session. These are
metadata checks: no screen reader runs, so what one announces is not verified here.

- The tree's accessible name names the sheet Calc shows. It follows Calc's activation, a
  refresh that rebuilds the rows, and a menu round, and never the list's picks; rows keep the
  plain sheet name with textual states.
- An assistive selection, made through `XAccessibleSelection` as a screen reader selects rows,
  is taken even when a property refresh rebuilds the rows before the list's queued intake reads
  the tree. The list's timers and observation only post to LibreOffice's main-thread queue, so
  holding the main thread after a property change, past the refresh delay, and then selecting
  queues the rebuilding refresh ahead of any intake: the ordering is deterministic.
"""

import time
from typing import Any

import uno
import unohelper
from com.sun.star.accessibility import XAccessibleEventListener
from main_thread import close_document
from sheet_list_view import (
    labels,
    menu_entries,
    names,
    on_main_thread,
    open_list,
    poll,
    row_point,
    selection,
)
from teardown import run_checks
from test_sheet_list import VCL_RIGHT, Robot, say

from sheet_manager.sheet_list import list_name
from sheet_manager.uno_list import REFRESH_DELAY
from sheet_manager.uno_menu import MOVE_IDS

NAME_CHANGED = uno.getConstantByName(
    "com.sun.star.accessibility.AccessibleEventId.NAME_CHANGED"
)
SELECTED = uno.getConstantByName("com.sun.star.accessibility.AccessibleStateType.SELECTED")
FIVE = ["Alfa", "Bravo", "Charlie", "Delta", "Echo"]
# Longer than the refresh delay of a list of five sheets, whose refresh costs milliseconds.
REFRESH_HOLD = 2.5 * REFRESH_DELAY
_CREATED: list[Any] = []


class _Names(unohelper.Base, XAccessibleEventListener):
    """Record the tree's announced names, as an accessibility bridge receives them."""

    def __init__(self):
        self.names: list[str] = []

    def notifyEvent(self, event):
        if event.EventId == NAME_CHANGED:
            self.names.append(str(event.NewValue))

    def disposing(self, event):
        pass


def workbook(desktop, active):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    _CREATED.append(document)
    sheets = document.getSheets()
    sheets.getByIndex(0).setName(FIVE[0])
    for index, name in enumerate(FIVE[1:], 1):
        sheets.insertNewByName(name, index)
    document.getCurrentController().setActiveSheet(sheets.getByName(active))
    document.getUndoManager().clear()
    return document


def close(context, document):
    _CREATED.remove(document)
    close_document(context, document)


def accessible(tree):
    return tree.getProperty("XAccessible").getAccessibleContext()


def read(context, tree):
    """The tree's name, and each row's name and selected state, read in one main-thread step."""
    found: dict[str, Any] = {}

    def work():
        tree_context = accessible(tree)
        found["name"] = tree_context.getAccessibleName()
        rows = []
        for index in range(tree_context.getAccessibleChildCount()):
            row = tree_context.getAccessibleChild(index).getAccessibleContext()
            rows.append((row.getAccessibleName(), bool(row.getAccessibleStateSet() & SELECTED)))
        found["rows"] = rows

    on_main_thread(context, work)
    return found


def viewing(name):
    """The accessible name the tree has while Calc shows `name`, from the shipped rule."""
    expected = list_name(name)
    assert expected == f"Sheets, current sheet: {name}", expected  # The en-US text itself.
    return expected


def check_viewed_sheet(context, desktop, menus):
    document = workbook(desktop, "Bravo")
    controller = document.getCurrentController()
    sheets = document.getSheets()
    _, tree = open_list(context, document)
    poll(lambda: names(tree) == FIVE, "every sheet in the list")
    events = _Names()
    on_main_thread(context, lambda: accessible(tree).addAccessibleEventListener(events))
    try:
        robot = Robot(context)
        poll(lambda: read(context, tree)["name"] == viewing("Bravo"), "the viewed sheet's name")

        say("a pick elsewhere leaves the name on the viewed sheet")
        robot.click(tree, row_point(tree, 3))
        poll(lambda: selection(tree, FIVE) == ["Delta"], "a click to pick Delta")
        seen = read(context, tree)
        assert seen["name"] == viewing("Bravo"), seen
        assert seen["rows"] == [(name, name == "Delta") for name in FIVE], seen
        assert controller.getActiveSheet().getName() == "Bravo"

        say("Calc activates another sheet: the name follows and is announced")
        controller.setActiveSheet(sheets.getByName("Echo"))
        poll(lambda: read(context, tree)["name"] == viewing("Echo"), "the name to follow Calc")
        poll(lambda: viewing("Echo") in events.names, "a NAME_CHANGED event for Echo")
        robot.click(tree, row_point(tree, 0))
        poll(lambda: selection(tree, FIVE) == ["Alfa"], "a click to pick Alfa")

        say("a refresh that rebuilds the rows keeps the viewed sheet's name")
        sheets.getByName("Charlie").protect("")
        poll(lambda: "Charlie (protected)" in labels(tree), "the rebuilt rows")
        seen = read(context, tree)
        assert seen["name"] == viewing("Echo"), seen
        assert [picked for _, picked in seen["rows"]] == [True] + [False] * 4, seen
        announced = list(events.names)

        say("the list's own activation renames the tree too")
        robot.double_click(tree, row_point(tree, 2))
        poll(lambda: controller.getActiveSheet().getName() == "Charlie", "activation by the list")
        poll(lambda: read(context, tree)["name"] == viewing("Charlie"), "the name after it")

        moved = None
        if menus:
            say("a menu round: the menu's move keeps the name on the viewed sheet")
            robot.click(tree, row_point(tree, 0))
            poll(lambda: selection(tree, FIVE) == ["Alfa"], "a click to pick Alfa")
            entries = menu_entries(context, document, ["Alfa"])
            robot.click(tree, row_point(tree, 0), buttons=VCL_RIGHT)
            robot.choose(tree, entries, list(MOVE_IDS)[2])  # Down.
            order = ["Bravo", "Alfa", "Charlie", "Delta", "Echo"]
            poll(lambda: names(tree) == order, "the menu's move")
            poll(lambda: selection(tree, order) == ["Alfa"], "the pick after the move")
            seen = read(context, tree)
            assert seen["name"] == viewing("Charlie"), seen
            assert controller.getActiveSheet().getName() == "Charlie"
            moved = seen["rows"]
    finally:
        on_main_thread(context, lambda: accessible(tree).removeAccessibleEventListener(events))
    close(context, document)
    return {
        "names_announced": events.names,
        "announced_before_list_activation": announced,
        "rows_after_menu_move": moved if menus else "skipped: robot input reaches no gtk3 menu",
    }


def check_assistive_selection_before_rebuild(context, desktop):
    document = workbook(desktop, "Alfa")
    controller = document.getCurrentController()
    sheets = document.getSheets()
    _, tree = open_list(context, document)
    poll(lambda: names(tree) == FIVE, "every sheet in the list")
    poll(lambda: read(context, tree)["name"] == viewing("Alfa"), "the viewed sheet's name")
    Robot(context).click(tree, row_point(tree, 0))
    poll(lambda: selection(tree, FIVE) == ["Alfa"], "a click to pick Alfa")

    def select(index):
        tree_context = accessible(tree)
        tree_context.clearAccessibleSelection()
        tree_context.selectAccessibleChild(index)  # As a screen reader selects a row.

    say("control: with stable rows, the queued intake takes an assistive selection")
    on_main_thread(context, lambda: select(1))
    time.sleep(1.0)  # Several observation ticks, each followed by its queued intake.
    sheets.getByName("Echo").protect("")
    poll(lambda: "Echo (protected)" in labels(tree), "a rebuild after the intake")
    assert selection(tree, FIVE) == ["Bravo"], selection(tree, FIVE)

    say("an assistive selection just before a rebuilding refresh is taken too")

    def select_then_rebuild():
        sheets.getByName("Charlie").protect("")  # The list schedules a rebuilding refresh.
        # Every timer of the list only posts to this queue, and observation never takes the tree
        # selection at once: it posts the intake. Holding the main thread past the refresh delay
        # queues the refresh ahead of any intake of the selection made next.
        time.sleep(REFRESH_HOLD)
        select(3)  # Delta.

    on_main_thread(context, select_then_rebuild)
    poll(lambda: "Charlie (protected)" in labels(tree), "the refresh that rebuilds the rows")
    poll(lambda: selection(tree, FIVE) == ["Delta"], "the assistive selection after the rebuild")
    # Another rebuild writes the list's own picks: the selection was taken, not just shown.
    sheets.getByName("Alfa").protect("")
    poll(lambda: "Alfa (protected)" in labels(tree), "a second rebuild")
    seen = read(context, tree)
    assert selection(tree, FIVE) == ["Delta"], seen
    assert seen["name"] == viewing("Alfa"), seen
    assert controller.getActiveSheet().getName() == "Alfa"
    close(context, document)
    return {"taken": True}


def exercise(context, desktop, directory, output, *, headless):
    return run_checks(
        [
            ("viewed_sheet", lambda: check_viewed_sheet(context, desktop, headless)),
            (
                "assistive_selection_before_rebuild",
                lambda: check_assistive_selection_before_rebuild(context, desktop),
            ),
        ],
        _CREATED,
        lambda document: close_document(context, document),
    )
