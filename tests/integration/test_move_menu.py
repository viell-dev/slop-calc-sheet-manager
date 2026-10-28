"""Real UNO popup enablement; packaged menu actions use robot input where VCL draws menus."""

from typing import cast

from com.sun.star.beans import PropertyValue
from main_thread import close_after
from sheet_list_view import menu_entries, names, open_list, poll, row_point, selection
from test_sheet_list import VCL_MOD1, VCL_RIGHT, Robot

from sheet_manager.reorder import Action, Sheet, target_order
from sheet_manager.uno_menu import MOVE_IDS, SheetMenu
from sheet_manager.uno_reorder import snapshot

SIX = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]


class MenuProbe(SheetMenu):
    def states(self, observed, picked):
        popup = self._popup()
        self._add_actions(popup, observed, picked)
        return {
            action: (popup.isItemEnabled(item), popup.getTipHelpText(item))
            for item, action in MOVE_IDS.items()
        }


def move_states(context, document, picked):
    """Build the same real UNO popup used by the panel, against the document's permissions."""
    controller = document.CurrentController
    menu = MenuProbe(context, controller.Frame, document, controller)
    return menu.states(snapshot(document), picked)


def exercise(context, desktop, directory, output, *, headless):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    try:
        sheets = document.Sheets
        sheets.getByIndex(0).Name = SIX[0]
        for index, name in enumerate(SIX[1:], 1):
            sheets.insertNewByName(name, index)
        document.CurrentController.Frame.activate()
        document.UndoManager.clear()
        _, tree = open_list(context, document)
        empty = move_states(context, document, [])
        assert all(not enabled for enabled, _ in empty.values())
        edges = move_states(context, document, [SIX[0]])
        assert not edges["top"][0] and not edges["up"][0] and edges["down"][0]
        assert "already in that position" in edges["top"][1]
        robot = Robot(context)
        if headless:
            for index, action in enumerate(("top", "up", "down", "bottom")):
                poll(lambda: names(tree) == SIX, "the original sheet order")
                robot.click(tree, row_point(tree, 2))
                robot.click(tree, row_point(tree, 4), modifiers=VCL_MOD1)
                poll(lambda: selection(tree, SIX) == [SIX[2], SIX[4]], "two separate picks")
                active = document.CurrentController.ActiveSheet.Name
                before = tuple(document.UndoManager.AllUndoActionTitles)
                expected = list(
                    target_order([Sheet(n) for n in SIX], [SIX[2], SIX[4]], cast(Action, action))
                )
                entries = menu_entries(context, document, [SIX[2], SIX[4]])
                robot.click(tree, row_point(tree, 4), buttons=VCL_RIGHT)
                robot.choose(tree, entries, list(MOVE_IDS)[index])
                poll(lambda e=expected: list(sheets.ElementNames) == e, "the menu's move")
                poll(lambda e=expected: selection(tree, e) == [SIX[2], SIX[4]], "picks after move")
                poll(
                    lambda active=active: document.CurrentController.ActiveSheet.Name == active,
                    "view restored",
                )
                assert tuple(document.UndoManager.AllUndoActionTitles) == ("Move Sheets", *before)
                document.UndoManager.undo()
                poll(lambda: list(sheets.ElementNames) == SIX, "one undo restoring the order")
        document.protect("synthetic")
        protected = move_states(context, document, [SIX[2]])
        assert all(not enabled and "protected" in reason for enabled, reason in protected.values())
        document.unprotect("synthetic")
        document.RecordChanges = True
        recorded = move_states(context, document, [SIX[2]])
        assert all(not enabled and "recorded" in reason for enabled, reason in recorded.values())
        document.RecordChanges = False
        path = directory / "move-menu-readonly.ods"
        document.storeToURL(path.as_uri(), ())
        argument = PropertyValue()
        argument.Name, argument.Value = "ReadOnly", True
        readonly = desktop.loadComponentFromURL(path.as_uri(), "_blank", 0, (argument,))
        try:
            states = move_states(context, readonly, [SIX[2]])
            assert all(not enabled and "read-only" in reason for enabled, reason in states.values())
        except BaseException as failure:
            close_after(context, readonly, failure)
            raise
        close_after(context, readonly)
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return {"popup_permissions_and_reasons": True, "robot_menu_moves": headless}
