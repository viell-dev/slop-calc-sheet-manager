"""Exceptional exits from the menu must leave it closed and Calc's view untouched.

The menu used to register a dispatch interceptor on the frame while Calc's own popup was open
(#63). It now dispatches a chosen command itself after its popup has closed, so nothing outlives
the popup but its result.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.unit.source_methods import method


@pytest.mark.parametrize("failure", ["popup", "commands", "execute"])
def test_failed_popup_leaves_the_menu_closed_and_calc_untouched(failure: str) -> None:
    popup = Mock()
    popup.getItemCount.return_value = 0
    if failure == "execute":
        popup.execute.side_effect = RuntimeError("execute")

    def make_popup() -> Mock:
        if failure == "popup":
            raise RuntimeError("popup")
        return popup

    owner = SimpleNamespace(
        is_open=False,
        _closed_at=0,
        _popup=make_popup,
        _add_commands=Mock(side_effect=RuntimeError("commands") if failure == "commands" else None),
        _add_actions=Mock(return_value=set()),
        _controller=Mock(),
        _frame=Mock(),
    )
    owner._add_commands.return_value = set()
    build = method(
        "src/sheet_manager/uno_menu.py",
        "SheetMenu",
        "build",
        {"Snapshot": object, "HELP": 20006, "tr": str},
    )

    def bound_build(observed: object, picked: list[str]) -> object:
        return build(owner, observed, picked)

    owner.build = bound_build
    show = method(
        "src/sheet_manager/uno_menu.py",
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
    with pytest.raises(RuntimeError, match=failure):
        show(owner, object(), 1, 2, object(), ["Delta"])
    assert not owner.is_open and owner._closed_at == 100
    assert not owner._controller.mock_calls and not owner._frame.mock_calls
