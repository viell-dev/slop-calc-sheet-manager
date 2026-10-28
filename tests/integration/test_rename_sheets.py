"""Batch rename against a real office and the packaged modules (#102).

The menu's enablement and reasons; Calc's naming rules through the adapter; swaps and cycles with
formulas, named ranges and charts; one undo step at undo capacities 0, 1 and 2; failures after
real mutations, silent refusals by Calc, and recovery; permissions, stale and replaced targets;
another window on the same document; and, in headless sessions, timings with 200 and 1,000
populated sheets. The dialog's real keyboard and mouse use is checked in the real-input UI tests.

Failures are injected through test-only forwarding handles and documents; nothing ships for it.
`check_native_refusal_after_search` runs last: the Find & Replace it dispatches leaves Calc's
sheet-name comparison ignoring character width for the rest of the office session (#112).
"""

import json
import statistics
import time
from dataclasses import replace
from typing import Any
from unittest.mock import patch

from com.sun.star.beans import PropertyValue
from main_thread import close_after
from sheet_list_view import on_main_thread
from test_reorder import BrokenUndo, FaultyDocument, populated_workbook, undo_capacity

from sheet_manager.rename import Plan, Step, plan_renames
from sheet_manager.uno_calc import select_tabs, selected_tabs
from sheet_manager.uno_menu import RENAME, RENAME_SHEETS, SheetMenu
from sheet_manager.uno_rename import apply_renames, preflight
from sheet_manager.uno_reorder import Snapshot, snapshot
from sheet_manager.uno_structure import monitor_for

SIX = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
TITLE = "Rename Sheets"  # The undo step, in the English fallback.


def prop(name, value):
    item = PropertyValue()
    item.Name, item.Value = name, value
    return item


def make_book(desktop, names=SIX):
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    sheets = document.Sheets
    sheets.getByIndex(0).Name = names[0]
    for index, name in enumerate(names[1:], 1):
        sheets.insertNewByName(name, index)
    for name in names:
        sheets.getByName(name).getCellRangeByName("B1").String = f"identity {name}"
    document.CurrentController.Frame.activate()
    document.UndoManager.clear()
    return document


def names(document):
    return list(document.Sheets.ElementNames)


def identities(document):
    sheets = document.Sheets
    return {
        sheets.getByIndex(i).Name: sheets.getByIndex(i).getCellRangeByName("B1").String
        for i in range(sheets.Count)
    }


def view_of(context, document):
    """The viewed sheet and Calc's selected tabs, by position: renames keep both."""
    controller = document.CurrentController
    active = names(document).index(controller.ActiveSheet.Name)
    return active, selected_tabs(context, controller)


def titles(document):
    return list(document.UndoManager.AllUndoActionTitles)


def rename(context, document, renames, observed=None):
    observed = observed or snapshot(document)
    plan = plan_renames([sheet.name for sheet in observed.sheets], renames)
    return plan, apply_renames(context, document, observed, plan)


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


def check_menu_entry(context, desktop, directory):
    """Rename Sheets takes Rename's place for two or more targets, with the right reasons."""
    document = make_book(desktop)
    evidence = {}
    try:
        sheets = document.Sheets
        one = states(context, document, ["Charlie"])
        assert RENAME in one and RENAME_SHEETS not in one, one
        two = states(context, document, ["Charlie", "Delta"])
        assert RENAME not in two and two[RENAME_SHEETS][:2] == (True, ""), two
        assert two[RENAME_SHEETS][2] == "Rename Sheets...", two
        sheets.getByName("Delta").IsVisible = False
        hidden = states(context, document, ["Charlie", "Delta"])
        assert hidden[RENAME_SHEETS][0], "Hidden targets can be renamed: nothing is viewed"
        sheets.getByName("Delta").IsVisible = True
        cases = {}
        sheets.getByName("Delta").protect("")
        cases["protected sheet"] = states(context, document, ["Charlie", "Delta"])
        sheets.getByName("Delta").unprotect("")
        document.protect("")
        cases["protected structure"] = states(context, document, ["Charlie", "Delta"])
        document.unprotect("")
        document.IsUndoEnabled = False
        cases["undo off"] = states(context, document, ["Charlie", "Delta"])
        document.IsUndoEnabled = True
        undo = document.UndoManager
        undo.lock()
        cases["undo locked"] = states(context, document, ["Charlie", "Delta"])
        undo.unlock()
        undo.enterUndoContext("Someone else's edit")
        sheets.getByName("Alfa").getCellRangeByName("C1").Value = 1
        cases["open undo context"] = states(context, document, ["Charlie", "Delta"])
        undo.leaveUndoContext()
        undo.clear()
        expected = {
            "protected sheet": "Protected sheets cannot be renamed.",
            "protected structure": "protected",
            "undo off": "Enable undo",
            "undo locked": "Enable undo",
            "open undo context": "Finish the current undo action",
        }
        for case, found in cases.items():
            enabled, reason, _ = found[RENAME_SHEETS]
            evidence[case] = reason
            assert not enabled and expected[case] in reason, (case, found[RENAME_SHEETS])
        document.RecordChanges = True
        recorded = states(context, document, ["Charlie", "Delta"])
        assert recorded[RENAME_SHEETS][0], "Calc renames while recording changes; so does this"
        document.RecordChanges = False
        path = directory / "rename-sheets-readonly.ods"
        document.storeToURL(path.as_uri(), ())
        readonly = desktop.loadComponentFromURL(
            path.as_uri(), "_blank", 0, (prop("ReadOnly", True),)
        )
        try:
            found = states(context, readonly, ["Charlie", "Delta"])
            assert not found[RENAME_SHEETS][0] and "read-only" in found[RENAME_SHEETS][1], found
        except BaseException as failure:
            close_after(context, readonly, failure)
            raise
        close_after(context, readonly)
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return evidence


def check_naming_rules(context, desktop):
    """Names Calc keeps exactly, each applied and read back, one undo step each."""
    document = make_book(desktop, ["A", *SIX])
    accepted = {
        "Alfa": " edge spaces ",
        "Bravo": "O'Brien",
        "Charlie": "Tab\tand\nline",
        "Delta": "X" * 300,
        "Echo": "\U0001f600 Echo",
        "Foxtrot": "Ａ",  # Fullwidth A beside A: distinct (the #112 regression control).
    }
    try:
        before = identities(document)
        _, result = rename(context, document, list(accepted.items()))
        assert result.status == "done", result
        assert names(document) == ["A", *accepted.values()], names(document)
        for old, new in accepted.items():
            assert identities(document)[new] == before[old], (old, new)
        assert titles(document) == [TITLE], titles(document)
        document.UndoManager.undo()
        assert names(document) == ["A", *SIX]
        document.UndoManager.redo()
        assert names(document) == ["A", *accepted.values()]
        document.UndoManager.undo()
        document.UndoManager.clear()
        refused = {}
        for proposal in ("", "a:b", "a\\b", "a/b", "a?b", "a*b", "a[b", "a]b", "'a", "a'", "a\0b"):
            try:
                plan_renames(names(document), [("Alfa", proposal), ("Bravo", "Fine")])
            except ValueError as error:
                refused[repr(proposal)] = str(error)
            else:
                raise AssertionError(f"{proposal!r} was not refused")
        for proposal in ("BRAVO", "bravo", "a", "Straße"):
            others = ["Straße" if proposal != "Straße" else "STRASSE"]
            try:
                plan_renames(names(document) + others, [("Alfa", proposal)])
            except ValueError as error:
                refused[proposal] = str(error)
            else:
                raise AssertionError(f"{proposal!r} beside {others} was not refused")
        assert names(document) == ["A", *SIX] and not titles(document)
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return {"accepted": len(accepted), "refused_before_any_change": refused}


def references_book(desktop):
    document = make_book(desktop, ["WIP North", "WIP South", "WIP West", "Summary"])
    sheets = document.Sheets
    north, south, west, summary = (sheets.getByIndex(i) for i in range(4))
    north.getCellRangeByName("A1:A2").setDataArray(((11,), (12,)))
    south.getCellRangeByName("A1").Value = 17
    west.getCellRangeByName("A1").Value = 5
    summary.getCellRangeByName("A1").Formula = "='WIP North'.A1+'WIP South'.A1*2+'WIP West'.A1*4"
    summary.getCellRangeByName("A2").Formula = "=SUM('WIP North'.A1:A2)"
    summary.getCellRangeByName("D1").Formula = "=INDIRECT(\"'WIP North'.A1\")"
    summary.getCellRangeByName("C1").String = "WIP North stays literal text"
    document.NamedRanges.addNewByName(
        "NorthValue", "$'WIP North'.$A$1", north.getCellRangeByName("A1").CellAddress, 0
    )
    from com.sun.star.awt import Rectangle

    summary.Charts.addNewByName(
        "NorthChart",
        Rectangle(0, 0, 8000, 4000),
        (north.getCellRangeByName("A1:A2").RangeAddress,),
        False,
        False,
    )
    document.calculateAll()
    document.UndoManager.clear()
    return document


def reference_state(context, document) -> dict[str, Any]:
    document.calculateAll()
    sheets = document.Sheets
    summary = sheets.getByName("Summary")
    return {
        "names": names(document),
        "identities": identities(document),
        "formula": summary.getCellRangeByName("A1").Formula,
        "value": summary.getCellRangeByName("A1").Value,
        "sum": summary.getCellRangeByName("A2").Value,
        "indirect_formula": summary.getCellRangeByName("D1").Formula,
        "indirect_error": summary.getCellRangeByName("D1").getError(),
        "indirect_value": summary.getCellRangeByName("D1").Value,
        "literal": summary.getCellRangeByName("C1").String,
        "named_value": document.NamedRanges.getByName("NorthValue").ReferredCells.Value,
        "chart_source": sheets.getByIndex(summary.Charts.getByName("NorthChart").Ranges[0].Sheet)
        .getCellRangeByName("B1")
        .String,
        "view": view_of(context, document),
    }


def check_swaps_and_cycles(context, desktop):
    """Swaps and cycles through temporary names, with references kept and text untouched."""
    document = references_book(desktop)
    evidence = {}
    try:
        controller = document.CurrentController
        controller.setActiveSheet(document.Sheets.getByName("Summary"))
        select_tabs(context, controller.Frame, [1, 3])
        monitor = monitor_for(document)
        original = reference_state(context, document)
        assert original["indirect_value"] == 11 and original["value"] == 11 + 34 + 20, original
        for case, renames, calls in (
            ("swap", [("WIP North", "WIP South"), ("WIP South", "WIP North")], 3),
            (
                "cycle",
                [("WIP North", "WIP South"), ("WIP South", "WIP West"), ("WIP West", "WIP North")],
                4,
            ),
            ("case swap", [("WIP North", "wip south"), ("WIP South", "wip north")], 3),
            ("prefix removal", [("WIP North", "North"), ("WIP South", "South")], 2),
            ("case only", [("WIP North", "wip north")], 1),
        ):
            generation = monitor.check()
            plan, result = rename(context, document, renames)
            assert result.status == "done" and result.moves == calls, (case, result)
            assert len(plan.steps) == calls, (case, plan.steps)
            after = reference_state(context, document)
            mapping = dict(plan.renames)
            expected = {
                mapping.get(name, name): text for name, text in original["identities"].items()
            }
            assert after["identities"] == expected, (case, after)
            for key in ("value", "sum", "named_value", "literal", "view", "indirect_formula"):
                assert after[key] == original[key], (case, key, after[key], original[key])
            assert after["chart_source"] == "identity WIP North", (case, after)
            assert after["formula"] != original["formula"], "Direct references follow renames"
            # INDIRECT's text is not rewritten: it names whichever sheet now has that name.
            sheets = document.Sheets
            if sheets.hasByName("WIP North"):
                holder = sheets.getByName("WIP North").getCellRangeByName("A1").Value
                assert (after["indirect_error"], after["indirect_value"]) == (0, holder), after
            else:
                assert after["indirect_error"] != 0, after
            assert titles(document) == [TITLE], (case, titles(document))
            assert monitor.check() == generation, "The list's own rename moved the generation"
            document.UndoManager.undo()
            undone = reference_state(context, document)
            assert undone == original, (case, undone)
            document.UndoManager.redo()
            assert reference_state(context, document)["identities"] == expected, case
            document.UndoManager.undo()
            document.UndoManager.clear()
            evidence[case] = {"calls": calls, "formula": after["formula"]}
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return evidence


def check_capacities(context, desktop):
    """Undo steps 0 refuses; 1 and 2 still undo the whole batch in one step (#16 is moves')."""
    evidence = {}
    for steps in (0, 1, 2):
        with undo_capacity(context, steps):
            document = make_book(desktop)  # The limit is set before the document exists (#37).
            try:
                document.Sheets.getByName("Alfa").getCellRangeByName("C1").Value = 7
                history = titles(document)
                renames = [
                    ("Alfa", "Bravo"),
                    ("Bravo", "Charlie"),
                    ("Charlie", "Alfa"),
                    ("Delta", "D"),
                ]
                if steps == 0:
                    observed = snapshot(document)
                    plan = plan_renames(names(document), renames)
                    reason = preflight(context, document, observed, plan)
                    result = apply_renames(context, document, observed, plan)
                    assert result.status == "refused" and "Enable undo" in reason, result
                    assert names(document) == SIX and titles(document) == history
                    evidence[steps] = reason
                else:
                    evidence[steps] = one_step_at_capacity(context, document, renames, steps)
            except BaseException as failure:
                close_after(context, document, failure)
                raise
            close_after(context, document)
    return evidence


def one_step_at_capacity(context, document, renames, steps):
    """A batch is one undo step at this capacity, and a failure part-way still recovers."""
    plan, result = rename(context, document, renames)
    assert result.status == "done" and len(plan.steps) == 5, result
    found = titles(document)
    assert found[0] == TITLE and len(found) <= steps, found
    document.UndoManager.undo()
    assert names(document) == SIX, names(document)
    assert document.Sheets.getByName("Alfa").getCellRangeByName("C1").Value == 7
    document.UndoManager.redo()
    assert names(document) == ["Bravo", "Charlie", "Alfa", "D", "Echo", "Foxtrot"]
    document.UndoManager.undo()
    observed = snapshot(document)
    plan = plan_renames(names(document), renames)
    result = apply_renames(context, document, failing(observed, after=3), plan)
    assert result.status == "failed-restored", result
    assert names(document) == SIX and not document.UndoManager.AllRedoActionTitles
    return "one step"


class Handle:
    """Test-only: forwards to a real sheet handle, and fails or refuses at a chosen call."""

    def __init__(self, real, calls, fail):
        self.real, self.calls, self.fail = real, calls, fail

    def __getattr__(self, name) -> Any:
        return getattr(self.real, name)

    def setName(self, name):
        self.calls.append(name)
        kind = self.fail(len(self.calls))
        if kind == "before":
            raise RuntimeError("Injected before the call")
        if kind == "silent":
            return  # Calc's silent refusal: no error, no change.
        self.real.setName(name)
        if kind == "after":
            raise RuntimeError("Injected after the call")


def failing(observed: Snapshot, *, after=None, before=None, silent=None, hook=None) -> Snapshot:
    """The same snapshot, whose handles fail at the given call number (counted across them)."""
    calls: list[str] = []

    def fail(number):
        if hook is not None and number == hook[0]:
            hook[1]()
        return {after: "after", before: "before", silent: "silent"}.get(number)

    return replace(observed, handles=tuple(Handle(h, calls, fail) for h in observed.handles))


def check_failures(context, desktop):
    """Recovery after each real call, Calc's silent refusal, and failures before any change."""
    document = make_book(desktop)
    evidence = {}
    try:
        sheets = document.Sheets
        renames = [("Alfa", "Bravo"), ("Bravo", "Charlie"), ("Charlie", "Alfa"), ("Echo", "E")]
        user_edit = "Input"
        for kind in ("after", "silent", "before"):
            for number in range(1, 6):
                document.UndoManager.clear()
                sheets.getByName("Delta").getCellRangeByName("C1").String = "user edit"
                history = titles(document)
                assert history, "The user's previous edit must be on the undo stack"
                observed = snapshot(document)
                plan = plan_renames(names(document), renames)
                assert len(plan.steps) == 5
                result = apply_renames(context, document, failing(observed, **{kind: number}), plan)
                state = (kind, number, result)
                assert result.status == "failed-restored", state
                assert names(document) == SIX and identities(document)["Alfa"] == "identity Alfa"
                assert titles(document) == history, (state, titles(document))
                assert not document.UndoManager.AllRedoActionTitles, state
                if kind == "silent":
                    assert "did not accept" in result.message, state
                user_edit = history[0]
        evidence["each_call"] = True
        evidence["user_edit_kept"] = user_edit
        # A broken undo: recovery cannot be verified, and says so.
        document.UndoManager.clear()
        observed = snapshot(document)
        plan = plan_renames(names(document), renames)
        wrapped = FaultyDocument(document, document.Sheets, BrokenUndo(document.UndoManager))
        result = apply_renames(context, wrapped, failing(observed, after=2), plan)
        assert result.status == "failed-not-restored" and "Check" in result.message, result
        document.UndoManager.undo()
        assert names(document) == SIX
        document.UndoManager.clear()
        # A real refusal by Calc after real calls: another program protects the structure
        # during the batch, so Calc refuses the third call. That protection is recorded inside
        # the batch's undo step, so recovering the step undoes it too.
        observed = snapshot(document)
        plan = plan_renames(names(document), renames)
        during: list[bool] = []

        def protect():
            document.protect("")
            during.append(bool(document.isProtected()))

        result = apply_renames(context, document, failing(observed, hook=(3, protect)), plan)
        assert during == [True] and result.status == "failed-restored", (during, result)
        assert "did not accept" in result.message and names(document) == SIX, result
        assert not document.isProtected(), "The protection was part of the recovered step"
        assert not titles(document) and not document.UndoManager.AllRedoActionTitles
        evidence["native_refusal_after_protection"] = result.message
        # A forged plan is refused before any change.
        observed = snapshot(document)
        forged = Plan(
            tuple(SIX), (("Alfa", "Bravo"),), tuple(SIX), (Step("Alfa", "Alfa", "Bravo"),)
        )
        assert preflight(context, document, observed, forged), "A forged plan was accepted"
        assert apply_renames(context, document, observed, forged).status == "refused"
        assert names(document) == SIX
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return evidence


def casefold_only(name):
    """Test-only: a comparator that misses Calc's uppercase lookup, as a weaker one would."""
    return ((0, name.casefold()),)


def check_lookup_verification(context, desktop):
    """A final name that Calc accepts but looks up as another sheet is undone and reported.

    Calc accepts `ı` (dotless i) beside `I`, but then finds `I` for both (#113). The planner's
    comparator refuses that pair, so this weakens it for the test: the adapter's lookup check
    must still catch the result.
    """
    document = make_book(desktop, ["I", *SIX])
    try:
        with patch("sheet_manager.rename.keys", casefold_only):
            plan, result = rename(context, document, [("Alfa", "ı"), ("Bravo", "Two")])
        assert len(plan.steps) == 2, plan
        assert result.status == "failed-restored", result
        assert "looks up another sheet" in result.detail, result
        assert names(document) == ["I", *SIX] and not titles(document)
        assert document.Sheets.getByName("Alfa").getName() == "Alfa"
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return result.detail


def check_stale_targets(context, desktop):
    """A held snapshot is refused after a rename, a replacement, protection, or Undo."""
    document = make_book(desktop)
    evidence = {}
    try:
        sheets = document.Sheets
        renames = [("Bravo", "Two"), ("Delta", "Four")]

        def renamed_elsewhere():
            sheets.getByName("Delta").Name = "Elsewhere"

        def replaced():
            index = names(document).index("Bravo")
            sheets.removeByName("Bravo")
            sheets.insertNewByName("Bravo", index)

        def protected():
            sheets.getByName("Bravo").protect("")

        def undone():
            sheets.getByName("Alfa").getCellRangeByName("C1").Value = 3
            document.UndoManager.undo()

        def readonly_lock():
            document.UndoManager.lock()

        for case, change in (
            ("renamed elsewhere", renamed_elsewhere),
            ("replaced", replaced),
            ("protected", protected),
            ("undo", undone),
            ("undo locked", readonly_lock),
        ):
            document.UndoManager.clear()
            observed = snapshot(document)
            plan = plan_renames(names(document), renames)
            before = names(document), identities(document)
            change()
            changed = names(document), identities(document)
            history = titles(document)
            result = apply_renames(context, document, observed, plan)
            evidence[case] = result.message
            assert result.status == "refused", (case, result)
            assert (names(document), identities(document)) == changed, case
            assert titles(document) == history, case
            if document.UndoManager.isLocked():
                document.UndoManager.unlock()
            if sheets.getByName("Bravo").isProtected():
                sheets.getByName("Bravo").unprotect("")
            if sheets.hasByName("Elsewhere"):
                sheets.getByName("Elsewhere").Name = "Delta"
            assert names(document) == before[0], case
        assert (
            apply_renames(
                context, document, snapshot(document), plan_renames(SIX, [("Alfa", "Alfa")])
            ).status
            == "refused"
        ), "A plan without changes is refused"
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return evidence


def check_other_window(context, desktop):
    """Another window on the document keeps its view; renaming from either needs no focus."""
    document = make_book(desktop)
    evidence = {}
    try:
        first = document.CurrentController
        dispatcher = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.DispatchHelper", context
        )
        dispatcher.executeDispatch(first.Frame, ".uno:NewWindow", "", 0, ())
        controllers = document.getControllers()
        second = None
        while controllers.hasMoreElements():
            candidate = controllers.nextElement()
            if candidate != first:
                second = candidate
        assert second is not None, "No second window opened"
        second.setActiveSheet(document.Sheets.getByName("Echo"))
        select_tabs(context, second.Frame, [3, 4])
        first.setActiveSheet(document.Sheets.getByName("Bravo"))
        second_view = second.ActiveSheet.Name, selected_tabs(context, second)
        first_view = first.ActiveSheet.Name, selected_tabs(context, first)
        other = second.Frame.isActive()
        _, result = rename(context, document, [("Delta", "Echo"), ("Echo", "Delta")])
        assert result.status == "done", result
        assert (second.ActiveSheet.Name, selected_tabs(context, second)) == ("Delta", [3, 4])
        assert (first.ActiveSheet.Name, selected_tabs(context, first)) == first_view
        document.UndoManager.undo()
        assert names(document) == SIX
        assert (second.ActiveSheet.Name, selected_tabs(context, second)) == second_view
        evidence["second_view"] = second_view
        evidence["second_frame_active"] = other
        on_main_thread(context, lambda: second.Frame.close(True))
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return evidence


def check_main_thread(context, desktop):
    """The same rename from LibreOffice's main thread, as the list makes it."""
    document = make_book(desktop)
    try:
        out = {}

        def run():
            out["plan"], out["result"] = rename(
                context, document, [("Alfa", "Foxtrot"), ("Foxtrot", "Alfa")]
            )

        on_main_thread(context, run)
        assert out["result"].status == "done", out
        assert names(document)[0] == "Foxtrot" and names(document)[-1] == "Alfa"
        assert titles(document) == [TITLE]
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return True


def performance(context, desktop):
    """Median complete-batch and undo timings: three runs at 200 populated sheets, one at 1,000.

    Measured from this test process, so every call crosses the UNO bridge; the extension makes
    the same calls inside the office. Measurements, not limits.
    """
    results = []
    for count, repeats in ((200, 3), (1000, 1)):
        document = populated_workbook(desktop, count)
        try:
            original = names(document)
            for case, renames in (
                ("every-sheet", [(name, "Renamed " + name) for name in original]),
                ("one-cycle", list(zip(original, original[1:] + original[:1], strict=True))),
            ):
                applied, undone, calls = [], [], 0
                for _ in range(repeats):
                    started = time.perf_counter()
                    plan, result = rename(context, document, renames)
                    applied.append((time.perf_counter() - started) * 1000)
                    assert result.status == "done", result
                    calls = len(plan.steps)
                    started = time.perf_counter()
                    document.UndoManager.undo()
                    undone.append((time.perf_counter() - started) * 1000)
                    assert names(document) == original
                    sheet = document.Sheets.getByIndex(0)
                    assert sheet.getCellRangeByName("B1").Value == 2  # Its direct reference.
                document.UndoManager.clear()
                results.append(
                    {
                        "sheets": count,
                        "case": case,
                        "calls": calls,
                        "runs": repeats,
                        "rename_ms": round(statistics.median(applied), 2),
                        "undo_ms": round(statistics.median(undone), 2),
                    }
                )
                print(json.dumps(results[-1]), flush=True)
        except BaseException as failure:
            close_after(context, document, failure)
            raise
        close_after(context, document)
    return results


def check_native_refusal_after_search(context, desktop):
    """After a Find & Replace, Calc refuses a name the plan accepts; recovery is verified (#112).

    Runs last: the dispatched search leaves Calc ignoring width for the rest of the session.
    """
    document = make_book(desktop, ["A", *SIX])
    try:
        dispatcher = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.DispatchHelper", context
        )
        arguments = (
            prop("SearchItem.SearchString", "IDENTITY"),
            prop("SearchItem.Command", 0),
            prop("SearchItem.TransliterateFlags", 1280),  # Ignore case and width: the default.
            prop("SearchItem.AlgorithmType", 0),
            prop("Quiet", True),
        )
        dispatcher.executeDispatch(
            document.CurrentController.Frame, ".uno:ExecuteSearch", "", 0, arguments
        )
        document.UndoManager.clear()
        renames = [("Alfa", "One"), ("Bravo", "Ａ"), ("Charlie", "Three")]
        _, result = rename(context, document, renames)
        assert result.status == "failed-restored", result
        assert "Ａ" in result.message and "did not accept" in result.message, result
        assert names(document) == ["A", *SIX] and not titles(document)
    except BaseException as failure:
        close_after(context, document, failure)
        raise
    close_after(context, document)
    return result.message


def exercise(context, desktop, directory, output, headless=True):
    result = {
        "menu_entry": check_menu_entry(context, desktop, directory),
        "naming_rules": check_naming_rules(context, desktop),
        "swaps_and_cycles": check_swaps_and_cycles(context, desktop),
        "capacities": check_capacities(context, desktop),
        "failures": check_failures(context, desktop),
        "lookup_verification": check_lookup_verification(context, desktop),
        "stale_targets": check_stale_targets(context, desktop),
        "other_window": check_other_window(context, desktop),
        "main_thread": check_main_thread(context, desktop),
    }
    if headless:  # Measurements, not gates: painted sessions skip them to save CI time.
        timings = performance(context, desktop)
        (output / "rename-performance-headless.json").write_text(
            json.dumps(timings, indent=2) + "\n", encoding="utf-8"
        )
        result["timings"] = timings
    result["native_refusal_after_search"] = check_native_refusal_after_search(context, desktop)
    return result
