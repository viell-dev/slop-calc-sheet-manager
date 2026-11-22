"""Real clicks and tab-bar input: picks, activation, the accessible name and the list's notices.

Clicking a row picks it without changing Calc's viewed sheet or grouped tabs; double-click
activates it and ends grouped editing (#25). Calc's own tab changes, including real Ctrl+clicks on
the native tab bar, are followed without rebuilding the rows. The list's accessible name follows
the viewed sheet, never the picks (#83); a press in the panel's margins never undocks the sidebar
(#133); and the selection notice expires without moving the focus (#90). Clicks after the wheel
or a key scrolled the list act on the rows they land on (#299).
"""

import time

import sheet_list_view as view
import uno
from workbook import NAMES, wait_until
from xinput import Pointer

from sheet_manager.sheet_list import list_name
from sheet_manager.uno_calc import select_tabs


def check_click_activates(book):
    before = book.active(), book.calc_tabs()
    evidence = []
    for index, x in ((1, 5), (2, 20), (3, 50), (4, book.tree.getOutputSize().Width - 24)):
        rect = view.row_rect(book.tree, index)
        book.pointer.click(x, rect.Y + rect.Height // 2)
        wait_until(lambda i=index: book.selection() == [NAMES[i]], "full-row selection")
        assert (book.active(), book.calc_tabs()) == before
        evidence.append({"x": x, "picks": book.selection()})
    book.double_click(4)
    wait_until(lambda: book.active() == NAMES[4], "double-click activation")
    assert book.selection() == [NAMES[4]]
    assert book.labels()[4] == NAMES[4]
    return {"single_clicks": evidence, "double_click_active": book.active()}


def check_clicks_after_scrolls(book):
    """Clicks after the wheel or a key scrolled the list act on the rows they land on.

    A press made before such a scroll would map to another row, so the list holds presses while
    the rows may have moved (#299): a key's write that scrolls, and a paint that shows the rows at
    a new position, hold every row until work posted after them has run. A click made once the
    scrolled rows are painted must still act; a refused one picks nothing. The pointer helper
    waits 0.4 s after the wheel and the tap 0.6 s after End, so this shows that the paint and the
    write note the position, not how soon they do.
    """
    tree = book.tree
    tree.makeNodeVisible(book.nodes()[0])
    time.sleep(0.3)
    first = book.first_visible()
    x, y = view.row_point(tree, first + 2, scroll=False)
    book.pointer.wheel(x, y, down=True, ticks=4)
    wheeled = book.first_visible()
    clicked = wheeled + 1
    book.pointer.click(*view.row_point(tree, clicked, scroll=False))
    wait_until(lambda: book.selection() == [NAMES[clicked]], "the click after the wheel")
    book.pointer.wheel(x, y, down=True, ticks=3)
    again = book.first_visible()
    activated = again + 2
    point = view.row_point(tree, activated, scroll=False)
    book.pointer.click(*point, pause=0.02)
    book.pointer.click(*point)
    wait_until(lambda: book.active() == NAMES[activated], "the double click after the wheel")
    book.lab.input.tap("End", pause=0.6)
    wait_until(lambda: book.selection() == [NAMES[-1]], "End's write")
    bottom = book.first_visible()
    keyed = bottom + 1
    book.pointer.click(*view.row_point(tree, keyed, scroll=False))
    wait_until(lambda: book.selection() == [NAMES[keyed]], "the click after End")
    evidence = {
        "first_visible": [first, wheeled, again, bottom],
        "clicked_after_wheel": NAMES[clicked],
        "activated_after_wheel": book.active(),
        "clicked_after_end": book.selection(),
    }
    assert wheeled > first and again > wheeled and bottom > again, evidence
    tree.makeNodeVisible(book.nodes()[0])
    return evidence


def check_viewed_sheet_name(book):
    """The list's accessible name follows the sheet Calc shows, never the picks (#83).

    Real input picks a row, runs Calc's next-sheet command from the list, activates a row and
    moves through the real menu; a property change rebuilds the rows in between. This reads the
    same metadata as the integration suite, in a painted session; no screen reader runs.
    """

    def name():
        return book.tree.getProperty("XAccessible").getAccessibleContext().getAccessibleName()

    names = {}
    wait_until(lambda: name() == list_name(NAMES[0]), "the name of the viewed sheet")
    book.click(3)
    wait_until(lambda: book.selection() == [NAMES[3]], "a click to pick Delta")
    names["picked_elsewhere"] = name()
    assert names["picked_elsewhere"] == list_name(NAMES[0]), names
    book.lab.input.tap("Next", ("Control_L",), pause=0.6)  # Calc's next-sheet command.
    wait_until(lambda: book.active() == NAMES[1], "Ctrl+Page Down to show Bravo")
    wait_until(lambda: name() == list_name(NAMES[1]), "the name to follow Calc")
    book.document.getSheets().getByName(NAMES[9]).IsVisible = False
    wait_until(lambda: f"{NAMES[9]} (hidden)" in book.labels(), "a refresh that rebuilds the rows")
    names["after_rebuild"] = name()
    assert names["after_rebuild"] == list_name(NAMES[1]), names
    book.double_click(4)
    wait_until(lambda: book.active() == NAMES[4], "double-click activation")
    wait_until(lambda: name() == list_name(NAMES[4]), "the name after the list's activation")
    book.click(0)
    wait_until(lambda: book.selection() == [NAMES[0]], "a click to pick Alfa")
    book.move_action("down")
    wait_until(lambda: book.order()[:2] == [NAMES[1], NAMES[0]], "the menu's move")
    names["after_menu"] = name()
    assert names["after_menu"] == list_name(NAMES[4]) and book.active() == NAMES[4], names
    return names


def check_margin_drag_keeps_sidebar_docked(book):
    """A real press in the panel's empty margins, dragged away, leaves the sidebar docked (#133).

    The list's controls lie over a disabled backdrop that swallows the press. With an enabled
    plain window there, the same drag undocks the sidebar with the `win` interface; gtk3's
    embedded sidebar does not undock either way. The picks stay as they were.
    """
    toolkit = book.lab.context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", book.lab.context
    )
    panel = book.panel.getProperty("XAccessible").getAccessibleContext()
    tree = book.tree.getPosSize()  # In the panel's coordinates; the pointer uses the tree's.
    buttons = view.move_buttons(book.panel)
    top, up = buttons["Top"].getPosSize(), buttons["Up"].getPosSize()
    starts = {
        "left of the list": (1 - tree.X, 60),
        "between buttons": (
            (top.X + top.Width + up.X) // 2 - tree.X,
            top.Y + top.Height // 2 - tree.Y,
        ),
    }
    book.click(2)
    wait_until(lambda: book.selection() == [NAMES[2]], "a click to pick Charlie")
    evidence = {}
    for name, start in starts.items():
        location = panel.getLocationOnScreen()
        before = (location.X, location.Y, toolkit.getTopWindowCount())
        book.pointer.press(*start)
        book.pointer.glide(start, (start[0] - 300, start[1] + 90))
        book.pointer.release()
        time.sleep(1.0)
        location = panel.getLocationOnScreen()
        after = (location.X, location.Y, toolkit.getTopWindowCount())
        evidence[name] = {"start": start, "before": before, "after": after}
        assert after == before, f"A drag from the panel's margin moved the sidebar: {evidence}"
    assert book.selection() == [NAMES[2]], book.selection()
    return evidence


def check_ctrl_shift_selection(book):
    book.double_click(1)
    wait_until(lambda: book.active() == NAMES[1], "double-click activation")
    book.click(3, modifiers=("Control_L",))
    wait_until(lambda: len(book.selection()) == 2, "Ctrl+click to add a row")
    ctrl = book.selection()
    book.click(5, modifiers=("Shift_L",))
    wait_until(lambda: len(book.selection()) == 3, "Shift+click to select a range")
    shift = book.selection()
    evidence = {
        "ctrl": ctrl,
        "shift": shift,
        "active": book.active(),
        "calc_tabs": book.calc_tabs(),
    }
    assert ctrl == [NAMES[1], NAMES[3]], evidence
    assert shift == NAMES[3:6], evidence
    # The list's own selection: Calc's tabs are not grouped and the active sheet stays.
    assert book.active() == NAMES[1] and book.calc_tabs() == [NAMES[1]], evidence
    return evidence


def check_plain_click_ends_group(book):
    """Activation leaves one selected tab; subsequent typing edits only that sheet (#25)."""
    book.click(1)
    book.click(3, modifiers=("Control_L",))
    wait_until(lambda: book.selection() == [NAMES[1], NAMES[3]], "Bravo and Delta selected")
    tabs = book.calc_tabs()
    book.lab.input.tap("Menu", pause=0.8)
    book.lab.input.tap("Escape", pause=0.5)
    assert book.calc_tabs() == tabs, "The menu grouped tabs without running a command"
    # A command can leave its targets grouped, as Calc's tab menu does. Group them natively.
    select_tabs(book.lab.context, book.frame, [1, 3])
    book.double_click(1)
    wait_until(lambda: book.calc_tabs() == [NAMES[1]], "activation to leave one selected tab")

    def cursor():
        address = book.controller.getSelection().getRangeAddress()
        return (address.Sheet, address.StartColumn, address.StartRow)

    # Click a cell of the sheet, as a user does, and type there. In October 2026 CI with gen
    # under gdb, Calc once moved the cell cursor more than 0.6 s after the click and once not
    # within ten seconds (#42). The repeat added then, after five seconds, never ran in any
    # retained CI artifact from 2026-10-19 to 2026-11-17 (205 gen and 229 gtk3 sessions), so it
    # only hid a recurrence. One click must move the cursor within five seconds; a failure keeps
    # watching, without further input, to record whether the click arrived late or not at all.
    before = cursor()
    screen = Pointer(book.lab.input, (0, 0))
    sent = time.monotonic()
    screen.click(260, 420, pause=0)
    try:
        wait_until(lambda: cursor() != before, "the click to move the cell cursor", 5)
    except AssertionError as error:
        try:  # Classification only: a failed read must not replace the original assertion.
            arrival = None
            deadline = time.monotonic() + 10
            while arrival is None and time.monotonic() < deadline:
                if cursor() != before:
                    arrival = round(time.monotonic() - sent, 2)
                time.sleep(0.1)
            error.add_note(
                f"Cell cursor before the click {before!r}, now {cursor()!r}, tabs "
                f"{book.calc_tabs()!r}; "
                + (
                    f"the click arrived late, {arrival} s after it was sent"
                    if arrival is not None
                    else "the click had not arrived 15 s after it was sent"
                )
            )
        except Exception as diagnostic_error:
            error.add_note(f"Click diagnostics failed: {diagnostic_error!r}")
        raise
    click_seconds = round(time.monotonic() - sent, 3)
    address = book.controller.getSelection().getRangeAddress()
    book.lab.input.tap("x")
    book.lab.input.tap("Return", pause=0.6)
    sheets = book.document.getSheets()

    def cell(name):
        sheet = sheets.getByName(name)
        return sheet.getCellByPosition(address.StartColumn, address.StartRow).getString()

    evidence = {
        "tabs": book.calc_tabs(),
        "cell": [address.Sheet, address.StartColumn, address.StartRow],
        "bravo": cell(NAMES[1]),
        "delta": cell(NAMES[3]),
        "click_seconds": click_seconds,
    }
    assert address.Sheet == 1 and evidence["bravo"] == "x" and evidence["delta"] == "", evidence
    sheets.getByName(NAMES[1]).getCellByPosition(address.StartColumn, address.StartRow).setString(
        ""
    )
    return evidence


def check_tab_selection_sync(book):
    book.click(0)
    before = view.root(book.tree)
    started = time.monotonic()
    select_tabs(book.lab.context, book.frame, [0, 2])
    wait_until(lambda: book.selection() == ["Alfa", "Charlie"], "a same-active tab change")
    elapsed = time.monotonic() - started
    assert book.active() == "Alfa"
    assert view.root(book.tree) == before, "Selection-only following rebuilt the rows"
    field = view.footer_text(book.panel, "Cell edits affect")
    assert field.getText() == "Edits affect 2 Calc tabs: Alfa, Charlie"
    accessible = field.getProperty("XAccessible").getAccessibleContext()
    assert "Alfa" in accessible.getAccessibleName() and "Charlie" in accessible.getAccessibleName()
    book.click(1, ("Control_L",))
    wanted = ["Alfa", "Bravo", "Charlie"]
    wait_until(lambda: book.selection() == wanted, "independent list picks")
    time.sleep(0.6)
    assert book.selection() == wanted and book.calc_tabs() == ["Alfa", "Charlie"]

    # Exercise the actual tab bar too. Do not traverse a grid's enormous accessible table.
    page_tab = uno.getConstantByName("com.sun.star.accessibility.AccessibleRole.PAGE_TAB")
    skip = {
        uno.getConstantByName("com.sun.star.accessibility.AccessibleRole." + name)
        for name in ("TABLE", "MENU_BAR", "MENU", "TOOL_BAR")
    }
    pending = [book.window.getProperty("XAccessible").getAccessibleContext()]
    target = None
    for _ in range(400):
        if not pending:
            break
        context = pending.pop(0)
        role = context.getAccessibleRole()
        if role == page_tab and context.getAccessibleName() == "Delta":
            target = context
            break
        if role not in skip:
            pending.extend(
                context.getAccessibleChild(index).getAccessibleContext()
                for index in range(min(context.getAccessibleChildCount(), 100))
            )
    assert target is not None, "The native Delta sheet tab was not accessible"
    point, size = target.getLocationOnScreen(), target.getSize()
    assert size.Width > 0 and size.Height > 0
    previous_active = book.active()
    book.lab.input.move(point.X + size.Width // 2, point.Y + size.Height // 2)
    book.lab.input.key("Control_L", True)
    book.lab.input.button(1, True)
    book.lab.input.button(1, False)
    book.lab.input.key("Control_L", False)
    wait_until(lambda: "Delta" in book.calc_tabs(), "Ctrl+click on the native tab")
    wait_until(lambda: book.selection() == book.calc_tabs(), "following real tab-bar input")
    return {
        "same_active_seconds": round(elapsed, 4),
        "same_model": True,
        "independent_picks": wanted,
        "native_tab_click": {"before_active": previous_active, "active": book.active()},
        "native_group": book.calc_tabs(),
    }


def check_ctrl_clicks_after_a_ctrl_shift_range(book):
    """Ctrl+clicks after a real Ctrl+Shift+click toggle their rows, and a quick triple Ctrl+click
    toggles its row three times (#294, #310's review).

    After a Ctrl+Shift+click, VCL's selection engine stays in add mode until a plain or Shift
    click, and a Ctrl+click on an unselected row then only moves the tree's cursor: it selects
    nothing (measured with 26.8.2.2 on gtk3 and gen). The second and third presses of a quick
    triple click change nothing either, since the engine handles only a click count of 1. The
    list counts the tree's changes that it did not make, and must expect no change from these
    presses: before that, it refused each of them and cleared the selection.
    """
    evidence = {}
    book.click(0)
    wait_until(lambda: book.selection() == [NAMES[0]], "a click to pick Alfa")
    book.click(2, modifiers=("Control_L", "Shift_L"))
    wait_until(lambda: book.selection() == NAMES[:3], "a Ctrl+Shift+click range to Charlie")
    book.click(4, modifiers=("Control_L",))
    wait_until(lambda: book.selection() == [*NAMES[:3], NAMES[4]], "a Ctrl+click adding Echo")
    evidence["unselected_in_add_mode"] = book.selection()
    book.click(1, modifiers=("Control_L",))
    wait_until(lambda: book.selection() == [NAMES[0], NAMES[2], NAMES[4]], "Bravo toggled off")
    evidence["selected_in_add_mode"] = book.selection()
    book.click(3)
    wait_until(lambda: book.selection() == [NAMES[3]], "a plain click on Delta")
    book.click(5, modifiers=("Control_L",))
    wait_until(lambda: book.selection() == [NAMES[3], NAMES[5]], "a Ctrl+click adding Foxtrot")
    evidence["after_a_plain_click"] = book.selection()
    point = book.point(6)
    for _ in range(3):
        book.pointer.click(*point, modifiers=("Control_L",), pause=0.02)
    time.sleep(1)
    evidence["triple_ctrl_click"] = book.selection()
    assert evidence["triple_ctrl_click"] == [NAMES[3], NAMES[5], NAMES[6]], evidence
    return evidence


ASSISTIVE_ATTEMPTS = 6


def check_assistive_selection_then_ctrl_input(book):
    """A selection made through accessibility, followed at once by a real Ctrl+click on its row
    or Ctrl+Space with the cursor there, never picks the row the user meant to deselect (#294).

    Alfa is picked by a click; Bravo is then selected through the tree's `XAccessibleSelection`,
    from this process as a remote assistive client selects a row, which LibreOffice runs on a
    bridge thread, and real input follows without waiting for the list's intake, which takes such
    a selection at its next tab sample. Before the fix, the list toggled Bravo against picks that
    lacked it in 7 of 8 such runs of the click (#294's measurement). A selection made through a
    main-thread callback from here holds the main thread long enough for a tab sample to queue,
    and the intake then took it first in every attempt. Each attempt either finds the selection
    the list has not taken and refuses, clearing the tree with the notice, or meets an intake that
    took Bravo first and toggles it off; it records which.
    """
    context = book.tree.getProperty("XAccessible").getAccessibleContext()
    notice = view.footer_text(book.panel, "Why the sheet list")
    outcomes = {"ctrl_click": [], "ctrl_space": []}
    for kind in ("ctrl_click", "ctrl_space"):
        for _ in range(ASSISTIVE_ATTEMPTS):
            book.click(0)
            wait_until(lambda: book.selection() == [NAMES[0]], "a click to pick Alfa")
            if kind == "ctrl_space":
                book.lab.input.tap("Down", modifiers=("Control_L",))  # The cursor to Bravo.
            time.sleep(0.6)  # The list's write and a tab sample have run.
            context.selectAccessibleChild(1)  # Bravo, on a bridge thread in the office.
            if kind == "ctrl_click":
                book.click(1, modifiers=("Control_L",))
            else:
                book.lab.input.tap("space", modifiers=("Control_L",))
            time.sleep(1.5)  # The listener, the write and several tab samples have run.
            shown = book.selection()
            assert NAMES[1] not in shown, f"{kind}: the list picked Bravo, deselected: {shown}"
            assert shown in ([], [NAMES[0]]), f"{kind}: {shown}"
            if shown:
                outcomes[kind].append("intake first")
            else:
                assert notice.getText().startswith("Selection cleared"), notice.getText()
                outcomes[kind].append("refused")
    wait_until(lambda: not notice.getText(), "notice expiration", timeout=14)
    return outcomes


def check_selection_notice(book):
    """Real Ctrl+Z creates a bounded notice without moving focus into a cell (#90).

    The move undone is Calc's own, made through the API: an Undo of the list's own move keeps
    the picks (#91, `undo_own_move`)."""
    before = book.order()
    book.click(2)
    book.click(5, modifiers=("Control_L",))
    wait_until(lambda: book.selection() == [NAMES[2], NAMES[5]], "independent picks")
    book.document.getSheets().moveByName(NAMES[7], 0)
    wait_until(lambda: book.order() != before, "move before Undo")
    time.sleep(1)
    assert book.selection() == [NAMES[2], NAMES[5]] and book.tree.hasFocus()
    book.lab.input.tap("z", modifiers=("Control_L",), pause=0.2)
    wait_until(lambda: book.order() == before, "Ctrl+Z restoring order")
    notice = view.footer_text(book.panel, "Why the sheet list")
    wait_until(lambda: notice.getText().startswith("Selection cleared"), "the panel notice")
    started = time.monotonic()
    assert not book.controller.hasInfobar("dev.viell.sheetmanager.selection-cleared")
    origin = book.tree.getPosSize().Y

    # Grouping is a distinct persistent warning; newer independent picks survive expiration.
    select_tabs(book.lab.context, book.frame, [0, 1])
    group = view.footer_text(book.panel, "Cell edits affect")
    wait_until(lambda: group.getText() == "Edits affect 2 Calc tabs: Alfa, Bravo", "group warning")
    book.click(3)
    wait_until(lambda: book.selection() == [NAMES[3]], "newer independent pick")
    assert book.tree.hasFocus()
    state = book.active(), book.calc_tabs(), book.selection()
    content = [book.document.Sheets.getByName(n).getCellRangeByName("A1").String for n in before]
    time.sleep(1)
    assert notice.getText() and notice.isVisible()
    book.lab.screenshot("selection-notice")
    wait_until(lambda: not notice.getText(), "notice expiration", timeout=14)
    elapsed = time.monotonic() - started
    assert 9 <= elapsed <= 14, elapsed
    assert not notice.isVisible() and notice.getPosSize().Height == 0
    assert book.tree.hasFocus(), "Expiring the notice moved focus out of the list"
    assert (book.active(), book.calc_tabs(), book.selection()) == state
    assert origin == book.tree.getPosSize().Y
    assert group.isVisible() and group.getText() == "Edits affect 2 Calc tabs: Alfa, Bravo"
    book.lab.input.tap("d")
    assert [
        book.document.Sheets.getByName(n).getCellRangeByName("A1").String for n in before
    ] == content
    return {"expired_seconds": round(elapsed, 2), "focus_kept": True, "group_warning_kept": True}
