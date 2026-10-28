"""The Rename Sheets dialog through real keyboard and mouse input (#102).

The dialog is found as the visible dialog window over the document, and observed through public
UNO only: its child windows' text, items, and enabled state, and their accessible names. Pointer
positions come from those windows and their accessible list items, after calibrating the X input
against a motion listener on the dialog's list, as the sheet list itself is calibrated.
"""

import time
from typing import Any

import uno
from run import wait_for
from sheet_list_view import on_main_thread
from xinput import Pointer

from sheet_manager.uno_calc import select_tabs
from sheet_manager.uno_menu import RENAME, RENAME_SHEETS

LIST_ITEM = "com.sun.star.accessibility.AccessibleRole.LIST_ITEM"


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
    """The open Rename Sheets dialog's controls, by kind and position."""

    def __init__(self, book):
        self.book = book
        self.window = wait_for(lambda: find_dialog(book), "the Rename Sheets dialog")
        children = list(self.window.getWindows())

        def top(window):
            size = window.getPosSize()
            return size.Y, size.X

        lists = [c for c in children if "com.sun.star.awt.XListBox" in _types(c)]
        assert len(lists) == 1, [sorted(_types(c)) for c in children]
        self.rows = lists[0]
        edits = sorted(
            (
                c
                for c in children
                if "com.sun.star.awt.XTextComponent" in _types(c)
                and "com.sun.star.awt.XListBox" not in _types(c)
            ),
            key=top,
        )
        assert len(edits) == 3, len(edits)
        self.find, self.replace, self.name = edits
        self.buttons = {
            self.accessible_name(c): c for c in children if "com.sun.star.awt.XButton" in _types(c)
        }
        assert set(self.buttons) == {"Replace All", "Reset All", "Rename", "Cancel"}, self.buttons
        texts = sorted((c for c in children if "com.sun.star.awt.XFixedText" in _types(c)), key=top)
        self.status = texts[-1]
        self.pointer = None

    @staticmethod
    def accessible_name(window):
        return window.getProperty("XAccessible").getAccessibleContext().getAccessibleName()

    def items(self):
        return list(self.rows.getItems())

    def state(self) -> dict[str, Any]:
        return {
            "rows": self.items(),
            "selected": self.rows.getSelectedItemPos(),
            "name": self.name.getText(),
            "status": self.status.getText(),
            "rename_enabled": bool(self.buttons["Rename"].isEnabled()),
        }

    def labels(self):
        """Accessible names, as a screen reader announces the controls."""
        return {
            "find": self.accessible_name(self.find),
            "replace": self.accessible_name(self.replace),
            "name": self.accessible_name(self.name),
            "rows": self.accessible_name(self.rows),
        }

    def calibrate(self):
        if self.pointer is None:
            offset = self.book.lab.calibrate(self.rows, self.window)
            place = self.rows.getPosSize()
            self.pointer = Pointer(self.book.lab.input, (offset[0] - place.X, offset[1] - place.Y))
        return self.pointer

    def click(self, window):
        place = window.getPosSize()
        self.calibrate().click(place.X + place.Width // 2, place.Y + place.Height // 2, pause=0.4)

    def click_row(self, index):
        """Click a row of the list where its accessible item says it is.

        Item positions are taken relative to the list's own accessible position, so that both
        come from the same coordinate system; the calibrated pointer places the list itself.
        """
        role = uno.getConstantByName(LIST_ITEM)
        context = self.rows.getProperty("XAccessible").getAccessibleContext()
        items = []

        def walk(node):
            for child in range(node.getAccessibleChildCount()):
                item = node.getAccessibleChild(child).getAccessibleContext()
                if item.getAccessibleRole() == role:
                    items.append(item)
                else:
                    walk(item)

        walk(context)
        item = items[index]
        here, there = item.getLocationOnScreen(), context.getLocationOnScreen()
        size, place = item.getSize(), self.rows.getPosSize()
        self.calibrate().click(
            place.X + here.X - there.X + min(size.Width // 2, 40),
            place.Y + here.Y - there.Y + size.Height // 2,
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
        evidence["opened"] = dialog.state()
        evidence["accessible_names"] = dialog.labels()
        assert dialog.items() == [f"{name}   (unchanged)" for name in picks], dialog.state()
        assert not dialog.state()["rename_enabled"], dialog.state()
        assert (book.active(), book.calc_tabs(), book.selection()) == (*view, picks)
        assert book.order() == names and not book.undo_titles()
        book.lab.screenshot("rename-sheets-opened")
        type_text(book.lab, "a")  # The Find field has the focus first.
        wait_for(lambda: dialog.find.getText() == "a", "Find to take the typed text")
        book.lab.input.tap("Tab", pause=0.2)
        type_text(book.lab, "4")
        wait_for(lambda: dialog.replace.getText() == "4", "Replace with to take the text")
        book.lab.input.tap("Return", pause=0.6)  # No default button: nothing is applied.
        assert find_dialog(book) is not None and book.order() == names, "Enter applied the batch"
        book.lab.input.tap("a", ("Alt_L",), pause=0.4)  # Replace All.
        expected = ["Bravo   →   Br4vo", "Charlie   →   Ch4rlie", "Delta   →   Delt4"]
        wait_for(lambda: dialog.items() == expected, "the replaced proposals")
        evidence["replaced"] = dialog.state()
        assert dialog.state()["rename_enabled"], dialog.state()
        book.lab.input.tap("s", ("Alt_L",), pause=0.3)  # The Sheets list.
        book.lab.input.tap("Down", pause=0.3)
        wait_for(lambda: dialog.name.getText() == "Ch4rlie", "the second row in the name field")
        book.lab.input.tap("n", ("Alt_L",), pause=0.3)  # The New name field.
        book.lab.input.tap("a", ("Control_L",), pause=0.1)
        type_text(book.lab, "a/b")
        wait_for(lambda: "cannot contain" in dialog.state()["status"], "the refused name")
        evidence["refused"] = dialog.state()
        assert not dialog.state()["rename_enabled"] and "⚠" in dialog.items()[1]
        book.lab.screenshot("rename-sheets-refused-name")
        book.lab.input.tap("a", ("Control_L",), pause=0.1)
        type_text(book.lab, "Bravo")  # Free once Bravo has its new name: a chain.
        wait_for(lambda: dialog.state()["rename_enabled"], "a valid batch again")
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
        wait_for(lambda: dialog.name.getText() == "F0xtr0t", "the clicked row in the name field")
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
        book.lab.input.tap("r", ("Alt_L",), pause=0.8)
        wait_for(lambda: "changed" in dialog.state()["status"], "the refusal in the dialog")
        evidence["refused"] = dialog.state()
        assert find_dialog(book) is not None, "A refused batch closed the dialog"
        assert book.order() == [n if n != names[3] else "Elsewhere" for n in names]
        assert book.undo_titles() == history
        book.lab.screenshot("rename-sheets-stale")
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
