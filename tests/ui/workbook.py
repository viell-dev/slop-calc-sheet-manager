"""The synthetic workbook and the lab-neutral helpers that every real-input check shares.

`run_ui.py` (Xvfb, gtk3 and gen) and `run_windows_ui.py` (a visible Windows desktop, #114) run
the same checks, so a check reaches the desktop only through its lab: `lab.input` (keysym names,
`popup_windows`, `modal_dialog`), `lab.place`, `lab.calibrate`, `lab.screenshot` and
`lab.failure_evidence`, never through X11 tools or Windows calls directly. Checks observe only
public UNO: the panel's `XPanel.getDialog()` window, its child tree control, the document, and
its undo manager. Each check takes the open `Workbook` or its lab, returns evidence and raises
AssertionError on failure; `reset` restores the 80-sheet workbook between checks.

Nothing here imports a runner: a check module imports what it needs from this module, `lab.py`
and its siblings, and the runners import the checks.
"""

import time

import sheet_list_view as view
import unohelper
from com.sun.star.awt import XMouseListener
from main_thread import close_document
from run import wait_for
from xinput import Pointer

from sheet_manager.uno_calc import select_tabs
from sheet_manager.uno_menu import DELETE, HIDE, INSERT, MOVE_IDS, RENAME, RENAME_SHEETS

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
ENTRY_NAMES = {
    INSERT: "insert",
    DELETE: "delete",
    RENAME: "rename",
    RENAME_SHEETS: "rename-sheets",
    HIDE: "hide",
}
MOVES = {action: item for item, action in MOVE_IDS.items()}


class PressProbe(unohelper.Base, XMouseListener):
    """When the tree's mouse listeners heard each button press and release.

    VCL notifies a window's mouse listeners in one callback that it posts to the main thread.
    Listener containers notify the most recently added first, so this probe hears a press
    before the list's own listener has run; `Workbook.hold` waits for the rest of the callback.
    """

    def __init__(self):
        self.heard = []

    def mousePressed(self, event):
        self.heard.append(("pressed", time.monotonic()))

    def mouseReleased(self, event):
        self.heard.append(("released", time.monotonic()))

    def mouseEntered(self, event):
        pass

    def mouseExited(self, event):
        pass

    def disposing(self, event):
        pass


class Workbook:
    def __init__(self, lab, title, names, stored=True):
        """A synthetic workbook with the list open, stored unless `stored` is false."""
        self.lab = lab
        self.path = lab.directory / f"{title}.ods"
        document = lab.desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
        sheets = document.getSheets()
        sheets.getByIndex(0).setName(names[0])
        for index, name in enumerate(names[1:], start=1):
            sheets.insertNewByName(name, index)
        sheets.getByIndex(0).getCellRangeByName("A1").setString("keep")
        if stored:
            document.storeAsURL(self.path.as_uri(), ())
        document.getUndoManager().clear()
        self.document = document
        self.controller = document.getCurrentController()
        self.frame = self.controller.getFrame()
        self.window = self.frame.getContainerWindow()
        lab.place(self.window)
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

    def hold(self, index, probe=None):
        """Press the button on a row and keep it down; return once the list has handled it.

        The tree selects the row natively, then VCL posts the mouse listeners' callback, which
        runs without the solar mutex. A selection alone therefore does not show that the list
        knows of the press: an API change made before its listener has run reaches the list
        first, and the list rightly counts the press as newer input (#134). Once a probe has
        heard the press, a round trip to the main thread returns only after that callback, and
        so the list's listener, has finished. `probe`, a `PressProbe` already added to the
        tree, is used instead of a temporary one.
        """
        own = probe is None
        if own:
            probe = PressProbe()
            self.tree.addMouseListener(probe)
        try:
            heard = len(probe.heard)
            self.pointer.press(*self.point(index))
            wait_until(
                lambda: any(kind == "pressed" for kind, _ in probe.heard[heard:]),
                "the tree's listeners to hear the press",
            )
            view.on_main_thread(self.lab.context, lambda: None)
        finally:
            if own:
                self.tree.removeMouseListener(probe)

    def focus_list(self):
        """Click the active sheet's row: the list gets the focus, nothing else changes."""
        self.click(self.order().index(self.active()))

    def click_control(self, control):
        """Click the middle of another panel control, placed from the tree's calibration."""
        bounds, tree = control.getPosSize(), self.tree.getPosSize()
        offset = (
            self.pointer.offset[0] + bounds.X - tree.X,
            self.pointer.offset[1] + bounds.Y - tree.Y,
        )
        Pointer(self.lab.input, offset).click(bounds.Width // 2, bounds.Height // 2)

    def double_click(self, index):
        point = self.point(index)
        self.pointer.click(*point, pause=0.02)
        self.pointer.click(*point)

    def move_action(self, action):
        """Open the real menu and select one of its enabled move actions."""
        picked = self.selection()
        entries = self.entries(picked)
        self.lab.input.tap("Menu", pause=0.4)
        self.choose(MOVES[action], entries)
        wait_until(lambda: self.selection() == picked, "menu picks restored")

    def entries(self, targets):
        """The menu's enabled entries for these targets, from the menu's own code."""
        return view.menu_entries(self.lab.context, self.document, targets)

    def choose(self, item, entries):
        """Choose an entry of the open menu with the keyboard, among its enabled `entries`.

        End reaches Help, always the last entry, in gtk3 and gen; Home does not when the
        first entries are unavailable (#84). Up skips separators and unavailable entries.
        """
        self.lab.input.tap("End")
        for _ in range(len(entries) - 1 - entries.index(item)):
            self.lab.input.tap("Up")
        self.lab.screenshot(f"menu-{ENTRY_NAMES.get(item, item)}")
        self.lab.input.tap("Return", pause=0.5)
        return entries

    def close(self):
        close_document(self.lab.context, self.document)


def wait_until(function, what, timeout=10):
    return wait_for(function, what, timeout=timeout)


def native_dialog(book):
    """A dialog over the frame: GTK's is found natively, gen's as a shown VCL dialog."""
    if book.lab.input.modal_dialog():
        return True
    toolkit = book.lab.context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.Toolkit", book.lab.context
    )
    windows = [toolkit.getTopWindow(i) for i in range(toolkit.getTopWindowCount())]
    return any(
        window != book.window
        and window.isVisible()
        and "com.sun.star.awt.XDialog2" in [kind.typeName for kind in window.getTypes()]
        for window in windows
    )


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
