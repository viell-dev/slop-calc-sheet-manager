"""Deterministic races and display guards; real UNO behaviour is checked in integration."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from sheet_manager.selection import Ref, Selection
from tests.unit.source_methods import method


@pytest.mark.parametrize("changed", ["structure", "activation"])
def test_menu_keeps_intent_and_pick_proof_before_a_fresh_snapshot(changed: str) -> None:
    monitor = SimpleNamespace(generation=0)
    monitor.check = lambda: monitor.generation
    allowed: list[bool] = []

    def snapshot(document: object) -> object:
        # A reported replacement during the snapshot still has the picked name, but the
        # selection has never been proved at the newer generation.
        if changed == "structure":
            monitor.generation += 1
        else:
            owner._activation_input += 1
        return SimpleNamespace(sheets=[SimpleNamespace(name="Bravo")])

    def show(*args: Any) -> None:
        allowed.append(args[-1]())

    def current(ref: object) -> bool:
        return True

    def no_ref(name: str) -> None:
        return None

    def tabs(*args: object) -> list[int]:
        return []

    owner = SimpleNamespace(
        _disposed=False,
        _busy=False,
        _observed=True,
        _menu_context=False,
        _current_picks=lambda: [SimpleNamespace(name="Bravo")],
        _generation=0,
        _proven=0,
        _activation_input=0,
        _monitor=monitor,
        _menu=SimpleNamespace(show=show),
        _acknowledge_view=Mock(),
        refresh=Mock(),
        _ref=no_ref,
        names=lambda: ["Alfa", "Bravo"],
        context=object(),
        controller=SimpleNamespace(getActiveSheet=lambda: SimpleNamespace(getName=lambda: "Alfa")),
        post=Mock(),
        document=object(),
        peer=object(),
    )
    open_menu = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_open_menu",
        {
            "snapshot": snapshot,
            "_current": current,
            "SHOW": 1,
            "Ref": Ref,
            "selected_tabs": tabs,
            "MOVE_IDS": {},
            "HELP": 20006,
        },
    )
    open_menu(owner, 0, 0, [Ref("Bravo", object())])
    assert allowed == [], "A stale proof must be refused before temporary native grouping"
    owner.refresh.assert_called_once()


@pytest.mark.parametrize("failure", [False, True])
def test_modal_native_command_finishes_before_view_restoration(failure: bool) -> None:
    queued: list[Any] = []
    restored: list[bool] = []
    menu = SimpleNamespace(
        _dispatch_depth=0,
        _completion=None,
        command=None,
        _post=queued.append,
    )
    begin = method("src/sheet_manager/uno_menu.py", "SheetMenu", "_begin_command", {})
    end = method("src/sheet_manager/uno_menu.py", "SheetMenu", "_end_command", {})
    defer = method(
        "src/sheet_manager/uno_menu.py",
        "SheetMenu",
        "defer_completion",
        {
            "Callable": Callable,
        },
    )

    def complete() -> None:
        if not defer(menu, complete):
            restored.append(True)

    def native_dispatch(url: Any, arguments: object) -> None:
        # A modal dialog pumps the queued completion while the command is still on the stack.
        complete()
        assert not restored
        begin(menu, ".uno:SelectTables")  # A nested dispatch cannot change the command's intent.
        end(menu)
        assert menu.command == ".uno:Remove" and not queued
        if failure:
            raise RuntimeError("native command failed")

    def starting(command: str) -> None:
        begin(menu, command)

    guard = SimpleNamespace(
        _verify=lambda: True,
        _refused=Mock(),
        _begin=starting,
        _end=lambda: end(menu),
        _real=SimpleNamespace(dispatch=native_dispatch),
    )
    dispatch = method("src/sheet_manager/uno_menu.py", "_GuardedDispatch", "dispatch", {})
    if failure:
        with pytest.raises(RuntimeError, match="native command failed"):
            dispatch(guard, SimpleNamespace(Complete=".uno:Remove"), ())
    else:
        dispatch(guard, SimpleNamespace(Complete=".uno:Remove"), ())
    assert not restored and len(queued) == 1 and menu._dispatch_depth == 0
    queued[0]()
    assert restored == [True] and menu._completion is None


@pytest.mark.parametrize("newer_context", [False, True])
def test_superseded_context_only_clears_its_own_target(newer_context: bool) -> None:
    target = object()
    owner = SimpleNamespace(
        _input=2,
        _context_input=2 if newer_context else 1,
        _context_target=target,
    )
    open_menu = method("src/sheet_manager/uno_list.py", "SheetList", "_open_menu", {"Ref": Ref})
    open_menu(owner, 10, 20, seen=1)
    assert owner._context_target is (target if newer_context else None)


def test_right_release_keeps_the_press_intent_before_newer_keyboard_input() -> None:
    owner = SimpleNamespace(_input=5, _context_input=3, _open_menu=Mock(), post=Mock())
    release = method(
        "src/sheet_manager/uno_list.py", "SheetList", "mouse_released", {"RIGHT": 2, "LEFT": 1}
    )
    release(owner, SimpleNamespace(Buttons=2, X=10, Y=20))
    owner.post.call_args.args[0]()
    owner._open_menu.assert_called_once_with(10, 20, seen=3)


@pytest.mark.parametrize("closed", [False, True])
def test_failed_menu_restore_refreshes_and_notifies_unless_the_view_closed(closed: bool) -> None:
    class ClosedView(Exception):
        pass

    logged, shown = Mock(), Mock()
    failure = ClosedView("closed") if closed else RuntimeError("restore refused")
    owner = SimpleNamespace(
        _disposed=False,
        _view_stopped=False,
        _activating=True,
        _menu_context=True,
        _context_target=object(),
        _menu=SimpleNamespace(restore_view=Mock(side_effect=failure), command=None),
        refresh=Mock(),
        _selection=SimpleNamespace(revalidate=Mock()),
        _apply_selection=Mock(),
        _acknowledge_view=Mock(),
        peer=object(),
    )
    finish = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_finish_menu",
        {
            "MenuView": Any,
            "DisposedException": ClosedView,
            "SELECT_COMMANDS": set(),
            "report": logged,
            "show_error": shown,
            "tr": str,
        },
    )
    finish(owner, object(), lambda: True)
    assert not owner._activating and not owner._menu_context and owner._context_target is None
    owner._acknowledge_view.assert_called_once()
    if closed:
        assert owner._view_stopped
        owner.refresh.assert_not_called()
        shown.assert_not_called()
        logged.assert_not_called()
    else:
        owner.refresh.assert_called_once()
        owner._apply_selection.assert_called_once()
        assert "could not restore" in shown.call_args.args[2]
        logged.assert_called_once()


def test_move_request_keeps_its_snapshot_refs_and_proof_while_queued() -> None:
    queued: list[Any] = []
    seen: list[tuple[Any, ...]] = []
    original_snapshot, original_ref = object(), object()

    def post(callback: Any, where: str) -> None:
        queued.append(callback)

    def move(*args: Any) -> None:
        seen.append(args)

    def take_selection(paint: bool) -> None:
        assert not paint
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


def test_failed_move_releases_busy_and_refreshes() -> None:
    refreshed: list[bool] = []

    def fail_apply(*args: Any) -> None:
        raise RuntimeError("injected move failure")

    def current(ref: object) -> bool:
        return True

    def plan(sheets: object, names: list[str], action: str) -> object:
        return object()

    owner = SimpleNamespace(
        _disposed=False,
        _busy=False,
        _monitor=SimpleNamespace(check=lambda: 7),
        context=object(),
        document=object(),
        refresh=lambda: refreshed.append(True),
    )
    move = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_move_selection",
        {"_current": current, "plan_move": plan, "apply_order": fail_apply},
    )
    with pytest.raises(RuntimeError, match="move failure"):
        move(owner, "top", SimpleNamespace(sheets=()), (SimpleNamespace(name="Bravo"),), 7)
    assert not owner._busy and refreshed == [True]


def test_owned_navigation_accumulates_while_the_ui_queue_is_paused() -> None:
    from sheet_manager.keys import DOWN, END, HOME, PAGEDOWN, PAGEUP, SPACE, UP, A

    names = ["Alfa", "Bravo", "Charlie", "Delta", "Echo"]
    handles = {name: object() for name in names}
    selection = Selection(lambda ref: True)
    selection.choose("Bravo", handles, names)
    queued: list[Any] = []

    def ref(name: str) -> Ref | None:
        return selection.ref(name, handles, names)

    def post(work: Any, where: str) -> None:
        queued.append(work)

    owner = SimpleNamespace(
        _input=0,
        _proven=0,
        _monitor=SimpleNamespace(generation=0),
        _selection=selection,
        _handles=handles,
        _page_rows=3,
        _selection_write_pending=False,
        _selection_scroll=False,
        _flush_selection=lambda: None,
        _note_view_input=Mock(),
        names=lambda: names,
        _ref=ref,
        post=post,
    )
    queue = method("src/sheet_manager/uno_list.py", "SheetList", "_queue_selection", {})

    def queue_selection(scroll: bool = False) -> None:
        queue(owner, scroll)

    owner._queue_selection = queue_selection
    key = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "tree_key",
        {
            "A": A,
            "DOWN": DOWN,
            "UP": UP,
            "HOME": HOME,
            "END": END,
            "PAGEUP": PAGEUP,
            "PAGEDOWN": PAGEDOWN,
            "SPACE": SPACE,
            "MOD1": 2,
            "SHIFT": 1,
        },
    )
    key(owner, DOWN, 2)
    key(owner, DOWN, 2)
    assert selection.names() == ["Bravo"]
    assert selection.cursor is not None and selection.cursor.name == "Delta"
    assert len(queued) == 1
    key(owner, SPACE, 2)
    assert selection.names() == ["Bravo", "Delta"]


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
        _pointer_depth=0,
        _restoring_cursor=restoring,
        _selection_write_pending=False,
        _press=None,
        _context_target=None,
        _menu_context=False,
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
        _selection_write_pending=False,
        _press=None,
        _context_target=None,
        _menu_context=False,
        _selection=SimpleNamespace(cursor=original),
        _pointer_depth=0,
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
    "active,owned,expected", [(False, True, []), (True, False, []), (True, True, ["calc"])]
)
def test_posted_focus_respects_later_focus(active: bool, owned: bool, expected: list[str]) -> None:
    focused: list[str] = []
    owner = SimpleNamespace(
        _disposed=False,
        frame=SimpleNamespace(
            isActive=lambda: active,
            getComponentWindow=lambda: SimpleNamespace(setFocus=lambda: focused.append("calc")),
        ),
        owns_keys=lambda: owned,
    )
    focus = method("src/sheet_manager/uno_list.py", "SheetList", "_focus_control", {})
    focus(owner, None)
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
