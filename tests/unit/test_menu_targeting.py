"""The menu groups Calc's tabs only when a built-in command runs, after every check."""

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.selection import Ref
from tests.unit.source_methods import method

INSERT, DELETE, RENAME, HIDE, SHOW = 2, 3, 4, 5, 1
COMMANDS = {
    INSERT: ".uno:Insert",
    DELETE: ".uno:Remove",
    RENAME: ".uno:RenameTable",
    HIDE: ".uno:Hide",
}
STALE = "stale"
MENU = "src/sheet_manager/uno_menu.py"


def _stale() -> str:
    return STALE


def menu_function(name: str) -> Any:
    """A module-level function of uno_menu, without importing LibreOffice's modules."""
    import ast

    from tests.unit.source_methods import ROOT

    tree = ast.parse((ROOT / MENU).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace: dict[str, Any] = {
        "Snapshot": object,
        "tr": str,
        "_stale": _stale,
        "INSERT": INSERT,
        "DELETE": DELETE,
        "RENAME": RENAME,
        "HIDE": HIDE,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), MENU, "exec"), namespace)
    return namespace[name]


class Sheet:
    """A retained sheet handle: its name can change under it, as Calc's handles do."""

    def __init__(self, name: str, visible: bool = True, protected: bool = False) -> None:
        self.name = name
        self.IsVisible = visible
        self.protected = protected

    def getName(self) -> str:
        return self.name

    def isProtected(self) -> bool:
        return self.protected


class Calc:
    """Calc's view as far as the menu sees it, with its tab-selection rules.

    Selected tabs always include the viewed sheet. Selecting tabs keeps the viewed sheet when it
    is among them and views the first otherwise; viewing a sheet outside the group ends it.
    """

    def __init__(self, names: list[str], active: str, tabs: list[str]) -> None:
        self.sheets = [Sheet(name) for name in names]
        self.active = active
        self.tabs = list(tabs)
        self.refuse_selection = False
        self.readonly = self.protected = self.recording = False
        self.dispatched: list[str] = []
        self.enabled = True

    def by_name(self, name: str) -> Sheet:
        return next(sheet for sheet in self.sheets if sheet.name == name)

    def order(self) -> list[str]:
        return [sheet.name for sheet in self.sheets]

    def set_active(self, sheet: Sheet) -> None:
        self.active = sheet.name
        if sheet.name not in self.tabs:
            self.tabs = [sheet.name]

    def select(self, context: object, frame: object, indices: list[int]) -> None:
        if self.refuse_selection:
            self.refuse_selection = False
            self.tabs = [self.order()[indices[0]]]  # Calc took only part of the group, once.
        else:
            self.tabs = [self.order()[index] for index in indices]
        if self.active not in self.tabs:
            self.active = self.tabs[0]

    def selected(self, context: object, controller: object) -> list[int]:
        order = self.order()
        return sorted(order.index(name) for name in self.tabs)

    def view(self) -> tuple[str, list[str]]:
        return self.active, sorted(self.tabs, key=self.order().index)

    def document(self) -> SimpleNamespace:
        return SimpleNamespace(
            getSheets=lambda: SimpleNamespace(getElementNames=self.order, getByName=self.by_name),
            isReadonly=lambda: self.readonly,
            isProtected=lambda: self.protected,
            getPropertyValue=self.property,
        )

    def property(self, name: str) -> object:
        return self.recording if name == "RecordChanges" else None

    def snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(
            sheets=[SimpleNamespace(name=sheet.name) for sheet in self.sheets],
            handles=list(self.sheets),
        )


@dataclass(frozen=True)
class View:
    active: Ref
    tabs: tuple[Ref, ...]
    visible: frozenset[str]


def bound_menu(
    calc: Calc, report: Callable[[str], None] | None = None, *, dispatches: bool = True
) -> SimpleNamespace:
    """SheetMenu's targeting methods from the source, bound to a fake Calc."""
    refusal = menu_function("command_refusal")

    def enabled(context: object, frame: object, command: str) -> bool:
        return calc.enabled

    def dispatch(context: object, frame: object, command: str) -> bool:
        if dispatches:
            calc.dispatched.append(command)
        return dispatches  # False: the frame had no dispatcher for the command.

    namespace: dict[str, Any] = {
        "Snapshot": object,
        "Callable": Callable,
        "MenuView": View,
        "Ref": Ref,
        "tr": str,
        "_stale": _stale,
        "COMMANDS": COMMANDS,
        "command_refusal": refusal,
        "command_enabled": enabled,
        "dispatch": dispatch,
        "report": report or Mock(),
        "select_tabs": calc.select,
        "selected_tabs": calc.selected,
    }
    owner = SimpleNamespace(
        _context=object(),
        _frame=object(),
        _document=calc.document(),
        _controller=SimpleNamespace(
            getActiveSheet=lambda: calc.by_name(calc.active), setActiveSheet=calc.set_active
        ),
    )
    for name in ("capture_view", "restore_view", "group_calc_tabs", "run"):
        function = method(MENU, "SheetMenu", name, dict(namespace))

        def bind(*args: Any, function: Any = function) -> Any:
            return function(owner, *args)

        setattr(owner, name, bind)
    return owner


NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo"]


def fresh() -> Calc:
    # The viewed sheet, the grouped tabs and the targets below all differ.
    return Calc(NAMES, "Alfa", ["Alfa", "Bravo"])


@pytest.mark.parametrize(
    ("item", "picked", "view"),
    [
        (RENAME, ["Delta"], ("Delta", ["Delta"])),
        (INSERT, ["Delta"], ("Delta", ["Delta"])),
        (DELETE, ["Charlie", "Echo"], ("Charlie", ["Charlie", "Echo"])),
        (HIDE, ["Charlie", "Echo"], ("Charlie", ["Charlie", "Echo"])),
    ],
)
def test_command_runs_on_exactly_its_targets_and_keeps_calc_there(
    item: int, picked: list[str], view: tuple[str, list[str]]
) -> None:
    """Calc stays on the targets after dispatch: its dialogs can still be open (#100)."""
    calc = fresh()
    menu = bound_menu(calc)
    assert menu.run(item, calc.snapshot(), picked, lambda: True) == ""
    assert calc.dispatched == [COMMANDS[item]]
    assert calc.view() == view


@pytest.mark.parametrize(
    "change",
    [
        "unchanged-false",
        "renamed",
        "hidden",
        "protected",
        "readonly",
        "structure",
        "recording",
    ],
)
def test_changed_targets_are_refused_before_calc_is_touched(change: str) -> None:
    calc = fresh()
    observed = calc.snapshot()
    menu = bound_menu(calc)
    target = calc.by_name("Delta")
    unchanged = True
    if change == "unchanged-false":
        unchanged = False
    elif change == "renamed":
        target.name = "Other"
    elif change == "hidden":
        target.IsVisible = False
    elif change == "protected":
        target.protected = True
    elif change == "readonly":
        calc.readonly = True
    elif change == "structure":
        calc.protected = True
    else:
        calc.recording = True
    before = calc.view()
    # Delete is refused for all of them; protection and recording also block Rename or not.
    reason = menu.run(DELETE, observed, ["Delta"], lambda: unchanged)
    assert reason, change
    assert calc.view() == before and not calc.dispatched, "A refused command touched Calc"
    if change in ("renamed", "unchanged-false"):
        assert reason == STALE


@pytest.mark.parametrize("failure", ["native-disabled", "changed-after-grouping", "no-dispatch"])
def test_refusal_after_grouping_restores_the_view(failure: str) -> None:
    calc = fresh()
    calc.enabled = failure != "native-disabled"
    menu = bound_menu(calc, dispatches=failure != "no-dispatch")
    calls = 0

    def unchanged() -> bool:
        nonlocal calls
        calls += 1
        # A structural change reported after grouping stays reported.
        return failure != "changed-after-grouping" or calls == 1

    before = calc.view()
    reason = menu.run(RENAME, calc.snapshot(), ["Delta"], unchanged)
    assert reason and not calc.dispatched
    if failure == "changed-after-grouping":
        # The targets cannot be proved any more, so neither can the earlier view's sheets.
        assert reason == STALE
        assert calc.view() == ("Delta", ["Delta"])
    else:
        assert "does not allow" in reason
        assert calc.view() == before, "The view from before the refused command was not restored"


def test_partial_grouping_restores_the_users_tabs() -> None:
    calc = fresh()
    calc.refuse_selection = True
    menu = bound_menu(calc)
    before = calc.view()
    reason = menu.run(DELETE, calc.snapshot(), ["Charlie", "Echo"], lambda: True)
    assert "could not select" in reason and not calc.dispatched
    assert calc.view() == before


def test_failed_restoration_is_reported_with_the_refusal() -> None:
    calc = fresh()
    calc.enabled = False
    logged = Mock()
    original = calc.select

    def stuck(context: object, frame: object, indices: list[int]) -> None:
        if not calc.dispatched and calc.tabs != ["Alfa", "Bravo"]:
            return  # After grouping, Calc takes no further selection.
        original(context, frame, indices)

    calc.select = stuck  # type: ignore[method-assign]
    menu = bound_menu(calc, logged)
    reason = menu.run(RENAME, calc.snapshot(), ["Delta"], lambda: True)
    assert "does not allow" in reason and "could not be restored" in reason, reason
    logged.assert_called_once()
    assert not calc.dispatched


@pytest.mark.parametrize(
    ("item", "picked", "setup", "expected"),
    [
        (INSERT, ["Bravo", "Delta"], None, "Choose one sheet to insert"),
        (RENAME, ["Bravo", "Delta"], None, "Choose one sheet to rename"),
        (DELETE, ["Bravo", "Delta"], None, ""),
        (HIDE, ["Bravo", "Delta"], None, ""),
        (RENAME, ["Delta"], "hidden", "Show the hidden sheets first."),
        (INSERT, ["Delta"], "hidden", "Show the hidden sheets first."),
        (HIDE, ["Bravo", "Delta"], "hidden", "Show the hidden sheets first."),
        (RENAME, ["Delta"], "protected", "This sheet is protected."),
        (INSERT, ["Delta"], "protected", ""),
        (HIDE, ["Delta"], "protected", ""),
        (DELETE, ["Bravo", "Delta"], "protected", "Protected sheets cannot be deleted."),
        (DELETE, ["Delta"], "recording", "while changes are being recorded"),
        (RENAME, ["Delta"], "recording", ""),
        (INSERT, ["Delta"], "readonly", "read-only"),
        (HIDE, ["Delta"], "structure", "structure is protected"),
        (DELETE, NAMES, None, "At least one other sheet must stay visible."),
        (HIDE, ["Alfa", "Bravo", "Charlie", "Delta"], "last-visible", "must stay visible"),
        (DELETE, ["Alfa"], "renamed", STALE),
        (DELETE, ["Zulu"], None, STALE),
        (DELETE, [], None, STALE),
    ],
)
def test_command_refusal(item: int, picked: list[str], setup: str | None, expected: str) -> None:
    calc = fresh()
    if setup == "hidden":
        calc.by_name("Delta").IsVisible = False
    elif setup == "protected":
        calc.by_name("Delta").protected = True
    elif setup == "recording":
        calc.recording = True
    elif setup == "readonly":
        calc.readonly = True
    elif setup == "structure":
        calc.protected = True
    elif setup == "last-visible":
        calc.by_name("Echo").IsVisible = False
    observed = calc.snapshot()
    if setup == "renamed":
        calc.by_name("Alfa").name = "Spare"
    reason = menu_function("command_refusal")(calc.document(), observed, item, picked)
    assert (reason == "") if not expected else (expected in reason), reason


def test_unverifiable_state_is_refused() -> None:
    calc = fresh()
    document = calc.document()

    def broken() -> bool:
        raise RuntimeError("disposed")

    document.isReadonly = broken
    reason = menu_function("command_refusal")(document, calc.snapshot(), RENAME, ["Delta"])
    assert reason == "Sheet Manager could not verify that this is safe."


def with_build(owner: SimpleNamespace) -> SimpleNamespace:
    build = method(MENU, "SheetMenu", "build", {"Snapshot": object, "HELP": 20006, "tr": str})

    def bound_build(observed: object, picked: list[str]) -> object:
        return build(owner, observed, picked)

    owner.build = bound_build
    return owner


def show_owner(popup: Mock, enabled: set[int]) -> SimpleNamespace:
    return with_build(
        SimpleNamespace(
            is_open=False,
            _closed_at=0,
            _popup=lambda: popup,
            _add_commands=Mock(return_value=set(enabled)),
            _add_actions=Mock(return_value=set()),
            group_calc_tabs=Mock(),
            capture_view=Mock(),
            run=Mock(),
        )
    )


def show_function() -> Any:
    return method(
        MENU,
        "SheetMenu",
        "show",
        {
            "time": SimpleNamespace(monotonic=lambda: 100),
            "REPEAT_GUARD_SECONDS": 0.3,
            "Snapshot": object,
            "HELP": 20006,
            "Rectangle": Mock(),
            "tr": str,
        },
    )


@pytest.mark.parametrize("choice", [RENAME, DELETE, 20002, 20006, 0])
def test_opening_or_choosing_from_the_menu_never_targets_calc(choice: int) -> None:
    popup = Mock()
    popup.execute.return_value = choice
    popup.getItemCount.return_value = 0
    owner = show_owner(popup, {DELETE})
    owner._add_actions.return_value = {20002}
    chosen = show_function()(owner, object(), 4, 8, object(), ["Bravo", "Delta"])
    # Rename is disabled for two targets: even if a stale popup returned it, it is not chosen.
    assert chosen == (None if choice in (RENAME, 0) else choice)
    owner.group_calc_tabs.assert_not_called()
    owner.capture_view.assert_not_called()
    owner.run.assert_not_called()
    assert not owner.is_open and owner._closed_at == 100


def test_refused_repeat_and_open_menu_build_no_popup() -> None:
    popup = Mock()
    owner = show_owner(popup, {DELETE})
    owner._closed_at = 99.9  # gtk3's duplicate request
    assert show_function()(owner, object(), 0, 0, object(), ["Delta"]) is None
    owner.is_open, owner._closed_at = True, 0
    assert show_function()(owner, object(), 0, 0, object(), ["Delta"]) is None
    assert owner.is_open, "A refused reopen must not end the menu that is still open"
    popup.execute.assert_not_called()


@pytest.mark.parametrize("stopped", [False, True])
def test_menu_completion_touches_no_calc_view(stopped: bool) -> None:
    controller = Mock()
    caller = SimpleNamespace(
        _disposed=False,
        _view_stopped=stopped,
        _activating=True,
        _menu_context=True,
        _context_target=object(),
        _menu=SimpleNamespace(_controller=controller),
        refresh=Mock(),
        _selection=SimpleNamespace(revalidate=Mock()),
        _apply_selection=Mock(),
        _acknowledge_view=Mock(),
    )
    finish = method("src/sheet_manager/uno_list.py", "SheetList", "_finish_menu", {})
    finish(caller)
    assert not controller.mock_calls, "Completing the menu changed Calc's view"
    assert not caller._activating and not caller._menu_context and caller._context_target is None
    caller._acknowledge_view.assert_called_once()
    if stopped:
        caller.refresh.assert_not_called()
    else:
        caller.refresh.assert_called_once()
        caller._selection.revalidate.assert_called_once()
