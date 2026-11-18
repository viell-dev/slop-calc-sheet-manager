"""Real clicks and tab-bar input: picks, activation, the accessible name and the list's notices.

Clicking a row picks it without changing Calc's viewed sheet or grouped tabs; double-click
activates it and ends grouped editing (#25). Calc's own tab changes, including real Ctrl+clicks on
the native tab bar, are followed without rebuilding the rows. The list's accessible name follows
the viewed sheet, never the picks (#83); a press in the panel's margins never undocks the sidebar
(#133); and the selection notice expires without moving the focus (#90).
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

    # Click a cell of the sheet, as a user does, and type there. In CI with gen under gdb, Calc
    # once moved the cell cursor more than 0.6 s after the click and once not within ten seconds;
    # locally it moved within 0.15 s in 15 of 15 attempts. This check is about where the typing
    # goes, so a click that has not arrived after five seconds is repeated once, and the evidence
    # says so.
    before = cursor()
    screen = Pointer(book.lab.input, (0, 0))
    attempts = 0
    while True:
        attempts += 1
        screen.click(260, 420, pause=0)
        try:
            wait_until(lambda: cursor() != before, "the click to move the cell cursor", 5)
            break
        except AssertionError:
            if attempts == 2:
                raise
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
        "click_attempts": attempts,
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
