"""Observe the sheet list through public UNO only, for the integration and UI tests.

The panel's ``XPanel.getDialog()`` window holds the list's tree control as a child; the tree's
nodes carry the sheet names. No test hook exists in the extension.
"""

import time
import xml.etree.ElementTree as ET
from pathlib import Path

import unohelper
from com.sun.star.frame import XStatusListener
from com.sun.star.lang import IllegalArgumentException
from com.sun.star.util import URL

DECK = "SheetManagerDeck"
PANEL = "SheetManagerPanel"
TREE = "com.sun.star.awt.tree.XTreeControl"
MENU_NS = "{http://openoffice.org/2001/menu}"


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
