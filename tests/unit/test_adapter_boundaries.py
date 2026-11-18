"""Deterministic races and display guards; real UNO behaviour is checked in integration."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from sheet_manager.keys import DOWN, END, HOME, PAGEDOWN, PAGEUP, SPACE, UP, A
from sheet_manager.selection import Ref, Selection, structure_kept
from sheet_manager.sheet_list import SheetRow
from tests.unit.source_methods import function, method


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
        _proven=7,
        post=post,
        _move_selection=move,
        _note_view_input=Mock(),
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


ROWS = ["Alfa", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Bravo", "Hotel"]
LIST = "src/sheet_manager/uno_list.py"
LEFT, RIGHT, MIDDLE = 1, 2, 4  # com.sun.star.awt.MouseButton
SHIFT, MOD1 = 1, 2  # com.sun.star.awt.KeyModifier
NAME_OR_NONE = function(LIST, "_name_or_none", {"Any": Any})


def bind(owner: Any, name: str, namespace: dict[str, Any] | None = None) -> None:
    """Give `owner` the list's own method `name`, read from the source."""
    defaults = {"Ref": Ref, "_Press": Any, "_name_or_none": NAME_OR_NONE}
    loaded = method(LIST, "SheetList", name, {**defaults, **(namespace or {})})

    def bound(*arguments: Any, **keywords: Any) -> Any:
        return loaded(owner, *arguments, **keywords)

    setattr(owner, name, bound)


class Sheet:
    """A retained sheet handle, reporting whatever name its sheet has now."""

    def __init__(self, name: str) -> None:
        self.name = name

    def getName(self) -> str:
        return self.name


def refused_press_owner(
    names: tuple[str, ...],
    cursor: str | None,
    stale: str | None = None,
    *,
    generation: int = 0,
    proven: int = 0,
):
    """A list holding a press on Bravo, which a refresh moved away from the pressed row.

    The press went down at structure generation 0; `generation` is the monitor's now and
    `proven` the one at which the list last proved its refs.
    """
    handles = {name: object() for name in ROWS}
    selection = Selection(lambda ref: ref.name != stale)
    selection.picked = [Ref(name, handles[name]) for name in names]
    selection.cursor = Ref(cursor, handles[cursor]) if cursor is not None else None
    applied: list[Ref | None] = []
    owner = SimpleNamespace(
        _disposed=False,
        _pointer_depth=0,
        _restoring_cursor=False,
        _selection_write_pending=False,
        _context_target=None,
        _menu_context=False,
        _press=SimpleNamespace(
            row=1, name="Bravo", handle=Sheet("Bravo"), generation=0, voided=False
        ),
        _monitor=SimpleNamespace(check=lambda: generation),
        _proven=proven,
        _pressed_sheet_in_place=Mock(return_value=False),
        _selection=selection,
        _handles=handles,
        rows=[SimpleNamespace(name=name) for name in ROWS],
        names=lambda: list(ROWS),
        _queue_selection=Mock(),
        _apply_selection=lambda: applied.append(selection.cursor),
    )
    bind(owner, "_fallback_cursor")
    return owner, applied


def release(owner: Any, buttons: int = 1) -> None:
    released = method(LIST, "SheetList", "mouse_released", {"LEFT": LEFT, "RIGHT": RIGHT})
    released(owner, SimpleNamespace(Buttons=buttons))


def release_refused(owner: Any) -> None:
    release(owner)


def native_cursor_on(owner: Any, row: int) -> None:
    """The tree reports its native cursor on `row`, as its accessibility events do."""
    changed = method(
        LIST, "SheetList", "cursor_changed", {"Any": Any, "Ref": Ref, "DisposedException": OSError}
    )
    context = SimpleNamespace(getAccessibleIndexInParent=lambda: row)
    changed(owner, SimpleNamespace(getAccessibleContext=lambda: context))


@pytest.mark.parametrize(
    "names,cursor,stale,expected",
    [
        (("Bravo",), "Bravo", None, "Bravo"),  # The press's own cursor.
        (("Bravo",), "Hotel", None, "Hotel"),  # Moved outside the picks during the hold (#71).
        (("Bravo", "Delta"), "Delta", None, "Delta"),  # Moved to another pick.
        (("Delta",), "Delta", None, "Delta"),  # A newer typed pick.
        ((), "Hotel", None, "Hotel"),  # No pick survives, the cursor does.
        (("Alfa", "Bravo"), "Hotel", "Hotel", "Bravo"),  # Replaced: the pressed pick takes it,
        (("Alfa", "Delta"), "Hotel", "Hotel", "Alfa"),  # or else the first pick,
        ((), "Hotel", "Hotel", None),  # or nothing.
        (("Alfa", "Bravo"), None, None, "Bravo"),
        (("Delta",), None, None, "Delta"),
        ((), None, None, None),
    ],
)
def test_refused_release_keeps_the_lists_cursor_while_it_is_its_sheet(
    names: tuple[str, ...], cursor: str | None, stale: str | None, expected: str | None
) -> None:
    owner, applied = refused_press_owner(names, cursor, stale)
    before = [ref for ref in owner._selection.picked if ref.name != stale]
    kept = owner._selection.cursor
    release_refused(owner)
    result = cast(Ref | None, owner._selection.cursor)
    assert owner._selection.picked == before
    assert owner._press is None
    assert (result.name if result is not None else None) == expected
    assert applied == [result]
    if result is not None:
        # Always a ref the list made at the user's input, never one from the release.
        assert any(result is ref for ref in [*before, kept])


def test_a_late_native_release_cannot_become_the_refused_gestures_cursor() -> None:
    """The native release moves the tree's cursor to the row under the pointer first (#71)."""
    owner, applied = refused_press_owner(("Bravo",), "Hotel")
    # Charlie now shows in the pressed row; the press is still held when the tree says so.
    native_cursor_on(owner, 1)
    assert owner._selection.cursor.name == "Hotel"
    release_refused(owner)
    assert [ref.name if ref is not None else None for ref in applied] == ["Hotel"]


@pytest.mark.parametrize("proven", [0, 1])
def test_a_refused_release_writes_only_refs_proved_at_the_current_generation(proven: int) -> None:
    """Hotel was replaced under its name after Ctrl+Down reached it: the monitor is at 1.

    Its old handle can report "Hotel" for the replacement, so before any refresh (`proven` 0)
    the release writes nothing and leaves the queued write's refresh to decide. A refresh
    during the hold that proved generation 1 already kept Hotel's newer ref; that stays.
    """
    owner, applied = refused_press_owner(("Bravo",), "Hotel", generation=1, proven=proven)
    release_refused(owner)
    assert owner._press is None
    if proven == 0:
        assert applied == []
        owner._queue_selection.assert_called_once_with()
    else:
        assert [ref.name if ref is not None else None for ref in applied] == ["Hotel"]


def test_another_buttons_release_leaves_the_held_left_press_and_its_gate() -> None:
    """A middle release names only that button, while the left one stays down."""
    owner, applied = refused_press_owner(("Bravo",), "Hotel")
    press = owner._press
    release(owner, MIDDLE)
    assert owner._press is press and applied == []
    native_cursor_on(owner, 1)  # Still ignored: the left button is down.
    assert owner._selection.cursor.name == "Hotel"
    release_refused(owner)
    assert [ref.name if ref is not None else None for ref in applied] == ["Hotel"]


@pytest.mark.parametrize(
    "voided,reported,expected",
    [(False, "Bravo", "Bravo"), (True, "Bravo", "Alfa"), (False, "Bravo 2", "Alfa")],
)
def test_only_a_press_that_still_identifies_its_sheet_takes_a_lost_cursor(
    voided: bool, reported: str, expected: str
) -> None:
    """The pressed sheet takes a lost cursor before the first pick only while the press still
    identifies it: no refresh has dropped the picks since it went down (`voided`), and its
    retained handle still reports its name. Otherwise a pick under that name may be another
    sheet, such as a replacement, and the first pick takes the cursor (#71).
    """
    owner, applied = refused_press_owner(("Alfa", "Bravo"), "Hotel", "Hotel")
    owner._press.voided, owner._press.handle = voided, Sheet(reported)
    release_refused(owner)
    assert [ref.name if ref is not None else None for ref in applied] == [expected]


class HeldBravo:
    """A list running its own press, refreshes, keys and release, while Bravo is held.

    Only the document, the tree and the UI queue are fakes. The tree is the set of rows it shows
    as selected; posted work runs on `drain`. Replacing a sheet under its own name advances the
    structure generation, as deleting and inserting it does, and the old handle keeps reporting
    that name, as a deleted sheet's handle can.
    """

    METHODS = (
        "_refresh",
        "_identities_kept",
        "_drop_all_picks",
        "_fallback_cursor",
        "_apply_selection",
        "_show_native",
        "_take_tree_selection",
        "_current_picks",
        "_ref",
        "tree_key",
        "_queue_selection",
        "_flush_selection",
        "mouse_pressed",
        "mouse_released",
        "_pressed_sheet_in_place",
    )

    def __init__(self, names: tuple[str, ...], picks: tuple[str, ...]) -> None:
        self.sheets = [Sheet(name) for name in names]
        self.native: set[str] = set()
        self.posted: list[Any] = []
        namespace: dict[str, Any] = {
            "_Press": function(LIST, "_Press", {"dataclass": dataclass, "Any": Any}),
            "Any": Any,
            "Snapshot": Any,
            "Mapping": Mapping,
            "replace": replace,
            "structure_kept": structure_kept,
            "snapshot": self.snapshot,
            "read_rows": self.read_rows,
            **dict(LEFT=LEFT, RIGHT=RIGHT, SHIFT=SHIFT, MOD1=MOD1, A=A, SPACE=SPACE, UP=UP),
            **dict(DOWN=DOWN, HOME=HOME, END=END, PAGEUP=PAGEUP, PAGEDOWN=PAGEDOWN),
        }
        monitor = SimpleNamespace(generation=0)
        monitor.check = lambda: monitor.generation
        observed = self.snapshot(None)
        owner = self.owner = SimpleNamespace(
            _disposed=False,
            _pointer_depth=0,
            _selection_write_pending=False,
            _selection_scroll=False,
            _restoring_cursor=False,
            _press=None,
            _context_target=None,
            _menu_context=False,
            _proven=0,
            _generation=0,
            _input=0,
            _user_picks=False,
            _view_generation=0,
            _view_names=frozenset(names),
            _view_stopped=True,
            _page_rows=5,
            _monitor=monitor,
            _selection=Selection(function(LIST, "_current", {"Ref": Ref})),
            _observed=observed,
            _handles=dict(zip(names, observed.handles, strict=True)),
            rows=[SheetRow(name) for name in names],
            _nodes=list(names),  # A node is its row's name here.
            _shown=(),
            document=None,
            controller=None,
            tree=SimpleNamespace(
                clearSelection=self.native.clear,
                addSelection=self.native.add,
                makeNodeVisible=Mock(),
            ),
            peer=SimpleNamespace(invalidate=Mock()),
            geometry=lambda: SimpleNamespace(row_at=self.row_at),
            post=self.post,
            claim_window=Mock(),
            activate=Mock(),
            _note_view_input=Mock(),
            _name_viewed=Mock(),
            _update_moves=Mock(),
            _show_cleared_notice=Mock(),
        )
        owner.names = lambda: [row.name for row in owner.rows]
        owner.selected_names = lambda: [name for name in owner.names() if name in self.native]
        owner.refresh = self.list_refresh
        owner._move_tree_cursor = self.move_cursor
        owner._rebuild = self.rebuild
        for name in self.METHODS:
            bind(owner, name, namespace)
        owner._selection.take(picks, owner._handles, owner.names())
        self.press(names.index("Bravo"))

    def snapshot(self, document: object) -> Any:
        return SimpleNamespace(
            sheets=[SimpleNamespace(name=sheet.name) for sheet in self.sheets],
            handles=list(self.sheets),
        )

    def read_rows(self, controller: object, seen: Any) -> list[SheetRow]:
        return [SheetRow(sheet.name) for sheet in seen.sheets]

    def row_at(self, y: int) -> int:
        return y  # A row's Y is its index here.

    def post(self, work: Callable[[], None], where: str) -> None:
        self.posted.append(work)

    def list_refresh(self, renamed: Mapping[str, str] | None = None) -> None:
        self.owner._refresh(renamed or {})

    def move_cursor(self, index: int, scroll: bool = True) -> None:
        """In single selection mode, selecting a row moves the tree's cursor there too."""
        self.native.clear()
        self.native.add(self.owner.names()[index])

    def rebuild(self, rows: list[SheetRow]) -> None:
        """A new data model shows no selection until the list writes its own."""
        owner = self.owner
        owner.rows, owner._nodes, owner._shown = rows, [row.name for row in rows], ()
        self.native.clear()
        owner._apply_selection()

    def drain(self) -> None:
        while self.posted:
            self.posted.pop(0)()

    def replace(self, name: str) -> Sheet:
        index = [sheet.name for sheet in self.sheets].index(name)
        self.sheets[index] = Sheet(name)
        self.owner._monitor.generation += 1
        return self.sheets[index]

    def move(self, name: str, index: int) -> None:
        sheet = self.sheets.pop([sheet.name for sheet in self.sheets].index(name))
        self.sheets.insert(index, sheet)

    def rename(self, name: str, new: str) -> None:
        next(sheet for sheet in self.sheets if sheet.name == name).name = new

    def refresh(self) -> None:
        self.owner.refresh()
        self.drain()

    def key(self, code: int, modifiers: int = 0) -> None:
        self.owner.tree_key(code, modifiers)
        self.drain()

    def press(self, row: int) -> None:
        event = SimpleNamespace(Buttons=LEFT, Y=row, Modifiers=0, ClickCount=1)
        self.owner.mouse_pressed(event)
        self.drain()

    def release(self, row: int) -> None:
        """The tree's native release selects the row under the pointer before the listener."""
        self.native.clear()
        self.native.add(self.owner.names()[row])
        self.owner.mouse_released(SimpleNamespace(Buttons=LEFT, X=0, Y=row))
        self.drain()

    def cursor(self) -> str | None:
        cursor = self.owner._selection.cursor
        return cursor.name if cursor is not None else None

    def picks(self) -> list[str]:
        return self.owner._selection.names()


ORIGINAL = ("Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel")


@pytest.mark.parametrize("unpicked,expected", [(False, "Bravo"), (True, "Alfa")])
def test_a_refresh_during_the_hold_gives_a_lost_cursor_to_the_pressed_pick(
    unpicked: bool, expected: str
) -> None:
    """Alfa and Bravo are picked and Bravo is held while another window moves it to row 6.
    Ctrl+Down takes the cursor to Hotel, and Hotel is renamed before the release. The refresh
    drops Hotel's ref while Bravo is still held and gives the cursor to the pressed sheet, which
    merely moved, or to the first pick once Ctrl+Space has unpicked Bravo. The refused release
    keeps whatever cursor that refresh wrote (#71).
    """
    held = HeldBravo(ORIGINAL, ("Alfa", "Bravo"))
    held.move("Bravo", 6)
    held.refresh()
    if unpicked:
        held.key(SPACE, MOD1)
    held.key(DOWN, MOD1)
    assert held.cursor() == "Hotel"
    held.rename("Hotel", "Hotel 2")
    held.refresh()
    assert held.cursor() == expected
    kept = held.owner._selection.cursor
    held.release(1)
    assert held.owner._press is None
    assert held.picks() == (["Alfa"] if unpicked else ["Alfa", "Bravo"])
    assert held.owner._selection.cursor is kept
    held.key(SPACE, MOD1)
    assert held.picks() == ([] if unpicked else ["Alfa"])


def test_a_voided_press_gives_its_same_name_replacement_no_cursor_preference() -> None:
    """Bravo, held, is replaced under its name, and the refresh drops every pick and voids the
    press. Ctrl+A then picks every sheet, the replacement Bravo among them, and Ctrl+End puts
    the cursor on Hotel, which is renamed before the release. The refresh that drops that
    cursor must not give it to the replacement for the pressed sheet's name: the first pick
    takes it, and Ctrl+Space after the refused release unpicks Alfa (#71).
    """
    held = HeldBravo(("Alfa", "Bravo", "Charlie", "Hotel"), ("Bravo",))
    held.replace("Bravo")
    held.refresh()
    assert held.owner._press.voided and held.picks() == []
    held.key(A, MOD1)
    held.key(END, MOD1)
    assert held.cursor() == "Hotel"
    held.rename("Hotel", "Hotel 2")
    held.refresh()
    assert held.cursor() == "Alfa"
    held.release(1)
    assert held.cursor() == "Alfa"
    held.key(SPACE, MOD1)
    assert held.picks() == ["Bravo", "Charlie"]


def test_a_refresh_that_proves_nothing_writes_the_lists_selection_even_when_none_dropped() -> None:
    """Bravo, held, is replaced under its name, and the refresh drops every pick. Hotel is
    replaced too before the release, which the tree answers by selecting the pressed row. The
    release writes nothing at that unproved generation; the refresh it asks for proves nothing
    either and has no pick left to drop, but must still write the list's empty selection, or
    the next command would take the replacement Bravo from the tree (#71).
    """
    held = HeldBravo(("Alfa", "Bravo", "Charlie", "Hotel"), ("Bravo",))
    held.replace("Bravo")
    held.refresh()
    assert held.owner._press.voided and held.picks() == [] and held.native == set()
    held.replace("Hotel")
    held.release(1)
    assert held.owner._proven == 2
    assert held.native == set()
    assert held.owner._current_picks() == []


def test_a_lost_proof_clears_a_native_selection_awaiting_intake() -> None:
    """The same write outside a hold: a plain click on Bravo, Ctrl+Space to unpick it, and a
    replacement of Bravo leave nothing picked and no cursor. Assistive technology then selects
    Charlie, and Charlie is replaced under its name before the intake. The refresh must clear
    that selection rather than leave it for the next command under the replacement's handle.
    """
    held = HeldBravo(("Alfa", "Bravo", "Charlie", "Hotel"), ())
    held.release(1)
    held.key(SPACE, MOD1)
    held.replace("Bravo")
    held.refresh()
    assert held.owner._selection.cursor is None and held.native == set()
    held.native.add("Charlie")
    held.replace("Charlie")
    held.refresh()
    assert held.native == set()
    assert held.owner._current_picks() == []


def test_a_pick_made_after_a_lost_proof_survives_a_refused_release() -> None:
    """The control: after the refresh that dropped the picks, Down picks the replacement Bravo
    at the proved generation, and the refused release keeps that newer pick (#71)."""
    held = HeldBravo(("Alfa", "Bravo", "Charlie", "Hotel"), ("Bravo",))
    replacement = held.replace("Bravo")
    held.refresh()
    held.key(DOWN)
    held.release(1)
    picks = held.owner._current_picks()
    assert [ref.name for ref in picks] == ["Bravo"] and picks[0].token is replacement
    assert held.native == {"Bravo"}


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
