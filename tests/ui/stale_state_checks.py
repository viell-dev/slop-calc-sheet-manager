"""The list never acts on stale state (AGENTS.md's fifth safety invariant, #28).

A press, drag or pick made before its sheet was replaced, moved, inserted or deleted, or changed
by a batch with undo recording off, acts on nothing, and actions are refused while a batch's lock
is held. A sheet hidden just before its row is clicked is not activated (#43), newer picks survive
a repaint (#44), saving keeps the picks, and real input reaches the replacement panel after
Reload (#88).
"""

import json
import threading
import time
import traceback
from contextlib import contextmanager

import sheet_list_view as view
import uno
import unohelper
from com.sun.star.awt import XMouseListener
from menu_checks import hide_through_menu
from workbook import NAMES, PressProbe, reset, wait_until
from xinput import Pointer

from sheet_manager.uno_calc import dispatch, select_tabs

PUSH_BUTTON = uno.getConstantByName("com.sun.star.accessibility.AccessibleRole.PUSH_BUTTON")
unrecorded = view.unrecorded_batch


def check_reload_accepts_real_input(book):
    """Calibrated X input must reach the replacement panel after native Reload (#88)."""
    book.document.store()
    old = book.controller
    dispatch(book.lab.context, book.frame, ".uno:Reload")
    wait_until(lambda: book.frame.getController() != old, "a replacement controller after reload")
    book.controller = book.frame.getController()
    book.document = book.controller.getModel()
    book.panel, book.tree = view.open_list(book.lab.context, book.document)
    wait_until(lambda: view.names(book.tree) == NAMES, "the reloaded native rows")
    book.pointer = Pointer(book.lab.input, book.lab.calibrate(book.tree, book.window))
    before = book.active(), book.calc_tabs()
    book.click(1)
    wait_until(lambda: book.selection() == [NAMES[1]], "a real click after reload")
    assert (book.active(), book.calc_tabs()) == before
    book.double_click(1)
    wait_until(lambda: book.active() == NAMES[1], "real activation after reload")
    select_tabs(book.lab.context, book.frame, [1, 3])
    wait_until(lambda: book.selection() == [NAMES[1], NAMES[3]], "the replacement tab observer")
    return {"real_click": True, "activation": True, "replacement_observer": True}


def close_message(book):
    """Close the list's message box; True once it is gone.

    Return closes it, as a user does. In local gen sessions, Return sometimes never reached a
    box opened after a refused drop, with the code before and after #28's round 8 alike; the
    box's OK button is then pressed through accessibility instead. Only the result of the drop
    is under test here.
    """
    toolkit = book.lab.context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", book.lab.context
    )

    def boxes():
        windows = [toolkit.getTopWindow(i) for i in range(toolkit.getTopWindowCount())]
        kinds = "com.sun.star.awt.XMessageBox"
        return [w for w in windows if kinds in [kind.typeName for kind in w.getTypes()]]

    def press_button(context):
        if context.getAccessibleRole() == PUSH_BUTTON:
            context.doAccessibleAction(0)
            return True
        children = range(context.getAccessibleChildCount())
        return any(
            press_button(context.getAccessibleChild(i).getAccessibleContext()) for i in children
        )

    book.lab.input.tap("Return", pause=0.6)
    for _ in range(3):
        found = boxes()
        if not found:
            return True
        press_button(found[0].getProperty("XAccessible").getAccessibleContext())
        time.sleep(0.6)
    return not boxes()


def replace(document, name):
    """Delete a sheet and insert a different one with the same name at the same place."""
    sheets = document.getSheets()
    index = list(sheets.getElementNames()).index(name)
    sheets.removeByName(name)
    sheets.insertNewByName(name, index)
    sheets.getByName(name).getCellRangeByName("A1").setString("replacement")


def check_drop_after_replacement(book):
    """A drop is refused when a sheet was replaced during the drag (#28)."""
    book.click(2)
    before = book.order()
    start = book.point(2)
    end = book.point(10, 0.25)
    book.pointer.press(*start)
    book.pointer.glide(start, (start[0], start[1] + 12))
    book.pointer.glide((start[0], start[1] + 12), end)
    replace(book.document, NAMES[7])
    time.sleep(0.6)
    book.pointer.release()
    time.sleep(1.2)
    book.lab.screenshot("drop-refused")
    closed = close_message(book)  # The refusal message.
    evidence = {"order_unchanged": book.order() == before, "undo": book.undo_titles()}
    assert evidence["order_unchanged"] and "Move Sheets" not in evidence["undo"], evidence
    assert closed, "The refusal message did not close"
    return evidence


@contextmanager
def refresh_waiting(book):
    """Keep changing the last sheet's tab colour, so that the list waits to refresh.

    The list refreshes once changes pause, but at the latest two seconds after the first change
    it has not shown; the steps inside must take well under that. They then meet rows that are
    out of date, as a user can on a slow machine or in a large workbook.
    """
    sheet = book.document.getSheets().getByName(NAMES[-1])
    original = sheet.TabColor
    stop = threading.Event()

    def churn():
        count = 0
        while not stop.is_set():
            sheet.TabColor = (0x2A6099, 0x996633)[count % 2]
            count += 1
            stop.wait(0.05)

    thread = threading.Thread(target=churn, name="refresh-waiting", daemon=True)
    thread.start()
    time.sleep(0.2)
    try:
        yield
    finally:
        stop.set()
        thread.join()
        sheet.TabColor = original


def check_press_then_change(book):
    """A held press has no effect once its sheet was replaced or moved (#28).

    Neither the activation nor the selection that the tree makes on release survives, so the
    sheet tab menu that follows has nothing to act on. It runs after a refused drop, which
    made the tree select the replacement on release before this was fixed.
    """
    evidence = {}
    for change, picked in (("replace", []), ("move", [NAMES[1]])):
        reset(book)
        book.hold(1)
        wait_until(lambda: book.selection() == [NAMES[1]], "the press to select Bravo")
        if change == "replace":
            replace(book.document, NAMES[1])
            wait_until(lambda: book.selection() == [], "the refresh to drop the replaced Bravo")
        else:
            book.document.getSheets().moveByName(NAMES[1], 6)
            wait_until(lambda: view.names(book.tree)[1] == NAMES[2], "the list to show the move")
        book.pointer.release()
        time.sleep(1)
        state = {
            "active": book.active(),
            "calc_tabs": book.calc_tabs(),
            "selection": book.selection(),
        }
        if change == "replace":
            # With no surviving picks, Menu must not open even the stationary outer popup.
            titles = book.undo_titles()
            assert not book.lab.input.popup_windows(), "An earlier popup is still open"
            book.lab.input.tap("Menu", pause=0.8)
            state["popup_opened"] = bool(book.lab.input.popup_windows())
            state["calc_tabs_after_menu_key"] = book.calc_tabs()
            book.lab.input.tap("Escape", pause=0.3)
            state["undo_unchanged"] = book.undo_titles() == titles
        evidence[change] = state
        assert state["active"] == NAMES[0] and state["calc_tabs"] == [NAMES[0]], evidence
        assert state["selection"] == picked, evidence
        if change == "replace":
            assert not state["popup_opened"], evidence
            assert state["calc_tabs_after_menu_key"] == [NAMES[0]], evidence
            assert state["undo_unchanged"], evidence
    return evidence


def check_newer_pick_survives_voided_press(book):
    """A voided press brings back the list's newer pick, never what now sits in its row (#28).

    Two ways to a newer pick while Bravo is held: Calc goes to Delta and the list follows, or
    Bravo is moved away and the user types "d". Then the button is released over the row Bravo
    left. Delta stays picked, and the Menu key's Hide acts on Delta alone.

    Each step records what the list showed, Calc's view, the tree's focus, the held buttons, and
    when the tree's mouse listeners heard the press and release, so that a timeout can be
    classified from the evidence alone (#134).
    """
    sheets = book.document.getSheets()
    evidence = {}
    probe = PressProbe()
    book.tree.addMouseListener(probe)
    try:
        for way in ("calc_switch", "typing"):
            reset(book)
            probe.heard.clear()
            started = time.monotonic()
            steps = []
            # The office's own clock too: CLOCK_MONOTONIC is shared within the container.
            evidence[way] = {"clock": round(started, 3), "steps": steps}

            def step(what, condition=None, started=started, steps=steps):
                failure = None
                if condition is not None:
                    try:
                        wait_until(condition, what)
                    except AssertionError as error:
                        failure = error
                at = time.monotonic() - started  # Before the reads below, which take time.
                steps.append(
                    {
                        "step": what,
                        "at": round(at, 3),
                        "met": failure is None,
                        "selection": book.selection(),
                        "active": book.active(),
                        "calc_tabs": book.calc_tabs(),
                        "tree_focus": book.tree.hasFocus(),
                        "held": sorted(book.lab.input.held),
                        "heard": [(kind, round(when - started, 3)) for kind, when in probe.heard],
                    }
                )
                if failure is not None:
                    raise AssertionError(f"{failure}; evidence: {json.dumps(evidence)}")

            book.hold(1, probe)
            step("the press to select Bravo", lambda: book.selection() == [NAMES[1]])
            if way == "calc_switch":
                book.controller.setActiveSheet(sheets.getByName(NAMES[3]))
                step("Calc to go to Delta")
                step("the list to follow Delta", lambda: book.selection() == [NAMES[3]])
                sheets.moveByName(NAMES[1], 6)
                step("the list to show the move", lambda: view.names(book.tree)[1] == NAMES[2])
            else:
                sheets.moveByName(NAMES[1], 6)
                step("the list to show the move", lambda: view.names(book.tree)[1] == NAMES[2])
                book.lab.input.tap("d", pause=0.5)
                step("typing to pick Delta", lambda: book.selection() == [NAMES[3]])
            time.sleep(1)
            book.pointer.release()
            time.sleep(1)
            step("the release")
            state = evidence[way]
            state.update(selection=book.selection(), active=book.active())
            assert state["selection"] == [NAMES[3]], evidence
            state["menu"] = hide_through_menu(
                book, [NAMES[3]], lambda: book.lab.input.tap("Menu", pause=0.3)
            )
    finally:
        book.tree.removeMouseListener(probe)
    return evidence


def check_picks_dropped_when_sheets_change(book):
    """Once a sheet is inserted or deleted, no pick survives, and Menu then acts on nothing (#28).

    A deleted sheet's handle turns to another sheet and can report the deleted sheet's name
    again once that sheet is renamed, so the list cannot tell which sheet its handles mean.
    The ways: Bravo deleted and Alfa renamed to Bravo; a new sheet inserted before Bravo,
    Bravo deleted, and the new sheet renamed to Bravo (the sheet count ends as it began); Bravo
    replaced while it is held and the list follows Calc to Delta; the insert-delete-rename
    batch run on LibreOffice's main thread inside lockControllers, addActionLock, or
    disableSetModified, which LibreOffice reports with one modify notification or none; and the
    same batch with undo recording off inside either lock, recording back on after or before
    the unlock or before one recorded edit (`view.UNRECORDED`). The undo history is empty
    before each change, so that it shows no difference either.
    """
    sheets = book.document.getSheets()
    undo = book.document.getUndoManager()
    evidence = {}
    notice = view.footer_text(book.panel, "Why the sheet list")
    ways = ("delete_rename", "insert_delete_rename", "held_replace", *view.BATCHES)
    for way in (*ways, *view.UNRECORDED):
        reset(book)
        wait_until(
            lambda: not notice.getText(), "the previous clearing notice to expire", timeout=12
        )
        sheets.getByName(NAMES[0]).getCellRangeByName("A1").setString("victim")
        sheets.getByName(NAMES[1]).getCellRangeByName("A1").setString("original")
        undo.clear()
        if way == "held_replace":
            point = book.point(1)
            book.pointer.press(*point)
            wait_until(lambda: book.selection() == [NAMES[1]], "the press to select Bravo")
            book.controller.setActiveSheet(sheets.getByName(NAMES[3]))
            wait_until(lambda: book.selection() == [NAMES[3]], "the list to follow Delta")
            replace(book.document, NAMES[1])
            time.sleep(3)
            book.pointer.release()
        else:
            time.sleep(1.5)  # A refresh after the last way's undo would drop the pick.
            book.double_click(3)  # Delta becomes active.
            book.lab.input.tap("b", pause=0.5)  # Bravo is picked; Delta stays active.
            wait_until(lambda: book.selection() == [NAMES[1]], "typing to pick Bravo")
            time.sleep(1.5)
            assert book.selection() == [NAMES[1]], "The pick went before the change"
        if way in view.BATCHES:
            view.on_main_thread(book.lab.context, lambda w=way: view.cover_batch(book.document, w))
            time.sleep(3)
        elif way in view.UNRECORDED:
            view.on_main_thread(book.lab.context, lambda w=way: unrecorded(book.document, w))
            time.sleep(3)
        elif way != "held_replace":
            if way == "insert_delete_rename":
                sheets.insertNewByName("Newcomer", 1)
            sheets.removeByName(NAMES[1])
            renamed = "Newcomer" if way == "insert_delete_rename" else NAMES[0]
            sheets.getByName(renamed).setName(NAMES[1])
            time.sleep(3)
        time.sleep(1)
        tabs = book.calc_tabs()
        titles = book.undo_titles()
        state = {
            "selection": book.selection(),
            "active": book.active(),
            "notice": bool(notice.getText()),
        }
        # Empty stale picks must refuse the outer popup, whose presence cannot be inferred
        # from Calc's tabs: the outer popup intentionally leaves them unchanged.
        assert not book.lab.input.popup_windows(), "An earlier popup is still open"
        book.lab.input.tap("Menu", pause=0.8)
        state["popup_opened"] = bool(book.lab.input.popup_windows())
        state["calc_tabs_after_menu_key"] = book.calc_tabs()
        book.lab.input.tap("Escape", pause=0.3)
        state["undo_unchanged"] = book.undo_titles() == titles
        state["hidden"] = [n for n in book.order() if not sheets.getByName(n).IsVisible]
        state["hidden_markers"] = [
            sheets.getByName(n).getCellRangeByName("A1").getString() for n in state["hidden"]
        ]
        evidence[way] = state
        while undo.getAllUndoActionTitles():
            undo.undo()
        assert state["selection"] == [], evidence
        assert not state["popup_opened"], evidence
        assert state["calc_tabs_after_menu_key"] == tabs, evidence
        assert state["undo_unchanged"] and state["hidden"] == [], evidence
        if way != "held_replace":
            assert state["notice"], evidence
    return evidence


def check_drop_refused_after_unrecorded_batch(book):
    """A drag held while a batch with undo recording off replaces Bravo moves nothing (#28).

    Bravo is dragged towards the gap after Foxtrot with an empty undo history; while the button
    is held, `view.UNRECORDED`'s batch runs on LibreOffice's main thread. The release is
    refused: the order stays and no move is recorded.
    """
    sheets = book.document.getSheets()
    undo = book.document.getUndoManager()
    evidence = {}
    for way in view.UNRECORDED:
        reset(book)
        sheets.getByName(NAMES[1]).getCellRangeByName("A1").setString("original")
        undo.clear()
        time.sleep(1.5)
        before = book.order()
        start, end = book.point(1), book.point(5, 0.75)
        book.pointer.press(*start)
        book.pointer.glide(start, (start[0], start[1] + 12))
        book.pointer.glide((start[0], start[1] + 12), end)
        time.sleep(0.4)
        view.on_main_thread(book.lab.context, lambda w=way: unrecorded(book.document, w))
        time.sleep(1.5)
        book.pointer.release()
        time.sleep(1.2)
        book.lab.screenshot(f"drop-refused-{way.replace(' ', '-')}")
        titles = book.undo_titles()
        state = {
            "order_unchanged": book.order() == before,
            "undo": titles,
            "bravo": sheets.getByName(NAMES[1]).getCellRangeByName("A1").getString(),
            "message_closed": close_message(book),  # The refusal message.
        }
        evidence[way] = state
        while undo.getAllUndoActionTitles():
            undo.undo()
        assert state["order_unchanged"] and "Move Sheets" not in titles, evidence
        assert state["bravo"] == "replacement", evidence  # The batch did replace Bravo.
        assert state["message_closed"], evidence
    return evidence


def check_save_keeps_picks(book):
    """Saving with Ctrl+S, from the list or from a cell, keeps the list's picks (#28).

    LibreOffice reports a save as modify notifications without an undo action, between its
    save events, and may run the list's refresh in the middle with modify notifications off.
    """
    notice = view.footer_text(book.panel, "Why the sheet list")
    cell = book.document.getSheets().getByIndex(0).getCellRangeByName("B2")
    evidence = {}
    for where in ("list", "cell"):
        reset(book)
        wait_until(
            lambda: not notice.getText(), "the previous clearing notice to expire", timeout=12
        )
        time.sleep(1.5)
        book.click(1)
        book.click(3, modifiers=("Control_L",))
        wait_until(lambda: book.selection() == [NAMES[1], NAMES[3]], "Bravo and Delta picked")
        cell.setString(f"saved from the {where}")
        time.sleep(1.5)
        if where == "list":  # The clicks that made the picks gave the list the focus.
            wait_until(lambda: book.tree.hasFocus(), "the list to have the focus")
        else:
            Pointer(book.lab.input, (0, 0)).click(260, 420, pause=0.5)
        stamp = book.path.stat().st_mtime_ns
        book.lab.input.tap("s", ("Control_L",), pause=0.6)
        wait_until(lambda: not book.document.isModified(), "Ctrl+S to save", timeout=30)
        time.sleep(2)
        state = {
            "saved": book.path.stat().st_mtime_ns != stamp,
            "selection": book.selection(),
            "notice": bool(notice.getText()),
        }
        evidence[where] = state
        assert state == {"saved": True, "selection": [NAMES[1], NAMES[3]], "notice": False}, (
            evidence
        )
    cell.setString("")
    return evidence


def check_actions_refused_while_lock_held(book):
    """Enter and Menu → Hide act on nothing while a batch's outer lock is still held (#28).

    Bravo is picked with Delta active and an empty undo history. On LibreOffice's main thread,
    the insert-delete-rename batch runs with undo recording off inside an inner lock, recording
    comes back on, and only the inner lock is released (`view.held_batch`): LibreOffice reports
    nothing until the outer lock goes. Enter must not activate the replacement, and Menu must
    not open a menu whose Hide hides it; after the release, the picks are dropped.
    """
    sheets = book.document.getSheets()
    undo = book.document.getUndoManager()
    evidence = {}
    for lock in view.LOCKS:
        for action in ("enter", "menu"):
            reset(book)
            sheets.getByName(NAMES[1]).getCellRangeByName("A1").setString("original")
            undo.clear()
            time.sleep(1.5)
            book.double_click(3)
            wait_until(lambda: book.active() == NAMES[3], "Delta active before the held batch")
            book.lab.input.tap("b", pause=0.5)  # Bravo is picked; Delta stays active.
            wait_until(lambda: book.selection() == [NAMES[1]], "typing to pick Bravo")
            time.sleep(1.5)
            view.on_main_thread(
                book.lab.context, lambda lk=lock: view.held_batch(book.document, lk)
            )
            try:
                time.sleep(1)
                tabs = book.calc_tabs()
                if action == "enter":
                    book.lab.input.tap("Return", pause=0.8)
                else:
                    assert not book.lab.input.popup_windows(), "An earlier popup is still open"
                    book.lab.input.tap("Menu", pause=0.8)
                    popup = bool(book.lab.input.popup_windows())
                    book.lab.input.tap("Escape", pause=0.3)
                    assert not popup, "A menu opened while the document lock was held"
                state = {
                    "active": book.active(),
                    "calc_tabs": book.calc_tabs(),
                    "active_marker": sheets.getByName(book.active())
                    .getCellRangeByName("A1")
                    .getString(),
                    "hidden": [n for n in book.order() if not sheets.getByName(n).IsVisible],
                    "undo": book.undo_titles(),
                }
            finally:
                view.on_main_thread(
                    book.lab.context, lambda lk=lock: view.release(book.document, lk)
                )
            wait_until(lambda: book.selection() == [], "the picks to go once the lock is released")
            evidence[f"{lock} {action}"] = state
            while undo.getAllUndoActionTitles():
                undo.undo()
            assert state["active"] == NAMES[3] and state["active_marker"] != "replacement", evidence
            assert state["calc_tabs"] == tabs, evidence
            assert state["hidden"] == [] and state["undo"] == [], evidence
    return evidence


def check_click_hidden_before_refresh(book):
    """A sheet hidden just before its row is clicked is not activated, nor any other (#43)."""
    target = NAMES[3]
    point = book.point(3)
    with refresh_waiting(book):
        book.document.getSheets().getByName(target).IsVisible = False
        stale = "(hidden)" not in book.labels()[3]
        book.pointer.click(*point, pause=0.02)
        book.pointer.click(*point, pause=0.8)
    wait_until(lambda: "(hidden)" in book.labels()[3], "the list to show the sheet hidden")
    time.sleep(0.5)
    evidence = {
        "row_still_shown_visible_when_clicked": stale,
        "active": book.active(),
        "calc_tabs": book.calc_tabs(),
        "selection": book.selection(),
    }
    book.document.getSheets().getByName(target).IsVisible = True
    assert stale, evidence  # Otherwise the click met an up-to-date row and proves nothing.
    assert evidence["active"] == NAMES[0] and evidence["calc_tabs"] == [NAMES[0]], evidence
    return evidence


def check_newer_selection_kept(book):
    """Completed edits and queued real input precede repaint; newer picks survive it (#44).

    With LibreOffice's main thread held, real input is queued: a double click on Bravo, which
    activates it, then a Shift+click on Delta, then one recorded edit whose refresh rebuilds the
    rows. The newer picks, Bravo to Delta, survive the activation's and the edit's refreshes.

    The same with a Ctrl+click on Delta in place of the Shift+click: VCL handles all three
    presses before the first listener runs, so when the Ctrl+click's listener runs the tree has
    changed by more than its own toggle, which the list cannot tell from a selection made through
    accessibility (#294). It either picks Bravo and Delta, as before #294, or picks nothing and
    tells, with the notice; it never picks another set. Both outcomes are recorded.
    """
    wait_until(lambda: book.labels() == NAMES, "the preceding visibility change to repaint")
    evidence = {
        "shift": queue_input_before_repaint(book, ("Shift_L",)),
        "ctrl": queue_input_before_repaint(book, ("Control_L",)),
    }
    shift, ctrl = evidence["shift"], evidence["ctrl"]
    assert shift["after_refresh"] == NAMES[1:4], evidence
    assert ctrl["after_refresh"] in ([NAMES[1], NAMES[3]], []), evidence
    if not ctrl["after_refresh"]:
        assert str(ctrl["notice"]).startswith("Selection cleared"), evidence
    return evidence


def queue_input_before_repaint(book, modifiers):
    """Queue a double click on Bravo, a click on Delta with `modifiers` and a recorded edit, with
    the main thread held, and return what the list shows once its refreshes have run."""
    # A completed activation repaint gives this gesture a fresh baseline, independent of
    # the previous check's queued colour/visibility changes and maximum-refresh deadline.
    for index in (4, 0):
        before = view.root(book.tree)
        book.controller.setActiveSheet(book.document.Sheets.getByName(NAMES[index]))
        wait_until(
            lambda old=before: view.root(book.tree) not in (None, old),
            "the baseline activation to repaint",
        )
    select_tabs(book.lab.context, book.frame, [0])
    book.click(0)
    wait_until(lambda: book.selection() == [NAMES[0]], "a settled pick before the queued input")
    first, second = book.point(1), book.point(3)
    model = view.root(book.tree)
    sheet = book.document.Sheets.getByName(NAMES[-1])
    original = sheet.TabColor
    color = 0x996633 if original == 0x2A6099 else 0x2A6099
    history = book.undo_titles()
    received = threading.Event()
    releases = [0]
    state = {"marker_not_yet_moved": False, "error": ""}
    notice = view.footer_text(book.panel, "Why the sheet list")

    class ReleaseProbe(unohelper.Base, XMouseListener):
        def mouseReleased(self, event):
            releases[0] += 1
            if releases[0] == 3:
                try:
                    state["marker_not_yet_moved"] = view.root(book.tree) == model
                except Exception:
                    state["error"] = traceback.format_exc()
                finally:
                    received.set()

        def mousePressed(self, event):
            pass

        def mouseEntered(self, event):
            pass

        def mouseExited(self, event):
            pass

        def disposing(self, event):
            pass

    def queue():
        # The main thread waits for this callback. Queue real X events first, then complete
        # one recorded edit before returning: no refresh timer runs during client sleeps,
        # and no undo/modify pair is still in progress when the input is handled.
        book.pointer.click(*first, pause=0.02)
        book.pointer.click(*first, pause=0.05)
        book.pointer.click(*second, modifiers=modifiers, pause=0)
        sheet.TabColor = color

    probe = ReleaseProbe()
    book.tree.addMouseListener(probe)
    try:
        view.on_main_thread(book.lab.context, queue)
        assert received.wait(10), state
        assert not state["error"] and state["marker_not_yet_moved"], state
        assert len(book.undo_titles()) == len(history) + 1, "The fixture edit was not recorded"
        wait_until(
            lambda: view.root(book.tree) not in (None, model), "the activated row to repaint"
        )
        time.sleep(1)
        evidence = {
            **state,
            "releases": releases[0],
            "after_refresh": book.selection(),
            "active": book.active(),
            "notice": notice.getText(),
        }
        assert evidence["releases"] == 3, evidence
        assert evidence["active"] == NAMES[1], evidence
        return evidence
    finally:
        book.tree.removeMouseListener(probe)
        sheet.TabColor = original
