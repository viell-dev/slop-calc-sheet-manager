"""Real-input tests of the sheet list: XTEST mouse, wheel, and keys under Xvfb.

Run inside the Linux test image with LibreOffice's bundled Python, normally through
``tools/linux_integration.py <lane> --ui``. Each VCL plugin gets its own private office and
profile. The tests drive only real X input and observe only public UNO: the panel's
``XPanel.getDialog()`` window, its child tree control, the document, and its undo manager.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "tests" / "integration"), str(ROOT / "src")]

import sheet_list_view as view  # noqa: E402
import unohelper  # noqa: E402
from com.sun.star.awt import XMouseMotionListener  # noqa: E402
from run import office_session, wait_for  # noqa: E402
from xinput import RIGHT, Pointer, XInput  # noqa: E402

from sheet_manager.reorder import Sheet, target_order  # noqa: E402
from sheet_manager.sheet_list import ACTIVE_MARK  # noqa: E402

NATO = [
    "Alfa",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
    "India",
    "Juliett",
    "Kilo",
    "Lima",
    "Mike",
    "November",
    "Oscar",
    "Papa",
    "Quebec",
    "Romeo",
    "Sierra",
    "Tango",
    "Uniform",
    "Victor",
    "Whiskey",
    "X-ray",
    "Yankee",
    "Zulu",
]
NAMES = NATO + [f"Sheet {number}" for number in range(27, 81)]
PROGRAM = Path("/opt/lo/program")


class Tracker(unohelper.Base, XMouseMotionListener):
    """Records where the tree last saw the pointer, in its own coordinates."""

    def __init__(self):
        self.last = None

    def mouseMoved(self, e):
        self.last = (e.X, e.Y)

    def mouseDragged(self, e):
        self.last = (e.X, e.Y)

    def disposing(self, Source):
        pass


class Workbook:
    def __init__(self, lab, title, names):
        self.lab = lab
        self.path = lab.directory / f"{title}.ods"
        document = lab.desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
        sheets = document.getSheets()
        sheets.getByIndex(0).setName(names[0])
        for index, name in enumerate(names[1:], start=1):
            sheets.insertNewByName(name, index)
        sheets.getByIndex(0).getCellRangeByName("A1").setString("keep")
        document.storeAsURL(self.path.as_uri(), ())
        document.getUndoManager().clear()
        self.document = document
        self.controller = document.getCurrentController()
        self.frame = self.controller.getFrame()
        self.window = self.frame.getContainerWindow()
        self.window.IsMaximized = False
        self.window.setPosSize(0, 0, 1500, 950, 15)
        self.controller.setActiveSheet(sheets.getByIndex(0))
        _, self.tree = view.open_list(lab.context, document)
        wait_for(lambda: len(self.nodes()) == len(names), "every sheet in the list")
        time.sleep(1)
        self.pointer = Pointer(lab.input, lab.calibrate(self.tree, self.window))

    # What the list shows

    def nodes(self):
        return view.nodes(self.tree)

    def labels(self):
        return view.labels(self.tree)

    def selection(self):
        return view.selection(self.tree, self.order())

    def point(self, index, fraction=0.5):
        return view.row_point(self.tree, index, fraction)

    def first_visible(self):
        rect = view.row_rect(self.tree, 0, scroll=False)
        return -rect.Y // rect.Height

    # What the document says

    def order(self):
        return list(self.document.getSheets().getElementNames())

    def active(self):
        return self.controller.getActiveSheet().getName()

    def calc_tabs(self):
        order = self.order()
        return [order[index] for index in view.selected_tabs(self.lab.context, self.controller)]

    def undo_titles(self):
        return list(self.document.getUndoManager().getAllUndoActionTitles())

    def click(self, index, modifiers=()):
        self.pointer.click(*self.point(index), modifiers=modifiers)

    def focus_list(self):
        """Click the active sheet's row: the list gets the focus, nothing else changes."""
        self.click(self.order().index(self.active()))

    def choose(self, command):
        """Choose a menu entry with the keyboard; generated mnemonics differ between plugins."""
        items = wait_for(
            lambda: view.enabled_menu_items(self.lab.context, self.frame, PROGRAM) or None,
            "the menu's command states",
        )
        self.lab.input.tap("Home")
        for _ in range(items.index(command)):
            self.lab.input.tap("Down")
        self.lab.screenshot(f"menu-{command[5:].lower()}")
        self.lab.input.tap("Return", pause=0.5)
        return items

    def close(self):
        self.document.close(True)


class Lab:
    def __init__(self, context, desktop, directory, output):
        self.context = context
        self.desktop = desktop
        self.directory = directory
        self.output = output
        self.input = XInput()

    def screenshot(self, name):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "URE_BOOTSTRAP")
        }
        subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                "-c",
                "from PIL import ImageGrab; import sys; ImageGrab.grab().save(sys.argv[1])",
                str(self.output / f"{name}.png"),
            ],
            check=True,
            env=environment,
        )

    def calibrate(self, tree, window):
        """Find the tree's screen offset: move the pointer and ask the tree where it is."""
        tracker = Tracker()
        tree.addMouseMotionListener(tracker)
        try:
            candidates = []
            try:
                accessible = tree.getProperty("XAccessible").getAccessibleContext()
                location = accessible.getLocationOnScreen()
                candidates.append((location.X + 30, location.Y + 12))
            except Exception:
                pass
            frame = window.getPosSize()
            for y in range(frame.Y + 60, frame.Y + frame.Height - 40, 40):
                for x in range(frame.X + frame.Width - 40, frame.X + frame.Width // 2, -40):
                    candidates.append((x, y))
            for x, y in candidates:
                tracker.last = None
                self.input.move(x, y)
                deadline = time.monotonic() + 0.3
                while tracker.last is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                if tracker.last is not None:
                    self.input.move(x + 2, y + 2)
                    time.sleep(0.2)
                    local = tracker.last
                    return (x + 2 - local[0], y + 2 - local[1])
            raise AssertionError("The pointer never reached the sheet list")
        finally:
            tree.removeMouseMotionListener(tracker)


def wait_until(function, what, timeout=10):
    return wait_for(function, what, timeout=timeout)


# Checks. Each returns evidence and raises AssertionError on failure.


def check_click_activates(book):
    book.click(4)
    wait_until(lambda: book.active() == NAMES[4], "the clicked sheet to become active")
    assert book.selection() == [NAMES[4]], book.selection()
    assert book.labels()[4].startswith(ACTIVE_MARK), book.labels()[4]
    return {"active": book.active(), "selection": book.selection(), "label": book.labels()[4]}


def check_ctrl_shift_selection(book):
    book.click(1)
    wait_until(lambda: book.active() == NAMES[1], "a plain click to activate")
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


def drag(book, source, target, fraction, *, hold=0.0, cancel=False, shot=None):
    start = book.point(source)
    end = book.point(target, fraction)
    book.pointer.press(*start)
    book.pointer.glide(start, (start[0], start[1] + 12))
    book.pointer.glide((start[0], start[1] + 12), end)
    time.sleep(0.4 + hold)
    if shot:
        book.lab.screenshot(shot)
    if cancel:
        book.lab.input.tap("Escape", pause=0.3)
    book.pointer.release()
    time.sleep(1.0)


def check_drag_two_sheets(book, fraction, gap):
    book.click(2)
    book.click(5, modifiers=("Control_L",))
    wait_until(lambda: book.selection() == [NAMES[2], NAMES[5]], "two separate rows selected")
    before, undo_before = book.order(), book.undo_titles()
    active, tabs = book.active(), book.calc_tabs()
    sheets = [Sheet(name) for name in before]
    expected = list(target_order(sheets, [NAMES[2], NAMES[5]], "drop", gap))
    drag(book, 5, 12, fraction, shot=f"drag-gap-{gap}")
    wait_until(lambda: book.order() != before, "the drop to move the sheets")
    after, undo_after = book.order(), book.undo_titles()
    evidence = {
        "gap": gap,
        "fraction_of_row": fraction,
        "before": before[:16],
        "after": after[:16],
        "expected": expected[:16],
        "undo_added": undo_after[: len(undo_after) - len(undo_before)],
        "selection": book.selection(),
        "active": [active, book.active()],
        "calc_tabs": [tabs, book.calc_tabs()],
    }
    assert after == expected, evidence
    assert len(undo_after) == len(undo_before) + 1 and undo_after[0] == "Move Sheets", evidence
    assert book.active() == active and book.calc_tabs() == tabs, evidence
    wait_until(lambda: book.selection() == [NAMES[2], NAMES[5]], "the moved rows to stay selected")
    book.document.getUndoManager().undo()
    wait_until(lambda: book.order() == before, "one undo to restore the order")
    evidence["undo_restored"] = True
    return evidence


def check_drop_in_place_and_escape(book):
    book.click(6)
    before, undo_before = book.order(), book.undo_titles()
    drag(book, 6, 6, 0.8)
    in_place = book.order() == before and book.undo_titles() == undo_before
    drag(book, 6, 15, 0.5, cancel=True, shot="drag-escape")
    cancelled = book.order() == before and book.undo_titles() == undo_before
    evidence = {"dropped_in_place_unchanged": in_place, "escape_unchanged": cancelled}
    assert in_place and cancelled, evidence
    return evidence


def check_autoscroll(book):
    book.click(0)
    book.tree.makeNodeVisible(book.nodes()[0])
    time.sleep(0.3)
    first = book.first_visible()
    height = book.tree.getOutputSize().Height
    start = book.point(0)
    book.pointer.press(*start)
    book.pointer.glide(start, (start[0], start[1] + 12))
    book.pointer.glide((start[0], start[1] + 12), (start[0], height - 3))
    deadline = time.monotonic() + 6
    while book.first_visible() <= first + 3 and time.monotonic() < deadline:
        time.sleep(0.2)
    scrolled = book.first_visible()
    book.lab.screenshot("drag-autoscroll")
    book.lab.input.tap("Escape", pause=0.3)
    book.pointer.release()
    time.sleep(0.8)
    evidence = {"first_visible": [first, scrolled], "order_unchanged": book.order() == NAMES}
    assert scrolled > first + 3 and book.order() == NAMES, evidence
    return evidence


def check_wheel(book):
    book.tree.makeNodeVisible(book.nodes()[0])
    time.sleep(0.3)
    first = book.first_visible()
    x, y = book.point(3)
    book.pointer.wheel(x, y, down=True, ticks=5)
    down = book.first_visible()
    book.pointer.wheel(x, y, down=False, ticks=10)
    up = book.first_visible()
    evidence = {"first_visible": [first, down, up]}
    assert down > first and up == first, evidence
    return evidence


def check_keys_stay_in_list(book):
    book.click(0)
    wait_until(lambda: book.active() == NAMES[0], "the first sheet to be active")
    sheet = book.document.getSheets().getByIndex(0)
    cell = sheet.getCellRangeByName("A1")
    book.controller.select(cell)
    book.document.setModified(False)
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
    with_list_focus("ctrl_s", "s")
    wait_until(lambda: not book.document.isModified(), "Ctrl+S to save", timeout=20)
    evidence = {
        "ctrl_page_down": next_sheet,
        "ctrl_page_up": previous_sheet,
        "undo": True,
        "saved": book.path.stat().st_mtime_ns != stamp,
        "list_has_focus_after": focus,
    }
    assert next_sheet == NAMES[1] and previous_sheet == NAMES[0], evidence
    assert evidence["saved"], evidence
    return evidence


def reset(book):
    """Put the workbook back as it was created, whatever an earlier check left behind."""
    for _ in range(2):
        book.lab.input.tap("Escape", pause=0.2)
    sheets = book.document.getSheets()
    for index, name in enumerate(NAMES):
        if sheets.getByIndex(index).getName() != name:
            sheets.moveByName(name, index)
        sheets.getByIndex(index).IsVisible = True
    book.controller.setActiveSheet(sheets.getByIndex(0))
    book.document.getUndoManager().clear()
    wait_until(
        lambda: (
            [label.split(" (")[0] for label in book.labels()]
            == [(ACTIVE_MARK if index == 0 else "") + name for index, name in enumerate(NAMES)]
        ),
        "the list to show the original workbook",
    )


def hide_through_menu(book, picked, opener):
    before = book.undo_titles()
    opener()
    time.sleep(0.8)
    tabs = book.calc_tabs()
    items = book.choose(".uno:Hide")
    wait_until(
        lambda: all(not book.document.getSheets().getByName(n).IsVisible for n in picked),
        "Hide Sheet to hide the picked sheets",
    )
    hidden = [n for n in book.order() if not book.document.getSheets().getByName(n).IsVisible]
    evidence = {"calc_tabs_while_open": tabs, "menu": items, "hidden": hidden}
    assert tabs == picked and hidden == picked, evidence
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


def replace(document, name):
    """Delete a sheet and insert a different one with the same name at the same place."""
    sheets = document.getSheets()
    index = list(sheets.getElementNames()).index(name)
    sheets.removeByName(name)
    sheets.insertNewByName(name, index)
    sheets.getByName(name).getCellRangeByName("A1").setString("replacement")


def check_plain_click_ends_group(book):
    """After the menu grouped two tabs, a plain click leaves one; typing edits one sheet (#25)."""
    book.click(1)
    book.click(3, modifiers=("Control_L",))
    wait_until(lambda: book.selection() == [NAMES[1], NAMES[3]], "Bravo and Delta selected")
    book.lab.input.tap("Menu", pause=0.8)
    wait_until(lambda: book.calc_tabs() == [NAMES[1], NAMES[3]], "the menu to group the tabs")
    book.lab.input.tap("Escape", pause=0.5)
    book.click(1)
    wait_until(lambda: book.calc_tabs() == [NAMES[1]], "a plain click to leave one selected tab")

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


def check_cursor_across_refresh(book):
    """A refresh keeps the keyboard cursor where it was, not on the first selected row (#29)."""
    foxtrot = book.document.getSheets().getByName(NAMES[5])

    def graphic():
        return book.nodes()[5].getNodeGraphicURL()

    evidence = {}
    for keysym, modifiers in (("space", ("Control_L",)), ("Down", ("Shift_L",))):
        outcomes = []
        for refreshed in (False, True):
            foxtrot.TabColor = -1
            wait_until(lambda: graphic() == book.nodes()[0].getNodeGraphicURL(), "no colour")
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
    book.lab.input.tap("Return", pause=0.6)  # Close the refusal message.
    evidence = {"order_unchanged": book.order() == before, "undo": book.undo_titles()}
    assert evidence["order_unchanged"] and "Move Sheets" not in evidence["undo"], evidence
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
        point = book.point(1)
        book.pointer.press(*point)
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
            # The menu key opens the menu for the list's selection and groups Calc's tabs
            # to match while it is open; with nothing picked it does nothing.
            titles = book.undo_titles()
            book.lab.input.tap("Menu", pause=0.8)
            state["calc_tabs_after_menu_key"] = book.calc_tabs()
            book.lab.input.tap("Escape", pause=0.3)
            state["undo_unchanged"] = book.undo_titles() == titles
        evidence[change] = state
        assert state["active"] == NAMES[0] and state["calc_tabs"] == [NAMES[0]], evidence
        assert state["selection"] == picked, evidence
        if change == "replace":
            assert state["calc_tabs_after_menu_key"] == [NAMES[0]], evidence
            assert state["undo_unchanged"], evidence
    return evidence


def check_newer_pick_survives_voided_press(book):
    """A voided press brings back the list's newer pick, never a replacement (#28).

    Two ways to a newer pick while Bravo is held: Calc goes to Delta and the list follows, or
    the user types "d". Then Bravo is replaced and the button released. Delta stays picked,
    and the Menu key's Hide acts on Delta; the replacement Bravo stays visible.
    """
    sheets = book.document.getSheets()
    evidence = {}
    for way in ("calc_switch", "typing"):
        reset(book)
        point = book.point(1)
        book.pointer.press(*point)
        wait_until(lambda: book.selection() == [NAMES[1]], "the press to select Bravo")
        if way == "calc_switch":
            book.controller.setActiveSheet(sheets.getByName(NAMES[3]))
            wait_until(lambda: book.selection() == [NAMES[3]], "the list to follow Delta")
        else:
            sheets.moveByName(NAMES[1], 6)
            wait_until(lambda: view.names(book.tree)[1] == NAMES[2], "the list to show the move")
            book.lab.input.tap("d", pause=0.5)
            wait_until(lambda: book.selection() == [NAMES[3]], "typing to pick Delta")
        replace(book.document, NAMES[1])
        time.sleep(3)
        book.pointer.release()
        time.sleep(1)
        state = {"selection": book.selection(), "active": book.active()}
        evidence[way] = state
        assert state["selection"] == [NAMES[3]], evidence
        state["menu"] = hide_through_menu(
            book, [NAMES[3]], lambda: book.lab.input.tap("Menu", pause=0.3)
        )
        bravo = sheets.getByName(NAMES[1])
        state["replacement_visible"] = bool(bravo.IsVisible)
        state["replacement_marker"] = bravo.getCellRangeByName("A1").getString()
        assert state["replacement_visible"] and state["replacement_marker"] == "replacement"
    return evidence


def check_click_hidden_before_refresh(book):
    """A sheet hidden just before its row is clicked is not activated, nor any other (#43)."""
    target = NAMES[3]
    point = book.point(3)
    with refresh_waiting(book):
        book.document.getSheets().getByName(target).IsVisible = False
        stale = "(hidden)" not in book.labels()[3]
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
    """A delayed refresh keeps a Ctrl+click made after a plain click (#44)."""
    first, second = book.point(1), book.point(3)
    with refresh_waiting(book):
        book.pointer.click(*first, pause=0.05)
        book.pointer.click(*second, modifiers=("Control_L",), pause=0.3)
        stale = not book.labels()[1].startswith(ACTIVE_MARK)
        before_refresh = book.selection()
    wait_until(lambda: book.labels()[1].startswith(ACTIVE_MARK), "the marker to move to Bravo")
    time.sleep(1)
    evidence = {
        "marker_not_yet_moved": stale,
        "before_refresh": before_refresh,
        "after_refresh": book.selection(),
        "active": book.active(),
    }
    assert stale, evidence  # Otherwise the refresh ran before the Ctrl+click.
    assert evidence["after_refresh"] == [NAMES[1], NAMES[3]], evidence
    assert evidence["active"] == NAMES[1], evidence
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
        other.click(1)
        wait_until(lambda: other.active() == "Two", "the second document's list to activate")
    finally:
        other.close()
    book.frame.activate()
    book.window.toFront()
    time.sleep(1)
    book.click(3)
    wait_until(lambda: book.active() == NAMES[3], "the first document's list to still work")
    lab.input.tap("q", pause=0.4)
    evidence = {
        "typed_in_other_document": typed,
        "other_list_works": other_list_works,
        "first_list_after_switch": book.selection(),
    }
    assert typed == "x" and book.selection() == ["Quebec"], evidence
    return evidence


def run_checks(lab, output):
    book = Workbook(lab, "synthetic", NAMES)
    lab.screenshot("panel")
    checks = [
        ("click_activates", lambda: check_click_activates(book)),
        ("ctrl_shift_selection", lambda: check_ctrl_shift_selection(book)),
        ("drag_two_sheets_above_midpoint", lambda: check_drag_two_sheets(book, 0.25, 12)),
        ("drag_two_sheets_below_midpoint", lambda: check_drag_two_sheets(book, 0.75, 13)),
        ("drop_in_place_and_escape", lambda: check_drop_in_place_and_escape(book)),
        ("autoscroll", lambda: check_autoscroll(book)),
        ("wheel", lambda: check_wheel(book)),
        ("keys_stay_in_list", lambda: check_keys_stay_in_list(book)),
        ("shortcuts_reach_calc", lambda: check_shortcuts(book)),
        ("menu_right_click", lambda: check_menu_right_click(book)),
        ("menu_keyboard", lambda: check_menu_keyboard(book)),
        ("menu_hidden_only", lambda: check_menu_hidden_only(book)),
        ("plain_click_ends_group", lambda: check_plain_click_ends_group(book)),
        ("cursor_across_refresh", lambda: check_cursor_across_refresh(book)),
        ("drop_after_replacement", lambda: check_drop_after_replacement(book)),
        ("press_then_change", lambda: check_press_then_change(book)),
        ("newer_pick_survives_voided_press", lambda: check_newer_pick_survives_voided_press(book)),
        ("click_hidden_before_refresh", lambda: check_click_hidden_before_refresh(book)),
        ("newer_selection_kept", lambda: check_newer_selection_kept(book)),
        ("other_document", lambda: check_other_document(lab, book)),
    ]
    results = {}
    for name, check in checks:
        started = time.monotonic()
        try:
            reset(book)
            results[name] = {"pass": True, "evidence": check()}
        except Exception:
            results[name] = {"pass": False, "error": traceback.format_exc()}
            lab.screenshot(f"failed-{name}")
            for _ in range(2):
                lab.input.tap("Escape", pause=0.3)
        results[name]["seconds"] = round(time.monotonic() - started, 2)
        print(name, "pass" if results[name]["pass"] else "FAIL", flush=True)
        (output / "checks.json").write_text(json.dumps(results, indent=2) + "\n", "utf-8")
    book.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("test-results/ui"))
    parser.add_argument("--vcl", action="append", choices=["gtk3", "gen"])
    parser.add_argument("--ui", action="store_true", help="Accepted from the container session")
    parser.add_argument(
        "--backtrace", action="store_true", help="Linux only: use LibreOffice's gdb wrapper"
    )
    arguments = parser.parse_args()
    summary = {}
    failed = False
    for vcl in arguments.vcl or ["gtk3", "gen"]:
        output = (arguments.output / f"ui-{vcl}").resolve()
        output.mkdir(parents=True, exist_ok=True)
        result: dict[str, object] = {"vcl": vcl}
        summary[vcl] = result
        try:
            with office_session(
                arguments.program.resolve(),
                arguments.oxt.resolve(),
                output,
                result,
                headless=False,
                backtrace=arguments.backtrace,
                vcl=vcl,
            ) as (context, desktop, directory):
                checks = run_checks(Lab(context, desktop, directory, output), output)
                result["checks"] = {name: check["pass"] for name, check in checks.items()}
                failed = failed or not all(result["checks"].values())
        except Exception:
            result["error"] = traceback.format_exc()
            failed = True
        logs = "".join(p.read_text("utf-8", "replace") for p in output.glob("soffice-*.log"))
        result["extension_errors"] = logs.count("Sheet Manager: ")
        failed = failed or bool(result["extension_errors"])
    text = json.dumps(summary, indent=2) + "\n"
    (arguments.output / "ui-results.json").write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
