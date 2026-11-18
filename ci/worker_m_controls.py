"""Research controls for the installed package on a disposable desktop."""

import time

import uno
import unohelper
from com.sun.star.accessibility import XAccessibleEventListener
from sheet_list_view import move_buttons, on_main_thread
from test_accessibility import walk
from xinput import Pointer


def acc(window):
    return window.getProperty("XAccessible").getAccessibleContext()


def constant(group, name):
    return uno.getConstantByName(f"com.sun.star.accessibility.{group}.{name}")


def describe(node):
    location = node.getLocationOnScreen()
    size = node.getBounds()
    return dict(
        role=node.getAccessibleRole(), name=node.getAccessibleName(),
        description=node.getAccessibleDescription(), state=node.getAccessibleStateSet(),
        screen=[location.X, location.Y, size.Width, size.Height],
    )


class Events(unohelper.Base, XAccessibleEventListener):
    def __init__(self):
        self.events = []

    def notifyEvent(self, event):
        self.events.append((time.time(), event.EventId, event.NewValue))

    def disposing(self, source):
        pass

    def report(self):
        results = []
        for stamp, event, value in self.events:
            if not isinstance(value, (str, int, bool, type(None))):
                try:
                    value = value.getAccessibleContext().getAccessibleName()
                except Exception:
                    value = "<object>"
            results.append([stamp, event, value])
        return results


def button(peer):
    data = describe(acc(peer))
    data.update(
        native=peer.getProperty("NativeWidgetLook"),
        high_contrast=peer.getProperty("HighContrastMode"),
        enabled=peer.getProperty("Enabled"),
    )
    return data


def stock_dialog(book, record, marker, screen_reader):
    context = book.lab.context
    manager = context.ServiceManager

    def create(name):
        return manager.createInstanceWithContext(f"com.sun.star.awt.{name}", context)

    def setup():
        model = create("UnoControlDialogModel")
        model.Title = "Stock UNO controls"
        model.PositionX, model.PositionY, model.Width, model.Height = 40, 35, 255, 120
        for index, label in enumerate(("Stock native", "Stock VCL", "Stock set text", "Enabled")):
            ctl = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
            ctl.Label = label
            ctl.PositionX, ctl.PositionY, ctl.Width, ctl.Height = 8 + 62 * index, 8, 58, 15
            ctl.Enabled = index == 3
            if index == 2:
                ctl.TextColor = 0xFF00FF
            model.insertByName(f"button{index}", ctl)
        tree_model = model.createInstance("com.sun.star.awt.tree.TreeControlModel")
        tree_model.PositionX, tree_model.PositionY, tree_model.Width, tree_model.Height = 8, 33, 238, 78
        tree_model.RootDisplayed = False
        data = create("tree.MutableTreeDataModel")
        root = data.createNode("Root", False)
        for name in ("Control Alpha", "Control Bravo", "Control Charlie"):
            root.appendChild(data.createNode(name, False))
        data.setRoot(root)
        tree_model.DataModel = data
        model.insertByName("tree", tree_model)
        dialog = create("UnoControlDialog")
        dialog.setModel(model)
        dialog.createPeer(create("Toolkit"), book.window)
        buttons = [dialog.getControl(f"button{i}").getPeer() for i in range(4)]
        for index in (1, 2):
            buttons[index].setProperty("NativeWidgetLook", False)
        tree = dialog.getControl("tree").getPeer()
        tree.setProperty("AccessibleName", "Stock tree")
        dialog.setVisible(True)
        return dialog, buttons, tree

    def main(work):
        return on_main_thread(context, work)

    result = []
    main(lambda: result.extend(setup()))
    dialog, buttons, tree = result
    try:
        record["stock_buttons"] = [button(peer) for peer in buttons]
        book.lab.screenshot("stock-dialog")
        if screen_reader:
            node = acc(tree)
            events = Events()
            main(lambda: node.addAccessibleEventListener(events))
            try:
                marker("Focus stock tree by click, then Down")
                x, y, _, _ = describe(node)["screen"]
                Pointer(book.lab.input, (0, 0)).click(x + 25, y + 12)
                book.lab.input.tap("Down", pause=0.8)
                if book.lab.input.__class__.__name__ == "WinInput":
                    marker("Report NVDA focus on stock tree via Insert+Tab")
                    book.lab.input.tap("Tab", ("Insert",), pause=0.8)
                marker("Stock tree focus complete")
                record["stock_tree"] = {
                    "tree": describe(node), "events": events.report(),
                    "rows": [describe(node.getAccessibleChild(i).getAccessibleContext())
                             for i in range(node.getAccessibleChildCount())],
                }
            finally:
                main(lambda: node.removeAccessibleEventListener(events))
    finally:
        main(dialog.dispose)


def sidebar_before(book, record):
    record["initial_move_buttons"] = [button(peer) for peer in move_buttons(book.panel).values()]
    book.lab.screenshot("sidebar-initial")
    node = acc(book.tree)
    events = Events()
    on_main_thread(book.lab.context, lambda: node.addAccessibleEventListener(events))
    return node, events


def sidebar_after(book, record, node, events):
    on_main_thread(book.lab.context, lambda: node.removeAccessibleEventListener(events))
    record["sidebar_tree"] = {
        "tree": describe(node), "events": events.report(),
        "rows": [describe(node.getAccessibleChild(i).getAccessibleContext())
                 for i in range(node.getAccessibleChildCount())],
        "hierarchy": walk(book.lab.context, book.panel, book.tree),
    }


def rename_candidates(book, dialog, record, marker):
    name = acc(dialog.name)
    status = acc(dialog.status)
    listener = Events()
    for node in (name, status):
        node.addAccessibleEventListener(listener)
    try:
        record["candidate_before"] = [describe(name), describe(status)]
        # Use distinct speech markers so a subsequent focus query cannot count as success.
        marker("Candidate focused edit HelpText update")
        dialog.name.setProperty("HelpText", "Validation help. Another sheet is already named this.")
        marker("Candidate focused edit AccessibleName update")
        dialog.name.setProperty("AccessibleName", "New name. Validation name. Another sheet is already named this.")
        marker("Candidate status control AccessibleName update")
        dialog.status.setProperty("AccessibleName", "Validation status. Another sheet is already named this.")
        marker("Candidate observations complete")
        record["candidate_after"] = [describe(name), describe(status)]
        record["candidate_events"] = listener.report()
    finally:
        for node in (name, status):
            node.removeAccessibleEventListener(listener)
        dialog.name.setProperty("AccessibleName", "")
        dialog.name.setProperty("HelpText", "The selected sheet's new name.")
        dialog.status.setProperty("AccessibleName", "")
