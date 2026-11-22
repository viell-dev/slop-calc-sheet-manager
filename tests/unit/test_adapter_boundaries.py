"""Deterministic races and display guards; real UNO behaviour is checked in integration."""

import _thread
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from sheet_manager.selection import Ref, Selection
from tests.unit.source_methods import method, source_class


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
        _tabs=SimpleNamespace(acknowledge=Mock()),
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


@pytest.mark.parametrize("refusal", ["", "The sheets changed while the menu was open."])
def test_menu_command_runs_through_the_menu_and_reports_its_refusal(refusal: str) -> None:
    shown: list[str] = []

    def show_error(peer: object, title: str, message: str) -> None:
        shown.append(message)

    menu = SimpleNamespace(run=Mock(return_value=refusal))
    owner = SimpleNamespace(_menu=menu, refresh=Mock(), peer=object())
    action = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_menu_action",
        {
            "MOVE_IDS": {},
            "HELP": 20006,
            "SHOW": 1,
            "RENAME_SHEETS": 6,
            "COMMANDS": {4: ".uno:RenameTable"},
            "show_error": show_error,
            "tr": str,
        },
    )
    observed, unchanged = object(), Mock()
    refs = [Ref("Delta", object())]
    action(owner, 4, observed, refs, 0, unchanged)
    # The targets are the refs' names when the menu opened; `run` checks them again.
    menu.run.assert_called_once_with(4, observed, ["Delta"], unchanged)
    assert shown == ([refusal] if refusal else [])
    assert owner.refresh.call_count == (1 if refusal else 0)


@pytest.mark.parametrize(
    "shown, targets",
    [
        pytest.param(("Alfa", "Echo"), ["Alfa", "Echo"], id="the tree shows the picks"),
        pytest.param(None, ["Echo"], id="the record is unknown"),
        pytest.param(("Alfa",), ["Echo"], id="the record is not the picks"),
    ],
)
def test_a_right_presss_menu_targets_the_picks_only_while_the_tree_shows_them(
    shown: tuple[str, ...] | None, targets: list[str]
) -> None:
    """Alfa and Echo picked, and a right press on Echo. The menu targets both only while the
    record says the tree shows the picks; after the press's write failed partway or left a
    newer change in the tree, it targets the pressed row alone (#257, #307)."""
    picked = [Ref("Alfa", object()), Ref("Echo", object())]
    opened: list[list[str]] = []

    def show(peer: object, x: int, y: int, observed: object, names: list[str]) -> None:
        opened.append(names)

    owner = SimpleNamespace(
        _input=1,
        _context_input=1,
        _context_target=picked[1],
        _context_generation=0,
        _monitor=SimpleNamespace(check=lambda: 0),
        _disposed=False,
        _busy=False,
        _menu_context=False,
        _observed=object(),
        _selection=SimpleNamespace(picked=picked, names=lambda: ["Alfa", "Echo"]),
        _shown=shown,
        _generation=0,
        _proven=0,
        _activation_input=0,
        _menu=SimpleNamespace(show=show),
        peer=object(),
        document=object(),
        post=Mock(),
    )

    def snapshot(document: object) -> object:
        return SimpleNamespace(sheets=[SimpleNamespace(name=name) for name in ("Alfa", "Echo")])

    def current(ref: object) -> bool:
        return True

    open_menu = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_open_menu",
        {"Ref": Ref, "snapshot": snapshot, "_current": current},
    )
    open_menu(owner, 10, 20, seen=1)
    assert opened == [targets]


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
        _shown=(),
        _proven=7,
        post=post,
        _move_selection=move,
        _tabs=SimpleNamespace(note_input=Mock()),
        claim_window=Mock(),
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
        _update_moves=Mock(),
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


def test_move_enablement_does_not_consume_pending_identity_evidence() -> None:
    def translate(text: str) -> str:
        return text

    permission = SimpleNamespace(allowed=True, reason="")
    owner = SimpleNamespace(
        _disposed=False,
        _busy=False,
        _moves=Mock(),
        _observed=SimpleNamespace(sheets=()),
        _selection=SimpleNamespace(picked=[object()], names=lambda: ["Bravo"]),
        _monitor=SimpleNamespace(generation=7, check=Mock(side_effect=AssertionError("consumed"))),
        _proven=7,
        context=object(),
        document=object(),
    )
    update = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_update_moves",
        {
            "ACTIONS": ("top", "up", "down", "bottom"),
            "move_availability": Mock(return_value=permission),
            "plan_move": Mock(),
            "plan_availability": Mock(return_value=permission),
            "Availability": SimpleNamespace,
            "cast": cast,
            "Action": str,
            "tr": translate,
        },
    )
    update(owner)
    assert len(owner._moves.update.call_args.args[0]) == 4
    owner._monitor.check.assert_not_called()


def test_a_newer_input_cancels_a_queued_panel_focus_request() -> None:
    target = Mock()
    owner = SimpleNamespace(
        _disposed=False,
        _input=2,
        frame=SimpleNamespace(isActive=Mock(side_effect=AssertionError("stale focus query"))),
    )
    focus = method("src/sheet_manager/uno_list.py", "SheetList", "_focus_control", {})
    focus(owner, target, 1)
    target.setFocus.assert_not_called()


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
        _shown=("Bravo",),  # The tree shows the pick,
        _toggles_held=None,  # and toggles act on it.
        _deferred=None,  # No intake waits,
        _unowned=0,  # and nothing but the list changed the tree (#294).
        _accounted=0,
        _hold_toggles=Mock(),  # A key's change holds presses until its write (#291).
        _hold_ranges=Mock(),  # A Ctrl key holds range presses until its write (#313).
        _handles=handles,
        _page_rows=3,
        _selection_write_pending=False,
        _selection_scroll=False,
        _flush_selection=lambda: None,
        _tabs=SimpleNamespace(note_input=Mock()),
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
        context=SimpleNamespace(
            ServiceManager=SimpleNamespace(createInstanceWithContext=Mock(return_value=model))
        ),
        tree=SimpleNamespace(getModel=lambda: SimpleNamespace()),
        names=names,
        _selection=SimpleNamespace(picked=[]),
        _toggles_shown=Mock(),  # The new model shows the empty picks.
        _nodes=[],  # No rows were shown: no scroll position to read, no presses held (#293).
        _presses_held=None,
        _release_presses=Mock(),
        _unowned=0,  # The list's own writes count nothing (#294).
        _accounted=0,
        _writing=0,
        _writer=None,
        _write_start=0,
        _note_rebuilt_position=Mock(),  # The new rows show: their position is noted (#299).
    )

    def fail_restore() -> None:
        assert owner._restoring_cursor
        raise RuntimeError("injected cursor restoration failure")

    owner._apply_selection = fail_restore
    owner._prove = Mock()
    account_write = method("src/sheet_manager/uno_list.py", "SheetList", "_account_write", {})

    def account(start: int) -> None:
        account_write(owner, start)

    owner._account_write = account
    rebuild = method(
        "src/sheet_manager/uno_list.py",
        "SheetList",
        "_rebuild",
        {
            "SheetRow": Any,
            "Snapshot": Any,
            "report": Mock(),
            "_OwnWrites": source_class(
                "src/sheet_manager/uno_list.py", "_OwnWrites", {"_thread": _thread}
            ),
        },
    )
    with pytest.raises(RuntimeError, match="cursor restoration failure"):
        rebuild(owner, [], object(), 0)
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
    "names,cursor,gone,voided,written,kept",
    [
        (("Bravo",), "Bravo", False, False, "Bravo", "Bravo"),  # The press's own cursor.
        (("Bravo",), "Hotel", False, False, "Bravo", "Hotel"),  # Moved outside the picks (#71).
        (("Bravo", "Delta"), "Delta", False, False, "Delta", "Delta"),  # Moved to another pick.
        (("Delta",), "Delta", False, False, "Delta", "Delta"),  # A newer typed pick.
        ((), "Hotel", False, False, None, "Hotel"),  # No pick survives, the cursor does.
        (
            ("Alfa", "Bravo"),
            "Hotel",
            True,
            False,
            "Bravo",
            "Bravo",
        ),  # Gone: the pressed pick takes it,
        (("Alfa", "Delta"), "Hotel", True, False, "Alfa", "Alfa"),  # or else the first pick,
        ((), "Hotel", True, False, None, None),  # or nothing.
        (("Alfa", "Bravo"), None, False, False, "Bravo", "Bravo"),
        # After a refresh dropped every pick, one under the pressed name may be a replacement.
        (("Alfa", "Bravo"), "Hotel", True, True, "Alfa", "Alfa"),
        (("Alfa", "Bravo"), "Hotel", False, True, "Alfa", "Hotel"),
        ((), None, False, False, None, None),
    ],
)
def test_a_refused_release_writes_a_picked_cursor_and_keeps_the_lists_own(
    names: tuple[str, ...],
    cursor: str | None,
    gone: bool,
    voided: bool,
    written: str | None,
    kept: str | None,
) -> None:
    """A press on Bravo, which a refresh moved away from the pressed row. The tree's native
    release has moved its cursor to that row, Charlie's now, but the list ignored that while the
    press was held, so its cursor is where its keys left it. The listener writes the picks back
    with the tree's cursor on a pick, as before #71, and then keeps the list's own cursor, which
    the write it queues shows; a cursor whose sheet is gone (`gone`) falls back to a pick, the
    pressed sheet's unless a refresh has dropped every pick since the press (`voided`). The
    cursor is always a ref the list made at the user's input, never one from the release, and the
    listener reads no handle for it: the press's would fail the test."""
    rows = ["Alfa", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Bravo", "Hotel"]
    handles = {name: SimpleNamespace(getName=lambda name=name: name) for name in rows}
    selection = Selection(lambda ref: not (gone and ref.name == cursor))
    selection.picked = [Ref(name, handles[name]) for name in names]
    selection.cursor = Ref(cursor, handles[cursor]) if cursor is not None else None
    refs = [*selection.picked, selection.cursor]
    writes: list[Ref | None] = []
    owner = SimpleNamespace(
        _press=SimpleNamespace(
            row=1,
            name="Bravo",
            handle=SimpleNamespace(getName=Mock(side_effect=AssertionError("a handle read"))),
            generation=0,
            voided=voided,
        ),
        _monitor=SimpleNamespace(generation=0),  # No `check()` in the listener (#284).
        _unowned=0,  # The release reads the count, and nothing else of it (#307).
        _input_seen=0,
        _pressed_sheet_in_place=Mock(return_value=False),
        _selection=selection,
        names=lambda: rows,
        _show_selection=lambda: writes.append(selection.cursor),
    )
    released = method(
        "src/sheet_manager/uno_list.py", "SheetList", "mouse_released", {"LEFT": 1, "RIGHT": 2}
    )
    released(owner, SimpleNamespace(Buttons=1))
    result = cast(Ref | None, owner._selection.cursor)
    assert owner._press is None
    assert [ref.name for ref in selection.picked] == list(names)
    assert [ref.name if ref is not None else None for ref in writes] == [written]
    assert (result.name if result is not None else None) == kept
    assert result is None or any(result is ref for ref in refs)


@pytest.mark.parametrize(
    "active,owned,expected", [(False, True, []), (True, False, []), (True, True, ["calc"])]
)
def test_posted_focus_respects_later_focus(active: bool, owned: bool, expected: list[str]) -> None:
    focused: list[str] = []
    owner = SimpleNamespace(
        _disposed=False,
        _input=1,
        frame=SimpleNamespace(
            isActive=lambda: active,
            getComponentWindow=lambda: SimpleNamespace(setFocus=lambda: focused.append("calc")),
        ),
        owns_keys=lambda: owned,
    )
    focus = method("src/sheet_manager/uno_list.py", "SheetList", "_focus_control", {})
    focus(owner, None, 1)
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
