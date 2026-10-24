"""Packaged native move controls, public UNO state and robot clicks; shortcuts use real X input."""

from typing import cast

from main_thread import close_after
from sheet_list_view import move_buttons, names, open_list, poll, row_point, selection
from test_sheet_list import Robot

from sheet_manager.reorder import Action, Sheet, target_order

SIX = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]


def exercise(context, desktop, directory, output):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    try:
        sheets = document.Sheets
        sheets.getByIndex(0).Name = SIX[0]
        for index, name in enumerate(SIX[1:], 1):
            sheets.insertNewByName(name, index)
        document.CurrentController.Frame.activate()
        document.UndoManager.clear()
        panel, tree = open_list(context, document)
        buttons = move_buttons(panel)
        assert set(buttons) == {"Top", "Up", "Down", "Bottom"}, buttons
        assert all(button.isVisible() for button in buttons.values())
        robot = Robot(context)
        for action, label in (("top", "Top"), ("up", "Up"), ("down", "Down"), ("bottom", "Bottom")):
            poll(lambda: names(tree) == SIX, "the original sheet order")
            robot.click(tree, row_point(tree, 2))
            robot.click(tree, row_point(tree, 4), modifiers=0x2000)
            poll(lambda: selection(tree, SIX) == [SIX[2], SIX[4]], "two separate picks")
            poll(buttons[label].isEnabled, "the move button to be enabled")
            active = document.CurrentController.ActiveSheet.Name
            before = tuple(document.UndoManager.AllUndoActionTitles)
            expected = list(
                target_order([Sheet(n) for n in SIX], [SIX[2], SIX[4]], cast(Action, action))
            )
            button = buttons[label]
            size = button.getPosSize()
            robot.click(button, (size.Width // 2, size.Height // 2))
            poll(lambda e=expected: list(sheets.ElementNames) == e, "the button's move")
            poll(lambda e=expected: selection(tree, e) == [SIX[2], SIX[4]], "picks after the move")
            assert document.CurrentController.ActiveSheet.Name == active
            assert tuple(document.UndoManager.AllUndoActionTitles) == ("Move Sheets", *before)
            document.UndoManager.undo()
            poll(lambda: list(sheets.ElementNames) == SIX, "one undo restoring the order")
        document.protect("synthetic")
        robot.click(tree, row_point(tree, 2))
        poll(lambda: all(not button.isEnabled() for button in buttons.values()), "disabled moves")
        assert all("protected" in button.getProperty("HelpText") for button in buttons.values())
        document.unprotect("synthetic")
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return {"four_buttons_one_undo": True, "native_names_and_refusal_tooltips": True}
