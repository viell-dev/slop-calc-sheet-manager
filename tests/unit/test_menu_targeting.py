"""Opening the extension menu must not perform native tab targeting."""

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.unit.source_methods import method


@pytest.mark.parametrize("choice", [20002, 20006, 0, 20000])
@pytest.mark.parametrize("visibility", ["visible", "mixed", "becomes-hidden"])
def test_outer_move_help_and_cancel_never_target_native_tabs(choice: int, visibility: str) -> None:
    popup = Mock()
    hidden_names = ["Hidden"] if visibility == "mixed" else []

    def choose(*args: object) -> int:
        if visibility == "becomes-hidden":
            hidden_names[:] = [
                "Hidden"
            ]  # A macro changes visibility while the outer popup is open.
        return choice

    popup.execute.side_effect = choose
    owner = SimpleNamespace(
        is_open=False,
        _closed_at=0,
        _popup=lambda: popup,
        _add_actions=Mock(),
        group_calc_tabs=Mock(return_value=True),
        capture_view=Mock(return_value=object()),
        _native=Mock(return_value=None),
        _safe=Mock(return_value=None),
    )

    def hidden(observed: object, picked: list[str]) -> list[str]:
        return list(hidden_names)

    def translate(text: str) -> str:
        return text

    show = method(
        "src/sheet_manager/uno_menu.py",
        "SheetMenu",
        "show",
        {
            "time": SimpleNamespace(monotonic=lambda: 100),
            "REPEAT_GUARD_SECONDS": 0.3,
            "hidden_targets": hidden,
            "Snapshot": object,
            "Callable": Callable,
            "ACTIONS": ("top", "up", "down", "bottom"),
            "NATIVE": 20000,
            "HELP": 20006,
            "MOVE_IDS": {20002: "up"},
            "Rectangle": Mock(),
            "tr": translate,
        },
    )
    picked = ["Bravo"] if visibility == "visible" else ["Bravo", "Hidden"]
    assert show(owner, object(), 4, 8, object(), picked) == (
        None if choice == 20000 else choice or None
    )
    if choice == 20000 and visibility == "visible":
        owner.capture_view.assert_called_once()
        owner.group_calc_tabs.assert_called_once_with(["Bravo"])
        owner._native.assert_called_once()
        assert owner._targeted_native
    else:
        owner.capture_view.assert_not_called()
        owner.group_calc_tabs.assert_not_called()
        owner._native.assert_not_called()
        assert not owner._targeted_native
    if choice == 20000 and visibility != "visible":
        owner._safe.assert_called_once()
    else:
        owner._safe.assert_not_called()
    assert not owner.is_open


def test_outer_menu_completion_never_reselects_the_original_tabs() -> None:
    controller = Mock()
    owner = SimpleNamespace(_targeted_native=False, _controller=controller)
    restore = method(
        "src/sheet_manager/uno_menu.py",
        "SheetMenu",
        "restore_view",
        {"MenuView": object, "Callable": Callable},
    )
    restore(owner, object(), Mock())
    assert not controller.mock_calls


def test_refused_repeat_does_not_restore_the_previous_popups_view() -> None:
    state = SimpleNamespace(active="Delta", tabs=[1])
    handles = {
        name: SimpleNamespace(getName=lambda name=name: name, IsVisible=True)
        for name in ("Alfa", "Delta")
    }
    ref = SimpleNamespace(name="Alfa", token=handles["Alfa"])
    previous = SimpleNamespace(active=ref, tabs=(ref,), visible=frozenset({"Alfa"}))

    def set_active(sheet: SimpleNamespace) -> None:
        state.active = sheet.getName()

    def select(context: object, frame: object, indices: list[int]) -> None:
        state.tabs = list(indices)

    def selected(context: object, controller: object) -> list[int]:
        return state.tabs

    owner = SimpleNamespace(
        is_open=False,
        _closed_at=99.9,
        _targeted_native=True,
        view=previous,
        command=None,
        _context=object(),
        _frame=object(),
        _controller=SimpleNamespace(
            getActiveSheet=lambda: handles[state.active], setActiveSheet=set_active
        ),
        _document=SimpleNamespace(
            getSheets=lambda: SimpleNamespace(getElementNames=lambda: ["Alfa", "Delta"])
        ),
    )
    show = method(
        "src/sheet_manager/uno_menu.py",
        "SheetMenu",
        "show",
        {
            "time": SimpleNamespace(monotonic=lambda: 100),
            "REPEAT_GUARD_SECONDS": 0.3,
            "Snapshot": object,
            "Callable": Callable,
        },
    )
    restore = method(
        "src/sheet_manager/uno_menu.py",
        "SheetMenu",
        "restore_view",
        {
            "MenuView": object,
            "Callable": Callable,
            "SELECT_COMMANDS": set(),
            "select_tabs": select,
            "selected_tabs": selected,
            "tr": str,
        },
    )
    assert show(owner, object(), 0, 0, object(), ["Delta"]) is None
    if owner.view is not None:  # The caller completes even a refused invocation.
        restore(owner, owner.view, lambda: True)
    assert (state.active, state.tabs) == ("Delta", [1]), "A refused repeat restored an earlier view"


def test_in_progress_menu_keeps_its_restoration_state() -> None:
    previous = object()
    owner = SimpleNamespace(is_open=True, view=previous, _targeted_native=True)
    show = method(
        "src/sheet_manager/uno_menu.py",
        "SheetMenu",
        "show",
        {"Snapshot": object, "Callable": Callable},
    )
    assert show(owner, object(), 0, 0, object(), ["Delta"]) is None
    assert owner.view is previous and owner._targeted_native
