"""Observe the sheet list through public UNO only, for the integration and UI tests.

The panel's ``XPanel.getDialog()`` window holds the list's tree control as a child; the tree's
nodes carry the sheet names. No test hook exists in the extension.
"""

import threading
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

import unohelper
from com.sun.star.awt import XCallback
from com.sun.star.frame import XStatusListener
from com.sun.star.lang import IllegalArgumentException
from com.sun.star.util import URL

DECK = "SheetManagerDeck"
PANEL = "SheetManagerPanel"
TREE = "com.sun.star.awt.tree.XTreeControl"
MENU_NS = "{http://openoffice.org/2001/menu}"


class _OnMain(unohelper.Base, XCallback):
    def __init__(self, work):
        self.work, self.done, self.error = work, threading.Event(), None

    def notify(self, aData):
        try:
            self.work()
        except Exception:
            self.error = traceback.format_exc()
        finally:
            self.done.set()


def on_main_thread(context, work, timeout=60):
    """Run `work` on LibreOffice's main thread, as a macro runs; nothing else runs meanwhile.

    The office calls back into this process with its main thread waiting, so the calls `work`
    makes run on that thread: the list cannot refresh halfway through.
    """
    job = _OnMain(work)
    callback = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.AsyncCallback", context
    )
    callback.addCallback(job, None)
    if not job.done.wait(timeout):
        raise AssertionError("The work on LibreOffice's main thread did not finish")
    if job.error:
        raise AssertionError(job.error)


BATCHES = ("lockControllers", "addActionLock", "disableSetModified")
# Unrecorded batches: the lock, and when undo recording comes back on, "after" the unlock or
# "before" it; "mixed" turns it back on before one recorded cell edit under the same lock.
UNRECORDED = tuple(
    f"{lock} {when}"
    for lock in ("lockControllers", "addActionLock")
    for when in ("after", "before", "mixed")
)


def _wrapper(document, wrapper):
    return {
        "lockControllers": (document.lockControllers, document.unlockControllers),
        "addActionLock": (document.addActionLock, document.removeActionLock),
        "disableSetModified": (document.disableSetModified, document.enableSetModified),
    }[wrapper]


def _cover(sheets):
    index = list(sheets.getElementNames()).index("Bravo")
    sheets.insertNewByName("Newcomer", index)
    sheets.getByName("Newcomer").getCellRangeByName("A1").setString("replacement")
    sheets.removeByName("Bravo")
    sheets.getByName("Newcomer").setName("Bravo")


def cover_batch(document, wrapper):
    """Insert a sheet before Bravo, delete Bravo, rename the newcomer to Bravo, in one batch.

    The wrappers are the ones that make LibreOffice report the batch differently: one modify
    notification at the end (`lockControllers`, `addActionLock`) or none
    (`disableSetModified`). The undo notifications still come for each step.
    """
    begin, end = _wrapper(document, wrapper)
    begin()
    try:
        _cover(document.getSheets())
    finally:
        end()


def unrecorded_batch(document, way):
    """`cover_batch` inside a lock with undo recording off: one of `UNRECORDED`.

    LibreOffice then records nothing and sends one modify notification when the lock ends, with
    recording still off ("after"), back on ("before"), or after one recorded edit ("mixed").
    """
    wrapper, when = way.split()
    begin, end = _wrapper(document, wrapper)
    begin()
    try:
        document.IsUndoEnabled = False
        try:
            _cover(document.getSheets())
        finally:
            if when != "after":
                document.IsUndoEnabled = True
        if when == "mixed":
            document.getSheets().getByIndex(0).getCellRangeByName("B1").setString("recorded")
    finally:
        end()
        document.IsUndoEnabled = True


def poll(function, description, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {description}")


def tree_of(panel):
    for child in panel.getWindows():
        if TREE in [kind.typeName for kind in child.getTypes()]:
            return child
    return None


def open_list(context, document):
    """Show the deck for this document and return its panel window and tree control."""
    frame = document.getCurrentController().getFrame()
    frame.activate()
    dispatcher = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.DispatchHelper", context
    )
    dispatcher.executeDispatch(frame, ".uno:SidebarDeck." + DECK, "", 0, ())
    deck = document.getCurrentController().getSidebar().getDecks().getByName(DECK)
    panel = poll(lambda: deck.getPanels().getByName(PANEL).getDialog(), "the panel window")
    tree = poll(lambda: tree_of(panel), "the sheet list's tree control")
    return panel, tree


def root(tree):
    selection = tree.getSelection()
    nodes = selection if isinstance(selection, tuple) else (selection,)
    for node in nodes:
        if node is not None:
            return node.getParent()
    for x in (20, 40, 60):
        for y in (3, 9):
            node = tree.getNodeForLocation(x, y)
            if node is not None:
                return node.getParent()
    return None


def nodes(tree):
    parent = root(tree)
    return [] if parent is None else [parent.getChildAt(i) for i in range(parent.getChildCount())]


def names(tree):
    return [node.DataValue for node in nodes(tree)]


def labels(tree):
    return [node.getDisplayValue() for node in nodes(tree)]


def selection(tree, order):
    selected = tree.getSelection()
    if selected is None:
        return []
    picked = {node.DataValue for node in (selected if isinstance(selected, tuple) else (selected,))}
    return [name for name in order if name in picked]


def row_rect(tree, index, scroll=True):
    """Row `index`'s rectangle, measured again if a refresh replaces the rows meanwhile."""
    deadline = time.monotonic() + 10
    while True:
        node = nodes(tree)[index]
        try:
            if scroll:
                tree.makeNodeVisible(node)
                time.sleep(0.2)
            return tree.getNodeRect(node)
        except IllegalArgumentException:  # The node left the tree in a rebuild.
            if time.monotonic() > deadline:
                raise


def row_point(tree, index, fraction=0.5):
    rect = row_rect(tree, index)
    return rect.X + 12, rect.Y + int(rect.Height * fraction)


def selected_tabs(context, controller):
    reflection = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.reflection.CoreReflection", context
    )
    method = reflection.forName("com.sun.star.sheet.XSelectedSheetsSupplier").getMethod(
        "getSelectedSheets"
    )
    return sorted(method.invoke(controller, ())[0])


class _State(unohelper.Base, XStatusListener):
    def __init__(self):
        self.enabled = None

    def statusChanged(self, State):
        self.enabled = State.IsEnabled

    def disposing(self, Source):
        pass


def enabled_menu_items(context, frame, program: Path):
    """The sheet tab menu's commands that are enabled now, in menu order.

    The built-in menu hides disabled entries, so this is the order keyboard navigation sees.
    """
    menu = program.parent / "share/config/soffice.cfg/modules/scalc/popupmenu/sheettab.xml"
    transformer = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.util.URLTransformer", context
    )
    enabled = []
    for item in ET.parse(menu).getroot().iter(f"{MENU_NS}menuitem"):
        url = URL()
        url.Complete = item.attrib[f"{MENU_NS}id"]
        url = transformer.parseStrict(url)[1]
        dispatcher = frame.queryDispatch(url, "", 0)
        if dispatcher is None:
            continue
        state = _State()
        dispatcher.addStatusListener(state, url)
        dispatcher.removeStatusListener(state, url)
        if state.enabled:
            enabled.append(url.Complete)
    return enabled
