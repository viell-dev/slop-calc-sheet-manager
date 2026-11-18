"""The list's context menu, opened by right click and the Menu key, and its commands.

A command acts on the menu's targets, never on the viewed sheet left from earlier (#100). Entries
are chosen with `Workbook.choose` among the menu's own enabled entries (#84). Mixed hidden and
visible targets get the list's own Show, without grouping.
"""

import time

import sheet_list_view as view
from workbook import MOVES, NAMES, native_dialog, wait_until
from xinput import RIGHT

from sheet_manager.uno_calc import select_tabs
from sheet_manager.uno_menu import DELETE, HIDE, INSERT, RENAME, RENAME_SHEETS, SHOW


def hide_through_menu(book, picked, opener):
    before = book.undo_titles()
    native_view = book.active(), book.calc_tabs()
    entries = book.entries(picked)
    assert not book.lab.input.popup_windows(), "The menu probe must start without a popup"
    opener()
    time.sleep(0.8)
    assert book.lab.input.popup_windows(), "The menu did not create a native popup"
    assert (book.active(), book.calc_tabs()) == native_view, "The open menu changed the view"
    book.choose(HIDE, entries)
    wait_until(
        lambda: all(not book.document.getSheets().getByName(n).IsVisible for n in picked),
        "Hide Sheet to hide the picked sheets",
    )
    hidden = [n for n in book.order() if not book.document.getSheets().getByName(n).IsVisible]
    second = bool(book.lab.input.popup_windows())
    evidence = {"menu": entries, "hidden": hidden, "second_popup": second}
    assert hidden == picked and not second, evidence
    if native_view[0] not in picked:
        expected = native_view[0], [name for name in native_view[1] if name not in picked]
        wait_until(
            lambda: (book.active(), book.calc_tabs()) == expected,
            "Hide to preserve the unaffected view and remaining tab group",
        )
    else:
        assert book.active() not in picked
    evidence["view_after_hide"] = [book.active(), book.calc_tabs()]
    assert len(book.undo_titles()) == len(before) + 1, book.undo_titles()
    undo = book.document.getUndoManager()
    while len(book.undo_titles()) > len(before):
        undo.undo()
    wait_until(
        lambda: all(book.document.getSheets().getByName(n).IsVisible for n in picked),
        "undo to show the sheets again",
    )
    return evidence


def check_menu_right_click(book):
    book.click(2)
    book.click(4, modifiers=("Control_L",))
    picked = [NAMES[2], NAMES[4]]
    wait_until(lambda: book.selection() == picked, "two rows selected")

    def open_menu():
        book.pointer.click(*book.point(4), button=RIGHT, pause=0.2)

    return hide_through_menu(book, picked, open_menu)


def check_menu_keyboard(book):
    evidence = {}
    for index, key in ((7, ("Menu", ())), (8, ("F10", ("Shift_L",)))):
        book.click(index)
        wait_until(lambda i=index: book.selection() == [NAMES[i]], "one row selected")
        evidence[key[0]] = hide_through_menu(
            book, [NAMES[index]], lambda k=key: book.lab.input.tap(k[0], k[1])
        )
    return evidence


def check_context_preserves_view_and_picks(book):
    book.document.Sheets.getByName(NAMES[6]).getCellRangeByName("A1").String = "menu target"
    select_tabs(book.lab.context, book.frame, [0, 2])
    wait_until(lambda: book.selection() == [NAMES[0], NAMES[2]], "native grouped tabs")
    book.click(1)
    book.click(3, modifiers=("Control_L",))
    before = book.active(), book.selection(), frozenset(book.calc_tabs())

    def state():
        return book.active(), book.selection(), frozenset(book.calc_tabs())

    for index in (1, 6):
        book.pointer.click(*book.point(index), button=RIGHT, pause=0.5)
        try:
            assert state() == before, (
                "The outer context menu changed the viewed sheet, tabs or picks"
            )
        finally:
            book.lab.input.tap("Escape", pause=0.5)
        wait_until(lambda: state() == before, "cancel to restore the original view and picks")
        book.lab.input.tap("space", modifiers=("Control_L",), pause=0.3)
        assert book.selection() == [NAMES[1]], "Right-click changed the keyboard cursor"
        book.lab.input.tap("space", modifiers=("Control_L",), pause=0.3)
        assert book.selection() == before[1]
    entries = book.entries([NAMES[6]])
    history = book.undo_titles()  # Includes the edit that gives Golf data to confirm.
    book.pointer.click(*book.point(6), button=RIGHT, pause=0.4)
    book.choose(DELETE, entries)
    wait_until(book.lab.input.modal_dialog, "native delete confirmation")
    # Calc's tabs are set on the target only once its command runs.
    assert book.calc_tabs() == [NAMES[6]], "Delete must target exactly the right-clicked row"
    assert not book.lab.input.popup_windows(), "A second menu opened after choosing Delete"
    assert book.selection() == before[1]
    book.lab.screenshot("context-delete-confirmation")
    book.lab.input.tap("Escape", pause=0.5)
    # A chosen command keeps Calc on its target, even when its own dialog is cancelled (#100).
    kept = NAMES[6], before[1], frozenset([NAMES[6]])
    wait_until(lambda: state() == kept, "a cancelled native command to keep its target")
    assert NAMES[6] in book.order() and book.undo_titles() == history, "Cancel deleted a sheet"
    book.controller.setActiveSheet(book.document.Sheets.getByIndex(0))
    select_tabs(book.lab.context, book.frame, [0, 2])
    wait_until(lambda: book.selection() == [NAMES[0], NAMES[2]], "native grouped tabs again")
    book.click(1)
    book.click(3, modifiers=("Control_L",))
    wait_until(lambda: state() == before, "the original context again")
    order = book.order()
    entries = book.entries([NAMES[6]])
    book.pointer.click(*book.point(6), button=RIGHT, pause=0.4)
    book.choose(MOVES["bottom"], entries)
    wait_until(lambda: book.order()[-1] == NAMES[6], "context move of the unpicked row")
    wait_until(lambda: state() == before, "context move to keep independent picks and view")
    book.document.UndoManager.undo()
    wait_until(lambda: book.order() == order, "one undo of the context move")
    book.click(1)
    book.pointer.click(*book.point(6), button=RIGHT, pause=0.4)
    # The open menu has not touched the native view. A macro can still change it, and
    # dismissing the menu keeps that newer view: nothing is restored.
    book.controller.setActiveSheet(book.document.Sheets.getByName(NAMES[9]))
    select_tabs(book.lab.context, book.frame, [9, 11])
    newer_view = state()
    book.lab.input.tap("Escape", pause=0.5)
    wait_until(lambda: not book.lab.input.popup_windows(), "the dismissed menu to close")
    view.on_main_thread(book.lab.context, lambda: None)
    time.sleep(0.5)
    assert state() == newer_view, "Dismissing the menu changed the view"
    return {
        "picked_and_unpicked_cancel": True,
        "unpicked_move": True,
        "one_undo": True,
        "modal_command_context_kept": True,
        "dismissal_leaves_view": True,
    }


def check_context_rename_targets_row(book):
    """Rename from the menu acts on its target, not the earlier viewed sheet (#100).

    Calc's Rename Sheet dialog is asynchronous and renames the sheet viewed when it is
    confirmed, so the view must stay on the target while the dialog is open. The active sheet,
    the list's picks and the right-clicked row all differ; each sheet has identifying text.
    """
    sheets = book.document.getSheets()
    target, picks = NAMES[3], [NAMES[2], NAMES[4]]
    for name in NAMES[:6]:
        sheets.getByName(name).getCellRangeByName("B1").String = f"identity {name}"
    undo = book.document.getUndoManager()
    undo.clear()
    evidence = {}

    def rename(label, opener, finish):
        entries = book.entries([target])
        opener()
        book.choose(RENAME, entries)
        wait_until(lambda: native_dialog(book), "the native Rename Sheet dialog")
        # Barriers: the menu's queued completion has run under the open dialog.
        view.on_main_thread(book.lab.context, lambda: None)
        view.on_main_thread(book.lab.context, lambda: None)
        evidence[f"{label}_dialog"] = book.active(), book.calc_tabs()
        assert not book.lab.input.popup_windows(), "A second menu opened after choosing Rename"
        book.lab.screenshot(f"context-rename-{label}")
        finish()
        wait_until(lambda: not native_dialog(book), "the dialog to close")
        view.on_main_thread(book.lab.context, lambda: None)
        evidence[f"{label}_after"] = book.active(), book.calc_tabs(), book.selection()

    def type_name():
        book.lab.input.tap("a", ("Control_L",))
        for char in "renamed":
            book.lab.input.tap(char, pause=0.03)
        book.lab.input.tap("Return", pause=0.5)

    def identities():
        return {
            sheets.getByIndex(i).getName(): sheets.getByIndex(i).getCellRangeByName("B1").String
            for i in range(6)
        }

    def right_click():
        book.pointer.click(*book.point(3), button=RIGHT, pause=0.5)

    def view_first_sheet(picked):
        book.controller.setActiveSheet(sheets.getByIndex(0))
        select_tabs(book.lab.context, book.frame, [0])
        # Newer list input wins over following this native change.
        book.click(NAMES.index(picked[0]))
        for name in picked[1:]:
            book.click(NAMES.index(name), modifiers=("Control_L",))
        wait_until(lambda: book.selection() == picked, f"the picks {picked}")
        assert (book.active(), book.calc_tabs()) == (NAMES[0], [NAMES[0]])

    expected = {("renamed" if n == target else n): f"identity {n}" for n in NAMES[:6]}
    try:
        view_first_sheet(picks)
        original = identities()
        rename("unpicked", right_click, type_name)
        wait_until(lambda: "renamed" in book.order(), "the confirmed rename")
        evidence["unpicked_identities"] = identities()
        assert identities() == expected, evidence
        assert evidence["unpicked_dialog"] == (target, [target]), evidence
        assert book.undo_titles() == ["Rename Sheet"], book.undo_titles()
        assert evidence["unpicked_after"] == ("renamed", ["renamed"], picks), evidence
        undo.undo()
        wait_until(lambda: book.order()[3] == target, "one undo of the rename")

        view_first_sheet(picks)
        rename("cancel", right_click, lambda: book.lab.input.tap("Escape", pause=0.5))
        assert identities() == original and not book.undo_titles(), "Cancel renamed a sheet"
        assert evidence["cancel_after"] == (target, [target], picks), evidence

        view_first_sheet([target])
        rename("keyboard", lambda: book.lab.input.tap("Menu", pause=0.4), type_name)
        wait_until(lambda: "renamed" in book.order(), "the keyboard rename")
        evidence["keyboard_identities"] = identities()
        assert evidence["keyboard_dialog"] == (target, [target]), evidence
        assert identities() == expected, evidence
    finally:
        for _ in range(2):
            if native_dialog(book):
                book.lab.input.tap("Escape", pause=0.5)
        while book.undo_titles():
            undo.undo()
    return evidence


def identify(book, count=6):
    sheets = book.document.getSheets()
    for name in NAMES[:count]:
        sheets.getByName(name).getCellRangeByName("B1").String = f"identity {name}"
    book.document.getUndoManager().clear()


def identities(book, count=6):
    sheets = book.document.getSheets()
    return {
        sheets.getByIndex(i).getName(): sheets.getByIndex(i).getCellRangeByName("B1").String
        for i in range(min(count, sheets.getCount()))
    }


def view_first_sheet(book, picked):
    """Calc views Alfa alone; the list picks `picked`. Newer list input wins over following."""
    sheets = book.document.getSheets()
    book.controller.setActiveSheet(sheets.getByIndex(0))
    select_tabs(book.lab.context, book.frame, [0])
    book.click(NAMES.index(picked[0]))
    for name in picked[1:]:
        book.click(NAMES.index(name), modifiers=("Control_L",))
    wait_until(lambda: book.selection() == picked, f"the picks {picked}")
    assert (book.active(), book.calc_tabs()) == (NAMES[0], [NAMES[0]])


def check_context_insert_targets_row(book):
    """Insert Sheet anchors on the right-clicked row, not the viewed sheet or the picks.

    Calc's Insert Sheet dialog is asynchronous and inserts before the sheet viewed when it is
    confirmed, so the view stays on the target. The active sheet, the picks and the
    right-clicked row all differ; each sheet has identifying text.
    """
    target, picks = NAMES[3], [NAMES[2], NAMES[4]]
    identify(book)
    undo = book.document.getUndoManager()
    original, order = identities(book), book.order()
    evidence = {}

    def insert(label, opener, finish):
        entries = book.entries([target])
        opener()
        book.choose(INSERT, entries)
        wait_until(lambda: native_dialog(book), "the native Insert Sheet dialog")
        view.on_main_thread(book.lab.context, lambda: None)
        view.on_main_thread(book.lab.context, lambda: None)
        evidence[f"{label}_dialog"] = book.active(), book.calc_tabs()
        assert not book.lab.input.popup_windows(), "A second menu opened after choosing Insert"
        book.lab.screenshot(f"context-insert-{label}")
        finish()
        wait_until(lambda: not native_dialog(book), "the dialog to close")
        view.on_main_thread(book.lab.context, lambda: None)

    def right_click():
        book.pointer.click(*book.point(3), button=RIGHT, pause=0.5)

    def confirm():
        book.lab.input.tap("Return", pause=0.5)  # OK: a new sheet before the current one.

    def inserted():
        new = [name for name in book.order() if name not in order]
        assert len(new) == 1, book.order()
        return new[0]

    try:
        for label, opener, picked in (
            ("unpicked", right_click, picks),
            ("keyboard", lambda: book.lab.input.tap("Menu", pause=0.4), [target]),
        ):
            view_first_sheet(book, picked)
            insert(label, opener, confirm)
            wait_until(lambda: len(book.order()) == len(order) + 1, "the confirmed insert")
            name = inserted()
            evidence[f"{label}_order"] = book.order()[:6]
            assert evidence[f"{label}_dialog"] == (target, [target]), evidence
            assert book.order()[3:5] == [name, target], evidence
            assert {n: t for n, t in identities(book, 7).items() if n != name} == original
            assert book.undo_titles() == ["Insert Sheet"], book.undo_titles()
            undo.undo()
            wait_until(lambda: book.order() == order, "one undo of the insert")
            undo.clear()

        view_first_sheet(book, picks)
        insert("cancel", right_click, lambda: book.lab.input.tap("Escape", pause=0.5))
        assert book.order() == order and not book.undo_titles(), "Cancel inserted a sheet"
        assert (book.active(), book.calc_tabs(), book.selection()) == (target, [target], picks)
    finally:
        for _ in range(2):
            if native_dialog(book):
                book.lab.input.tap("Escape", pause=0.5)
        while book.undo_titles():
            undo.undo()
    return evidence


def check_context_delete_targets(book):
    """Delete acts on exactly the targeted picks, after Calc's own confirmation.

    The picks Charlie and Echo hold data, so Calc asks first. Cancelling deletes nothing and
    leaves Calc grouped on them, with the footer's warning; confirming deletes exactly them in
    one undo step. One-sheet commands are unavailable for two targets.
    """
    picks = [NAMES[2], NAMES[4]]
    identify(book)
    undo = book.document.getUndoManager()
    original, order = identities(book), book.order()
    entries = book.entries(picks)
    evidence = {"entries": entries}
    assert DELETE in entries and HIDE in entries, entries
    assert INSERT not in entries and RENAME not in entries, entries
    group = view.footer_text(book.panel, "Cell edits affect")
    try:
        for label, key in (("cancel", "Escape"), ("confirm", "Return")):
            view_first_sheet(book, picks)
            book.pointer.click(*book.point(4), button=RIGHT, pause=0.5)
            book.choose(DELETE, entries)
            wait_until(book.lab.input.modal_dialog, "Calc's delete confirmation")
            evidence[f"{label}_confirmation"] = book.active(), book.calc_tabs()
            assert book.calc_tabs() == picks, evidence
            assert not book.lab.input.popup_windows(), "A second menu opened after Delete"
            book.lab.screenshot(f"context-delete-{label}")
            book.lab.input.tap(key, pause=0.5)
            wait_until(lambda: not book.lab.input.modal_dialog(), "the confirmation to close")
            view.on_main_thread(book.lab.context, lambda: None)
            if label == "cancel":
                assert book.order() == order and not book.undo_titles(), "Cancel deleted"
                assert book.calc_tabs() == picks and book.selection() == picks
                wait_until(
                    lambda: group.getText() == f"Edits affect 2 Calc tabs: {picks[0]}, {picks[1]}",
                    "the grouped-tabs warning",
                )
            else:
                wait_until(lambda: len(book.order()) == len(order) - 2, "the confirmed delete")
                left = {n: t for n, t in original.items() if n not in picks}
                assert identities(book, 4) == left, identities(book, 4)
                assert len(book.undo_titles()) == 1, book.undo_titles()
                undo.undo()
                wait_until(lambda: book.order() == order, "one undo of the delete")
                assert identities(book) == original
    finally:
        if book.lab.input.modal_dialog():
            book.lab.input.tap("Escape", pause=0.5)
        while book.undo_titles():
            undo.undo()
    return evidence


def check_help_menu(book):
    path = book.lab.output / "opened-uris.txt"
    before = path.read_text().splitlines() if path.exists() else []
    book.focus_list()
    book.lab.input.tap("Menu", pause=0.4)
    book.lab.input.tap("End")
    book.lab.input.tap("Return", pause=0.5)
    wait_until(
        lambda: path.exists() and len(path.read_text().splitlines()) > len(before),
        "the native desktop opener to receive Help",
    )
    opened = path.read_text().splitlines()[len(before) :]
    assert opened == ["https://viell-dev.github.io/slop-calc-sheet-manager/"], opened
    return {"native_desktop_uri": opened[0]}


def check_menu_hidden_only(book):
    name = NAMES[9]
    sheet = book.document.getSheets().getByName(name)
    sheet.IsVisible = False
    book.document.getUndoManager().clear()
    wait_until(lambda: "(hidden)" in book.labels()[9], "the hidden label")
    active = book.active()
    book.click(9)
    wait_until(lambda: book.selection() == [name], "the hidden row selected")
    assert book.active() == active, "A hidden row must not become the active sheet"
    book.pointer.click(*book.point(9), button=RIGHT, pause=0.8)
    book.lab.screenshot("menu-hidden-only")
    tabs = book.calc_tabs()
    book.lab.input.tap("Down")
    book.lab.input.tap("Return", pause=0.6)
    wait_until(lambda: sheet.IsVisible, "Show Sheet to show the hidden sheet")
    titles = book.undo_titles()
    book.document.getUndoManager().undo()
    wait_until(lambda: not sheet.IsVisible, "one undo to hide it again")
    sheet.IsVisible = True
    evidence = {"calc_tabs_unchanged": tabs == [active], "undo_titles": titles}
    assert tabs == [active] and len(titles) == 1, evidence
    return evidence


def check_menu_mixed_visibility(book):
    """Mixed targets get the list's own Show in place of Calc's commands, without grouping."""
    sheet = book.document.Sheets.getByName(NAMES[9])
    sheet.IsVisible = False
    book.click(2)
    book.click(9, modifiers=("Control_L",))
    picked = [NAMES[2], NAMES[9]]
    wait_until(lambda: book.selection() == picked, "visible and hidden picks")
    before = book.active(), book.calc_tabs()
    history = book.undo_titles()
    try:
        book.lab.input.tap("Menu", pause=0.4)
        assert (book.active(), book.calc_tabs()) == before, "The open menu changed the view"
        book.lab.screenshot("menu-mixed-visibility")
        # Show takes Hide's place; Calc's commands cannot target a hidden sheet. The list's
        # Rename Sheets comes first among the available entries. Down skips unavailable
        # entries in gtk3 and gen alike (#84).
        entries = book.entries(picked)
        assert RENAME_SHEETS in entries and SHOW in entries, entries
        for _ in range(entries.index(SHOW) + 1):
            book.lab.input.tap("Down")
        book.lab.input.tap("Return", pause=0.5)
        wait_until(lambda: sheet.IsVisible, "safe Show to show the hidden target")
        assert book.undo_titles() == ["Show Sheet", *history]
        assert (book.active(), book.calc_tabs()) == before and book.selection() == picked
        book.document.UndoManager.undo()
        wait_until(lambda: not sheet.IsVisible, "one Undo to hide the target again")
    finally:
        book.lab.input.tap("Escape", pause=0.2)
        sheet.IsVisible = True
    return {"safe_mixed_targets": True, "one_undo": True, "view_kept": True}
