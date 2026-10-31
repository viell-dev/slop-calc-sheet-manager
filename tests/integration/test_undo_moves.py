"""Undo and Redo of the list's own moves keep its picks and the view; nothing else does (#91).

The packaged panel is driven through public UNO and robot clicks, as in `test_move_buttons`;
Undo and Redo are `.uno:Undo` and `.uno:Redo` dispatched to the frame, as Ctrl+Z and Ctrl+Y
run them, or `XUndoManager` calls from this process, which LibreOffice runs on a bridge thread.
The real-input drag and Ctrl+Z of the owner's report is `tests/ui/run_ui.py`'s
`undo_own_move` check. Every case that must not keep the picks is one in which a pick could
otherwise reach another sheet, or one the markers cannot prove: they clear conservatively and
show the panel's notice, as before. Each undo capacity gets new workbooks: lowering it for an
open document can make Calc abort on Undo (#37).
"""

import time
from types import SimpleNamespace
from typing import Any

from main_thread import close_document
from sheet_list_view import (
    footer_text,
    move_buttons,
    names,
    on_main_thread,
    open_list,
    poll,
    row_point,
    selected_tabs,
    selection,
    unrecorded_batch,
)
from teardown import run_checks
from test_reorder import FaultyDocument, FaultySheets, undo_capacity
from test_sheet_list import VCL_SHIFT, Robot

from sheet_manager.reorder import Action, plan_move
from sheet_manager.uno_calc import select_tabs
from sheet_manager.uno_reorder import apply_order, is_current, snapshot

TWELVE = [
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
]
PICKS = TWELVE[4:8]  # Echo to Hotel.
UP = TWELVE[:3] + PICKS + [TWELVE[3]] + TWELVE[8:]  # One move: Delta below Hotel.
TOP = PICKS + TWELVE[:4] + TWELVE[8:]  # Four moves.
SETTLE = 1.5  # Longer than the list's refresh delay and the view sampling interval.
_CREATED: list[Any] = []


def say(text):
    print("   ", text, flush=True)


def workbook(desktop):
    """Twelve sheets, Kilo active and the only selected tab, an empty undo history."""
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    _CREATED.append(document)
    sheets = document.Sheets
    sheets.getByIndex(0).Name = TWELVE[0]
    for index, name in enumerate(TWELVE[1:], 1):
        sheets.insertNewByName(name, index)
    controller = document.CurrentController
    controller.Frame.activate()
    controller.setActiveSheet(sheets.getByName("Kilo"))
    document.UndoManager.clear()
    return document


def close(context, document):
    close_document(context, document)
    _CREATED.remove(document)


def order(document):
    return list(document.Sheets.ElementNames)


def dispatch(context, frame, command):
    helper = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.DispatchHelper", context
    )
    helper.executeDispatch(frame, command, "", 0, ())


def make_current(document, controller):
    """Activate a window and make its controller the document's current one, as a click does.

    Headless sessions do not switch the current controller on frame activation alone.
    """
    controller.Frame.activate()
    document.setCurrentController(controller)
    poll(lambda: document.CurrentController == controller, "the window to be current")


def view(context, controller):
    """The view as names: the active sheet and Calc's selected tabs."""
    sheets = list(controller.Model.Sheets.ElementNames)
    tabs = [sheets[index] for index in selected_tabs(context, controller)]
    return controller.ActiveSheet.Name, tabs


class Panel:
    """The sheet list of one document window, through its public panel window."""

    def __init__(self, context, document):
        self.document = document
        self.panel, self.tree = open_list(context, document)
        self.robot = Robot(context)
        poll(lambda: names(self.tree) == order(document), "the list's rows")

    def picks(self):
        return selection(self.tree, order(self.document))

    def notice(self):
        return bool(footer_text(self.panel, "Why the sheet list").getText())

    def pick(self, first, last=None):
        rows = order(self.document)
        poll(lambda: names(self.tree) == rows, "the list's rows before picking")
        self.robot.click(self.tree, row_point(self.tree, rows.index(first)))
        if last is not None:
            point = row_point(self.tree, rows.index(last))
            self.robot.click(self.tree, point, modifiers=VCL_SHIFT)
        wanted = rows[rows.index(first) : rows.index(last or first) + 1]
        try:
            poll(lambda: self.picks() == wanted, f"the picks {wanted}")
        except AssertionError as error:
            shown = {"picks": self.picks(), "rows": names(self.tree), "focus": self.tree.hasFocus()}
            raise AssertionError(f"{error}: {shown}") from None

    def move(self, label, expected):
        button = move_buttons(self.panel)[label]
        poll(button.isEnabled, f"the {label} button to be enabled")
        size = button.getPosSize()
        self.robot.click(button, (size.Width // 2, size.Height // 2))
        poll(lambda: order(self.document) == expected, f"the {label} move")


def replay(context, document, command, way="dispatch"):
    if way == "dispatch":
        dispatch(context, document.CurrentController.Frame, f".uno:{command}")
    elif command == "Undo":
        document.UndoManager.undo()
    else:
        document.UndoManager.redo()


def assert_kept(context, panel, picks, shown, expected_order):
    """After settling: the order, the same picks, the same view, and no notice."""
    document = panel.document
    poll(lambda: order(document) == expected_order, "the replayed order")
    time.sleep(SETTLE)
    controller = document.CurrentController
    state = {"picks": panel.picks(), "view": view(context, controller), "notice": panel.notice()}
    assert state == {"picks": picks, "view": shown, "notice": False}, state
    return state


def assert_cleared(panel, why, picks=PICKS):
    """The picks went, as before #91; the list may follow the view Calc left instead."""
    poll(lambda: panel.picks() != picks, f"the picks to go after {why}")
    time.sleep(SETTLE)
    assert panel.notice(), f"No notice after {why}"
    return {"picks": panel.picks(), "notice": True}


def check_owner_case(context, desktop):
    """The owner's sequence, with Undo and Redo dispatched and from another thread."""
    results = {}
    for capacity, label, moved in ((100, "Up", UP), (2, "Top", TOP), (2, "Up", UP)):
        with undo_capacity(context, capacity):
            say(f"undo capacity {capacity}, {label}")
            document = workbook(desktop)
            panel = Panel(context, document)
            panel.pick("Echo", "Hotel")
            panel.move(label, moved)
            shown = ("Kilo", ["Kilo"])
            states = [assert_kept(context, panel, PICKS, shown, moved)]
            for command, way, expected in (
                ("Undo", "dispatch", TWELVE),
                ("Redo", "dispatch", moved),
                ("Undo", "api", TWELVE),
                ("Redo", "api", moved),
                ("Undo", "dispatch", TWELVE),
            ):
                replay(context, document, command, way)
                states.append(assert_kept(context, panel, PICKS, shown, expected))
            # What a replay keeps is the view just before it, not the one the move was made in.
            controller = document.CurrentController
            controller.setActiveSheet(document.Sheets.getByName("Alfa"))
            select_tabs(context, controller.Frame, [0, 1])
            group = ("Alfa", ["Alfa", "Bravo"])
            poll(lambda c=controller, g=group: view(context, c) == g, "a native tab group")
            time.sleep(SETTLE)
            picks = panel.picks()  # The list follows a group Calc selected.
            replay(context, document, "Redo")
            states.append(assert_kept(context, panel, picks, group, moved))
            results[f"{capacity} {label}"] = states
            close(context, document)
    return results


def check_titled_replacement(context, document, panel):
    """Adversarial: another group titled as the own move's, unreported when undone.

    The group inserts a newcomer after Bravo, deletes Bravo and renames the newcomer Bravo; the
    newcomer is then picked. Undoing the group deletes the newcomer and brings the old Bravo
    back under the same name, and under `disableSetModified` the Undo reports only itself. The
    picked sheet is gone, so the list must drop its pick and say so. Calc's Undo activates the
    restored Bravo, and the list follows it after dropping, so the row alone proves nothing; the
    notice does. Measured with 26.8.1.1: a monitor that trusts the title alone keeps the
    generation, and the pick then goes without a notice.
    """
    sheets, undo = document.Sheets, document.UndoManager

    def replace():
        undo.enterUndoContext("Move Sheets")
        sheets.insertNewByName("Newcomer", order(document).index("Bravo") + 1)
        sheets.getByName("Newcomer").getCellRangeByName("A1").String = "replacement"
        sheets.removeByName("Bravo")
        sheets.getByName("Newcomer").Name = "Bravo"
        undo.leaveUndoContext()

    on_main_thread(context, replace)
    poll(lambda: names(panel.tree) == TWELVE, "the rows after the replacement")
    time.sleep(SETTLE)
    panel.pick("Bravo")
    assert sheets.getByName("Bravo").getCellRangeByName("A1").String == "replacement"
    assert tuple(undo.AllUndoActionTitles) == ("Move Sheets",)

    def quiet_undo():
        document.disableSetModified()
        try:
            undo.undo()
        finally:
            document.enableSetModified()

    poll(lambda: not panel.notice(), "no notice before the Undo", timeout=15)
    on_main_thread(context, quiet_undo)
    assert sheets.getByName("Bravo").getCellRangeByName("A1").String == ""
    # Calc's Undo activates the restored Bravo, and a list that dropped the pick follows it, so
    # the row alone proves nothing: the notice shows that the picked newcomer was dropped.
    poll(panel.notice, "the notice that the newcomer's pick was dropped")
    time.sleep(SETTLE)
    controller = document.CurrentController
    tabs = view(context, controller)[1]
    assert panel.picks() in ([], tabs), (panel.picks(), tabs)
    return {"picks": panel.picks(), "calc_tabs": tabs, "notice": True}


def check_conservative(context, desktop):
    """What still clears: the old behaviour, now only where continuity is not proved."""

    def own_move():
        document = workbook(desktop)
        panel = Panel(context, document)
        panel.pick("Echo", "Hotel")
        panel.move("Up", UP)
        time.sleep(SETTLE)
        assert panel.picks() == PICKS
        return document, panel

    def intervening_insertion():
        document, panel = own_move()
        document.Sheets.insertNewByName("Newcomer", 0)
        document.UndoManager.undo()
        cleared = assert_cleared(panel, "the insertion's Undo")
        panel.pick("Echo", "Hotel")
        replay(context, document, "Undo")
        poll(lambda: order(document) == TWELVE, "the move's Undo")
        return document, [cleared, assert_cleared(panel, "an Undo the insertion revoked")]

    def unrecorded_replacement():
        """Measured: turning undo recording off clears Calc's undo history, so no unrecorded
        edit can come between the move and its Undo; `XUndoManager.lock` does not stop Calc
        recording sheet edits. The picks go, and there is no move left to undo."""
        document, panel = own_move()
        on_main_thread(context, lambda: unrecorded_batch(document, "lockControllers after"))
        cleared = assert_cleared(panel, "an unrecorded replacement")
        undo = document.UndoManager
        assert not undo.isUndoPossible() and tuple(undo.AllUndoActionTitles) == ()
        assert document.Sheets.getByName("Bravo").getCellRangeByName("A1").String == "replacement"
        return document, cleared

    def hidden_context():
        document, panel = own_move()
        undo = document.UndoManager

        def hidden():
            undo.enterHiddenUndoContext()
            document.Sheets.getByName("Alfa").getCellRangeByName("C3").Value = 7
            undo.leaveUndoContext()

        on_main_thread(context, hidden)
        time.sleep(SETTLE)
        assert panel.picks() == PICKS, "A cell edit alone is not structural"
        replay(context, document, "Undo")
        poll(lambda: order(document) == TWELVE, "the merged group's Undo")
        assert document.Sheets.getByName("Alfa").getCellRangeByName("C3").Value == 0
        return document, assert_cleared(panel, "the merged group's Undo")

    def native_move():
        document = workbook(desktop)
        panel = Panel(context, document)
        panel.pick("Echo", "Hotel")
        document.Sheets.moveByName("Kilo", 0)
        time.sleep(SETTLE)
        assert panel.picks() == PICKS
        assert tuple(document.UndoManager.AllUndoActionTitles) == ("Move Sheets",)
        replay(context, document, "Undo")
        poll(lambda: order(document) == TWELVE, "the native move's Undo")
        return document, assert_cleared(panel, "a native move's Undo")

    def titled_replacement():
        document = workbook(desktop)
        return document, check_titled_replacement(context, document, Panel(context, document))

    results = {}
    for name, case in (
        ("intervening insertion", intervening_insertion),
        ("unrecorded replacement", unrecorded_replacement),
        ("hidden context", hidden_context),
        ("native move", native_move),
        ("titled replacement", titled_replacement),
    ):
        say(name)
        document, results[name] = case()
        close(context, document)
    return results


def check_adapter_history(context, desktop):
    """Snapshots across own replays, failures and their rollback, capacity one, Redo."""

    def run(document, observed, selected, action: Action = "top", target=None):
        plan = plan_move(observed.sheets, selected, action)
        return apply_order(context, target or document, observed, plan)

    def snapshots(document, capacity):
        say("a held snapshot is current again after an own Undo, and after its Redo")
        undo = document.UndoManager
        original = snapshot(document)
        assert run(document, original, ["Hotel", "India"]).status == "done"
        moved = snapshot(document)
        assert moved.generation == original.generation
        undo.undo()
        assert order(document) == TWELVE and is_current(document, original)
        undo.redo()
        assert is_current(document, moved)
        say("a new action clears Redo; undoing that action moves the generation")
        undo.undo()
        document.Sheets.getByName("Alfa").getCellRangeByName("B2").Value = 3
        assert not undo.isRedoPossible()
        undo.undo()
        assert not is_current(document, original)

    def failures(document, capacity):
        say("a failed move is rolled back and clears conservatively")
        undo = document.UndoManager
        for step in (1, 2, 4):
            undo.clear()
            observed = snapshot(document)
            wrapped = FaultyDocument(document, FaultySheets(document.Sheets, step))
            selected = ["Hotel", "India", "Juliett", "Kilo"]
            result = run(document, observed, selected, target=wrapped)
            assert result.status == "failed-restored", result
            assert order(document) == TWELVE
            assert tuple(undo.AllUndoActionTitles) == ()
            assert tuple(undo.AllRedoActionTitles) == ()
            assert not is_current(document, observed), "A rollback is no own Undo"
        if capacity <= 2:
            return  # Opening any context at a full history evicts its oldest entry (native).
        say("a failure before the first move removes the markers' group again")
        undo.clear()
        cell = document.Sheets.getByName("Alfa").getCellRangeByName("B3")
        cell.Value = 1
        cell.Value = 2
        undo.undo()  # The user's Redo, which the markers' group costs (docs/reordering.md).
        history = tuple(undo.AllUndoActionTitles)
        for options in ({"before": True}, {"silent": True}):
            observed = snapshot(document)
            wrapped = FaultyDocument(document, FaultySheets(document.Sheets, 1, **options))
            result = run(document, observed, ["Hotel"], target=wrapped)
            assert result.status == "failed-restored", (options, result)
            assert tuple(undo.AllUndoActionTitles) == history, options
            assert tuple(undo.AllRedoActionTitles) == (), options
            assert cell.Value == 1 and order(document) == TWELVE

    def one_step(document, capacity):
        say("with one undo step there is no room for markers: Undo clears as before")
        undo = document.UndoManager
        observed = snapshot(document)
        assert run(document, observed, ["Hotel"], "up").status == "done"
        assert tuple(undo.AllUndoActionTitles) == ("Move Sheets",)
        undo.undo()
        assert order(document) == TWELVE and not is_current(document, observed)

    results = {}
    for capacity, checks in ((100, (snapshots, failures)), (2, (failures,)), (1, (one_step,))):
        with undo_capacity(context, capacity):
            document = workbook(desktop)
            for check in checks:
                on_main_thread(context, lambda c=check, d=document, n=capacity: c(d, n))
                results[f"{check.__name__} {capacity}"] = True
            close(context, document)
    return results


def check_windows_and_disposal(context, desktop):
    """A second window keeps its own view; disposal of the panel or the document is safe."""
    results = {}
    document = workbook(desktop)
    panel = Panel(context, document)
    first = document.CurrentController
    # Opening a window can move the generation (`test_sync_sheet_list`): a move made before it
    # is no longer provable, so the windows exist before the move.
    dispatch(context, first.Frame, ".uno:NewWindow")
    controllers = []
    enumeration = document.getControllers()
    while enumeration.hasMoreElements():
        controllers.append(enumeration.nextElement())
    second = next(controller for controller in controllers if controller != first)
    second.setActiveSheet(document.Sheets.getByName("Bravo"))
    poll(lambda: view(context, second) == ("Bravo", ["Bravo"]), "the second window's view")
    shown = SimpleNamespace(getCurrentController=lambda: second, Sheets=document.Sheets)
    other = Panel(context, shown)
    make_current(document, first)
    panel = Panel(context, document)  # Opening a window can replace this one's panel window.
    poll(lambda: not panel.notice(), "a notice from opening the window to expire", timeout=15)
    panel.pick("Echo", "Hotel")
    panel.move("Up", UP)
    other.pick("Golf")
    picks = panel.picks()
    assert picks == PICKS

    say("Undo in the first window: the second keeps its view")
    make_current(document, first)
    replay(context, document, "Undo")
    assert_kept(context, panel, picks, ("Kilo", ["Kilo"]), TWELVE)
    assert view(context, second) == ("Bravo", ["Bravo"])
    assert other.picks() == ["Golf"] and not other.notice()

    say("Redo in the second window: each window keeps its own view, and the picks stay")
    make_current(document, second)
    dispatch(context, second.Frame, ".uno:Redo")
    poll(lambda: order(document) == UP, "the Redo in the second window")
    time.sleep(SETTLE)
    assert view(context, second) == ("Bravo", ["Bravo"]), view(context, second)
    assert view(context, first) == ("Kilo", ["Kilo"]), view(context, first)
    assert panel.picks() == picks and not panel.notice()
    results["two_windows"] = True
    make_current(document, first)

    say("Undo after the sidebar closed keeps the view; the list starts afresh")
    sidebar = first.getSidebar()
    dispatch(context, first.Frame, ".uno:Sidebar")
    poll(lambda: not sidebar.isVisible(), "a closed sidebar")
    replay(context, document, "Undo")
    poll(lambda: order(document) == TWELVE, "the Undo without a panel")
    time.sleep(SETTLE)
    assert view(context, first) == ("Kilo", ["Kilo"]), view(context, first)
    Panel(context, document)
    results["without_panel"] = True

    say("closing the document right after Redo and Undo")

    def replay_and_close():
        document.UndoManager.redo()
        document.UndoManager.undo()
        document.close(True)

    _CREATED.remove(document)
    on_main_thread(context, replay_and_close)
    time.sleep(SETTLE)  # The posted restorations find the document gone.
    results["closed"] = True
    return results


def exercise(context, desktop, directory, output):
    return run_checks(
        (
            ("owner case", lambda: check_owner_case(context, desktop)),
            ("conservative", lambda: check_conservative(context, desktop)),
            ("adapter history", lambda: check_adapter_history(context, desktop)),
            ("windows and disposal", lambda: check_windows_and_disposal(context, desktop)),
        ),
        _CREATED,
        lambda document: close_document(context, document),
        label="undo of own moves",
    )
