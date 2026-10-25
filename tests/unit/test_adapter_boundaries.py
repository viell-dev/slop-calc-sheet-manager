"""Deterministic races and display guards; real UNO behaviour is checked in integration."""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from sheet_manager.selection import Ref, Selection
from sheet_manager.structure import Quiet, StructureEvents

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
        _acknowledge_view=Mock(),
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
        _note_view_input=Mock(),
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


def test_move_enablement_does_not_consume_an_edits_pending_modify_notification() -> None:
    events = StructureEvents(count=80, history=(0, None))
    states: list[Any] = []
    permission = SimpleNamespace(allowed=True)

    def availability(allowed: bool, reason: str) -> SimpleNamespace:
        return SimpleNamespace(allowed=allowed, reason=reason)

    monitor = SimpleNamespace(
        generation=0,
        check=lambda: events.check(80, (1, "Tab Color"), Quiet.NONE),
    )
    owner = SimpleNamespace(
        _moves=SimpleNamespace(update=states.append),
        _disposed=False,
        _busy=False,
        _observed=SimpleNamespace(sheets=()),
        _selection=SimpleNamespace(picked=["Bravo"], names=lambda: ["Bravo"]),
        _monitor=monitor,
        _proven=0,
        context=object(),
        document=object(),
    )
    update = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_update_moves",
        {
            "ACTIONS": ("up",),
            "Availability": availability,
            "move_availability": Mock(return_value=permission),
            "plan_move": Mock(return_value=object()),
            "plan_availability": Mock(return_value=permission),
            "cast": cast,
            "Action": str,
            "tr": str,
        },
    )
    # An ordinary edit reports its undo action before its modify notification. A hint
    # requested between them must not make that notification look unrecorded (#66).
    events.action_added(80, Quiet.NONE)
    update(owner)
    events.modified(80, Quiet.NONE)
    assert events.generation == 0
    assert states[-1]["up"].allowed

    # Reported structural changes still disable the hint before execution's full preflight.
    monitor.generation = 1
    update(owner)
    assert not states[-1]["up"].allowed


def test_native_cursor_wins_over_repeated_key_callbacks() -> None:
    names = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
    handles = {name: object() for name in names}
    queued: list[Any] = []

    def post(callback: Any, where: str) -> None:
        queued.append(callback)

    owner = SimpleNamespace(
        _disposed=False,
        _restoring_cursor=False,
        _input=0,
        _selection=SimpleNamespace(cursor=Ref("Bravo", handles["Bravo"], 1)),
        _handles=handles,
        rows=[SimpleNamespace(name=name) for name in names],
        _take_tree_selection=lambda: None,
        _note_view_input=Mock(),
        post=post,
    )
    key = method("src/sheet_manager/uno_list.py", "SheetList", "tree_key", {})
    changed = method(
        "src/sheet_manager/uno_list.py", "SheetList", "cursor_changed", {"Any": Any, "Ref": Ref}
    )
    for index in (2, 3):
        before = owner._selection.cursor
        key(owner, 1024, 2)
        key(owner, 1024, 2)  # Two toolkit deliveries, but one native cursor movement.
        assert owner._selection.cursor is before

        def native_index(position: int = index) -> int:
            return position

        accessible = SimpleNamespace(
            getAccessibleContext=lambda: SimpleNamespace(getAccessibleIndexInParent=native_index)
        )
        changed(owner, accessible)
    assert owner._selection.cursor.name == "Delta"
    assert owner._selection.cursor.token is handles["Delta"]
    assert len(queued) == 4


@pytest.mark.parametrize(
    "disposed,restoring,index,expected,queried",
    [
        (True, False, 0, "Bravo", False),
        (False, True, 0, "Bravo", False),
        (False, False, -1, "Bravo", True),
        (False, False, 2, "Bravo", True),
        (False, False, 0, "Alfa", True),
    ],
)
def test_native_cursor_uses_only_current_rows_outside_restoration(
    disposed: bool, restoring: bool, index: int, expected: str, queried: bool
) -> None:
    calls: list[bool] = []
    handle = object()

    def context() -> Any:
        calls.append(True)
        return SimpleNamespace(getAccessibleIndexInParent=lambda: index)

    owner = SimpleNamespace(
        _disposed=disposed,
        _restoring_cursor=restoring,
        _selection=SimpleNamespace(cursor=Ref("Bravo", object(), 1)),
        _handles={"Alfa": handle, "Bravo": object()},
        rows=[SimpleNamespace(name="Alfa"), SimpleNamespace(name="Bravo")],
    )
    changed = method(
        "src/sheet_manager/uno_list.py", "SheetList", "cursor_changed", {"Any": Any, "Ref": Ref}
    )
    changed(owner, SimpleNamespace(getAccessibleContext=context))
    assert owner._selection.cursor.name == expected
    assert bool(calls) == queried
    if expected == "Alfa":
        assert owner._selection.cursor.token is handle


def test_failed_rebuild_releases_the_cursor_restoration_guard() -> None:
    model = Mock()

    def names() -> list[str]:
        return []

    owner = SimpleNamespace(
        _restoring_cursor=False,
        _first_visible_name=lambda: None,
        context=SimpleNamespace(
            ServiceManager=SimpleNamespace(createInstanceWithContext=Mock(return_value=model))
        ),
        tree=SimpleNamespace(getModel=lambda: SimpleNamespace()),
        _selection=SimpleNamespace(anchor=None),
        names=names,
    )

    def fail_restore() -> None:
        assert owner._restoring_cursor
        raise RuntimeError("injected cursor restoration failure")

    owner._apply_selection = fail_restore
    rebuild = method("src/sheet_manager/uno_list.py", "SheetList", "_rebuild", {"SheetRow": Any})
    with pytest.raises(RuntimeError, match="cursor restoration failure"):
        rebuild(owner, [])
    assert not owner._restoring_cursor


@pytest.mark.parametrize("stage", ["context", "index"])
@pytest.mark.parametrize("disposed", [True, False])
def test_stale_accessible_rows_preserve_cursor_without_hiding_other_errors(
    stage: str, disposed: bool
) -> None:
    class DisposedRow(Exception):
        pass

    failure = DisposedRow if disposed else RuntimeError
    original = Ref("Bravo", object(), 1)
    handle = object()
    owner = SimpleNamespace(
        _disposed=False,
        _restoring_cursor=False,
        _selection=SimpleNamespace(cursor=original),
        rows=[SimpleNamespace(name="Alfa")],
        _handles={"Alfa": handle},
    )

    def index() -> int:
        raise failure("stale accessible row")

    def context() -> Any:
        if stage == "context":
            raise failure("stale accessible row")
        return SimpleNamespace(getAccessibleIndexInParent=index)

    changed = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "cursor_changed",
        {"Any": Any, "Ref": Ref, "DisposedException": DisposedRow},
    )
    if disposed:
        changed(owner, SimpleNamespace(getAccessibleContext=context))
    else:
        with pytest.raises(RuntimeError, match="stale accessible row"):
            changed(owner, SimpleNamespace(getAccessibleContext=context))
    assert owner._selection.cursor is original
    changed(
        owner,
        SimpleNamespace(
            getAccessibleContext=lambda: SimpleNamespace(getAccessibleIndexInParent=lambda: 0)
        ),
    )
    assert owner._selection.cursor.name == "Alfa"
    assert owner._selection.cursor.token is handle


@pytest.mark.parametrize(
    "names,expected",
    [(("Bravo",), "Bravo"), (("Delta",), "Delta"), (("Alfa", "Bravo"), "Bravo"), ((), None)],
)
def test_refused_release_restores_a_surviving_pick_instead_of_native_release_cursor(
    names: tuple[str, ...], expected: str | None
) -> None:
    selection = Selection(lambda ref: True)
    selection.picked = [Ref(name, object()) for name in names]
    selection.cursor = Ref("Charlie", object())  # Native deferred release changed the cursor.
    before = tuple(selection.picked)
    applied: list[Ref | None] = []
    owner = SimpleNamespace(
        _press=SimpleNamespace(row=1, name="Bravo", generation=0, voided=False),
        _monitor=SimpleNamespace(check=lambda: 0),
        _pressed_sheet_in_place=Mock(return_value=False),
        _selection=selection,
        _apply_selection=lambda: applied.append(selection.cursor),
    )
    released = method(
        "src/sheet_manager/uno_list.py", "SheetList", "mouse_released", {"LEFT": 1, "RIGHT": 2}
    )
    released(owner, SimpleNamespace(Buttons=1))
    cursor = cast(Ref | None, owner._selection.cursor)
    assert tuple(selection.picked) == before
    assert owner._press is None
    assert (cursor.name if cursor is not None else None) == expected
    assert applied == [cursor]
    if cursor is not None:
        assert any(cursor is ref for ref in before)


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
