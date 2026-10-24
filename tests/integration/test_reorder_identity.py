"""The adapter itself rejects replaced sheets, without a panel supplying an identity guard."""

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
from sheet_manager.reorder import plan_move
from sheet_manager.uno_list import SheetList
from sheet_manager.uno_reorder import apply_order, preflight, snapshot
from sheet_manager.uno_structure import monitor_for


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


def exercise(context, desktop, directory, output):
    run_checks(
        [
            (wrapper, lambda w=wrapper: check_replacement(context, desktop, w))
            for wrapper in ("unbatched", *BATCHES, *UNRECORDED, *(f"held {w}" for w in LOCKS))
        ]
        + [("shared monitor lifetime and undo", lambda: check_lifetime(context, desktop))],
        [],
        lambda document: close_after(context, document),
    )
    return {"adapter_replacement_refusals": 12, "shared_monitor_lifetime_and_undo": True}
