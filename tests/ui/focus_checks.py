"""Keys stay in the list, shortcuts reach Calc, and the focus and keyboard cursor stay put.

Letters, Space, Delete and the other keys typed in the list never edit a cell or modify the
document. Calc's shortcuts still work from the list, and their dialogs keep the focus
while they are open (#23). A refresh that rebuilds the rows keeps the keyboard cursor where it
was (#29), and a second document's list works independently of the first. These checks rebuild
the rows by protecting a sheet, which changes its label: a painted-only change such as a tab
colour keeps the tree and its cursor (#22).
"""

import time

import sheet_list_view as view
from workbook import NAMES, Workbook, native_dialog, reset, wait_until


def check_keys_stay_in_list(book):
    # A modification without an undo action makes the list drop its picks (#28): mark the
    # document unmodified before the list's own input, and let the list refresh first.
    book.document.setModified(False)
    time.sleep(1.5)
    book.click(0)
    wait_until(lambda: book.active() == NAMES[0], "the first sheet to be active")
    sheet = book.document.getSheets().getByIndex(0)
    cell = sheet.getCellRangeByName("A1")
    book.controller.select(cell)
    keys = book.lab.input
    steps = {}
    keys.tap("q", pause=0.4)
    steps["q"] = book.selection()
    time.sleep(1.2)  # Start a new type-ahead word.
    keys.tap("k", pause=0.4)
    steps["k"] = book.selection()
    keys.tap("Down", pause=0.4)
    steps["Down"] = book.selection()
    for key, modifiers in (
        ("space", ()),
        ("space", ("Shift_L",)),
        ("space", ("Control_L",)),
        ("Delete", ()),
        ("BackSpace", ()),
        ("z", ()),
        ("1", ()),
        ("numbersign", ("Shift_L",)),
    ):
        keys.tap(key, modifiers, pause=0.25)
    # Still on the first sheet: Ctrl+Space or Shift+Space would have selected a column or row.
    selection = book.controller.getSelection().getRangeAddress()
    time.sleep(1.2)
    keys.tap("m", pause=0.4)
    steps["m"] = book.selection()
    keys.tap("Return", pause=0.8)
    evidence = {
        "selections": steps,
        "active_after_enter": book.active(),
        "A1": cell.getString(),
        "cell_selection": [
            selection.Sheet,
            selection.StartColumn,
            selection.StartRow,
            selection.EndColumn,
            selection.EndRow,
        ],
        "modified": book.document.isModified(),
    }
    assert steps["q"] == ["Quebec"] and steps["k"] == ["Kilo"], evidence
    assert steps["Down"] == ["Lima"], evidence  # Arrow keys continue from the typed row.
    assert steps["m"] == ["Mike"] and book.active() == "Mike", evidence
    assert cell.getString() == "keep" and not book.document.isModified(), evidence
    assert evidence["cell_selection"] == [0, 0, 0, 0, 0], evidence
    return evidence


def check_shortcuts(book):
    keys = book.lab.input
    focus = {}

    def with_list_focus(name, keysym):
        book.focus_list()
        wait_until(lambda: book.tree.hasFocus(), "the list to have the focus")
        keys.tap(keysym, ("Control_L",), pause=0.6)
        focus[name] = bool(book.tree.hasFocus())

    book.click(0)
    wait_until(lambda: book.active() == NAMES[0], "the first sheet to be active")
    with_list_focus("ctrl_page_down", "Next")
    next_sheet = book.active()
    with_list_focus("ctrl_page_up", "Prior")
    previous_sheet = book.active()
    cell = book.document.getSheets().getByIndex(0).getCellRangeByName("B2")
    cell.setString("changed")
    with_list_focus("ctrl_z", "z")
    wait_until(lambda: cell.getString() == "", "Ctrl+Z to undo the cell change")
    cell.setString("saved")
    assert book.document.isModified()
    stamp = book.path.stat().st_mtime_ns
    book.focus_list()
    wait_until(lambda: book.tree.hasFocus(), "the list to have the focus")
    view_before = book.selection(), book.active(), book.calc_tabs()
    keys.tap("s", ("Control_L",), pause=0.6)
    wait_until(lambda: not book.document.isModified(), "Ctrl+S to save", timeout=20)
    # With gtk3, the save moves the focus to the sheet; the list takes it back (#23).
    focus["ctrl_s"] = wait_for_list_focus(book)
    evidence = {
        "ctrl_page_down": next_sheet,
        "ctrl_page_up": previous_sheet,
        "undo": True,
        "saved": book.path.stat().st_mtime_ns != stamp,
        "list_has_focus_after": focus,
        "view_kept": (book.selection(), book.active(), book.calc_tabs()) == view_before,
    }
    assert next_sheet == NAMES[1] and previous_sheet == NAMES[0], evidence
    assert evidence["saved"], evidence
    assert all(focus.values()) and evidence["view_kept"], evidence
    evidence["typed_after_save"] = typing_reaches_list(book, "k", "Kilo")
    return evidence


def wait_for_list_focus(book, timeout=10):
    """Whether the tree has the focus within `timeout` and still has it a second later."""
    deadline = time.monotonic() + timeout
    while not book.tree.hasFocus():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    time.sleep(1)
    return bool(book.tree.hasFocus())


def typing_reaches_list(book, letter, name):
    """A typed letter selects `name` in the list, and Enter shows it; no cell changes."""
    sheet = book.controller.getActiveSheet()
    address = book.controller.getSelection().getRangeAddress()
    cell = sheet.getCellByPosition(address.StartColumn, address.StartRow)
    text, modified = cell.getString(), book.document.isModified()
    book.lab.input.tap(letter, pause=0.4)
    selected = book.selection()
    book.lab.input.tap("Return", pause=0.8)
    result = {
        "selection": selected,
        "active_after_enter": book.active(),
        "cell_unchanged": cell.getString() == text,
        "modified_unchanged": book.document.isModified() == modified,
    }
    assert result == {
        "selection": [name],
        "active_after_enter": name,
        "cell_unchanged": True,
        "modified_unchanged": True,
    }, result
    return result


def save_with_prompt(book, answer, shot):
    """Ctrl+S from the list opens a dialog, which keeps the focus while it is open (#23).

    Checks what was seen while the dialog was open, and that the list has the focus again after
    `answer` closed it, before the caller types into it.
    """
    book.document.getSheets().getByIndex(0).getCellRangeByName("B2").setString("changed")
    time.sleep(1)
    book.focus_list()
    wait_until(lambda: book.tree.hasFocus(), "the list to have the focus")
    view_before = book.selection(), book.active(), book.calc_tabs()
    book.lab.input.tap("s", ("Control_L",), pause=0.3)
    wait_until(lambda: native_dialog(book), "the save dialog", timeout=20)
    time.sleep(1.5)  # A focus request made too early would have reached the list by now.
    state: dict[str, object] = {
        "dialog_kept": native_dialog(book),
        "list_focus_during": bool(book.tree.hasFocus()),
    }
    book.lab.screenshot(shot)
    book.lab.input.tap(answer, pause=0.5)
    wait_until(lambda: not native_dialog(book), "the dialog to close", timeout=20)
    state["list_focus_after"] = wait_for_list_focus(book)
    state["view_kept"] = (book.selection(), book.active(), book.calc_tabs()) == view_before
    assert state == {
        "dialog_kept": True,
        "list_focus_during": False,
        "list_focus_after": True,
        "view_kept": True,
    }, state
    return state


def check_save_prompts_keep_focus(lab):
    """Save As cancelled with Escape, and a write error, both from the list (#23)."""
    names = ["Alfa", "Bravo", "Charlie", "Delta"]
    evidence = {}

    unsaved = Workbook(lab, "unsaved", names, stored=False)
    try:
        state = save_with_prompt(unsaved, "Escape", "save-as-cancelled")
        state["still_unsaved"] = not unsaved.document.hasLocation()
        state["typed"] = typing_reaches_list(unsaved, "c", "Charlie")
        evidence["save_as_cancelled"] = state
    finally:
        unsaved.close()

    locked = Workbook(lab, "write-error", names)
    try:
        locked.path.chmod(0o444)
        state = save_with_prompt(locked, "Return", "write-error")
        state["still_modified"] = locked.document.isModified()
        state["typed"] = typing_reaches_list(locked, "c", "Charlie")
        evidence["write_error"] = state
    finally:
        locked.path.chmod(0o644)
        locked.close()

    assert evidence["save_as_cancelled"]["still_unsaved"], evidence
    assert evidence["write_error"]["still_modified"], evidence
    return evidence


def check_single_tap_after_client_pause(book):
    """A paused input client still delivers one Down press on the private display."""
    book.click(1)
    try:
        book.lab.input.key("Control_L", True)
        book.lab.input.key("Down", True)
        time.sleep(1)  # Longer than Xvfb's default repeat delay, as if the client lost its CPU.
    finally:
        book.lab.input.key("Down", False)
        book.lab.input.key("Control_L", False)
    book.lab.input.tap("space", ("Control_L",), pause=0.4)
    evidence = {"selection": book.selection()}
    assert evidence["selection"] == [NAMES[1], NAMES[2]], evidence
    return evidence


def toggle_protection(book, sheet):
    """Protect or unprotect `sheet` and wait for the new data model that shows its label."""
    model = view.root(book.tree)
    if sheet.isProtected():
        sheet.unprotect("")
    else:
        sheet.protect("")
    wait_until(lambda: view.root(book.tree) not in (None, model), "the list to rebuild")


def check_cursor_across_refresh(book):
    """A rebuild keeps the keyboard cursor where it was, not on the first selected row (#29)."""
    foxtrot = book.document.getSheets().getByName(NAMES[5])
    evidence = {}
    for keysym, modifiers in (("space", ("Control_L",)), ("Down", ("Shift_L",))):
        outcomes = []
        for refreshed in (False, True):
            if foxtrot.isProtected():
                toggle_protection(book, foxtrot)
            book.click(1)
            book.lab.input.tap("Down", ("Control_L",))
            book.lab.input.tap("Down", ("Control_L",), pause=0.4)
            if refreshed:
                toggle_protection(book, foxtrot)
                time.sleep(0.4)
            book.lab.input.tap(keysym, modifiers, pause=0.5)
            outcomes.append(book.selection())
        evidence[f"{'+'.join(modifiers)}+{keysym}"] = outcomes
        assert outcomes[0] == outcomes[1], evidence
    assert evidence["Control_L+space"][1] == [NAMES[1], NAMES[3]], evidence
    toggle_protection(book, foxtrot)
    return evidence


def check_native_cursor_positions(book):
    """Native focus events cover edge and page navigation independently of the picks."""
    foxtrot = book.document.getSheets().getByName(NAMES[5])
    evidence = {}
    for key, index in (("End", -1), ("Home", 0)):
        book.click(1)
        book.lab.input.tap(key, ("Control_L",), pause=0.3)
        before = set(book.selection())  # Home/End retain the native control's pick semantics.
        toggle_protection(book, foxtrot)
        book.lab.input.tap("space", ("Control_L",), pause=0.4)
        wanted = [name for name in NAMES if name in before ^ {NAMES[index]}]
        assert book.selection() == wanted
        evidence[key] = wanted
    book.click(1)
    book.lab.input.tap("Next", pause=0.4)
    page = book.selection()
    assert len(page) == 1 and page != [NAMES[1]], page
    toggle_protection(book, foxtrot)
    book.lab.input.tap("space", ("Control_L",), pause=0.4)
    assert book.selection() == []
    evidence["PageDown"] = page
    if foxtrot.isProtected():
        toggle_protection(book, foxtrot)
    return evidence


def check_selected_press_cursor(book):
    """A refused already-selected press restores its picks and a picked keyboard cursor."""
    evidence = {}
    for newer in (False, True):
        reset(book)
        book.click(1)
        book.hold(1)
        try:
            book.document.getSheets().moveByName(NAMES[1], 6)
            wait_until(lambda: view.names(book.tree) == book.order(), "the moved list")
            if newer:
                book.lab.input.tap("d", pause=0.5)
                wait_until(lambda: book.selection() == [NAMES[3]], "the newer typed pick")
        finally:
            book.pointer.release()
        wanted = [NAMES[3] if newer else NAMES[1]]
        wait_until(lambda w=wanted: book.selection() == w, "picks after the refused release")
        book.lab.input.tap("space", ("Control_L",), pause=0.4)
        evidence[str(newer)] = {"picks_restored": wanted, "after_toggle": book.selection()}
        assert book.selection() == [], evidence
    return evidence


def check_other_document(lab, book):
    book.focus_list()
    other = Workbook(lab, "other", ["One", "Two", "Three"])
    try:
        other.controller.select(other.document.getSheets().getByIndex(0).getCellRangeByName("C3"))
        other.window.setFocus()
        time.sleep(0.5)
        lab.input.tap("x")
        lab.input.tap("Return", pause=0.6)
        typed = other.document.getSheets().getByIndex(0).getCellRangeByName("C3").getString()
        other_list_works = True
        other.double_click(1)
        wait_until(lambda: other.active() == "Two", "the second document's list to activate")
    finally:
        other.close()
    book.frame.activate()
    book.window.toFront()
    time.sleep(1)
    book.double_click(3)
    wait_until(lambda: book.active() == NAMES[3], "the first document's list to still work")
    lab.input.tap("q", pause=0.4)
    evidence = {
        "typed_in_other_document": typed,
        "other_list_works": other_list_works,
        "first_list_after_switch": book.selection(),
    }
    assert typed == "x" and book.selection() == ["Quebec"], evidence
    return evidence
