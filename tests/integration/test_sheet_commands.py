"""Calc's commands in the list's menu, against a real office and the packaged modules.

The real popup model's enablement and reasons, Calc's own labels and command state, and the
command path itself: identity and permission checks when the command runs, exact native targets,
one native undo step, refusal without touching Calc's view, and restoration after a refusal that
follows grouping. Commands whose dialogs need real input (Insert, Rename, Delete with data) are
checked in the real-input UI tests.
"""

from typing import Any
from unittest.mock import patch

from com.sun.star.beans import PropertyValue
from main_thread import close_after

from sheet_manager import uno_menu
from sheet_manager.uno_calc import command_enabled, select_tabs, selected_tabs
from sheet_manager.uno_menu import COMMANDS, DELETE, HIDE, INSERT, RENAME, SHOW, SheetMenu
from sheet_manager.uno_reorder import snapshot
from sheet_manager.uno_structure import monitor_for

SIX = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
EMPTY = {"Delta", "Echo"}  # Calc deletes empty sheets without asking.


def make_book(desktop):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    sheets = document.Sheets
    sheets.getByIndex(0).Name = SIX[0]
    for index, name in enumerate(SIX[1:], 1):
        sheets.insertNewByName(name, index)
    for name in SIX:
        if name not in EMPTY:
            sheets.getByName(name).getCellRangeByName("B1").String = f"identity {name}"
    document.CurrentController.Frame.activate()
    document.UndoManager.clear()
    return document


def states(context, document, picked):
    """The real popup the list shows: {entry: (enabled, reason, label)}."""
    controller = document.CurrentController
    menu = SheetMenu(context, controller.Frame, document, controller)
    popup, _ = menu.build(snapshot(document), picked)
    ids = [popup.getItemId(position) for position in range(popup.getItemCount())]
    return {
        item: (popup.isItemEnabled(item), popup.getTipHelpText(item), popup.getItemText(item))
        for item in ids
        if item
    }


def calc_label(context, command):
    """LibreOffice's own popup label for a Calc command, read independently of the menu."""
    commands = context.getValueByName("/singletons/com.sun.star.frame.theUICommandDescription")
    found = commands.getByName("com.sun.star.sheet.SpreadsheetDocument").getByName(command)
    labels = {item.Name: item.Value for item in found}
    return labels.get("PopupLabel") or labels["Label"]


def view_of(context, document):
    controller = document.CurrentController
    names = list(document.Sheets.ElementNames)
    tabs = [names[index] for index in selected_tabs(context, controller)]
    return controller.ActiveSheet.Name, tabs


def identities(document):
    sheets = document.Sheets
    return {
        sheets.getByIndex(i).Name: sheets.getByIndex(i).getCellRangeByName("B1").String
        for i in range(sheets.Count)
    }


def check_states(context, document, directory, desktop):
    sheets = document.Sheets
    one = states(context, document, ["Charlie"])
    assert all(one[item][0] for item in COMMANDS), one
    assert SHOW not in one, "Show replaces Hide only for hidden targets"
    for item, command in COMMANDS.items():
        # Calc's own labels, in LibreOffice's interface language, with its mnemonics.
        assert one[item][2] == calc_label(context, command), (item, one[item][2])
        assert "~" in one[item][2], "Not Calc's label: the English fallback has no mnemonic"
    two = states(context, document, ["Charlie", "Delta"])
    assert not two[INSERT][0] and "one sheet" in two[INSERT][1], two
    assert not two[RENAME][0] and "one sheet" in two[RENAME][1], two
    assert two[DELETE][0] and two[HIDE][0], two
    everything = states(context, document, SIX)
    assert not everything[DELETE][0] and "visible" in everything[DELETE][1], everything
    assert not everything[HIDE][0] and "visible" in everything[HIDE][1], everything

    sheets.getByName("Charlie").protect("")
    protected = states(context, document, ["Charlie"])
    assert not protected[RENAME][0] and "protected" in protected[RENAME][1], protected
    assert not protected[DELETE][0] and "Protected" in protected[DELETE][1], protected
    assert protected[INSERT][0] and protected[HIDE][0], protected
    sheets.getByName("Charlie").unprotect("")

    sheets.getByName("Foxtrot").IsVisible = False
    mixed = states(context, document, ["Charlie", "Foxtrot"])
    assert HIDE not in mixed and mixed[SHOW][0], mixed
    assert not any(mixed[item][0] for item in (INSERT, DELETE, RENAME)), mixed
    assert "hidden" in mixed[DELETE][1], mixed
    hidden = states(context, document, ["Foxtrot"])
    assert HIDE not in hidden and hidden[SHOW][0], hidden
    assert all("hidden" in hidden[item][1] for item in (INSERT, DELETE, RENAME)), hidden
    sheets.getByName("Foxtrot").IsVisible = True

    document.protect("synthetic")
    structure = states(context, document, ["Charlie"])
    assert all(not structure[i][0] and "protected" in structure[i][1] for i in COMMANDS)
    document.unprotect("synthetic")
    document.RecordChanges = True
    recorded = states(context, document, ["Charlie"])
    assert not recorded[DELETE][0] and "recorded" in recorded[DELETE][1], recorded
    assert recorded[RENAME][0] and recorded[INSERT][0] and recorded[HIDE][0], recorded
    document.RecordChanges = False

    path = directory / "sheet-commands-readonly.ods"
    document.storeToURL(path.as_uri(), ())
    argument = PropertyValue()
    argument.Name, argument.Value = "ReadOnly", True
    readonly = desktop.loadComponentFromURL(path.as_uri(), "_blank", 0, (argument,))
    try:
        found = states(context, readonly, ["Charlie"])
        assert all(not found[i][0] and "read-only" in found[i][1] for i in COMMANDS), found
    except BaseException as failure:
        close_after(context, readonly, failure)
        raise
    close_after(context, readonly)
    document.CurrentController.Frame.activate()
    document.UndoManager.clear()
    return {"enablement_and_reasons": True, "calc_labels": True}


def check_native_state(context, document):
    """Calc's own state follows the grouped tabs synchronously: Rename needs one tab."""
    frame = document.CurrentController.Frame
    select_tabs(context, frame, [2, 3])
    grouped = {command: command_enabled(context, frame, command) for command in COMMANDS.values()}
    select_tabs(context, frame, [2])
    single = command_enabled(context, frame, COMMANDS[RENAME])
    select_tabs(context, frame, [0])
    assert not grouped[COMMANDS[RENAME]] and grouped[COMMANDS[DELETE]], grouped
    assert single, "Calc's Rename state did not follow a single selected tab"
    return {"grouped": grouped, "single_rename": single}


def run(context, document, item, picked, observed=None, unchanged=None):
    controller = document.CurrentController
    monitor = monitor_for(document)
    structure = monitor.generation
    observed = observed or snapshot(document)
    menu = SheetMenu(context, controller.Frame, document, controller)
    return menu.run(item, observed, picked, unchanged or (lambda: monitor.check() == structure))


def check_commands(context, document):
    controller, frame = document.CurrentController, document.CurrentController.Frame
    sheets, undo = document.Sheets, document.UndoManager
    evidence: dict[str, Any] = {}

    def grouped_elsewhere():
        # The viewed sheet, Calc's tab group and the targets all differ.
        controller.setActiveSheet(sheets.getByName("Alfa"))
        select_tabs(context, frame, [0, 5])
        return view_of(context, document)

    grouped_elsewhere()
    assert run(context, document, HIDE, ["Bravo", "Delta"]) == ""
    hidden = [name for name in SIX if not sheets.getByName(name).IsVisible]
    evidence["hide"] = {"hidden": hidden, "undo": list(undo.AllUndoActionTitles)}
    assert hidden == ["Bravo", "Delta"] and len(undo.AllUndoActionTitles) == 1, evidence
    undo.undo()
    assert all(sheets.getByName(name).IsVisible for name in SIX)
    undo.clear()

    grouped_elsewhere()
    before = identities(document)
    assert run(context, document, DELETE, ["Delta", "Echo"]) == ""
    after = identities(document)
    evidence["delete"] = {"names": list(after), "undo": list(undo.AllUndoActionTitles)}
    expected = {name: text for name, text in before.items() if name not in EMPTY}
    assert after == expected and len(undo.AllUndoActionTitles) == 1, evidence
    undo.undo()
    assert identities(document) == before, "One undo did not bring back the deleted sheets"
    undo.clear()
    return evidence


def check_refusals(context, document):
    controller, frame = document.CurrentController, document.CurrentController.Frame
    sheets, undo = document.Sheets, document.UndoManager
    evidence: dict[str, Any] = {}

    def setup():
        controller.setActiveSheet(sheets.getByName("Alfa"))
        select_tabs(context, frame, [0, 5])
        undo.clear()
        return view_of(context, document), identities(document)

    # A replaced target: the structure generation moved.
    before = setup()
    monitor = monitor_for(document)
    structure = monitor.generation
    observed = snapshot(document)
    sheets.removeByName("Charlie")
    sheets.insertNewByName("Charlie", 2)
    titles = list(undo.AllUndoActionTitles)
    reason = run(
        context, document, HIDE, ["Charlie"], observed, lambda: monitor.check() == structure
    )
    assert reason and sheets.getByName("Charlie").IsVisible, reason
    assert list(undo.AllUndoActionTitles) == titles and view_of(context, document) == before[0]
    evidence["replaced"] = reason
    while undo.isUndoPossible():
        undo.undo()
    sheets.getByName("Charlie").getCellRangeByName("B1").String = "identity Charlie"

    # A renamed target: nothing inserted or deleted, but its handle has another name now.
    before = setup()
    observed = snapshot(document)
    sheets.getByName("Charlie").Name = "Spare"
    reason = run(context, document, RENAME, ["Charlie"], observed, lambda: True)
    assert reason and view_of(context, document) == before[0], reason
    evidence["renamed"] = reason
    sheets.getByName("Spare").Name = "Charlie"

    # Protected or hidden after the menu opened.
    for change in ("protected", "hidden"):
        before = setup()
        observed = snapshot(document)
        if change == "protected":
            sheets.getByName("Charlie").protect("")
        else:
            sheets.getByName("Charlie").IsVisible = False
        reason = run(context, document, DELETE, ["Charlie"], observed, lambda: True)
        assert reason and "Charlie" in sheets.ElementNames, (change, reason)
        assert view_of(context, document) == before[0], change
        evidence[change] = reason
        sheets.getByName("Charlie").unprotect("")
        sheets.getByName("Charlie").IsVisible = True

    # Calc refusing after grouping: forced through a test-only adapter; no document makes Calc
    # refuse a command that these checks allow.
    before = setup()
    with patch.object(uno_menu, "command_enabled", lambda *args: False):
        reason = run(context, document, HIDE, ["Bravo"])
    assert "does not allow" in reason and sheets.getByName("Bravo").IsVisible, reason
    assert view_of(context, document) == before[0], (before[0], view_of(context, document))
    assert not undo.AllUndoActionTitles and identities(document) == before[1]
    evidence["native_refusal_restores_view"] = True
    return evidence


def exercise(context, desktop, directory, output):
    document = make_book(desktop)
    try:
        result = {
            "states": check_states(context, document, directory, desktop),
            "native_state": check_native_state(context, document),
            "commands": check_commands(context, document),
            "refusals": check_refusals(context, document),
        }
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return result
