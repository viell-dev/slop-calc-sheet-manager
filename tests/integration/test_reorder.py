"""Live moves, reference integrity, permissions, and partial-failure recovery."""

import json
import statistics
import time
from contextlib import contextmanager
from typing import Any, cast

import uno
from com.sun.star.awt import Rectangle
from com.sun.star.beans import PropertyValue

from sheet_manager.reorder import Action, plan_move, plan_order
from sheet_manager.uno_reorder import apply_order, preflight, snapshot


def prop(name, value):
    item = PropertyValue()
    item.Name, item.Value = name, value
    return item


def order(document):
    return tuple(document.Sheets.ElementNames)


@contextmanager
def undo_capacity(context, steps):
    # The context belongs to this runner's private office/profile, never the user profile.
    provider = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.configuration.ConfigurationProvider", context
    )
    access = provider.createInstanceWithArguments(
        "com.sun.star.configuration.ConfigurationUpdateAccess",
        (prop("nodepath", "/org.openoffice.Office.Common/Undo"),),
    )
    original = access.getPropertyValue("Steps")
    try:
        access.setPropertyValue("Steps", steps)
        access.commitChanges()
        yield
    finally:
        access.setPropertyValue("Steps", original)
        access.commitChanges()
        access.dispose()


def workbook(desktop, count=7):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    document.CurrentController.Frame.activate()
    document.Sheets.getByIndex(0).Name = "Tab0000"
    for index in range(1, count):
        document.Sheets.insertNewByName(f"Tab{index:04}", index)
    document.UndoManager.clear()
    return document


def run_plan(context, document, action, selected, gap=None):
    observed = snapshot(document)
    plan = plan_move(observed.sheets, selected, action, gap)
    result = apply_order(context, document, observed, plan)
    assert result.status == "done", result
    assert order(document) == plan.target
    return plan


class FaultySheets:
    """Test-only seam: forward to real UNO, then throw after a selected mutation."""

    def __init__(self, sheets, fail_at, *, silent=False, before=False):
        self.sheets, self.fail_at = sheets, fail_at
        self.calls = 0
        self.silent, self.before = silent, before

    def __getattr__(self, name):
        return getattr(self.sheets, name)

    def moveByName(self, name, index):
        self.calls += 1
        if self.before:
            raise RuntimeError("Injected before mutation")
        if self.silent:
            return
        self.sheets.moveByName(name, index)
        if self.calls == self.fail_at:
            raise RuntimeError("Injected after mutation")


class FaultyDocument:
    def __init__(self, document, sheets, undo=None):
        self.document, self.sheets, self.undo = document, sheets, undo

    def __getattr__(self, name):
        return getattr(self.document, name)

    def getSheets(self):
        return self.sheets

    def getUndoManager(self):
        return self.document.UndoManager if self.undo is None else self.undo


class BrokenUndo:
    def __init__(self, undo):
        self.manager = undo

    def __getattr__(self, name):
        return getattr(self.manager, name)

    def undo(self):
        # Reproduce Calc's silent no-op when the view shell is not active.
        pass


def assert_failures(context, document):
    original = snapshot(document)
    plan = plan_order(original.sheets, tuple(reversed(order(document))))
    assert len(plan.moves) == 6
    for step in range(1, len(plan.moves) + 1):
        document.UndoManager.clear()
        wrapped = FaultyDocument(document, FaultySheets(document.Sheets, step))
        result = apply_order(context, wrapped, original, plan)
        assert result.status == "failed-restored", result
        assert order(document) == tuple(sheet.name for sheet in original.sheets)
        assert not document.hasControllersLocked()
        assert document.UndoManager.AllUndoActionTitles == ()
        assert document.UndoManager.AllRedoActionTitles == ()
    # Never consume a pre-existing user edit, even if its title is also Move Sheets.
    document.UndoManager.enterUndoContext("Move Sheets")
    document.Sheets.getByIndex(0).getCellRangeByName("D1").Value = 71
    document.UndoManager.leaveUndoContext()
    history = document.UndoManager.AllUndoActionTitles
    for options in ({"before": True}, {"silent": True}):
        wrapped = FaultyDocument(document, FaultySheets(document.Sheets, 1, **options))
        result = apply_order(context, wrapped, original, plan)
        assert result.status == "failed-restored", result
        assert document.UndoManager.AllUndoActionTitles == history
        assert document.Sheets.getByIndex(0).getCellRangeByName("D1").Value == 71
    wrapped = FaultyDocument(
        document, FaultySheets(document.Sheets, 1), BrokenUndo(document.UndoManager)
    )
    result = apply_order(context, wrapped, original, plan)
    assert result.status == "failed-not-restored", result
    assert order(document) != tuple(sheet.name for sheet in original.sheets)
    document.UndoManager.undo()  # Clean up the deliberately broken test adapter.


def assert_permissions(context, desktop, document, directory):
    def refused(reason):
        observed = snapshot(document)
        plan = plan_move(observed.sheets, [order(document)[0]], "bottom")
        before = order(document)
        history = document.UndoManager.AllUndoActionTitles
        permission = preflight(context, document, observed, plan)
        assert not permission.allowed and reason in permission.reason, permission
        result = apply_order(context, document, observed, plan)
        assert result.status == "refused", result
        assert order(document) == before
        assert document.UndoManager.AllUndoActionTitles == history

    document.protect("test")
    refused("protected")
    document.unprotect("test")
    document.RecordChanges = True
    refused("recorded")
    document.RecordChanges = False
    document.IsUndoEnabled = False
    refused("undo")
    document.IsUndoEnabled = True
    document.UndoManager.lock()
    refused("undo")
    document.UndoManager.unlock()
    with undo_capacity(context, 0):
        refused("undo")
    with undo_capacity(context, 1):
        observed = snapshot(document)
        many = plan_order(observed.sheets, tuple(reversed(order(document))))
        permission = preflight(context, document, observed, many)
        assert not permission.allowed and "two steps" in permission.reason, permission
        # A single native move is still undoable with this setting.
        original = order(document)
        run_plan(context, document, "bottom", [original[0]])
        document.UndoManager.undo()
        assert order(document) == original
    other = workbook(desktop, 2)
    other.CurrentController.Frame.activate()
    refused("Activate")
    other.close(True)
    document.CurrentController.Frame.activate()
    observed = snapshot(document)
    plan = plan_move(observed.sheets, [order(document)[0]], "bottom")
    document.Sheets.insertNewByName("External", len(order(document)))
    assert apply_order(context, document, observed, plan).status == "refused"
    document.Sheets.removeByName("External")
    # Same name is insufficient: a retained deleted handle must fail validation.
    document.Sheets.removeByName("Tab0006")
    document.Sheets.insertNewByName("Tab0006", 6)
    assert apply_order(context, document, observed, plan).status == "refused"
    path = directory / "readonly-moves.ods"
    document.storeToURL(path.as_uri(), (prop("FilterName", "calc8"),))
    readonly = desktop.loadComponentFromURL(path.as_uri(), "_blank", 0, (prop("ReadOnly", True),))
    try:
        observed = snapshot(readonly)
        plan = plan_move(observed.sheets, [order(readonly)[0]], "bottom")
        assert readonly.isReadonly()
        assert apply_order(context, readonly, observed, plan).status == "refused"
    finally:
        readonly.close(True)
    document.CurrentController.Frame.activate()


def assert_scenarios(context, desktop):
    document = workbook(desktop, 4)
    try:
        base = document.Sheets.getByName("Tab0001")
        ranges = (base.getCellRangeByName("A1").RangeAddress,)
        base.getScenarios().addNewByName("CaseOne", ranges, "synthetic scenario one")
        base.getScenarios().addNewByName("CaseTwo", ranges, "synthetic scenario two")
        other = document.Sheets.getByName("Tab0003")
        other.getScenarios().addNewByName(
            "OtherCase", (other.getCellRangeByName("A1").RangeAddress,), ""
        )
        original = order(document)
        expected = ("CaseOne", "CaseTwo")
        assert base.Scenarios.ElementNames == expected
        for selected, action, gap in (
            (["Tab0000"], "drop", 2),
            (["Tab0000"], "drop", 3),
            (["Tab0003"], "drop", 2),
            (["Tab0001"], "bottom", None),
            (["Tab0003"], "top", None),
            (["Tab0002"], "up", None),
        ):
            document.UndoManager.clear()
            observed = snapshot(document)
            plan = plan_move(observed.sheets, selected, cast(Action, action), gap)
            if not plan.moves:
                assert apply_order(context, document, observed, plan).status == "refused"
                assert order(document) == original
                assert document.UndoManager.AllUndoActionTitles == ()
                continue
            for step in range(1, len(plan.moves) + 1):
                wrapped = FaultyDocument(document, FaultySheets(document.Sheets, step))
                result = apply_order(context, wrapped, observed, plan)
                assert result.status == "failed-restored", result
                assert order(document) == original
                assert base.Scenarios.ElementNames == expected
                assert other.Scenarios.ElementNames == ("OtherCase",)
            run_plan(context, document, action, selected, gap)
            assert base.Scenarios.ElementNames == expected
            assert other.Scenarios.ElementNames == ("OtherCase",)
            document.UndoManager.undo()
            assert order(document) == original
            document.UndoManager.redo()
            assert order(document) == plan.target
            assert base.Scenarios.ElementNames == expected
            document.UndoManager.undo()
        assert not document.Sheets.getByName("CaseOne").IsVisible
    finally:
        document.close(True)


def populated_workbook(desktop, count):
    """Synthetic data with direct cross-sheet formulas, named ranges, and charts."""
    document = workbook(desktop, count)
    document.lockControllers()
    try:
        for index in range(count):
            sheet = document.Sheets.getByIndex(index)
            sheet.getCellRangeByName("A1:A2").setDataArray(((index + 1,), (index + 2,)))
            sheet.getCellRangeByName("B1").Formula = f"=Tab{(index + 1) % count:04}.A1"
            document.NamedRanges.addNewByName(
                f"Value{index:04}",
                f"$Tab{index:04}.$A$1",
                sheet.getCellRangeByName("A1").CellAddress,
                0,
            )
        first = document.Sheets.getByIndex(0)
        for index in (count // 2, count - 1):
            source = document.Sheets.getByIndex(index)
            first.Charts.addNewByName(
                f"Chart{index}",
                Rectangle(0, 0, 8000, 4000),
                (source.getCellRangeByName("A1:A2").RangeAddress,),
                False,
                False,
            )
        document.calculateAll()
    finally:
        document.unlockControllers()
    document.UndoManager.clear()
    return document


def assert_references(document, count):
    for index in (0, count // 2, count - 1):
        sheet = document.Sheets.getByName(f"Tab{index:04}")
        assert sheet.getCellRangeByName("B1").Value == (index + 1) % count + 1
        assert document.NamedRanges.getByName(f"Value{index:04}").ReferredCells.Value == index + 1
    first = document.Sheets.getByName("Tab0000")
    assert first.Charts.Count == 2
    # Calc recreates chart object names when their host sheet moves. References,
    # rather than these unstable object identifiers, are the integrity contract.
    referenced = {
        document.Sheets.getByIndex(first.Charts.getByName(name).Ranges[0].Sheet).Name
        for name in first.Charts.ElementNames
    }
    assert referenced == {f"Tab{count // 2:04}", f"Tab{count - 1:04}"}


def performance(context, desktop, directory):
    results = []
    for count in (200, 1000):
        print(f"Generating populated {count}-sheet synthetic workbook", flush=True)
        document = populated_workbook(desktop, count)
        try:
            original = order(document)
            document.storeAsURL((directory / f"synthetic-{count}.ods").as_uri(), ())
            for case, selected in (
                ("first-to-bottom", original[:1]),
                ("first-half-to-bottom", original[: count // 2]),
                ("all-but-last-to-bottom", original[:-1]),
                ("alternating-to-bottom", original[::2]),
            ):
                timings, undos = [], []
                call_count = 0
                for _ in range(3):
                    started = time.perf_counter()
                    observed = snapshot(document)
                    plan = plan_move(observed.sheets, selected, "bottom")
                    call_count = len(plan.moves)
                    result = apply_order(context, document, observed, plan)
                    timings.append((time.perf_counter() - started) * 1000)
                    assert result.status == "done", result
                    assert order(document) == plan.target
                    assert_references(document, count)
                    started = time.perf_counter()
                    assert document.CurrentController.Frame.isActive(), (count, case, "inactive")
                    document.UndoManager.undo()
                    undos.append((time.perf_counter() - started) * 1000)
                    assert order(document) == original, (
                        count,
                        case,
                        len(plan.moves),
                        order(document)[:10],
                        document.UndoManager.AllUndoActionTitles,
                    )
                    assert_references(document, count)
                results.append(
                    {
                        "sheets": count,
                        "case": case,
                        "calls": call_count,
                        "move_ms": round(statistics.median(timings), 2),
                        "undo_ms": round(statistics.median(undos), 2),
                    }
                )
                print(json.dumps(results[-1]), flush=True)
        finally:
            document.close(True)
    return results


def exercise(context, desktop, directory, output):
    document = workbook(desktop)
    try:
        original = order(document)
        document.Sheets.getByName("Tab0002").IsVisible = False
        document.Sheets.getByName("Tab0003").protect("test")  # Content protection allows moves.
        controller = document.CurrentController
        controller.setActiveSheet(document.Sheets.getByName("Tab0004"))
        dispatch = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.DispatchHelper", context
        )
        dispatch.executeDispatch(
            controller.Frame,
            ".uno:SelectTables",
            "",
            0,
            (prop("Tables", cast(Any, uno).Any("[]long", (1, 4, 6))),),
        )
        for action, selected, gap in (
            ("bottom", ["Tab0001", "Tab0003"], None),
            ("top", ["Tab0002", "Tab0005"], None),
            ("up", ["Tab0000", "Tab0002", "Tab0003", "Tab0006"], None),
            ("down", ["Tab0000", "Tab0002", "Tab0003", "Tab0006"], None),
            ("drop", ["Tab0001", "Tab0003"], 5),
        ):
            document.UndoManager.clear()
            controller.setActiveSheet(document.Sheets.getByName("Tab0004"))
            dispatch.executeDispatch(
                controller.Frame,
                ".uno:SelectTables",
                "",
                0,
                (prop("Tables", cast(Any, uno).Any("[]long", (1, 4, 6))),),
            )
            plan = run_plan(context, document, action, selected, gap)
            assert controller.ActiveSheet.Name == "Tab0004", (action, controller.ActiveSheet.Name)
            assert document.UndoManager.AllUndoActionTitles == ("Move Sheets",)
            assert not document.Sheets.getByName("Tab0002").IsVisible
            assert document.Sheets.getByName("Tab0003").isProtected()
            assert controller.Frame.isActive()
            document.UndoManager.undo()
            assert order(document) == original
            document.UndoManager.redo()
            assert order(document) == plan.target
            document.UndoManager.undo()
        assert_failures(context, document)
        with undo_capacity(context, 2):
            # Six moves require nested groups. Failure on either side of every
            # subgroup boundary must undo the complete partial operation once.
            assert_failures(context, document)
            observed = snapshot(document)
            target = tuple(reversed(order(document)))
            plan = plan_order(observed.sheets, target)
            assert apply_order(context, document, observed, plan).status == "done"
            assert order(document) == target
            document.UndoManager.undo()
            assert order(document) == original
            document.UndoManager.redo()
            assert order(document) == target
            document.UndoManager.undo()
            assert order(document) == original
        assert_permissions(context, desktop, document, directory)
    finally:
        document.close(True)
    assert_scenarios(context, desktop)
    with undo_capacity(context, 2):
        assert_scenarios(context, desktop)
    timings = performance(context, desktop, directory)
    (output / "reorder-performance.json").write_text(
        json.dumps(timings, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "moves_undo_redo": True,
        "permissions": True,
        "failure_each_step": True,
        "scenarios": True,
        "hidden": True,
        "performance": timings,
    }
