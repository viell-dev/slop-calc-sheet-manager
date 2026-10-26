"""Opening the extension menu must not perform native tab targeting."""

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.unit.source_methods import method


@pytest.mark.parametrize("choice", [20002, 20006, 0, 20000])
def test_outer_move_help_and_cancel_never_target_native_tabs(choice: int) -> None:
    popup = Mock()
    popup.execute.return_value = choice
    owner = SimpleNamespace(
        is_open=False,
        _closed_at=0,
        _popup=lambda: popup,
        _add_actions=Mock(),
        group_calc_tabs=Mock(return_value=True),
        capture_view=Mock(return_value=object()),
        _native=Mock(return_value=None),
    )

    def hidden(observed: object, picked: list[str]) -> list[str]:
        return []

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
    assert show(owner, object(), 4, 8, object(), ["Bravo"]) == (
        None if choice == 20000 else choice or None
    )
    if choice == 20000:
        owner.capture_view.assert_called_once()
        owner.group_calc_tabs.assert_called_once_with(["Bravo"])
        owner._native.assert_called_once()
        assert owner._targeted_native
    else:
        owner.capture_view.assert_not_called()
        owner.group_calc_tabs.assert_not_called()
        owner._native.assert_not_called()
        assert not owner._targeted_native
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
