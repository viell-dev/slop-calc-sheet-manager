"""Native selection must not apply a queued owned pointer toggle twice (#85)."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.selection import Selection
from tests.unit.source_methods import method

SOURCE = "src/sheet_manager/uno_list.py"


def native_picks() -> tuple[Any, Any, list[Callable[[], None]]]:
    live = SimpleNamespace(order=["Bravo", "Delta"], picks=["Bravo", "Delta"])
    handles = {name: Mock(getName=Mock(return_value=name)) for name in live.order}
    selection = Selection(lambda ref: ref.token.getName() == ref.name)
    selection.take(["Bravo"], handles, live.order)
    selection.cursor = selection.picked[0]
    queued: list[Callable[[], None]] = []

    def post(callback: Callable[[], None], where: str) -> None:
        queued.append(callback)

    owner = SimpleNamespace(
        _disposed=False,
        _input=1,
        _generation=0,
        _proven=0,
        _monitor=SimpleNamespace(generation=0),
        _press=None,
        _pointer_depth=0,
        _context_target=None,
        _menu_context=False,
        _selection_write_pending=False,
        _selection=selection,
        _handles=handles,
        _shown=("Bravo",),
        _user_picks=True,
        selected_names=lambda: live.picks,
        names=lambda: live.order,
        post=post,
        peer=SimpleNamespace(invalidate=Mock()),
    )
    take = method(SOURCE, "SheetList", "_take_tree_selection", {})

    def take_native(**kwargs: bool) -> bool:
        return bool(take(owner, **kwargs))

    owner._take_tree_selection = take_native
    return owner, live, queued


def test_native_ctrl_toggle_waits_for_the_owned_pointer_listener() -> None:
    owner, live, queued = native_picks()
    # Recorded native order: the tree has added Delta before the owned press arrives.
    assert owner._take_tree_selection(paint=False, defer=True)
    assert owner._selection.names() == ["Bravo"]
    owner.geometry = lambda: SimpleNamespace(row_at=Mock(return_value=1))
    owner.rows = [SimpleNamespace(name=name) for name in live.order]
    owner._note_view_input = Mock()
    owner._queue_selection = Mock()
    press = method(
        SOURCE,
        "SheetList",
        "mouse_pressed",
        {"LEFT": 1, "RIGHT": 2, "MOD1": 2, "SHIFT": 1, "_Press": Mock()},
    )
    press(owner, SimpleNamespace(Buttons=1, Modifiers=2, ClickCount=1, Y=33))
    queued.pop()()  # Its old sample cannot toggle or replace the newer picks.
    assert owner._selection.names() == ["Bravo", "Delta"]
    owner.peer.invalidate.assert_not_called()


def test_native_selection_without_owned_input_is_still_taken() -> None:
    owner, live, queued = native_picks()
    live.picks = ["Delta"]
    assert owner._take_tree_selection(defer=True)
    assert owner._selection.names() == ["Bravo"]
    queued.pop()()
    assert owner._selection.names() == ["Delta"]
    assert owner._shown == ("Delta",)
    owner.peer.invalidate.assert_called_once_with(0)


@pytest.mark.parametrize(
    "changed", ["input", "proof", "structure", "generation", "names", "closed"]
)
def test_deferred_native_intake_refuses_a_superseded_or_stale_view(changed: str) -> None:
    owner, live, queued = native_picks()
    owner._take_tree_selection(defer=True)
    if changed == "input":
        owner._input += 1
    elif changed == "proof":
        owner._proven += 1
    elif changed == "structure":
        owner._monitor.generation += 1
    elif changed == "generation":
        owner._generation += 1
    elif changed == "names":
        live.order.reverse()
    else:
        owner._disposed = True
    queued.pop()()
    assert owner._selection.names() == ["Bravo"]
    owner.peer.invalidate.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
def test_pointer_handler_defers_reentrant_paint_and_releases_its_guard(failure: bool) -> None:
    owner, _, queued = native_picks()
    owner._selection_write_pending = True
    owner._queue_selection = Mock()
    flush = method(SOURCE, "SheetList", "_flush_selection", {})

    def guarded(where: str, function: Callable[[object], None], event: object) -> None:
        function(event)

    handle = method(
        SOURCE,
        "_Mouse",
        "_handle",
        {"_guarded": guarded},
    )

    def input_handler(event: object) -> None:
        assert owner._pointer_depth == 1
        flush(owner)  # A callback runs while a UNO request from this handler is in progress.
        assert not owner._selection_write_pending
        assert not owner._take_tree_selection(defer=True)
        assert not queued and owner._selection.names() == ["Bravo"]
        owner._queue_selection.assert_not_called()
        if failure:
            raise RuntimeError("injected input failure")

    listener = SimpleNamespace(_owner=owner)
    if failure:
        with pytest.raises(RuntimeError, match="input failure"):
            handle(listener, "input", input_handler, object())
    else:
        handle(listener, "input", input_handler, object())
    assert owner._pointer_depth == 0
    owner._queue_selection.assert_called_once_with()
