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
from typing import cast

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "tests" / "integration"), str(ROOT / "src")]

import sheet_list_view as view  # noqa: E402
import uno  # noqa: E402
import unohelper  # noqa: E402
from com.sun.star.awt import XMouseListener, XMouseMotionListener  # noqa: E402
from run import office_session, wait_for  # noqa: E402
from teardown import stalled_callbacks  # noqa: E402
from xinput import RIGHT, Pointer, XInput  # noqa: E402

from sheet_manager.reorder import Action, Sheet, target_order  # noqa: E402
from sheet_manager.uno_calc import dispatch, select_tabs  # noqa: E402

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
PUSH_BUTTON = uno.getConstantByName("com.sun.star.accessibility.AccessibleRole.PUSH_BUTTON")
unrecorded = view.unrecorded_batch


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
        self.panel, self.tree = view.open_list(lab.context, document)
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
        return max(0, -(rect.Y - 3) // self.tree.getProperty("RowHeight"))

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

    def double_click(self, index):
        point = self.point(index)
        self.pointer.click(*point, pause=0.02)
        self.pointer.click(*point)

    def move_action(self, action):
        """Open the real menu and select one of its enabled move actions."""
        picked = self.selection()
        self.lab.input.tap("Menu", pause=0.4)
        self.lab.input.tap("Home")
        # These callers choose non-edge rows; all four actions are enabled.
        for _ in range(("top", "up", "down", "bottom").index(action)):
            self.lab.input.tap("Down")
        self.lab.input.tap("Return", pause=0.5)
        wait_until(lambda: self.selection() == picked, "menu picks restored")

    def native_menu(self):
        """Choose the outer popup's explicit Sheet actions command."""
        self.lab.input.tap("End")
        self.lab.input.tap("Up")
        self.lab.input.tap("Return", pause=0.4)

    def choose(self, command, *, native_open=False):
        """Choose a menu entry with the keyboard; generated mnemonics differ between plugins."""
        if not native_open:
            self.native_menu()
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


def native_modal():
    """Read native dialog identity: GTK can omit UNO exposure; gen omits the modal state hint."""
    active = subprocess.check_output(["xprop", "-root", "_NET_ACTIVE_WINDOW"], text=True)
    window = active.split()[-1]
    if window == "0x0":
        return False
    state = subprocess.check_output(
        ["xprop", "-id", window, "_NET_WM_WINDOW_TYPE", "WM_TRANSIENT_FOR"], text=True
    )
    return (
        "_NET_WM_WINDOW_TYPE_DIALOG" in state
        and "WM_TRANSIENT_FOR(WINDOW): window id # 0x" in state
    )


def configure_desktop_opener(output):
    # The office inherits these only inside the private test process/profile.
    os.environ["PATH"] = str(HERE) + os.pathsep + os.environ["PATH"]
    os.environ["SHEET_MANAGER_URI_LOG"] = str(output / "opened-uris.txt")


# Checks. Each returns evidence and raises AssertionError on failure.


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
    select_tabs(book.lab.context, book.frame, [0, 2, 3])
    wait_until(lambda: book.calc_tabs() == NAMES[:1] + NAMES[2:4], "a native Calc group")
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
    assert book.active() == active and set(book.calc_tabs()) == set(tabs), evidence
    wait_until(lambda: book.selection() == [NAMES[2], NAMES[5]], "the moved rows to stay selected")
    book.document.getUndoManager().undo()
    wait_until(lambda: book.order() == before, "one undo to restore the order")
    evidence["undo_restored"] = True
    return evidence


def check_move_controls(book, shortcuts, buttons=False):
    evidence = {}
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
            bounds, tree_bounds = button.getPosSize(), book.tree.getPosSize()
            pointer = Pointer(
                book.lab.input,
                (
                    book.pointer.offset[0] + bounds.X - tree_bounds.X,
                    book.pointer.offset[1] + bounds.Y - tree_bounds.Y,
                ),
            )
            pointer.click(bounds.Width // 2, bounds.Height // 2)
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


def check_move_edges_and_refusal(book):
    book.click(0)
    before, history = book.order(), book.undo_titles()
    book.lab.input.tap("Menu", pause=0.4)
    book.lab.screenshot("move-edge-disabled")
    # gen's Home leaves no highlight when the leading disabled entries are hidden.
    # Down selects the first enabled action on both backends.
    book.lab.input.tap("Down")
    book.lab.input.tap("Return", pause=0.4)
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


def check_row_paint_scroll(book, horizontal=False, prefix="row-paint-"):
    """Native geometry and screenshot pixels must agree throughout scrolling."""
    tree = book.tree
    original_height = tree.getProperty("RowHeight")
    native_view = book.active(), book.calc_tabs()
    evidence = {}

    def capture(name):
        if name != "native-height-picked":
            assert book.selection() == picked, "Scrolling or row sizing changed the picks"
        size = tree.getOutputSize()
        nodes = book.nodes()
        first = next(node for node in nodes if tree.getNodeRect(node).Y >= 0)
        rect = tree.getNodeRect(first)
        y = min(size.Height - 1, rect.Y + rect.Height // 2)
        viewport = next(
            x
            for x in range(size.Width, size.Width // 2, -1)
            if tree.getClosestNodeForLocation(x, y) is not None
        )
        content_height = next(
            bottom
            for bottom in range(size.Height, -1, -1)
            if tree.getClosestNodeForLocation(viewport // 2, bottom) is not None
        )
        rows = [tree.getNodeRect(node) for node in nodes]
        data = {
            "offset": book.pointer.offset,
            "width": size.Width,
            "height": size.Height,
            "viewport": viewport,
            "content_height": content_height,
            "shadow": tree.StyleSettings.ShadowColor,
            "rows": [{"Y": row.Y, "Height": row.Height} for row in rows],
        }
        stem = prefix + name
        path = book.lab.output / (stem + ".json")
        path.write_text(json.dumps(data, indent=2) + "\n")
        book.lab.screenshot(stem)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "URE_BOOTSTRAP")
        }
        checked = subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                str(HERE / "row_paint.py"),
                str(path.with_suffix(".png")),
                str(path),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert checked.returncode == 0, checked.stdout + checked.stderr
        evidence[name] = json.loads(checked.stdout)

    try:
        tree.makeNodeVisible(book.nodes()[0])
        book.click(2)
        picked = book.selection()
        capture("initial")
        if horizontal:
            # The final fixture row is long. A short first row's text extent does not
            # change when it scrolls, so it cannot prove that the thumb gesture worked.
            long_node = book.nodes()[-1]
            before = tree.getNodeRect(long_node).Width
            y = tree.getOutputSize().Height - 7
            assert tree.getClosestNodeForLocation(90, y) is None, "No horizontal scrollbar"
            book.pointer.press(35, y)
            book.pointer.glide((35, y), (120, y))
            book.pointer.release()
            wait_until(
                lambda: tree.getNodeRect(long_node).Width > before,
                "horizontal thumb movement",
            )
            capture("thumb-right")
            book.pointer.press(120, y)
            book.pointer.glide((120, y), (tree.getOutputSize().Width - 18, y))
            book.pointer.release()
            time.sleep(0.4)
            capture("thumb-end")
        book.pointer.wheel(90, 200, True, 4)
        capture("wheel-down")
        book.pointer.wheel(90, 200, False, 1)
        capture("wheel-up")
        tree.makeNodeVisible(book.nodes()[0])
        time.sleep(0.3)
        x = tree.getOutputSize().Width - 7
        book.pointer.press(x, 20)
        book.pointer.glide((x, 20), (x, 120))
        book.pointer.release()
        time.sleep(0.4)
        assert tree.getNodeRect(book.nodes()[0]).Y < 0, "The thumb gesture did not scroll"
        capture("thumb-down")
        book.pointer.press(x, 120)
        book.pointer.glide((x, 120), (x, 60))
        book.pointer.release()
        time.sleep(0.4)
        capture("thumb-up")
        tree.makeNodeVisible(book.nodes()[-1])
        time.sleep(0.4)
        capture("last-row")
        # Like a font/DPI change, VCL may choose a height larger than the model requested.
        tree.setProperty("RowHeight", original_height + 4)
        tree.makeNodeVisible(book.nodes()[0])
        tree.invalidate(0)
        time.sleep(0.4)
        capture("native-height-change")
        rect = tree.getNodeRect(book.nodes()[10])
        book.pointer.click(5, rect.Y + rect.Height - 2)
        wait_until(
            lambda: book.selection() == [book.order()[10]], "hit testing the native row bottom"
        )
        capture("native-height-picked")
        assert (book.active(), book.calc_tabs()) == native_view
    finally:
        tree.setProperty("RowHeight", original_height)
        tree.invalidate(0)
    return evidence


def check_row_paint_long_names(lab):
    """Exercise both native scrollbars without changing the ordinary workbook's state."""
    evidence = {}
    for name, names in (
        ("equal", ["W" * 28 + f"{n:02}" for n in range(80)]),
        ("mixed", [*NAMES[:-1], "W" * 30]),
    ):
        book = Workbook(lab, "synthetic long labels " + name, names)
        try:
            evidence[name] = check_row_paint_scroll(
                book, horizontal=True, prefix="row-paint-" + name + "-"
            )
        finally:
            book.close()
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
    select_tabs(book.lab.context, book.frame, [0])
    book.document.getUndoManager().clear()
    wait_until(
        lambda: [label.split(" (")[0] for label in book.labels()] == NAMES,
        "the list to show the original workbook",
    )


def hide_through_menu(book, picked, opener):
    before = book.undo_titles()
    native_view = book.active(), book.calc_tabs()
    assert not book.lab.input.popup_windows(), "The menu probe must start without a popup"
    opener()
    time.sleep(0.8)
    assert book.lab.input.popup_windows(), "The outer menu did not create a native popup"
    assert (book.active(), book.calc_tabs()) == native_view, "Outer menu changed the native view"
    book.native_menu()
    tabs = book.calc_tabs()
    items = book.choose(".uno:Hide", native_open=True)
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
    book.pointer.click(*book.point(6), button=RIGHT, pause=0.4)
    book.choose(".uno:Remove")
    wait_until(native_modal, "native delete confirmation")
    assert book.calc_tabs() == [NAMES[6]], "Restoration ran inside the native confirmation"
    assert book.selection() == before[1]
    book.lab.screenshot("context-delete-confirmation")
    book.lab.input.tap("Escape", pause=0.5)
    wait_until(
        lambda: state() == before, "cancelled native command to restore the original context"
    )
    order = book.order()
    book.pointer.click(*book.point(6), button=RIGHT, pause=0.4)
    book.lab.input.tap("Home")
    for _ in range(3):
        book.lab.input.tap("Down")
    book.lab.input.tap("Return", pause=0.5)
    wait_until(lambda: book.order()[-1] == NAMES[6], "context move of the unpicked row")
    wait_until(lambda: state() == before, "context move to keep independent picks and view")
    book.document.UndoManager.undo()
    wait_until(lambda: book.order() == order, "one undo of the context move")
    book.click(1)
    book.pointer.click(*book.point(6), button=RIGHT, pause=0.4)
    # The outer menu has not taken ownership of the native view. A macro can still change it.
    book.controller.setActiveSheet(book.document.Sheets.getByName(NAMES[9]))
    select_tabs(book.lab.context, book.frame, [9, 11])
    newer_view = state()
    book.lab.input.tap("End")
    book.lab.input.tap("Up")
    book.lab.input.tap("Return", pause=0.5)
    wait_until(lambda: book.calc_tabs() == [NAMES[6]], "explicit native menu targeting")
    book.lab.input.tap("Escape", pause=0.5)
    wait_until(lambda: state() == newer_view, "native menu to restore its entry-time view")
    book.click(1)
    book.pointer.click(*book.point(6), button=RIGHT, pause=0.4)
    book.choose(".uno:TableSelectAll")
    wait_until(lambda: book.calc_tabs() == order, "explicit native Select All Sheets")
    wait_until(lambda: book.selection() == order, "following the explicit selection command")
    return {
        "picked_and_unpicked_cancel": True,
        "unpicked_move": True,
        "one_undo": True,
        "explicit_native_selection": True,
        "modal_command_context_kept": True,
        "native_entry_time_view": True,
    }


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
    """Mixed targets get safe Show/move actions without native tab grouping."""
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
        assert (book.active(), book.calc_tabs()) == before
        book.native_menu()
        assert (book.active(), book.calc_tabs()) == before, "Fallback changed the native view"
        book.lab.screenshot("menu-mixed-visibility")
        book.lab.input.tap("Home")
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


def check_plain_click_ends_group(book):
    """Activation leaves one selected tab; subsequent typing edits only that sheet (#25)."""
    book.click(1)
    book.click(3, modifiers=("Control_L",))
    wait_until(lambda: book.selection() == [NAMES[1], NAMES[3]], "Bravo and Delta selected")
    book.lab.input.tap("Menu", pause=0.8)
    book.native_menu()
    wait_until(lambda: book.calc_tabs() == [NAMES[1], NAMES[3]], "the menu to group the tabs")
    book.lab.input.tap("Escape", pause=0.5)
    # Cancelling restored the original group. Establish a native group explicitly.
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


def check_selected_press_cursor(book):
    """A refused already-selected press restores its picks and a picked keyboard cursor."""
    evidence = {}
    for newer in (False, True):
        reset(book)
        book.click(1)
        start = book.point(1)
        book.pointer.press(*start)
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
            sheets.moveByName(NAMES[1], 6)
            wait_until(lambda: view.names(book.tree)[1] == NAMES[2], "the list to show the move")
        else:
            sheets.moveByName(NAMES[1], 6)
            wait_until(lambda: view.names(book.tree)[1] == NAMES[2], "the list to show the move")
            book.lab.input.tap("d", pause=0.5)
            wait_until(lambda: book.selection() == [NAMES[3]], "typing to pick Delta")
        time.sleep(1)
        book.pointer.release()
        time.sleep(1)
        state = {"selection": book.selection(), "active": book.active()}
        evidence[way] = state
        assert state["selection"] == [NAMES[3]], evidence
        state["menu"] = hide_through_menu(
            book, [NAMES[3]], lambda: book.lab.input.tap("Menu", pause=0.3)
        )
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
    ways = ("delete_rename", "insert_delete_rename", "held_replace", *view.BATCHES)
    for way in (*ways, *view.UNRECORDED):
        reset(book)
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
        notice = "dev.viell.sheetmanager.selection-cleared"
        state = {
            "selection": book.selection(),
            "active": book.active(),
            "notice": bool(book.controller.hasInfobar(notice)),
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
        if state["notice"]:
            book.controller.removeInfobar(notice)
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
    notice = "dev.viell.sheetmanager.selection-cleared"
    cell = book.document.getSheets().getByIndex(0).getCellRangeByName("B2")
    evidence = {}
    for where in ("list", "cell"):
        reset(book)
        if book.controller.hasInfobar(notice):
            book.controller.removeInfobar(notice)
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
            "notice": bool(book.controller.hasInfobar(notice)),
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
    """Completed edits and queued real input precede repaint; newer picks survive it (#44)."""
    wait_until(lambda: book.labels() == NAMES, "the preceding visibility change to repaint")
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
        book.pointer.click(*second, modifiers=("Control_L",), pause=0)
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
        }
        assert evidence["releases"] == 3, evidence
        assert evidence["after_refresh"] == [NAMES[1], NAMES[3]], evidence
        assert evidence["active"] == NAMES[1], evidence
        return evidence
    finally:
        book.tree.removeMouseListener(probe)
        sheet.TabColor = original


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


def check_tab_selection_sync(book):
    book.click(0)
    before = view.root(book.tree)
    started = time.monotonic()
    select_tabs(book.lab.context, book.frame, [0, 2])
    wait_until(lambda: book.selection() == ["Alfa", "Charlie"], "a same-active tab change")
    elapsed = time.monotonic() - started
    assert book.active() == "Alfa"
    assert view.root(book.tree) == before, "Selection-only following rebuilt the rows"
    fields = [
        child
        for child in book.panel.getWindows()
        if "com.sun.star.awt.XFixedText" in [kind.typeName for kind in child.getTypes()]
    ]
    assert len(fields) == 1
    assert fields[0].getText() == "Edits affect 2 Calc tabs: Alfa, Charlie"
    accessible = fields[0].getProperty("XAccessible").getAccessibleContext()
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


def run_checks(lab, output):
    book = Workbook(lab, "synthetic", NAMES)
    lab.screenshot("panel")
    checks = [
        ("move_menu", lambda: check_move_controls(book, False)),
        ("move_buttons", lambda: check_move_controls(book, False, buttons=True)),
        ("move_shortcuts", lambda: check_move_controls(book, True)),
        ("move_edges_and_refusal", lambda: check_move_edges_and_refusal(book)),
        ("move_focus_and_queued_navigation", lambda: check_move_focus_and_queued_navigation(book)),
        ("click_activates", lambda: check_click_activates(book)),
        ("ctrl_shift_selection", lambda: check_ctrl_shift_selection(book)),
        ("row_paint_scroll", lambda: check_row_paint_scroll(book)),
        ("tab_selection_sync", lambda: check_tab_selection_sync(book)),
        ("drag_two_sheets_above_midpoint", lambda: check_drag_two_sheets(book, 0.25, 12)),
        ("drag_two_sheets_below_midpoint", lambda: check_drag_two_sheets(book, 0.75, 13)),
        ("drop_in_place_and_escape", lambda: check_drop_in_place_and_escape(book)),
        ("autoscroll", lambda: check_autoscroll(book)),
        ("wheel", lambda: check_wheel(book)),
        ("keys_stay_in_list", lambda: check_keys_stay_in_list(book)),
        ("shortcuts_reach_calc", lambda: check_shortcuts(book)),
        ("menu_right_click", lambda: check_menu_right_click(book)),
        ("menu_keyboard", lambda: check_menu_keyboard(book)),
        ("context_preserves_view_and_picks", lambda: check_context_preserves_view_and_picks(book)),
        ("help_menu", lambda: check_help_menu(book)),
        ("menu_hidden_only", lambda: check_menu_hidden_only(book)),
        ("menu_mixed_visibility", lambda: check_menu_mixed_visibility(book)),
        ("reload_accepts_real_input", lambda: check_reload_accepts_real_input(book)),
        ("plain_click_ends_group", lambda: check_plain_click_ends_group(book)),
        ("single_tap_after_client_pause", lambda: check_single_tap_after_client_pause(book)),
        ("cursor_across_refresh", lambda: check_cursor_across_refresh(book)),
        ("native_cursor_positions", lambda: check_native_cursor_positions(book)),
        ("selected_press_cursor", lambda: check_selected_press_cursor(book)),
        ("drop_after_replacement", lambda: check_drop_after_replacement(book)),
        ("press_then_change", lambda: check_press_then_change(book)),
        ("newer_pick_survives_voided_press", lambda: check_newer_pick_survives_voided_press(book)),
        ("picks_dropped_when_sheets_change", lambda: check_picks_dropped_when_sheets_change(book)),
        (
            "drop_refused_after_unrecorded_batch",
            lambda: check_drop_refused_after_unrecorded_batch(book),
        ),
        ("save_keeps_picks", lambda: check_save_keeps_picks(book)),
        ("actions_refused_while_lock_held", lambda: check_actions_refused_while_lock_held(book)),
        ("click_hidden_before_refresh", lambda: check_click_hidden_before_refresh(book)),
        ("newer_selection_kept", lambda: check_newer_selection_kept(book)),
        ("other_document", lambda: check_other_document(lab, book)),
        ("row_paint_long_names", lambda: check_row_paint_long_names(lab)),
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
        if stalled_callbacks():  # The main thread is stuck: no reset, check, or close (#52).
            raise TimeoutError(stalled_callbacks()[0])
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
        configure_desktop_opener(output)
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
