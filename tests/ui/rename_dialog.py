"""The Rename Sheets dialog through real keyboard and mouse input (#102).

The dialog is found as the visible dialog window over the document, and observed through public
UNO only: its child windows' text, items, enabled state, focus and accessible name events. Pointer
positions come from those windows and their accessible list items, after calibrating the input
against a motion listener on the dialog's own background, with the lab's `Tracker` and
`settled_report` that calibrate the sheet list.
"""

import sys
import time
from itertools import groupby
from typing import Any

import uno
import unohelper
from button_pixels import capture as capture_disabled_buttons
from com.sun.star.accessibility import XAccessibleEventListener
from lab import Tracker, settled_report
from run import wait_for
from sheet_list_view import on_main_thread
from xinput import Pointer

from sheet_manager.uno_calc import select_tabs
from sheet_manager.uno_menu import RENAME, RENAME_SHEETS

FOCUSED = uno.getConstantByName("com.sun.star.accessibility.AccessibleStateType.FOCUSED")
NAME_CHANGED = uno.getConstantByName("com.sun.star.accessibility.AccessibleEventId.NAME_CHANGED")
# Calibration (#232): how long the dialog may take to report the confirming second move before
# the next point is tried, and how many points may fail to confirm before calibration fails.
CONFIRM_SECONDS = 2
REJECTED_POINTS = 3


class NameChanges(unohelper.Base, XAccessibleEventListener):
    """Record UNO name-change events from a control peer."""

    def __init__(self):
        self.names = []

    def notifyEvent(self, event):
        if event.EventId == NAME_CHANGED:
            self.names.append(event.NewValue)

    def disposing(self, source):
        pass


def _reported(tracker, before, seconds):
    """Whether the window reports a position other than `before` within `seconds`."""
    deadline = time.monotonic() + seconds
    while tracker.last in (None, before):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def _types(window):
    return {kind.typeName for kind in window.getTypes()}


def find_dialog(book):
    """The visible dialog window over the document, other than a message box, or None."""
    toolkit = book.lab.context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", book.lab.context
    )
    for index in range(toolkit.getTopWindowCount()):
        window = toolkit.getTopWindow(index)
        kinds = _types(window)
        if (
            window != book.window
            and window.isVisible()
            and "com.sun.star.awt.XDialog2" in kinds
            and "com.sun.star.awt.XMessageBox" not in kinds
        ):
            return window
    return None


class Dialog:
    """The open Rename Sheets dialog, seen through its child windows and its accessible tree.

    The edits' and the list's child peers are plain border windows without their controls'
    interfaces, so their text and items are read from the accessible tree, where each control
    has its role. Their places come from those child windows, in the dialog's own coordinates.
    """

    def __init__(self, book):
        self.book = book
        self.window = wait_for(lambda: find_dialog(book), "the Rename Sheets dialog")
        children = list(self.window.getWindows())

        def top(window):
            size = window.getPosSize()
            return size.Y, size.X

        kinds = {"com.sun.star.awt.XButton", "com.sun.star.awt.XFixedText"}
        plain = sorted(
            (c for c in children if not _types(c) & {*kinds, "com.sun.star.awt.XScrollBar"}),
            key=top,
        )
        assert len(plain) == 4, [sorted(_types(c)) for c in children]
        self.find, self.replace, self.rows, self.name = plain
        self.buttons = {
            self.accessible(c).getAccessibleName(): c
            for c in children
            if "com.sun.star.awt.XButton" in _types(c)
        }
        assert set(self.buttons) == {"Replace All", "Reset All", "Rename", "Cancel"}, self.buttons
        texts = sorted((c for c in children if "com.sun.star.awt.XFixedText" in _types(c)), key=top)
        self.status = texts[-1]
        self.pointer = None

    @staticmethod
    def accessible(window):
        return window.getProperty("XAccessible").getAccessibleContext()

    def _accessible(self, role_name):
        """The dialog's accessible descendants with this role, top to bottom."""
        role = uno.getConstantByName(f"com.sun.star.accessibility.AccessibleRole.{role_name}")
        root = self.window.getProperty("XAccessible").getAccessibleContext()
        found = []

        def walk(node, depth):
            for index in range(node.getAccessibleChildCount()):
                child = node.getAccessibleChild(index).getAccessibleContext()
                if child.getAccessibleRole() == role:
                    found.append(child)
                elif depth < 4:
                    walk(child, depth + 1)

        walk(root, 0)
        return sorted(found, key=lambda c: (c.getLocationOnScreen().Y, c.getLocationOnScreen().X))

    def edit(self, window):
        """The accessible edit field at the same height as its outer window."""
        fields = self._accessible("TEXT")
        assert len(fields) == 3, [field.getAccessibleName() for field in fields]
        return fields[(self.find, self.replace, self.name).index(window)]

    def text(self, window):
        """Read the contents of an edit through its accessible text interface."""
        return self.edit(window).getText()

    def _items(self):
        return self._accessible("LIST_ITEM")

    def items(self):
        return [item.getAccessibleName() for item in self._items()]

    def state(self) -> dict[str, Any]:
        return {
            "rows": self.items(),
            "name": self.text(self.name),
            "status": self.status.getText(),
            "rename_enabled": bool(self.buttons["Rename"].isEnabled()),
        }

    def labels(self):
        """Accessible names, as a screen reader announces the controls."""
        fields = self._accessible("TEXT")
        lists = self._accessible("LIST")
        return {
            "fields": [field.getAccessibleName() for field in fields],
            "lists": [item.getAccessibleName() for item in lists],
            "buttons": sorted(self.buttons),
        }

    def calibrate(self):
        """Find the dialog's screen offset from where the dialog says the pointer is.

        Between the rows of controls the dialog's own background takes the pointer, so points
        are tried until the dialog reports one. It hears a move only when LibreOffice's main
        thread gets to it, so a report can arrive after the pointer has gone on to the next
        point; taking the first report after a fixed wait could read it for that point's (#232).
        As for the sheet list (`Lab.calibrate`, #209), a point counts only when a second move,
        2 pixels further on both axes, is reported too, each report read with `settled_report`
        once the reports have stopped. The two reports must differ by that move. Otherwise one
        of them belongs to another point, or the second move went over a control, and the next
        point is tried; only a pair of moves can produce reports that differ by exactly (2, 2).
        """
        if self.pointer is not None:
            return self.pointer
        tracker = Tracker()
        self.window.addMouseMotionListener(tracker)
        try:
            root = self.window.getProperty("XAccessible").getAccessibleContext()
            origin, size = root.getLocationOnScreen(), root.getSize()
            points = [
                (x, y)
                for y in range(origin.Y + 2, origin.Y + size.Height, 3)
                for x in (origin.X + 4, origin.X + size.Width // 2, origin.X + size.Width - 5)
            ]
            rejected = []
            for x, y in points:
                tracker.last = None
                self.book.lab.input.move(x, y)
                if not _reported(tracker, None, 0.15):
                    continue
                first = settled_report(tracker, None, (x, y))
                self.book.lab.input.move(x + 2, y + 2)
                second = None
                if _reported(tracker, first, CONFIRM_SECONDS):
                    second = settled_report(tracker, first, (x + 2, y + 2))
                if second == (first[0] + 2, first[1] + 2):
                    # The pair agrees, so either report gives the offset.
                    self.pointer = Pointer(self.book.lab.input, (x - first[0], y - first[1]))
                    return self.pointer
                rejected.append({"point": (x, y), "reports": [first, second]})
                if len(rejected) == REJECTED_POINTS:
                    break
            raise AssertionError(
                "The dialog never confirmed a point on its background; the points whose "
                f"reports did not follow a 2-pixel second move: {rejected}"
            )
        finally:
            self.window.removeMouseMotionListener(tracker)

    def click(self, window):
        place = window.getPosSize()
        self.calibrate().click(place.X + place.Width // 2, place.Y + place.Height // 2, pause=0.4)

    def click_row(self, index):
        """Click a row of the list where its accessible item says it is, relative to the list."""
        lists = self._accessible("LIST")
        assert lists, "The dialog's list has no accessible list"
        item = self._items()[index]
        here, there = item.getLocationOnScreen(), lists[0].getLocationOnScreen()
        size, place = item.getSize(), self.rows.getPosSize()
        inner = lists[0].getSize()
        # The accessible list can sit inside the list window's border.
        border = (place.Width - inner.Width) // 2, (place.Height - inner.Height) // 2
        self.calibrate().click(
            place.X + border[0] + here.X - there.X + min(size.Width // 2, 40),
            place.Y + border[1] + here.Y - there.Y + size.Height // 2,
            pause=0.4,
        )


def type_text(lab, text):
    for char in text:
        if char.isupper():
            lab.input.tap(char.lower(), ("Shift_L",), pause=0.03)
        else:
            lab.input.tap(
                {" ": "space", "/": "slash", "4": "4", "0": "0"}.get(char, char), pause=0.03
            )


def wait_closed(book):
    wait_for(lambda: find_dialog(book) is None, "the dialog to close")
    on_main_thread(book.lab.context, lambda: None)  # The list's completion has run.
    on_main_thread(book.lab.context, lambda: None)


def open_dialog(book, picks, opener):
    entries = book.entries(picks)
    assert RENAME_SHEETS in entries and RENAME not in entries, entries
    opener()
    book.choose(RENAME_SHEETS, entries)
    dialog = Dialog(book)
    # Barriers: the menu's queued completion and the dialog's first posted work have run.
    on_main_thread(book.lab.context, lambda: None)
    on_main_thread(book.lab.context, lambda: None)
    return dialog


def identify(book, names):
    sheets = book.document.getSheets()
    for name in names:
        sheets.getByName(name).getCellRangeByName("B1").String = f"identity {name}"
    book.document.getUndoManager().clear()


def identities(book):
    sheets = book.document.getSheets()
    return {
        sheets.getByIndex(i).getName(): sheets.getByIndex(i).getCellRangeByName("B1").String
        for i in range(sheets.getCount())
        if sheets.getByIndex(i).getCellRangeByName("B1").String
    }


def pick(book, names):
    """Calc views the first sheet alone; the list picks `names`, by real clicks."""
    order = book.order()
    book.controller.setActiveSheet(book.document.getSheets().getByIndex(0))
    select_tabs(book.lab.context, book.frame, [0])
    book.click(order.index(names[0]))
    for name in names[1:]:
        book.click(order.index(name), modifiers=("Control_L",))
    wait_for(lambda: book.selection() == names, f"the picks {names}")
    assert (book.active(), book.calc_tabs()) == (order[0], [order[0]])


def undo_all(book):
    undo = book.document.getUndoManager()
    while undo.isUndoPossible():
        undo.undo()
    undo.clear()


def check_keyboard(book):
    """Find, Replace with, Replace All, a row's own name, a refused name, and Rename by keys."""
    names = book.order()
    picks = names[1:4]  # Bravo, Charlie, Delta; Calc views Alfa.
    identify(book, names[:6])
    original = identities(book)
    pick(book, picks)
    view = book.active(), book.calc_tabs()
    evidence = {}
    try:
        dialog = open_dialog(book, picks, lambda: book.lab.input.tap("Menu", pause=0.4))
        book.lab.screenshot("rename-sheets-opened")
        evidence["opened"] = dialog.state()
        evidence["accessible_names"] = dialog.labels()
        # Each field and the list are named by their labels for screen readers.
        assert dialog.labels()["fields"] == ["Find:", "Replace with:", "New name:"], evidence
        assert dialog.labels()["lists"] == ["Sheets:"], evidence
        assert dialog.items() == [f"{name}   (unchanged)" for name in picks], dialog.state()
        assert not dialog.state()["rename_enabled"], dialog.state()
        evidence["disabled_label_opened"] = capture_disabled_buttons(
            book.lab,
            {"Rename": dialog.buttons["Rename"]},
            "rename-disabled-label",
            dialog.calibrate().offset if sys.platform.startswith("linux") else None,
        )
        assert (book.active(), book.calc_tabs(), book.selection()) == (*view, picks)
        assert book.order() == names and not book.undo_titles()
        type_text(book.lab, "a")  # The Find field has the focus first.
        wait_for(lambda: dialog.text(dialog.find) == "a", "Find to take the typed text")
        book.lab.input.tap("Tab", pause=0.2)
        type_text(book.lab, "4")
        wait_for(lambda: dialog.text(dialog.replace) == "4", "Replace with to take the text")
        book.lab.input.tap("Return", pause=0.6)  # No default button: nothing is applied.
        assert find_dialog(book) is not None and book.order() == names, "Enter applied the batch"
        book.lab.input.tap("a", ("Alt_L",), pause=0.4)  # Replace All.
        expected = ["Bravo   →   Br4vo", "Charlie   →   Ch4rlie", "Delta   →   Delt4"]
        wait_for(lambda: dialog.items() == expected, "the replaced proposals")
        evidence["replaced"] = dialog.state()
        assert dialog.state()["rename_enabled"], dialog.state()
        assert dialog.buttons["Rename"].getProperty("NativeWidgetLook")
        book.lab.input.tap("s", ("Alt_L",), pause=0.3)  # The Sheets list.
        book.lab.input.tap("Down", pause=0.3)
        wait_for(lambda: dialog.text(dialog.name) == "Ch4rlie", "the second row in the name field")
        book.lab.input.tap("n", ("Alt_L",), pause=0.3)  # The New name field.
        field = dialog.edit(dialog.name)
        assert field.getAccessibleStateSet() & FOCUSED
        assert field.getAccessibleName() == "New name:"
        changes = NameChanges()
        field.addAccessibleEventListener(changes)
        try:
            book.lab.input.tap("a", ("Control_L",), pause=0.1)
            type_text(book.lab, "a/b")
            wait_for(lambda: "cannot contain" in dialog.state()["status"], "the refused name")
            evidence["refused"] = dialog.state()
            assert not dialog.state()["rename_enabled"] and "⚠" in dialog.items()[1]
            evidence["disabled_label_refused"] = capture_disabled_buttons(
                book.lab,
                {"Rename": dialog.buttons["Rename"]},
                "rename-refused-label",
                dialog.calibrate().offset if sys.platform.startswith("linux") else None,
            )
            book.lab.screenshot("rename-sheets-refused-name")
            syntax_name = f"New name: {evidence['refused']['status']}"
            wait_for(lambda: syntax_name in changes.names, "the syntax refusal on the edit")
            assert field.getAccessibleName() == syntax_name
            assert field.getAccessibleStateSet() & FOCUSED
            events_before_edit = len(changes.names)
            type_text(book.lab, "x")  # The same forbidden character remains in the proposal.
            wait_for(lambda: dialog.text(dialog.name) == "a/bx", "the longer invalid name")
            book.lab.input.tap("a", ("Control_L",), pause=0.1)
            book.lab.input.tap("BackSpace", pause=0.2)
            wait_for(lambda: "cannot be empty" in dialog.state()["status"], "the empty proposal")
            wait_for(lambda: field.getAccessibleName() == "New name:", "the ordinary edit name")
            assert set(changes.names[events_before_edit:]) == {"New name:"}, changes.names
            changes.names.clear()

            book.lab.input.tap("a", ("Control_L",), pause=0.1)
            type_text(book.lab, "Echo")  # Already used by an unpicked sheet.
            reason = "Another sheet is already named “Echo”."
            duplicate_name = f"New name: {reason}"
            wait_for(lambda: dialog.state()["status"] == reason, "a duplicate refusal")
            wait_for(lambda: duplicate_name in changes.names, "the edit's name change")
            assert field.getAccessibleName() == duplicate_name
            assert field.getAccessibleStateSet() & FOCUSED
            assert not dialog.state()["rename_enabled"]

            book.lab.input.tap("Home")
            book.lab.input.tap("Right", ("Shift_L",))
            type_text(book.lab, "e")  # Echo -> echo changes the reason.
            near_reason = (
                "Too close to “Echo”, another sheet's name: Calc can treat them as one name."
            )
            near_name = f"New name: {near_reason}"
            wait_for(lambda: near_name in changes.names, "the comparison-key conflict event")
            assert dialog.items()[1] == f"Charlie   →   echo   ⚠ {near_reason}"
            book.lab.input.tap("End")
            book.lab.input.tap("Left", ("Shift_L",))
            events_before_edit = len(changes.names)
            type_text(book.lab, "O")  # echo -> echO keeps the same reason.
            wait_for(
                lambda: dialog.items()[1] == f"Charlie   →   echO   ⚠ {near_reason}",
                "the changed proposal with the same conflict",
            )
            assert field.getAccessibleName() == near_name
            assert not dialog.state()["rename_enabled"]

            book.lab.input.tap("End")
            book.lab.input.tap("slash", ("Shift_L",), pause=0.2)
            wait_for(
                lambda: syntax_name in changes.names, "the conflict replaced by a syntax reason"
            )
            assert field.getAccessibleName() == syntax_name
            assert field.getAccessibleStateSet() & FOCUSED
            assert not dialog.state()["rename_enabled"]
            # The next reason comes after any events from the same-conflict edit.
            assert changes.names[events_before_edit] == syntax_name, changes.names

            book.lab.input.tap("a", ("Control_L",), pause=0.1)
            type_text(book.lab, "Bravo")  # Free once Bravo has its new name: a chain.
            wait_for(lambda: dialog.state()["rename_enabled"], "a valid batch again")
            wait_for(lambda: changes.names[-1:] == ["New name:"], "the ordinary edit name event")
            assert field.getAccessibleName() == "New name:"
            assert field.getAccessibleStateSet() & FOCUSED
            evidence["edit_name_changes"] = list(changes.names)
            # A single peer update can deliver consecutive duplicate events.
            assert [name for name, _ in groupby(changes.names)] == [
                duplicate_name,
                near_name,
                syntax_name,
                "New name:",
            ], changes.names
        finally:
            field.removeAccessibleEventListener(changes)
        assert dialog.items()[1] == "Charlie   →   Bravo", dialog.items()
        book.lab.screenshot("rename-sheets-ready")
        book.lab.input.tap("r", ("Alt_L",), pause=0.5)  # Rename.
        wait_closed(book)
        renamed = ["Br4vo", "Bravo", "Delt4"]
        wait_for(lambda: book.order()[1:4] == renamed, "the renamed sheets")
        evidence["after"] = {
            "order": book.order(),
            "undo": book.undo_titles(),
            "view": (book.active(), book.calc_tabs()),
            "picks": book.selection(),
        }
        assert identities(book) == {
            {"Bravo": "Br4vo", "Charlie": "Bravo", "Delta": "Delt4"}.get(name, name): text
            for name, text in original.items()
        }, identities(book)
        assert book.undo_titles() == ["Rename Sheets"], book.undo_titles()
        assert (book.active(), book.calc_tabs()) == (names[0], [names[0]]), evidence["after"]
        wait_for(lambda: book.selection() == renamed, "the picks carried to the new names")
        book.document.getUndoManager().undo()
        wait_for(lambda: book.order() == names, "one undo of the whole batch")
        assert identities(book) == original
    finally:
        if find_dialog(book) is not None:
            book.lab.input.tap("Escape", pause=0.5)
        undo_all(book)
    return evidence


def check_mouse(book):
    """The same dialog by mouse: fields, Replace All, a row, Reset All, Cancel, then Rename."""
    names = book.order()
    picks = [names[4], names[5]]  # Echo, Foxtrot.
    identify(book, names[:6])
    original = identities(book)
    pick(book, picks)
    view = book.active(), book.calc_tabs()
    evidence = {}

    def right_click():
        book.pointer.click(*book.point(5), button=3, pause=0.5)

    try:
        dialog = open_dialog(book, picks, right_click)
        dialog.click(dialog.find)
        type_text(book.lab, "o")
        dialog.click(dialog.replace)
        type_text(book.lab, "0")
        dialog.click(dialog.buttons["Replace All"])
        expected = ["Echo   →   Ech0", "Foxtrot   →   F0xtr0t"]
        wait_for(lambda: dialog.items() == expected, "proposals replaced by a click")
        dialog.click_row(1)
        wait_for(lambda: dialog.text(dialog.name) == "F0xtr0t", "the clicked row in the name field")
        dialog.click(dialog.name)
        book.lab.input.tap("a", ("Control_L",), pause=0.1)
        type_text(book.lab, "fox")
        wait_for(lambda: dialog.items()[1] == "Foxtrot   →   fox", "the typed name")
        evidence["edited"] = dialog.state()
        dialog.click(dialog.buttons["Reset All"])
        wait_for(lambda: not dialog.state()["rename_enabled"], "Reset All to undo the edits")
        assert dialog.items() == [f"{name}   (unchanged)" for name in picks], dialog.items()
        dialog.click(dialog.buttons["Cancel"])
        wait_closed(book)
        assert book.order() == names and not book.undo_titles(), "Cancel changed the document"
        assert (book.active(), book.calc_tabs(), book.selection()) == (*view, picks)

        dialog = open_dialog(book, picks, right_click)
        dialog.click(dialog.find)
        type_text(book.lab, "o")
        dialog.click(dialog.replace)
        type_text(book.lab, "0")
        dialog.click(dialog.buttons["Replace All"])
        wait_for(lambda: dialog.items() == expected, "the proposals again")
        dialog.click(dialog.buttons["Rename"])
        wait_closed(book)
        wait_for(lambda: book.order()[4:6] == ["Ech0", "F0xtr0t"], "the renamed sheets")
        assert book.undo_titles() == ["Rename Sheets"]
        assert identities(book)["F0xtr0t"] == original["Foxtrot"]
        assert (book.active(), book.calc_tabs()) == view
        wait_for(lambda: book.selection() == ["Ech0", "F0xtr0t"], "the carried picks")
        evidence["after"] = book.order()
    finally:
        if find_dialog(book) is not None:
            book.lab.input.tap("Escape", pause=0.5)
        undo_all(book)
    return evidence


def check_other_row(book):
    """When the edited row becomes valid, expose the refusal on the other proposal."""
    picks = ["Bravo", "Charlie"]
    pick(book, picks)
    keys = book.lab.input

    def edit(text):
        keys.tap("a", ("Control_L",), pause=0.1)
        type_text(book.lab, text)

    dialog = open_dialog(book, picks, lambda: keys.tap("Menu", pause=0.4))
    try:
        keys.tap("n", ("Alt_L",))
        edit("Gamma")
        wait_for(lambda: dialog.state()["rename_enabled"], "a free proposal for Bravo")
        keys.tap("s", ("Alt_L",))
        keys.tap("Down")
        keys.tap("n", ("Alt_L",))
        edit("Bravo")
        wait_for(lambda: dialog.items()[1] == "Charlie   →   Bravo", "a free proposal for Charlie")
        keys.tap("s", ("Alt_L",))
        keys.tap("Up")
        keys.tap("n", ("Alt_L",))
        field = dialog.edit(dialog.name)
        changes = NameChanges()
        field.addAccessibleEventListener(changes)
        try:
            edit("Bravo")
            reason = "Another sheet is already named “Bravo”."
            expected = f"New name: “Charlie”: {reason}"
            wait_for(lambda: dialog.items()[1].endswith(reason), "the conflict on Charlie's row")
            wait_for(lambda: expected in changes.names, "the other row's reason on the edit")
            assert field.getAccessibleName() == expected
            assert field.getAccessibleStateSet() & FOCUSED
            assert not dialog.state()["rename_enabled"]
            edit("Gamma")
            wait_for(lambda: dialog.state()["rename_enabled"], "both proposals valid again")
            wait_for(lambda: changes.names[-1:] == ["New name:"], "the ordinary edit name")
        finally:
            field.removeAccessibleEventListener(changes)
        return {"name_changes": changes.names}
    finally:
        keys.tap("Escape", pause=0.5)
        wait_closed(book)


def check_replace_conflict(book):
    """Replace All's mnemonic focuses the button and exposes the result of each attempt."""
    picks = ["Bravo", "Charlie"]
    pick(book, picks)
    keys = book.lab.input
    dialog = open_dialog(book, picks, lambda: keys.tap("Menu", pause=0.4))
    try:
        button = dialog.accessible(dialog.buttons["Replace All"])
        field = dialog.edit(dialog.name)
        changes = NameChanges()
        button.addAccessibleEventListener(changes)

        def replace(expected):
            keys.tap("n", ("Alt_L",), pause=0.2)
            assert field.getAccessibleStateSet() & FOCUSED
            keys.tap("a", ("Alt_L",), pause=0.4)
            wait_for(lambda: changes.names[-1:] == [expected], "the reason on Replace All")
            assert button.getAccessibleName() == expected
            assert button.getAccessibleStateSet() & FOCUSED

        try:
            replace("Replace All Type the text to find first.")
            keys.tap("f", ("Alt_L",), pause=0.2)
            type_text(book.lab, "Missing")
            replace("Replace All No new name contains “Missing”.")
            keys.tap("f", ("Alt_L",), pause=0.2)
            keys.tap("a", ("Control_L",), pause=0.1)
            type_text(book.lab, "Bravo")
            keys.tap("p", ("Alt_L",), pause=0.2)
            type_text(book.lab, "Echo")
            reason = "Another sheet is already named “Echo”."
            expected = f"Replace All “Bravo”: {reason}"
            replace(expected)
            wait_for(lambda: dialog.items()[0].endswith(reason), "the replacement conflict")
            assert not dialog.state()["rename_enabled"]
            events_before_retry = list(changes.names)
            keys.tap("space", pause=0.4)
            on_main_thread(book.lab.context, lambda: None)
            assert dialog.items()[0].endswith(reason)
            assert dialog.status.getText() == reason
            assert button.getAccessibleName() == expected
            assert changes.names == events_before_retry
            keys.tap("e", ("Alt_L",), pause=0.4)  # Reset All.
            wait_for(lambda: changes.names[-1:] == ["Replace All"], "the ordinary button name")
            assert button.getAccessibleName() == "Replace All"
        finally:
            button.removeAccessibleEventListener(changes)
        return {"name_changes": changes.names}
    finally:
        keys.tap("Escape", pause=0.5)
        wait_closed(book)


def check_stale(book):
    """A target renamed elsewhere while the dialog is open: Rename refuses, and says why."""
    names = book.order()
    picks = [names[1], names[3]]
    pick(book, picks)
    evidence = {}
    try:
        dialog = open_dialog(book, picks, lambda: book.lab.input.tap("Menu", pause=0.4))
        type_text(book.lab, "a")
        book.lab.input.tap("Tab", pause=0.2)
        type_text(book.lab, "A")
        book.lab.input.tap("a", ("Alt_L",), pause=0.4)
        wait_for(lambda: dialog.state()["rename_enabled"], "a valid batch")
        book.document.getSheets().getByName(names[3]).Name = "Elsewhere"  # Another program.
        history = book.undo_titles()
        book.lab.input.tap("n", ("Alt_L",), pause=0.2)
        assert dialog.edit(dialog.name).getAccessibleStateSet() & FOCUSED
        button = dialog.accessible(dialog.buttons["Rename"])
        changes = NameChanges()
        button.addAccessibleEventListener(changes)
        try:
            book.lab.input.tap("r", ("Alt_L",), pause=0.4)
            reason = "The sheets changed while this dialog was open. Cancel and try again."
            wait_for(lambda: dialog.status.getText() == reason, "the stale-target refusal")
            expected = f"Rename {reason}"
            wait_for(lambda: expected in changes.names, "the refusal on Rename")
            assert button.getAccessibleName() == expected
            assert button.getAccessibleStateSet() & FOCUSED
            events_before_retry = list(changes.names)
            book.lab.input.tap("space", pause=0.4)
            on_main_thread(book.lab.context, lambda: None)
            assert changes.names == events_before_retry
            evidence["refused"] = dialog.state()
            book.lab.screenshot("rename-sheets-stale")
            book.lab.input.tap("n", ("Alt_L",), pause=0.2)
            book.lab.input.tap("a", ("Control_L",), pause=0.1)
            type_text(book.lab, "Gamma")
            wait_for(lambda: changes.names[-1:] == ["Rename"], "the ordinary Rename name")
            assert button.getAccessibleName() == "Rename"
            assert dialog.state()["name"] == "Gamma"
            evidence["name_changes"] = changes.names
        finally:
            button.removeAccessibleEventListener(changes)
        assert find_dialog(book) is not None, "A refused batch closed the dialog"
        assert book.order() == [n if n != names[3] else "Elsewhere" for n in names]
        assert book.undo_titles() == history
        book.lab.input.tap("Escape", pause=0.5)
        wait_closed(book)
        assert book.undo_titles() == history, "Cancel after a refusal changed the document"
        time.sleep(0.5)
        evidence["picks_after"] = book.selection()
    finally:
        if find_dialog(book) is not None:
            book.lab.input.tap("Escape", pause=0.5)
        sheets = book.document.getSheets()
        if sheets.hasByName("Elsewhere"):
            sheets.getByName("Elsewhere").Name = names[3]
        undo_all(book)
    return evidence
