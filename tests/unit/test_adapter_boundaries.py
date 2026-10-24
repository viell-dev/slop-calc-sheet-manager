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
