"""The adapter itself rejects replaced sheets, without a panel supplying an identity guard.

It also keeps each sheet's own handle when Calc's name lookup cannot tell two names apart (#113).
"""

from typing import Any

from main_thread import close_after
from sheet_list_view import (
    BATCHES,
    LOCKS,
    UNRECORDED,
    cover_batch,
    held_batch,
    on_main_thread,
    release,
    unrecorded_batch,
)
from teardown import run_checks

from sheet_manager import uno_structure
from sheet_manager.rename import plan_renames
from sheet_manager.reorder import plan_move, plan_order
from sheet_manager.sheet_list import tab_color
from sheet_manager.uno_calc import read_rows
from sheet_manager.uno_list import SheetList
from sheet_manager.uno_menu import HIDE, SheetMenu
from sheet_manager.uno_rename import apply_renames
from sheet_manager.uno_reorder import apply_order, is_current, preflight, snapshot
from sheet_manager.uno_show import show_sheets
from sheet_manager.uno_structure import monitor_for

# Names Calc accepts side by side, although its lookup finds the first for both (#113): the fi
# ligature beside fi, and dotless i beside I in English locales.
CONFUSABLE = (("ﬁ", "fi"), ("I", "ı"))


def check_replacement(context, desktop, wrapper):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    try:

        def exercise():
            document.CurrentController.Frame.activate()
            sheets = document.Sheets
            sheets.getByIndex(0).Name = "Alfa"
            for index, name in enumerate(("Bravo", "Charlie", "Delta"), 1):
                sheets.insertNewByName(name, index)
            sheets.getByName("Bravo").getCellRangeByName("A1").String = "original"
            document.UndoManager.clear()
            observed = snapshot(document)
            plan = plan_move(observed.sheets, ["Bravo"], "bottom")
            if wrapper == "unbatched":
                sheets.insertNewByName("Newcomer", 1)
                sheets.getByName("Newcomer").getCellRangeByName("A1").String = "replacement"
                sheets.removeByName("Bravo")
                sheets.getByName("Newcomer").Name = "Bravo"
            elif wrapper in BATCHES:
                cover_batch(document, wrapper)
            elif wrapper.startswith("held "):
                held_batch(document, wrapper.removeprefix("held "))
            else:
                unrecorded_batch(document, wrapper)
            before = tuple(sheets.ElementNames)
            assert before == tuple(sheet.name for sheet in observed.sheets)
            assert all(
                h.Name == s.name for h, s in zip(observed.handles, observed.sheets, strict=True)
            )
            history = tuple(document.UndoManager.AllUndoActionTitles)
            try:
                permission = preflight(context, document, observed, plan)
                result = apply_order(context, document, observed, plan)
            finally:
                if wrapper.startswith("held "):
                    release(document, wrapper.removeprefix("held "))
            assert not permission.allowed and result.status == "refused", (
                wrapper,
                permission,
                result,
            )
            assert "sheet list has changed" in permission.reason
            assert tuple(sheets.ElementNames) == before
            assert tuple(document.UndoManager.AllUndoActionTitles) == history
            assert sheets.getByName("Bravo").getCellRangeByName("A1").String == "replacement"

        on_main_thread(context, exercise)
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)


def check_lifetime(context, desktop):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    held = []
    try:

        def exercise():
            document.CurrentController.Frame.activate()
            document.Sheets.insertNewByName("Second", 1)
            document.Sheets.insertNewByName("Third", 2)
            document.UndoManager.clear()
            original = snapshot(document)
            held.append(original)
            monitor = original.monitor
            assert snapshot(document).monitor is monitor
            frame = document.CurrentController.Frame
            first: Any = SheetList(context, frame, frame.getContainerWindow())
            try:
                second: Any = SheetList(context, frame, frame.getContainerWindow())
                try:
                    assert first._monitor is second._monitor is monitor
                    first.dispose()
                    assert monitor_for(document) is monitor
                    assert second._monitor.check() == original.generation
                finally:
                    second.dispose()
            finally:
                first.dispose()
            # A recorded ordinary edit does not change structural continuity.
            document.Sheets.getByIndex(0).getCellRangeByName("A1").Value = 42
            plan = plan_move(original.sheets, [original.sheets[0].name], "bottom")
            assert preflight(context, document, original, plan).allowed
            assert apply_order(context, document, original, plan).status == "done"
            assert monitor.check() == original.generation, "Own moves must keep the shared proof"
            document.UndoManager.undo()
            assert tuple(document.Sheets.ElementNames) == tuple(s.name for s in original.sheets)
            # The markers prove the own move's Undo (#91); any other Undo still invalidates.
            assert monitor.check() == original.generation
            assert preflight(context, document, original, plan).allowed
            document.UndoManager.undo()  # The cell edit.
            history = tuple(document.UndoManager.AllUndoActionTitles)
            assert not preflight(context, document, original, plan).allowed
            assert apply_order(context, document, original, plan).status == "refused"
            assert tuple(document.UndoManager.AllUndoActionTitles) == history
            fresh = snapshot(document)
            assert fresh.monitor is monitor and fresh.generation != original.generation
            assert apply_order(context, document, fresh, plan).status == "done"

        on_main_thread(context, exercise)
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    original = held[0]
    registry: Any = uno_structure
    assert original.document_id not in registry._MONITORS
    assert original.monitor._document is None
    try:
        original.monitor.check()
    except RuntimeError as error:
        assert "disposed" in str(error)
    else:
        raise AssertionError("A closed document retained usable structural proof")


class _LookupAfterPreflight:
    """Test-only: Calc's lookup seems to find each name's own sheet until a move locks the view.

    Preflight then sees no conflict, so only the check before each call can refuse the move.
    """

    def __init__(self, document):
        self.document = document
        self.sheets = _Lookup(document.getSheets())

    def __getattr__(self, name) -> Any:
        return getattr(self.document, name)

    def getSheets(self):
        return self.sheets

    def lockControllers(self):
        self.sheets.honest = True
        self.document.lockControllers()


class _Lookup:
    def __init__(self, sheets):
        self.real, self.honest = sheets, False

    def __getattr__(self, name) -> Any:
        return getattr(self.real, name)

    def getByName(self, name):
        if self.honest:
            return self.real.getByName(name)
        return self.real.getByIndex(list(self.real.getElementNames()).index(name))


def check_confusable_names(context, desktop, first, second):
    """Rows, Show, Hide, moves and renames act on each sheet of a confusable pair (#113)."""
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    try:
        controller = document.CurrentController
        frame = controller.Frame
        # A fresh window counts as active already; on Windows Calc then has no current view,
        # and undo can do nothing (#108). Come back to it as a user does.
        frame.deactivate()
        frame.activate()
        sheets, undo = document.Sheets, document.UndoManager
        sheets.getByIndex(0).Name = first
        sheets.insertNewByName("Second", 1)
        sheets.getByIndex(1).Name = second  # Calc refuses this name only for a new sheet.
        sheets.insertNewByName("Last", 2)
        names = (first, second, "Last")
        assert tuple(sheets.ElementNames) == names
        # Without the confusion this check proves nothing: Calc's lookup finds the first sheet.
        assert sheets.getByName(second).Name == first, "Calc's lookup now tells the names apart"
        for index, identity in enumerate(("first", "second", "last")):
            sheets.getByIndex(index).getCellRangeByName("A1").String = identity
        sheets.getByIndex(0).TabColor = 0xC00000
        sheets.getByIndex(0).protect("")
        sheets.getByIndex(1).TabColor = 0x0070C0
        sheets.getByIndex(1).IsVisible = False
        controller.setActiveSheet(sheets.getByIndex(2))
        undo.clear()

        def identities():
            return [sheets.getByIndex(i).getCellRangeByName("A1").String for i in range(3)]

        def shown():
            return [bool(sheets.getByIndex(i).IsVisible) for i in range(3)]

        observed = snapshot(document)
        assert [handle.Name for handle in observed.handles] == list(names)
        assert is_current(document, observed), "A confusable pair must not make the list stale"
        rows = [
            (row.name, row.visible, row.protected, row.active, row.color)
            for row in read_rows(controller, observed)
        ]
        assert rows == [
            (first, True, True, False, tab_color(0xC00000)),
            (second, False, False, False, tab_color(0x0070C0)),
            ("Last", True, False, True, None),
        ], rows

        result = show_sheets(context, document, observed, [second])
        assert result.status == "done", result
        assert shown() == [True, True, True] and list(undo.AllUndoActionTitles) == ["Show Sheet"]

        # Moves restore the viewed sheet afterwards; view the second of the pair.
        viewed_after_undo: list[str] = []
        controller.setActiveSheet(observed.handles[1])
        assert controller.ActiveSheet.Name == second
        undo.clear()

        # Calc moves a sheet only by its name, and this name finds the first of the pair.
        observed = snapshot(document)
        plan = plan_move(observed.sheets, [second], "bottom")
        refused = apply_order(context, document, observed, plan)
        assert refused.status == "refused" and "Rename one of them" in refused.message, refused
        assert tuple(sheets.ElementNames) == names and not undo.AllUndoActionTitles

        # When preflight is fooled, the check before each call still stops the move.
        lying = _LookupAfterPreflight(document)
        observed = snapshot(lying)
        plan = plan_move(observed.sheets, [second], "bottom")
        assert preflight(context, lying, observed, plan).allowed
        guarded = apply_order(context, lying, observed, plan)
        assert guarded.status == "failed-restored" and "lookup" in guarded.detail, guarded
        assert tuple(sheets.ElementNames) == names and not undo.AllUndoActionTitles
        assert identities() == ["first", "second", "last"]

        # The first of the pair is the one its name finds, so it moves.
        observed = snapshot(document)
        plan = plan_move(observed.sheets, [first], "bottom")
        moved = apply_order(context, document, observed, plan)
        assert moved.message == "Sheets moved.", moved
        assert controller.ActiveSheet.Name == second
        assert tuple(sheets.ElementNames) == (second, "Last", first)
        assert identities() == ["second", "last", "first"]
        assert list(undo.AllUndoActionTitles) == ["Move Sheets"]
        undo.undo()
        assert tuple(sheets.ElementNames) == names and identities() == ["first", "second", "last"]
        undo.clear()
        viewed_after_undo.append(controller.ActiveSheet.Name)
        controller.setActiveSheet(observed.handles[1])  # Calc's undo views a sheet it moved.

        # The first sheet moves behind the second, which then comes first, and moves itself.
        observed = snapshot(document)
        plan = plan_order(observed.sheets, ("Last", second, first))
        assert [move.name for move in plan.moves] == [first, second]
        moved = apply_order(context, document, observed, plan)
        assert moved.message == "Sheets moved.", moved
        assert controller.ActiveSheet.Name == second
        assert identities() == ["last", "second", "first"]
        assert list(undo.AllUndoActionTitles) == ["Move Sheets"]
        undo.undo()
        assert tuple(sheets.ElementNames) == names and identities() == ["first", "second", "last"]
        undo.clear()
        viewed_after_undo.append(controller.ActiveSheet.Name)
        controller.setActiveSheet(observed.handles[1])  # Calc's undo views a sheet it moved.

        # Calc's Hide, run from the list's menu, on the second of the pair.
        observed = snapshot(document)
        monitor, proof = observed.monitor, observed.generation
        menu = SheetMenu(context, frame, document, controller)
        assert menu.run(HIDE, observed, [second], lambda: monitor.check() == proof) == ""
        assert shown() == [True, False, True], "Hide must hide exactly the second sheet"
        assert len(undo.AllUndoActionTitles) == 1
        undo.clear()

        # A pair that Calc made already does not fail the batch rename's lookup of final names,
        # whether the batch keeps the pair or renames one of it.
        for renames, after in (
            ([("Last", "End")], (first, second, "End")),
            ([(second, "Other"), ("Last", "End")], (first, "Other", "End")),
        ):
            observed = snapshot(document)
            renamed = apply_renames(context, document, observed, plan_renames(names, renames))
            assert renamed.status == "done", renamed
            assert tuple(sheets.ElementNames) == after
            assert identities() == ["first", "second", "last"]
            assert list(undo.AllUndoActionTitles) == ["Rename Sheets"]
            undo.undo()
            assert tuple(sheets.ElementNames) == names
            undo.clear()

        # Calc's own limit, recorded rather than asserted: a formula naming the second sheet.
        cell = sheets.getByIndex(2).getCellRangeByName("B1")
        cell.Formula = f"='{second}'.A1"
        formula = {"formula": cell.Formula, "value": cell.String}
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return {
        "move_refusal": refused.message,
        "viewed_after_undo": viewed_after_undo,
        "formula_naming_second": formula,
    }


def exercise(context, desktop, directory, output):
    confusable = run_checks(
        [
            (
                f"confusable {ascii(first)} and {ascii(second)}",  # The console may lack them.
                lambda f=first, s=second: check_confusable_names(context, desktop, f, s),
            )
            for first, second in CONFUSABLE
        ],
        [],
        lambda document: close_after(context, document),
    )
    run_checks(
        [
            (wrapper, lambda w=wrapper: check_replacement(context, desktop, w))
            for wrapper in ("unbatched", *BATCHES, *UNRECORDED, *(f"held {w}" for w in LOCKS))
        ]
        + [("shared monitor lifetime and undo", lambda: check_lifetime(context, desktop))],
        [],
        lambda document: close_after(context, document),
    )
    return {
        "adapter_replacement_refusals": 12,
        "shared_monitor_lifetime_and_undo": True,
        "confusable_names": confusable,
    }
