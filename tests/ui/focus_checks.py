"""Keys stay in the list, shortcuts reach Calc, and the focus and keyboard cursor stay put.

Letters, Space, Delete and the other keys typed in the list never edit a cell or modify the
document. Calc's shortcuts still work from the list, and their dialogs keep the focus
while they are open (#23). A refresh keeps the keyboard cursor where it was (#29), and so does a
refused held press (#71). A second document's list works independently of the first.
"""

import time
from typing import Any

import sheet_list_view as view
import uno
import unohelper
from com.sun.star.accessibility import XAccessibleEventListener
from workbook import NAMES, PressProbe, Workbook, native_dialog, reset, wait_until

CURSOR_CHANGED = uno.getConstantByName(
    "com.sun.star.accessibility.AccessibleEventId.ACTIVE_DESCENDANT_CHANGED"
)


class CursorProbe(unohelper.Base, XAccessibleEventListener):
    """Each row the tree's keyboard cursor moves to, as an accessibility client hears it.

    Native focus changes and the list's own writes alike. `heard` holds the arrival time, on
    the same clock as `PressProbe`, and the row's index; a row of a replaced model has none.
    """

    def __init__(self):
        self.heard = []

    def rows(self):
        return [row for _, row in self.heard]

    def notifyEvent(self, event):
        if event.EventId == CURSOR_CHANGED:
            when = time.monotonic()
            try:
                row = event.NewValue.getAccessibleContext().getAccessibleIndexInParent()
            except Exception:  # A row of a replaced model.
                row = None
            self.heard.append((when, row))

    def disposing(self, source):
        pass


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


def check_cursor_across_refresh(book):
    """A refresh keeps the keyboard cursor where it was, not on the first selected row (#29)."""
    foxtrot = book.document.getSheets().getByName(NAMES[5])

    def graphic():
        return view.root(book.tree)

    evidence = {}
    for keysym, modifiers in (("space", ("Control_L",)), ("Down", ("Shift_L",))):
        outcomes = []
        for refreshed in (False, True):
            if foxtrot.TabColor != -1:
                before_model = graphic()
                foxtrot.TabColor = -1
                wait_until(lambda m=before_model: graphic() not in (None, m), "no colour")
            book.click(1)
            book.lab.input.tap("Down", ("Control_L",))
            book.lab.input.tap("Down", ("Control_L",), pause=0.4)
            if refreshed:
                plain = graphic()
                foxtrot.TabColor = 0x3FAF46
                wait_until(lambda p=plain: graphic() != p, "the list to rebuild")
                time.sleep(0.4)
            book.lab.input.tap(keysym, modifiers, pause=0.5)
            outcomes.append(book.selection())
        evidence[f"{'+'.join(modifiers)}+{keysym}"] = outcomes
        assert outcomes[0] == outcomes[1], evidence
    assert evidence["Control_L+space"][1] == [NAMES[1], NAMES[3]], evidence
    foxtrot.TabColor = -1
    return evidence


def check_native_cursor_positions(book):
    """Native focus events cover edge and page navigation independently of the picks."""
    foxtrot = book.document.getSheets().getByName(NAMES[5])

    def rebuild():
        graphic = view.root(book.tree)
        foxtrot.TabColor = 0x668833 if foxtrot.TabColor == 0x3FAF46 else 0x3FAF46
        wait_until(lambda: view.root(book.tree) not in (None, graphic), "the new list model")

    evidence = {}
    for key, index in (("End", -1), ("Home", 0)):
        book.click(1)
        book.lab.input.tap(key, ("Control_L",), pause=0.3)
        before = set(book.selection())  # Home/End retain the native control's pick semantics.
        rebuild()
        book.lab.input.tap("space", ("Control_L",), pause=0.4)
        wanted = [name for name in NAMES if name in before ^ {NAMES[index]}]
        assert book.selection() == wanted
        evidence[key] = wanted
    book.click(1)
    book.lab.input.tap("Next", pause=0.4)
    page = book.selection()
    assert len(page) == 1 and page != [NAMES[1]], page
    rebuild()
    book.lab.input.tap("space", ("Control_L",), pause=0.4)
    assert book.selection() == []
    evidence["PageDown"] = page
    foxtrot.TabColor = -1
    return evidence


REFUSED_HOLDS = ("pressed", "typed", "unpicked", "other_pick", "repeat", "renamed")
RENAMED = f"{NAMES[7]} 2"  # Hotel's name in the `renamed` case, until the case puts it back.


def _refused_hold(book, case, probe, press, marks) -> dict[str, Any]:
    """Hold Bravo while a refresh moves it away, give the case's input, and release over its row.

    Returns what `_verdict` judges: the picks before the hold, the order after the case's
    changes, the picks the release must restore, the cursor row `probe` last heard before the
    button went up, and the rows it heard after that, split at the moment `press` heard the
    release.

    The list starts at its top. An earlier check can leave it scrolled down by a row; the
    rebuild then keeps Bravo at the top, under the pointer, and the release lands on the
    pressed sheet's new row instead of Charlie, so no case observes the late release (measured
    in the full suite after `native_cursor_positions`, 26.2.1.2 gtk3). Each step waits for the
    event it follows, never for a count of events taken earlier, so that nothing heard before
    the button went up can stand for the release or the list's answer to it. `marks` receives
    when the moved rows were read and when the button went up.
    """
    book.tree.makeNodeVisible(book.nodes()[0])
    wait_until(lambda: book.first_visible() == 0, "the list at its top")
    if case == "renamed":
        book.click(0)
        book.click(1, modifiers=("Control_L",))
    else:
        book.click(1)
        if case == "other_pick":
            book.click(3, modifiers=("Control_L",))
    picked = book.selection()
    book.hold(1, press)
    try:
        book.document.getSheets().moveByName(NAMES[1], 6)
        wait_until(lambda: view.names(book.tree) == book.order(), "the moved list")
        marks.append((time.monotonic(), "moved rows read"))
        order = book.order()
        bravo = order.index(NAMES[1])
        # The refresh puts the list's cursor back on Bravo's new row. Let it finish and hear
        # that, so that nothing from before the hold's own input counts.
        view.on_main_thread(book.lab.context, lambda: None)
        wait_until(lambda: probe.rows()[-1:] == [bravo], "the cursor on the moved sheet")
        wanted = [name for name in order if name in picked]
        if case == "typed":
            book.lab.input.tap("d", pause=0.5)
            wanted = [NAMES[3]]
            wait_until(lambda: book.selection() == wanted, "the newer typed pick")
        elif case == "unpicked":
            book.lab.input.tap("Down", ("Control_L",), pause=0.5)
        elif case == "other_pick":
            for _ in range(4):
                book.lab.input.tap("Up", ("Control_L",), pause=0.2)
            time.sleep(0.3)
        elif case == "repeat":
            book.lab.input.repeat("Down", ("Control_L",))
        elif case == "renamed":
            # Ctrl+Down takes the cursor to Hotel, and Hotel's rename then drops that cursor
            # in a refresh while Bravo is still held.
            book.lab.input.tap("Down", ("Control_L",), pause=0.5)
            book.document.getSheets().getByName(NAMES[7]).setName(RENAMED)
            wait_until(lambda: view.names(book.tree) == book.order(), "the renamed list")
            order = book.order()
        # Whatever the input queued has run; the cursor heard last is the one the button-up
        # finds, and everything heard from here on comes after it.
        view.on_main_thread(book.lab.context, lambda: None)
        heard, rows = len(press.heard), len(probe.heard)
        held = probe.rows()[-1] if rows else None
        injected = time.monotonic()
    finally:
        book.pointer.release()
    marks.append((injected, "button up"))
    wait_until(
        lambda: "released" in [kind for kind, _ in press.heard[heard:]],
        "the tree's listeners to hear the release",
    )
    # The list's listener runs after the probe's, in the same posted callback.
    view.on_main_thread(book.lab.context, lambda: None)
    released = next(when for kind, when in press.heard[heard:] if kind == "released")
    later = [(when, row) for when, row in probe.heard[rows:] if when >= injected]
    return {
        "setup": picked,
        "order": order,
        "wanted": wanted,
        "held": held,
        "between": [row for when, row in later if when < released],
        "after": [row for when, row in later if when >= released],
    }


def _verdict(case, seen):
    """The cursor a refused hold must keep, and every way `seen` fails to show the case.

    `seen` is `_refused_hold`'s record with the picks after the release (`restored`) and after
    Ctrl+Space (`toggled`). A case shows something only if it set up the picks it names, the
    keys left the cursor on the case's row before the button went up, and the native release
    moved the tree's cursor to the pressed row, Charlie's now, after the button went up and
    before the tree's mouse listeners heard it. The server's timed repeat is judged by where
    the cursor was when the button went up, never by how often it repeated.
    """
    order, held = seen["order"], seen["held"]
    bravo = order.index(NAMES[1])
    cursor = {
        "pressed": NAMES[1],
        "typed": NAMES[3],
        "unpicked": order[bravo + 1],
        "other_pick": NAMES[3],
        "repeat": order[held] if held is not None and 0 <= held < len(order) else None,
        "renamed": NAMES[1],  # Hotel's ref is gone: the pressed pick takes the cursor.
    }[case]
    setup = {"other_pick": [NAMES[1], NAMES[3]], "renamed": [NAMES[0], NAMES[1]]}
    row = order.index(cursor) if cursor in order else None
    problems = []
    if seen["setup"] != setup.get(case, [NAMES[1]]):
        problems.append("the picks before the hold were not the case's")
    if row is None or held != row:
        problems.append("the cursor was not on the case's row when the button went up")
    if seen["between"][-1:] != [1]:
        problems.append("the release did not reach the pressed row after the button went up")
    if case == "repeat" and (row is None or row <= bravo + 2):
        problems.append("the server did not repeat Down")
    if seen["restored"] != seen["wanted"]:
        problems.append("the picks were not restored")
    if seen["after"][-1:] != [row]:
        problems.append("the tree's cursor was not put back on the list's")
    if seen["toggled"] != [name for name in order if name in set(seen["wanted"]) ^ {cursor}]:
        problems.append("Ctrl+Space toggled another row")
    return cursor, problems


def _undo_rename(book):
    """Give Hotel its name back after the `renamed` case, so that `reset` finds every sheet."""
    sheets = book.document.getSheets()
    if sheets.hasByName(RENAMED):
        sheets.getByName(RENAMED).setName(NAMES[7])


def _timeline(probe, press, marks, started):
    """Cursor rows, the tree's mouse listeners and `marks` in time order, from `started`.

    Cursor events name row indices, not sheets: the rows show the original order until the
    move is read, and the case's `order` after it.
    """
    events = [
        (when, f"row {row}" if row is not None else "row of a replaced model")
        for when, row in list(probe.heard)
    ]
    events += [(when, f"heard {kind}") for kind, when in list(press.heard)]
    events += marks
    events.sort(key=lambda event: event[0])
    return [[round(when - started, 3), what] for when, what in events if when >= started]


def check_selected_press_cursor(book):
    """A refused already-selected press restores its picks and the list's own keyboard cursor.

    Bravo is picked, pressed again and held while a refresh moves it away, and the button is
    released over the row it left, which then shows Charlie. The tree's native release moves
    its cursor to that row before the tree's mouse listeners hear the release; each case must
    hear that move after the button went up, from a cursor its own input left elsewhere, or it
    proves nothing (`_verdict`). The list then puts back its own cursor: Bravo's, a newer typed
    pick's, or wherever the keyboard took it during the hold, also outside the picks and with
    the X server's own timed repeat (#71). When a refresh during the hold drops that cursor, as
    a rename of its sheet does, the pressed sheet takes it. Ctrl+Space then toggles exactly the
    row the cursor is on. Every case runs before the check fails, so that one run shows which
    of them a change breaks; a gesture that cannot be made fails at once.
    """
    accessible = book.tree.getProperty("XAccessible").getAccessibleContext()
    probe, press, marks = CursorProbe(), PressProbe(), []
    view.on_main_thread(book.lab.context, lambda: accessible.addAccessibleEventListener(probe))
    book.tree.addMouseListener(press)
    evidence, failed = {}, {}
    try:
        for case in REFUSED_HOLDS:
            reset(book)
            started = time.monotonic()
            try:
                try:
                    seen = _refused_hold(book, case, probe, press, marks)
                except AssertionError as error:
                    evidence[case] = {"timeline": _timeline(probe, press, marks, started)}
                    raise AssertionError({case: str(error), "evidence": evidence}) from error
                seen["restored"] = book.selection()
                book.lab.input.tap("space", ("Control_L",), pause=0.4)
                seen["toggled"] = book.selection()
            finally:
                _undo_rename(book)
            cursor, problems = _verdict(case, seen)
            evidence[case] = {
                "cursor": cursor,
                "picks_before_hold": seen["setup"],
                "picks": seen["wanted"],
                "row_at_button_up": seen["held"],
                "restored": seen["restored"],
                "after_toggle": seen["toggled"],
                "rows_after_move": seen["order"][:12],
                "timeline": _timeline(probe, press, marks, started),
            }
            if problems:
                failed[case] = problems
    finally:
        book.tree.removeMouseListener(press)
        view.on_main_thread(
            book.lab.context, lambda: accessible.removeAccessibleEventListener(probe)
        )
    evidence["failed"] = failed
    assert not failed, evidence
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
