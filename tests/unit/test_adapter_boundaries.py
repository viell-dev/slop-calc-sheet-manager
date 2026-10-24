"""Deterministic races and display guards; real UNO behaviour is checked in integration."""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def method(path: str, owner: str, name: str, namespace: dict[str, Any]) -> Any:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    node = next(
        node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


def test_menu_keeps_the_pick_proof_before_reading_a_fresh_snapshot() -> None:
    monitor = SimpleNamespace(generation=0)
    monitor.check = lambda: monitor.generation
    allowed: list[bool] = []

    def snapshot(document: object) -> object:
        # A reported replacement during the snapshot still has the picked name, but the
        # selection has never been proved at the newer generation.
        monitor.generation += 1
        return SimpleNamespace(sheets=[SimpleNamespace(name="Bravo")])

    def show(*args: Any) -> None:
        allowed.append(args[-1]())

    def current(ref: object) -> bool:
        return True

    owner = SimpleNamespace(
        _disposed=False,
        _busy=False,
        _observed=True,
        _current_picks=lambda: [SimpleNamespace(name="Bravo")],
        _generation=0,
        _proven=0,
        _monitor=monitor,
        _menu=SimpleNamespace(show=show),
        document=object(),
        peer=object(),
    )
    open_menu = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_open_menu",
        {"snapshot": snapshot, "_current": current, "SHOW": 1},
    )
    open_menu(owner, 0, 0)
    assert allowed == [False], "A newer monitor generation must not become the menu's proof"


def test_move_request_keeps_its_snapshot_refs_and_proof_while_queued() -> None:
    queued: list[Any] = []
    seen: list[tuple[Any, ...]] = []
    original_snapshot, original_ref = object(), object()

    def post(callback: Any, where: str) -> None:
        queued.append(callback)

    def move(*args: Any) -> None:
        seen.append(args)

    def take_selection(update_moves: bool) -> None:
        assert not update_moves
        owner._selection.picked = [original_ref]

    owner = SimpleNamespace(
        _disposed=False,
        _busy=False,
        _input=0,
        _observed=original_snapshot,
        _selection=SimpleNamespace(picked=[object()]),  # A queued navigation callback is behind.
        _press=None,
        _take_tree_selection=take_selection,
        _proven=7,
        post=post,
        _move_selection=move,
    )
    request = method(
        "src/sheet_manager/uno_list.py", "SheetList", "queue_move", {"ACTIONS": ("top",)}
    )
    request(owner, "top")
    owner._observed, owner._selection.picked, owner._proven = object(), [object()], 8
    queued[0]()
    assert seen == [("top", original_snapshot, (original_ref,), 7)]
    assert owner._input == 1


def test_failed_move_control_update_releases_busy_and_refreshes() -> None:
    refreshed: list[bool] = []

    def fail_update() -> None:
        raise RuntimeError("injected control update failure")

    def current(ref: object) -> bool:
        return True

    def plan(sheets: object, names: list[str], action: str) -> object:
        return object()

    owner = SimpleNamespace(
        _disposed=False,
        _busy=False,
        _monitor=SimpleNamespace(check=lambda: 7),
        _update_moves=fail_update,
        refresh=lambda: refreshed.append(True),
    )
    move = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_move_selection",
        {"_current": current, "plan_move": plan},
    )
    with pytest.raises(RuntimeError, match="control update failure"):
        move(owner, "top", SimpleNamespace(sheets=()), (SimpleNamespace(name="Bravo"),), 7)
    assert not owner._busy and refreshed == [True]


@pytest.mark.parametrize(
    "active,owned,enabled,boundary,expected",
    [
        (False, True, True, False, []),
        (True, False, True, False, []),
        (True, True, True, False, ["button"]),
        (True, True, False, False, ["tree"]),
        (True, True, True, True, ["calc"]),
    ],
)
def test_posted_focus_respects_later_focus_and_disabled_targets(
    active: bool, owned: bool, enabled: bool, boundary: bool, expected: list[str]
) -> None:
    focused: list[str] = []
    button = SimpleNamespace(
        getModel=lambda: SimpleNamespace(Enabled=enabled), setFocus=lambda: focused.append("button")
    )
    owner = SimpleNamespace(
        _disposed=False,
        frame=SimpleNamespace(
            isActive=lambda: active,
            getComponentWindow=lambda: SimpleNamespace(setFocus=lambda: focused.append("calc")),
        ),
        owns_keys=lambda: owned,
        tree=SimpleNamespace(setFocus=lambda: focused.append("tree")),
    )
    focus = method("src/sheet_manager/uno_list.py", "SheetList", "_focus_control", {})
    focus(owner, None if boundary else button)
    assert focused == expected


@pytest.mark.parametrize("display", ["", ":0"])
def test_input_refuses_a_display_without_the_private_launcher_opt_in(display: str) -> None:
    opened: list[object] = []

    def open_display(value: object) -> None:
        opened.append(value)

    initialize = method(
        "tests/ui/xinput.py",
        "XInput",
        "__init__",
        {
            "os": SimpleNamespace(environ={"DISPLAY": display}),
            "_x11": SimpleNamespace(XOpenDisplay=open_display),
        },
    )
    with pytest.raises(RuntimeError, match="explicit opt-in"):
        initialize(SimpleNamespace())
    assert not opened, "Even opening an unapproved desktop display is forbidden"
