"""Moves from the menu, the buttons and Alt+arrow shortcuts, each one complete undo step.

Every move keeps the picks, the viewed sheet, Calc's tabs and the keyboard focus in the list and
adds exactly one "Move Sheets" undo step; a refused move (at an edge, with protected structure or
recorded changes) changes nothing. Input in the list activates an inactive frame, and the buttons'
enablement never waits for that (#211). `check_undo_own_move` replays the owner's drag-and-undo
sequence (#91).
"""

import time
from typing import cast

import sheet_list_view as view
from button_pixels import capture as capture_disabled_buttons
from drag_checks import drag
from workbook import MOVES, NAMES, native_dialog, wait_until

from sheet_manager.reorder import Action, Sheet, target_order
from sheet_manager.uno_calc import select_tabs


def check_move_controls(book, shortcuts, buttons=False):
    evidence = {}
    if buttons:
        before = book.order(), book.active(), book.calc_tabs(), book.undo_titles()
        view.on_main_thread(book.lab.context, book.tree.clearSelection)
        peers = view.move_buttons(book.panel)
        wait_until(
            lambda: all(not p.isEnabled() for p in peers.values()), "no-pick buttons disabled"
        )
        tree_bounds = book.tree.getPosSize()
        evidence["disabled_labels"] = capture_disabled_buttons(
            book.lab,
            peers,
            "move-buttons-disabled-labels",
            (book.pointer.offset[0] - tree_bounds.X, book.pointer.offset[1] - tree_bounds.Y),
        )
        assert (book.order(), book.active(), book.calc_tabs(), book.undo_titles()) == before
    for action, key in (
        ("top", "Home"),
        ("up", "Up"),
        ("down", "Down"),
        ("bottom", "End"),
    ):
        book.click(2)
        book.click(5, modifiers=("Control_L",))
        picked = [NAMES[2], NAMES[5]]
        try:
            wait_until(lambda p=picked: book.selection() == p, "two separate rows selected")
        except AssertionError as error:
            error.add_note(
                f"Before {action}: order={book.order()!r}, rows={view.names(book.tree)!r}, "
                f"picks={book.selection()!r}, focused={book.tree.hasFocus()!r}"
            )
            raise
        before, history, active, tabs = (
            book.order(),
            book.undo_titles(),
            book.active(),
            book.calc_tabs(),
        )
        expected = list(target_order([Sheet(n) for n in before], picked, cast(Action, action)))
        if shortcuts:
            book.lab.input.tap(key, modifiers=("Alt_L",), pause=0.3)
        elif buttons:
            button = view.move_buttons(book.panel)[action.capitalize()]
            wait_until(button.isEnabled, "the visible move control to be enabled")
            book.click_control(button)
        else:
            book.move_action(action)
        wait_until(lambda e=expected: book.order() == e, "the requested move")
        wait_until(lambda e=expected: view.names(book.tree) == e, "the moved list order")
        wait_until(lambda p=picked: book.selection() == p, "the picked sheets to stay picked")
        assert book.undo_titles() == ["Move Sheets", *history]
        assert book.active() == active and set(book.calc_tabs()) == set(tabs)
        assert book.tree.hasFocus(), "Moving must leave keyboard focus in the list"
        evidence[action] = {"one_undo": True, "picks_kept": book.selection(), "view_kept": True}
        book.document.getUndoManager().undo()
        wait_until(lambda b=before: book.order() == b, "one undo to restore the order")
        wait_until(lambda b=before: view.names(book.tree) == b, "the restored list order")
    return evidence


def check_repeated_move_shortcut(book):
    """Repeated and held shortcuts move one step at a time and never open a message (#340), also
    once the sheet is at the end of the list (#353).

    Keys that arrive while a move runs are delivered together after it. The list drops those that
    come while another request waits, so the number of steps depends on the machine's speed; each
    one that ran must be one place and one undo step.
    """
    evidence = {}
    before, history = book.order(), book.undo_titles()
    gestures = {
        "taps": lambda: [
            book.lab.input.tap("Down", modifiers=("Alt_L",), pause=0) for _ in range(6)
        ],
        "held": lambda: book.lab.input.repeat("Down", modifiers=("Alt_L",), seconds=1.3),
    }
    for gesture, run in gestures.items():
        book.click(2)
        wait_until(lambda: book.selection() == [NAMES[2]], "the sheet to move picked")
        run()
        steps, last = -1, 0.0
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:  # Until no further move has come for a while.
            count = len(book.undo_titles()) - len(history)
            if count != steps:
                steps, last = count, time.monotonic()
            elif time.monotonic() - last > 1.5:
                break
            time.sleep(0.2)
        dialog = native_dialog(book)
        evidence[gesture] = {"steps": steps, "dialog": dialog, "order": book.order()[:30]}
        if dialog:
            book.lab.screenshot(f"repeated-move-{gesture}")
        assert not dialog and steps >= 1, evidence
        expected = [name for name in before if name != NAMES[2]]
        expected.insert(2 + steps, NAMES[2])
        assert book.order() == expected, evidence
        assert book.undo_titles() == ["Move Sheets"] * steps + history, evidence
        wait_until(lambda: book.selection() == [NAMES[2]], "the moved sheet to stay picked")
        for _ in range(steps):
            book.document.getUndoManager().undo()
        wait_until(lambda: view.names(book.tree) == before, "the undone moves in the list")
        wait_until(lambda: book.order() == before, "the original order")
    book.click(2)
    wait_until(lambda: book.selection() == [NAMES[2]], "the sheet to move to the top picked")
    book.lab.input.repeat("Up", modifiers=("Alt_L",), seconds=3.0)
    evidence["held_to_the_top"] = {"dialog": native_dialog(book), "order": book.order()[:4]}
    if evidence["held_to_the_top"]["dialog"]:
        book.lab.screenshot("repeated-move-held-to-the-top")
    assert not evidence["held_to_the_top"]["dialog"], evidence
    # However many steps the held key made, the sheet is at the top now, and the list is settled.
    book.lab.input.tap("Home", modifiers=("Alt_L",), pause=0.5)
    top = [NAMES[2], *[name for name in before if name != NAMES[2]]]
    wait_until(lambda: book.order() == top == view.names(book.tree), "the sheet at the top")
    wait_until(lambda: book.selection() == [NAMES[2]], "the sheet at the top to stay picked")
    steps = len(book.undo_titles()) - len(history)
    for key in ("Up", "Home"):
        time.sleep(1.0)
        book.lab.input.tap(key, modifiers=("Alt_L",), pause=1.0)
        evidence[f"{key}_at_the_top"] = dialog = native_dialog(book)
        assert not dialog and book.tree.hasFocus(), evidence
        assert len(book.undo_titles()) - len(history) == steps, evidence
        assert book.order() == top and book.selection() == [NAMES[2]], evidence
    for _ in range(steps):
        book.document.getUndoManager().undo()
    wait_until(lambda: view.names(book.tree) == before, "the undone moves in the list")
    return evidence


def check_moves_after_inactive_frame(book):
    """Input in the list activates its window, and enablement never waits for that (#211).

    LibreOffice can leave the frame of the focused window inactive; then neither real clicks in
    it nor Calc's own dialogs activated it, and the move buttons stayed disabled. `deactivate()`
    makes that state on the private display; the window keeps the focus.
    """
    context, sheets = book.lab.context, book.document.getSheets()
    peers = view.move_buttons(book.panel)
    view.on_main_thread(context, book.frame.deactivate)
    assert not book.frame.isActive()
    view_before = book.active(), book.calc_tabs()
    book.click(2)
    book.click(5, modifiers=("Control_L",))
    picked = [NAMES[2], NAMES[5]]
    wait_until(lambda: book.selection() == picked, "two rows picked in the inactive window")
    wait_until(book.frame.isActive, "real input in the list to activate its window")
    wait_until(lambda: all(p.isEnabled() for p in peers.values()), "every move button enabled")
    assert (book.order(), book.active(), book.calc_tabs()) == (NAMES, *view_before)
    assert book.tree.hasFocus() and not book.undo_titles(), "Activation changed nothing else"
    # Inactive again while Calc's switch refreshes the list and its enablement.
    view.on_main_thread(context, book.frame.deactivate)
    book.controller.setActiveSheet(sheets.getByIndex(1))
    wait_until(lambda: book.selection() == [NAMES[1]], "the list to follow Calc's switch")
    wait_until(peers["Down"].isEnabled, "Down enabled while the window is inactive")
    assert not book.frame.isActive()
    expected = list(target_order([Sheet(n) for n in NAMES], [NAMES[1]], "down"))
    book.click_control(peers["Down"])
    wait_until(lambda: book.order() == expected, "Down's move from the inactive window")
    assert book.frame.isActive() and book.undo_titles() == ["Move Sheets"]
    assert book.active() == NAMES[1] and book.calc_tabs() == [NAMES[1]]
    book.document.getUndoManager().undo()
    wait_until(lambda: book.order() == NAMES, "one undo restoring the order")
    return {"activated_by_clicks": picked, "enabled_while_inactive": True, "moved": expected}


def check_move_edges_and_refusal(book):
    book.click(0)
    before, history = book.order(), book.undo_titles()
    entries = book.entries([NAMES[0]])
    assert MOVES["top"] not in entries and MOVES["up"] not in entries, entries
    book.lab.input.tap("Menu", pause=0.4)
    book.lab.screenshot("move-edge-disabled")
    book.choose(MOVES["down"], entries)
    wait_until(lambda: book.order().index(NAMES[0]) == 1, "the first enabled edge action")
    book.move_action("down")
    wait_until(lambda: book.order().index(NAMES[0]) == 2, "repeated menu movement")
    assert book.undo_titles() == ["Move Sheets", "Move Sheets", *history]
    book.document.getUndoManager().undo()
    book.document.getUndoManager().undo()
    wait_until(lambda: book.order() == before, "two undo steps")
    evidence = {"edge_actions_disabled": True, "repeated_moves": True}
    for setting in ("protected", "recorded"):
        if setting == "protected":
            book.document.protect("synthetic")
        else:
            book.document.RecordChanges = True
        try:
            book.click(2)
            book.lab.input.tap("Menu", pause=0.4)
            book.lab.screenshot("move-disabled-" + setting)
            book.lab.input.tap("Escape", pause=0.4)
            history = book.undo_titles()
            book.tree.setFocus()
            book.lab.input.tap("End", modifiers=("Alt_L",), pause=0.6)
            book.lab.input.tap("Escape", pause=0.4)
            assert book.order() == before and book.undo_titles() == history
            evidence[setting + "_refused"] = True
        finally:
            if setting == "protected":
                book.document.unprotect("synthetic")
            else:
                book.document.RecordChanges = False
    return evidence


def check_move_focus_and_queued_navigation(book):
    cell = book.controller.getActiveSheet().getCellRangeByName("A1")
    content = cell.String
    book.controller.select(cell)
    book.document.setModified(False)
    time.sleep(1.5)  # Let the unrecorded modified-state change renew the list's proof.
    book.click(3)
    buttons = view.move_buttons(book.panel)
    book.lab.input.tap("Tab", modifiers=("Shift_L",), pause=0.2)
    wait_until(buttons["Bottom"].hasFocus, "a focused button for the typing probe")
    book.lab.input.tap("x", pause=0.2)
    book.lab.input.tap("Tab", pause=0.2)
    wait_until(book.tree.hasFocus, "Tab from Bottom to the tree")
    book.lab.input.tap("Return", pause=0.4)
    wait_until(lambda: book.active() == NAMES[3], "Enter on the tree after button typing")
    assert cell.String == content and not book.document.isModified(), (
        "Typing on a button reached or modified the sheet"
    )
    book.click(2)
    before = book.order()
    book.lab.input.tap("Down", pause=0)
    book.lab.input.tap("Up", modifiers=("Alt_L",), pause=0.3)
    expected = list(target_order([Sheet(n) for n in before], [NAMES[3]], "up"))
    wait_until(lambda: book.order() == expected, "movement to use the newly navigated row")
    assert book.selection() == [NAMES[3]] and book.undo_titles() == ["Move Sheets"]
    book.document.UndoManager.undo()
    wait_until(lambda: view.names(book.tree) == before, "one undo of the queued move")
    book.click(3)
    history = book.undo_titles()
    buttons = view.move_buttons(book.panel)
    assert book.tree.hasFocus(), "Internal focus travel must start in the list"
    for label in ("Bottom", "Down", "Up", "Top"):
        book.lab.input.tap("Tab", modifiers=("Shift_L",), pause=0.2)
        wait_until(buttons[label].hasFocus, "reverse Tab to " + label)
    book.lab.input.tap("Return", pause=0.5)
    wait_until(lambda: book.order()[0] == NAMES[3], "native Enter on the Top button")
    assert book.tree.hasFocus() and book.undo_titles() == ["Move Sheets", *history]
    book.document.UndoManager.undo()
    wait_until(lambda: view.names(book.tree) == before, "undo of the keyboard button action")
    assert book.tree.hasFocus()
    book.lab.input.tap("Tab", pause=0.3)
    wait_until(lambda: not book.tree.hasFocus(), "Tab after the last panel control")
    history = book.undo_titles()
    book.lab.input.tap("Down", modifiers=("Alt_L",), pause=0.3)
    book.lab.input.tap("Escape", pause=0.2)
    assert book.order() == before and book.undo_titles() == history
    return {
        "button_typing_safe": True,
        "queued_navigation": True,
        "tab_boundaries": True,
        "outside_shortcut_scope": True,
    }


def check_undo_own_move(book):
    """#91, the owner's sequence: Kilo viewed, Echo to Hotel picked and dragged above Bravo,
    then real Ctrl+Z and Ctrl+Y. Calc's Undo activates the sheets it moves back; the list keeps
    its picks and puts the view back, with no notice."""
    picks = NAMES[4:8]
    kilo = NAMES.index("Kilo")
    book.controller.setActiveSheet(book.document.getSheets().getByIndex(kilo))
    select_tabs(book.lab.context, book.frame, [kilo])
    wait_until(lambda: book.calc_tabs() == ["Kilo"], "Kilo viewed alone")
    before = book.order()
    book.click(4)
    book.click(7, modifiers=("Shift_L",))
    wait_until(lambda: book.selection() == picks, "Echo to Hotel picked")
    drag(book, 6, 1, 0.25, shot="undo-own-move-drag")
    moved = before[:1] + picks + before[1:4] + before[8:]
    wait_until(lambda: book.order() == moved, "the drop above Bravo")
    notice = view.footer_text(book.panel, "Why the sheet list")
    steps = [("drop", moved)] + [
        (keysym, order) for keysym, order in (("z", before), ("y", moved), ("z", before))
    ]
    evidence = []
    for keysym, order in steps:
        if keysym != "drop":
            book.lab.input.tap(keysym, modifiers=("Control_L",), pause=0.2)
        wait_until(lambda o=order: book.order() == o, f"the order after {keysym}")
        time.sleep(1.5)  # Longer than the list's refresh and view sampling.
        state = {
            "step": keysym,
            "picks": book.selection(),
            "active": book.active(),
            "tabs": book.calc_tabs(),
            "notice": notice.getText(),
        }
        evidence.append(state)
        book.lab.screenshot(f"undo-own-move-{len(evidence)}-{keysym}")
        wanted = {"step": keysym, "picks": picks, "active": "Kilo", "tabs": ["Kilo"], "notice": ""}
        assert state == wanted, evidence
    return evidence
