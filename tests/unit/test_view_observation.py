"""Native-tab observation must not create picks from stale proof or overwrite newer input.

The observer is `uno_tabs.TabObserver`, loaded from source with its UNO exceptions replaced. Its
host is a fake list built from `SheetList`'s own `TabHost` methods, so these checks also cover
how the list pauses observation and follows Calc.
"""

import contextlib
import enum
import threading
import time
import uuid
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.refresh_schedule import RefreshSchedule
from sheet_manager.reorder import Sheet
from sheet_manager.selection import Ref, Selection, structure_kept
from sheet_manager.sheet_list import RowGeometry, SheetRow
from sheet_manager.structure import VIEW_RESTORE_LIMIT, History, Quiet, StructureEvents
from tests.unit.source_methods import function, method, source_class

SOURCE = "src/sheet_manager/uno_list.py"
INTAKE = source_class(SOURCE, "_Intake", {"enum": enum})
TABS = "src/sheet_manager/uno_tabs.py"
HOST_METHODS = (
    "input_count",
    "proven",
    "observation_paused",
    "sheets_changed",
    "pending_native_picks",
    "follow_tabs",
    "show_tabs",
    "apply_palette",
)
OBSERVER = source_class(
    TABS,
    "TabObserver",
    {
        "Any": Any,
        "Later": Any,
        "MainThread": Any,
        "TabHost": Any,
        "VIEW_INTERVAL": 0.25,
        "HIDDEN_VIEW_INTERVAL": 1.0,
        "DisposedException": ValueError,
        "NoSuchElementException": LookupError,
    },
)
LIST_HOST = type(
    "ListHost",
    (SimpleNamespace,),
    {name: method(SOURCE, "SheetList", name, {}) for name in HOST_METHODS},
)


@pytest.mark.parametrize(
    "barrier",
    ["_busy", "_pointer_depth", "_restoring_cursor", "_press", "_drag", "_menu_context", "menu"],
)
def test_the_list_pauses_observation_during_its_own_input_and_changes(barrier: str) -> None:
    owner, _, _ = observer()
    assert not owner.observation_paused()
    if barrier == "menu":
        owner._menu.is_open = True
    else:
        setattr(owner, barrier, 1 if barrier == "_pointer_depth" else True)
    assert owner.observation_paused()


@pytest.mark.parametrize("barrier", ["_busy", "menu", "lock", "replay"])
def test_palette_sampling_does_not_change_styles_during_an_input_or_replay(barrier: str) -> None:
    owner, tabs, live = observer()
    if barrier == "menu":
        owner._menu.is_open = True
    elif barrier == "lock":
        live.controllers_locked = True
    elif barrier == "replay":
        owner._monitor.events.view_replay = 1
    else:
        setattr(owner, barrier, True)
    tabs.observe(False)
    owner._theme.apply.assert_not_called()


def observer() -> tuple[Any, Any, Any]:
    """A list fake, its real tab observer, and the live Calc state both read."""
    live = SimpleNamespace(
        names=("Alfa", "Bravo", "Charlie"),
        shown=("Alfa", "Bravo", "Charlie"),
        active="Alfa",
        indices=(0,),
        controllers_locked=False,
        actions_locked=False,
    )

    def invoke(*args: object) -> tuple[Any]:
        return (live.indices,)

    live.invoke = Mock(side_effect=invoke)
    live.main = SimpleNamespace(post=Mock(), later=Mock(return_value=object()))
    owner = LIST_HOST(
        _disposed=False,
        _theme=SimpleNamespace(apply=Mock()),
        _busy=False,
        _pointer_depth=0,
        _restoring_cursor=False,
        _press=None,
        _drag=None,
        _menu=SimpleNamespace(is_open=False),
        _menu_context=False,
        _input=0,
        _proven=0,
        _monitor=SimpleNamespace(generation=0, events=StructureEvents()),
        _refreshes=SimpleNamespace(stale=False),
        _status=SimpleNamespace(show_tabs=Mock(return_value=False)),
        _bounds=(300, 600),
        set_bounds=Mock(),
        names=lambda: list(live.shown),
        controller=SimpleNamespace(
            getActiveSheet=lambda: SimpleNamespace(getName=lambda: live.active)
        ),
        document=SimpleNamespace(
            hasControllersLocked=lambda: live.controllers_locked,
            isActionLocked=lambda: live.actions_locked,
            getSheets=lambda: SimpleNamespace(getElementNames=lambda: live.names),
        ),
        _take_tree_selection=Mock(return_value=False),
        _update_moves=Mock(),
        owns_tree_keys=lambda: True,
        _select=Mock(),
        document_modified=Mock(),
    )
    live.frame = SimpleNamespace()
    tabs = OBSERVER(
        live.main,
        live.frame,
        owner.controller,
        owner.document,
        owner._monitor,
        SimpleNamespace(invoke=live.invoke),
        owner,
        0,
    )
    owner._tabs = tabs
    tabs.remember("Alfa", ("Alfa",))  # The baseline Calc showed when the list opened.
    owner._status.show_tabs.reset_mock()
    return owner, tabs, live


def test_tab_only_change_follows_once_without_rebuilding_or_consuming_monitor_evidence() -> None:
    owner, tabs, live = observer()
    tabs.observe(False)
    # The timer's tick, whose samples alone are ordered for the quiet-sample rule (#294).
    owner._take_tree_selection.assert_called_once_with(paint=False, defer=True, tick=True)
    owner._select.assert_not_called()
    live.indices = (0, 2)
    tabs.observe(False)
    owner._select.assert_called_once_with(["Alfa", "Charlie"], "Alfa")
    assert not owner._user_picks  # Calc's picks, not the user's.
    tabs.observe(False)
    assert owner._select.call_count == 1
    owner._status.show_tabs.assert_called_with(("Alfa", "Charlie"))


@pytest.mark.parametrize("newer", ["input", "acknowledgement", "pending_tree_selection"])
def test_newer_list_input_consumes_a_native_change_without_following_it_later(newer: str) -> None:
    owner, tabs, live = observer()
    live.indices = (0, 2)
    if newer == "input":
        owner._input += 1
    elif newer == "acknowledgement":
        tabs.note_input()
    else:
        owner._take_tree_selection.return_value = True
    tabs.observe(False)
    owner._select.assert_not_called()
    tabs._ack_pending = False
    owner._take_tree_selection.return_value = False
    tabs.observe(False)
    owner._select.assert_not_called()
    live.indices = (0, 1)  # A later, distinct native change is followed normally.
    tabs.observe(False)
    owner._select.assert_called_once_with(["Alfa", "Bravo"], "Alfa")


def test_acknowledgement_never_follows_its_own_native_change() -> None:
    owner, tabs, live = observer()
    live.indices = (0, 2)
    tabs.observe(True)
    tabs.observe(False)
    owner._select.assert_not_called()


def test_reordering_native_members_does_not_turn_independent_picks_into_calc_picks() -> None:
    owner, tabs, live = observer()
    tabs.remember("Alfa", ("Alfa", "Charlie"))
    owner._status.show_tabs.reset_mock()
    live.names = live.shown = ("Charlie", "Bravo", "Alfa")
    live.indices = (0, 2)
    tabs.observe(False)
    owner._select.assert_not_called()
    owner._status.show_tabs.assert_called_once_with(("Charlie", "Alfa"))


@pytest.mark.parametrize("change", ["rename", "new_generation"])
def test_new_namespace_or_proof_establishes_a_baseline_without_picking_replacements(
    change: str,
) -> None:
    owner, tabs, live = observer()
    live.indices = (0, 1)
    if change == "rename":
        live.names = live.shown = ("Alfa", "Renamed", "Charlie")
    else:
        owner._monitor.generation = owner._proven = 1
    tabs.observe(False)
    owner._select.assert_not_called()
    assert tabs._state == ("Alfa", frozenset({"Alfa", live.names[1]}))


@pytest.mark.parametrize("kept", [False, True])
def test_refresh_seeds_the_new_proof_before_a_subsequent_tab_change(kept: bool) -> None:
    owner, tabs, live = observer()
    observed = SimpleNamespace(sheets=(), handles=())
    rows = [object()]
    owner._observed, owner.rows, owner._nodes = observed, rows, [object()]
    owner._monitor.generation = 1
    owner._monitor.check = lambda: 1
    owner._renames_elsewhere = Mock(return_value={} if kept else None)
    owner._drop_all_picks = Mock(return_value=True)

    def selected_names() -> list[str]:
        return []

    def carry(renamed: Any, elsewhere: Any) -> bool:
        return False

    owner._selection = SimpleNamespace(carry=carry, names=selected_names, picked=[])
    owner._shown = ()
    owner._unowned = owner._accounted = owner._shown_at = 0
    owner._apply_selection = Mock()
    owner._generation = 0
    owner._name_viewed = Mock()
    owner._release_presses = Mock()  # The rows are kept: no press hold to end (#293).

    def snapshot(document: Any) -> Any:
        return observed

    def read_rows(controller: Any, picture: Any) -> list[object]:
        return rows

    refresh = method(
        SOURCE,
        "SheetList",
        "_refresh",
        {"snapshot": snapshot, "read_rows": read_rows, "Mapping": Mapping},
    )
    prove = method(SOURCE, "SheetList", "_prove", {"Snapshot": Any})

    def prove_rows(observed: Any, generation: int) -> None:
        prove(owner, observed, generation)

    owner._prove = prove_rows
    refresh(owner, {})
    assert owner._take_tree_selection.call_args_list[0].kwargs == {"defer": True}
    assert owner._proven == tabs._generation == 1
    assert tabs._state == ("Alfa", frozenset({"Alfa"}))
    owner._select.assert_not_called()  # Seeding neither repopulates nor overwrites the picks.
    assert owner._drop_all_picks.call_count == int(not kept)
    live.indices = (0, 2)
    tabs.observe(False)  # No sleep or intervening sample after the refreshed rows are ready.
    owner._select.assert_called_once_with(["Alfa", "Charlie"], "Alfa")


@pytest.mark.parametrize(
    "guard", ["busy", "pointer", "restore", "press", "drag", "menu", "controllers", "actions"]
)
def test_unsafe_or_transient_view_never_reads_selected_tabs_or_tree_picks(guard: str) -> None:
    owner, tabs, live = observer()
    if guard == "controllers":
        live.controllers_locked = True
    elif guard == "actions":
        live.actions_locked = True
    elif guard == "menu":
        owner._menu.is_open = True
    else:
        attribute = {
            "busy": "_busy",
            "pointer": "_pointer_depth",
            "restore": "_restoring_cursor",
            "press": "_press",
            "drag": "_drag",
        }
        setattr(owner, attribute[guard], True)
    tabs.observe(False)
    live.invoke.assert_not_called()
    owner._take_tree_selection.assert_not_called()


@pytest.mark.parametrize("stale", ["generation", "row_order"])
def test_stale_rows_request_refresh_without_using_their_indices(stale: str) -> None:
    owner, tabs, live = observer()
    if stale == "generation":
        owner._monitor.generation = 1
    else:
        live.names = ("Charlie", "Bravo", "Alfa")
    tabs.observe(False)
    owner.document_modified.assert_called_once_with()
    live.invoke.assert_not_called()
    owner._select.assert_not_called()
    owner._refreshes.stale = True
    tabs.observe(False)
    assert owner.document_modified.call_count == 1


def test_generation_change_during_the_native_getter_cannot_create_picks() -> None:
    owner, tabs, live = observer()

    def change(*args: object) -> tuple[tuple[int, ...]]:
        owner._monitor.generation += 1
        return (live.indices,)

    live.invoke.side_effect = change
    tabs.observe(False)
    owner._take_tree_selection.assert_not_called()
    owner._select.assert_not_called()


def test_listener_input_only_posts_one_acknowledgement_and_does_not_read_native_state() -> None:
    owner, tabs, live = observer()
    tabs.visible = Mock(return_value=True)
    tabs.note_input()
    tabs.note_input()
    live.invoke.assert_not_called()
    assert live.main.post.call_count == 1
    live.indices = (0, 2)
    live.main.post.call_args.args[0]()
    live.invoke.assert_called_once()
    owner._select.assert_not_called()
    assert not tabs._ack_pending


@pytest.mark.parametrize("key", ["Return", "Menu", "type-ahead", "button-Return", "button-Space"])
def test_queued_key_intent_prevents_an_older_observation_from_replacing_its_picks(key: str) -> None:
    from sheet_manager.keys import (
        CONTEXTMENU,
        RETURN,
        SHIFT,
        SPACE,
        TAB,
        A,
        KeyRoute,
        button_route,
        route_key,
    )

    owner, tabs, live = observer()
    queued: list[Any] = []
    actions: list[str] = []

    def post(function: Any, where: str) -> None:
        queued.append(function)

    owner.post = live.main.post = post
    note_input = method(SOURCE, "SheetList", "note_input", {})
    queue = method(SOURCE, "SheetList", "queue_input", {})
    owner.note_input = lambda: note_input(owner)
    tabs.acknowledge = Mock()
    owner.claim_window = Mock()

    def queue_input(function: Any, where: str) -> None:
        queue(owner, function, where)

    def type_ahead(char: str) -> None:
        actions.append("type-ahead")

    owner.queue_input = queue_input
    owner.activate_selection = lambda: actions.append("Return")
    owner.open_menu_for_keyboard = lambda: actions.append("Menu")
    owner.type_ahead = type_ahead
    owner.owns_keys = lambda: True
    button = key.startswith("button-")
    owner.owns_tree_keys = lambda: not button
    handler = SimpleNamespace(_list=owner, _consumed={})
    pressed = method(
        "src/sheet_manager/uno_keys.py",
        "ListKeyHandler",
        "keyPressed",
        {
            "route_key": route_key,
            "KeyRoute": KeyRoute,
            "TAB": TAB,
            "SHIFT": SHIFT,
            "SPACE": SPACE,
            "button_route": button_route,
        },
    )
    code, char = {
        "Return": (RETURN, "\r"),
        "Menu": (CONTEXTMENU, ""),
        "type-ahead": (A, "a"),
        "button-Return": (RETURN, "\r"),
        "button-Space": (SPACE, " "),
    }[key]
    event = SimpleNamespace(KeyCode=code, KeyChar=char, Modifiers=SHIFT if "Shift" in key else 0)
    assert pressed(handler, event) is not button
    assert owner._input == 1 and tabs._ack_pending
    live.indices = (0, 2)
    tabs.observe(False)  # Already queued ahead of the key's action.
    owner._select.assert_not_called()
    assert not actions
    queued[-1]()
    assert actions == ([] if button else [key])


def test_visibility_guards_native_deck_access_after_sidebar_removal() -> None:
    owner, tabs, live = observer()
    deck = SimpleNamespace(isActive=Mock(side_effect=AssertionError("unsafe native dereference")))
    sidebar = SimpleNamespace(isVisible=lambda: False)
    owner.controller.getSidebar = lambda: sidebar
    live.frame.getController = lambda: owner.controller
    live.frame.getContainerWindow = lambda: SimpleNamespace(IsMinimized=False)
    tabs._controls = deck, object()
    assert not tabs.visible()
    deck.isActive.assert_not_called()
    assert tabs._controls is None


@pytest.mark.parametrize("state", ["collapsed", "inactive", "not_ready"])
def test_visibility_does_not_repeatedly_create_or_lay_out_hidden_native_panels(state: str) -> None:
    owner, tabs, live = observer()
    panel = SimpleNamespace(isExpanded=lambda: state != "collapsed")
    panels = SimpleNamespace(getByName=Mock(return_value=panel))
    deck = SimpleNamespace(isActive=lambda: state != "inactive", getPanels=lambda: panels)
    decks = SimpleNamespace(getByName=Mock(return_value=deck))
    if state == "not_ready":
        decks.getByName.side_effect = LookupError("native sidebar context not ready")
    sidebar = SimpleNamespace(isVisible=lambda: True, getDecks=lambda: decks)
    owner.controller.getSidebar = lambda: sidebar
    live.frame.getController = lambda: owner.controller
    live.frame.getContainerWindow = lambda: SimpleNamespace(IsMinimized=False)
    assert not tabs.visible()
    assert not tabs.visible()
    assert panels.getByName.call_count == int(state == "collapsed")
    assert not tabs.stopped


def test_replaced_controller_stops_observation_before_reading_its_old_sidebar() -> None:
    owner, tabs, live = observer()
    owner.controller.getSidebar = Mock()
    live.frame.getController = lambda: object()
    assert not tabs.visible()
    assert tabs.stopped
    owner.controller.getSidebar.assert_not_called()


def test_an_old_queued_tick_cannot_clear_a_new_timer_or_create_a_second_chain() -> None:
    _, tabs, live = observer()
    current = object()
    tabs._token, tabs._timer = current, object()
    tabs.visible = Mock(return_value=True)
    tabs.observe = Mock()
    tabs._tick(object())
    tabs.visible.assert_not_called()
    tabs._tick(current)
    tabs.observe.assert_called_once_with(False)
    assert live.main.later.call_count == 1
    replacement = tabs._token, tabs._timer
    tabs._tick(current)
    assert (tabs._token, tabs._timer) == replacement
    assert live.main.later.call_count == 1


def test_disposal_cancels_the_chain_and_rejects_an_already_queued_tick() -> None:
    _, tabs, live = observer()
    timer = SimpleNamespace(cancel=Mock())
    live.main.later.return_value = timer
    tabs.start()
    tick = live.main.later.call_args.args[1]
    tabs.visible = Mock(return_value=True)
    tabs.dispose()
    timer.cancel.assert_called_once_with()
    tick()  # Already in the native queue when the list was disposed.
    tabs.visible.assert_not_called()
    assert live.main.later.call_count == 1


def shown_sidebar(owner: Any, live: Any) -> None:
    """Make `visible()` find the list's deck shown and its panel expanded."""
    panel = SimpleNamespace(isExpanded=lambda: True)
    panels = SimpleNamespace(getByName=Mock(return_value=panel))
    deck = SimpleNamespace(isActive=lambda: True, getPanels=lambda: panels)
    decks = SimpleNamespace(getByName=Mock(return_value=deck))
    sidebar = SimpleNamespace(isVisible=lambda: True, getDecks=lambda: decks)
    owner.controller.getSidebar = lambda: sidebar
    live.frame.getController = Mock(return_value=owner.controller)
    live.frame.getContainerWindow = lambda: SimpleNamespace(IsMinimized=False)


@pytest.mark.parametrize("queued", ["tick", "acknowledgement"])
def test_list_disposal_rejects_observer_work_that_runs_during_its_cleanup(queued: str) -> None:
    """Work already queued runs if releasing the list's listeners or controls dispatches events.

    Closing the posting queue cannot revoke it, so the list disposes the observer before that
    release. The work may not read Calc's view, follow its tabs, or schedule another sample.
    """
    owner, tabs, live = observer()
    shown_sidebar(owner, live)
    timer = SimpleNamespace(cancel=Mock())
    live.main.later.return_value = timer
    tabs.start()
    if queued == "tick":
        work = live.main.later.call_args.args[1]
    else:
        tabs.note_input()
        work = live.main.post.call_args.args[0]
    live.indices = (0, 2)  # A tab change that a live tick would follow.
    owner._main, owner._scroll = live.main, 1
    owner._refreshes = SimpleNamespace(close=Mock())
    owner._notice_token, owner._notice_timer = None, None
    owner._cleanup = contextlib.ExitStack()
    owner._cleanup.callback(work)  # Run by a native release, such as removing a listener.
    method(SOURCE, "SheetList", "dispose", {})(owner)
    live.frame.getController.assert_not_called()
    live.invoke.assert_not_called()
    owner._select.assert_not_called()
    assert live.main.later.call_count == 1
    timer.cancel.assert_called_once_with()


def test_stop_schedules_no_further_sample_but_an_outstanding_tick_runs_once() -> None:
    owner, tabs, live = observer()
    tabs.start()
    tick = live.main.later.call_args.args[1]
    tabs.visible = Mock(return_value=True)
    tabs.stop()
    live.indices = (0, 2)
    tick()  # Scheduled before the stop: it still samples, and can follow, once.
    owner._select.assert_called_once_with(["Alfa", "Charlie"], "Alfa")
    assert live.main.later.call_count == 1  # It schedules no successor.
    tabs.acknowledge()  # Nor does a later acknowledgement sample again.
    assert tabs.visible.call_count == 1


def test_calcs_view_during_an_own_replay_is_neither_followed_nor_a_baseline() -> None:
    """#91: until the adapter restores the view after an own Undo or Redo, nothing is read."""
    owner, tabs, live = observer()
    owner._monitor.events.view_replay = 1
    live.active, live.indices = "Charlie", (2,)
    tabs.observe(False)
    live.invoke.assert_not_called()
    owner._select.assert_not_called()
    assert tabs._state == ("Alfa", frozenset({"Alfa"}))
    owner._monitor.events.view_replay = None
    live.active, live.indices = "Alfa", (0,)  # Restored: the earlier baseline still holds.
    tabs.observe(False)
    owner._select.assert_not_called()


def test_a_replay_whose_restoration_never_runs_stops_suppressing_the_list() -> None:
    """#91: a proved replay's view is the adapter's only until its restoration is overdue.

    Without the bound, a restoration that never ran left the list neither sampling Calc's tabs
    nor following its switches for good, as `newer_pick_survives_voided_press` would show.
    """
    owner, tabs, live = observer()
    now = [10.0]
    events = StructureEvents(clock=lambda: now[0])
    # Proved at 10.0; the posted restoration never runs.
    events.serial, events.view_replay, events.view_proved, events.outcomes[1] = 1, 1, 10.0, True
    owner._monitor.events = events
    owner._input, owner._activating, owner.post = 7, False, Mock()
    tabs._input = 7  # The baseline already acknowledges this input.
    event = method(SOURCE, "SheetList", "active_sheet_event", {})
    live.active, live.indices = "Charlie", (2,)

    tabs.observe(False)
    event(owner)
    live.invoke.assert_not_called()
    owner.active_sheet_changed = Mock()
    owner.post.call_args.args[0]()
    owner.active_sheet_changed.assert_called_once_with(False, 7, 1)  # Not followed.

    now[0] += VIEW_RESTORE_LIMIT + 0.01
    owner.post.reset_mock()
    event(owner)
    owner.active_sheet_changed = Mock()
    owner.post.call_args.args[0]()
    owner.active_sheet_changed.assert_called_once_with(False, 7, None)  # Followed again.
    tabs.observe(False)
    live.invoke.assert_called()
    owner._select.assert_called_once_with(["Charlie"], "Charlie")


@pytest.mark.parametrize("outcome", ["proven", "failed", "pending", "none"])
def test_a_switch_during_an_own_replay_is_followed_only_if_the_replay_failed(outcome: str) -> None:
    events = StructureEvents()
    events.serial = 1
    if outcome in ("proven", "failed"):
        events.outcomes[1] = outcome == "proven"
    owner = SimpleNamespace(
        _disposed=False,
        _monitor=SimpleNamespace(events=events),
        _main=SimpleNamespace(later=Mock()),
        _follow_input=None,
        _busy=False,
        # A refresh is scheduled already, so the switch waits for it.
        _refreshes=SimpleNamespace(activated=Mock(return_value=False)),
        _run_refresh=Mock(),
    )
    changed = method(
        SOURCE,
        "SheetList",
        "active_sheet_changed",
        {"REPLAY_WAIT": 0.05, "REPLAY_WAITS": 40, "time": time},
    )
    changed(owner, False, 5, None if outcome == "none" else 1)
    if outcome == "pending":
        owner._main.later.assert_called_once()
        assert owner._follow_input is None
        owner._refreshes.activated.assert_not_called()
        return
    owner._main.later.assert_not_called()
    assert owner._follow_input == (None if outcome == "proven" else 5)
    owner._refreshes.activated.assert_called_once_with(False)
    owner._run_refresh.assert_not_called()


class Handle:
    """A retained sheet handle: it reports the sheet's current name, as Calc's does."""

    def __init__(self, name: str) -> None:
        self.name = name

    def getName(self) -> str:
        return self.name

    def getIsScenario(self) -> bool:
        return False


def drag_list() -> tuple[Any, Any, Any, list[Any]]:
    """A list showing Alfa, Bravo and Charlie with Alfa picked, wired for the real drag start.

    `start_drag`, `refresh`, `_refresh`, `_current_picks`, `_picks_at`, the identity checks, the
    refresh schedule, the picks and `uno_reorder.is_current_as_reported` are the shipped code;
    Calc's sheets, the tree and the drag source are fakes. Work the list posts waits in the
    returned queue, so a test can tell what ran inside the gesture listener from what ran when
    the posted work arrived. VCL fires the gesture with the solar mutex released, so the fake
    structure monitor fails the test if `start_drag` calls its `check()` (#284).
    """
    owner, tabs, live = observer()
    queued: list[Any] = []
    live.handles = [Handle(name) for name in live.names]
    gesture = [False]

    def check() -> int:
        assert not gesture[0], "check() in the drag gesture, without the solar mutex (#284)"
        return owner._monitor.generation

    def snapshot(document: Any) -> Any:
        handles = tuple(live.handles)
        return SimpleNamespace(
            sheets=tuple(Sheet(handle.getName()) for handle in handles),
            document_id="synthetic",
            monitor=owner._monitor,
            generation=owner._monitor.generation,
            handles=handles,
        )

    def read_rows(controller: Any, picture: Any) -> list[SheetRow]:
        return [SheetRow(sheet.name, active=sheet.name == live.active) for sheet in picture.sheets]

    def rebuild(rows: list[SheetRow], observed: Any, generation: int) -> None:
        owner.rows, owner._nodes = rows, [object() for _ in rows]
        owner._prove(observed, generation)

    def bind(name: str, namespace: dict[str, Any]) -> None:
        loaded = method(SOURCE, "SheetList", name, namespace)

        def bound(*arguments: object, **keywords: object) -> Any:
            return loaded(owner, *arguments, **keywords)

        setattr(owner, name, bound)

    def post(work: Any, where: str) -> None:
        queued.append(work)

    def transferable(token: str) -> Any:
        return SimpleNamespace(token=token)

    owner.rows = [SheetRow(name, active=name == live.active) for name in live.names]
    owner._nodes = [object() for _ in owner.rows]
    owner.names = lambda: [row.name for row in owner.rows]
    owner._monitor.check, owner._monitor.document = check, owner.document
    owner._refreshes = RefreshSchedule(Mock(), Mock())
    owner._main = SimpleNamespace(post=post)
    owner._generation, owner._user_picks = 0, False
    owner._handles = dict(zip(live.names, live.handles, strict=True))
    owner._selection = Selection(function(SOURCE, "_current", {"Ref": Ref}))
    owner._selection.take(["Alfa"], owner._handles, owner.names())
    owner._shown = ("Alfa",)
    owner._unowned = owner._accounted = owner._shown_at = 0
    owner._apply_selection, owner._rebuild = Mock(), Mock(side_effect=rebuild)
    owner._show_native, owner._name_viewed = Mock(), Mock()
    owner._release_presses = Mock()  # A refresh that keeps the rows ends no press hold (#293).
    # No press, toggle or range is held, and no write waits, so a drag may start (#295, #304).
    owner._presses_held = owner._toggles_held = owner._ranges_held = None
    owner._toggles_release = owner._ranges_release = None
    owner._selection_write_pending = False
    owner._busy, owner._drag = False, None
    owner._drag_source = SimpleNamespace(startDrag=Mock())
    owner._listeners = {"source": object()}
    owner.document.RuntimeUID = "synthetic"
    owner.document.isReadonly = owner.document.isProtected = lambda: False

    def sheet_at(index: int) -> Handle:
        return live.handles[index]

    owner.document.getSheets = lambda: SimpleNamespace(
        getElementNames=lambda: live.names, getByIndex=sheet_at
    )
    reorder = "src/sheet_manager/uno_reorder.py"
    current = function(
        reorder,
        "is_current_as_reported",
        {
            "Any": Any,
            "Snapshot": Any,
            "_read_sheets": function(reorder, "_read_sheets", {"Any": Any, "Sheet": Sheet}),
            "_shows": function(reorder, "_shows", {"Snapshot": Any, "Sheet": Sheet}),
        },
    )
    drag_type = source_class(SOURCE, "_Drag", {"dataclass": dataclass, "Snapshot": Any})
    bind("post", {})
    bind("refresh", {"Mapping": Mapping})
    bind("_refresh", {"snapshot": snapshot, "read_rows": read_rows, "Mapping": Mapping})
    bind("_prove", {"Snapshot": Any})
    name_or_none = function(SOURCE, "_name_or_none", {"Any": Any})
    bind(
        "_renames_elsewhere",
        {
            "Snapshot": Any,
            "Mapping": Mapping,
            "_name_or_none": name_or_none,
            "structure_kept": structure_kept,
        },
    )
    bind("_drop_all_picks", {"replace": replace})
    bind("_tell_dropped", {})
    bind("_hold_toggles", {})
    bind("_current_picks", {"Ref": Ref})
    bind("_picks_at", {"Ref": Ref})
    bind(
        "start_drag",
        {
            "is_current_as_reported": current,
            "_Transferable": transferable,
            "_Drag": drag_type,
            "uuid": uuid,
            "ACTION_MOVE": 2,
        },
    )
    start = owner.start_drag

    def start_drag(event: object) -> None:
        gesture[0] = True
        try:
            start(event)
        finally:
            gesture[0] = False

    owner.start_drag = start_drag
    owner._observed = snapshot(owner.document)
    return owner, tabs, live, queued


@pytest.mark.parametrize("stale", ["unpicked_rename", "insertion"])
def test_a_drag_on_stale_rows_is_refused_and_samples_tabs_only_in_its_posted_refresh(
    stale: str,
) -> None:
    """#264: the gesture listener never runs the selected-tabs getter.

    A rename of an unpicked sheet keeps the structure generation, so only
    `is_current_as_reported` sees that the rows are stale; an insertion moves the generation,
    which `_picks_at` sees.
    Either way the refresh, and the new tab baseline it samples, wait for the posted work.
    """
    owner, tabs, live, queued = drag_list()
    if stale == "unpicked_rename":
        live.handles[2].name = "Delta"
    else:
        live.handles.append(Handle("Delta"))
        owner._monitor.generation = 1
    live.names = tuple(handle.name for handle in live.handles)
    owner.start_drag(object())
    live.invoke.assert_not_called()
    owner._theme.apply.assert_not_called()  # The sample's palette step did not run either.
    owner._drag_source.startDrag.assert_not_called()
    assert owner._drag is None
    assert owner.names() == ["Alfa", "Bravo", "Charlie"]  # Nothing refreshed yet.
    assert len(queued) == 1
    queued.pop()()
    live.invoke.assert_called_once()
    assert owner.names() == list(live.names)
    assert tabs._state == ("Alfa", frozenset({"Alfa"}))  # A new baseline, not new picks.
    owner._select.assert_not_called()
    assert owner._selection.names() == (["Alfa"] if stale == "unpicked_rename" else [])
    assert not queued


def test_a_stale_drags_posted_refresh_does_nothing_once_the_list_is_disposed() -> None:
    owner, tabs, live, queued = drag_list()
    live.handles[2].name = "Delta"
    live.names = ("Alfa", "Bravo", "Delta")
    owner.start_drag(object())
    owner._disposed = True
    tabs.dispose()
    queued.pop()()
    live.invoke.assert_not_called()
    assert owner.names() == ["Alfa", "Bravo", "Charlie"]


def test_a_drag_on_current_rows_starts_at_once_without_posting_or_sampling_tabs() -> None:
    owner, _, live, queued = drag_list()
    event = object()
    observed = owner._observed
    owner.start_drag(event)
    owner._drag_source.startDrag.assert_called_once()
    trigger, action, _, _, transferable, listener = owner._drag_source.startDrag.call_args.args
    assert (trigger, action, listener) == (event, 2, owner._listeners["source"])
    assert owner._drag.transferable is transferable
    assert (owner._drag.names, owner._drag.observed, owner._drag.generation) == (
        ["Alfa"],
        observed,
        0,
    )
    assert not queued
    live.invoke.assert_not_called()


ROW = 20


def _report(where: str) -> None:
    raise AssertionError(f"{where} failed")  # Shows the error that `_guarded` would log.


class VisibleHandle(Handle):
    """A retained handle that also reports its sheet's visibility, which activation reads."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.IsVisible = True


def click_list() -> tuple[Any, Any, Any, list[Any]]:
    """A list showing Alfa, Bravo and Charlie with Alfa active and picked, wired for a release.

    The shipped `_Mouse` listener, `mouse_released`, `_pressed_sheet_in_place`,
    `_activate_pressed`, `activate` and `post`, the picks, the tab observer and
    `uno_calc.selected_tabs` run; Calc's view, the tree and the posting are fakes. Work the list
    posts waits in the returned queue, so a test can tell what ran inside the mouse listener
    from what ran when the posted work arrived (#269). Returns the list, the live Calc state,
    the listener and the queue.
    """
    owner, _, live = observer()
    queued: list[Any] = []
    live.handles = [VisibleHandle(name) for name in live.names]

    def set_active(handle: Any) -> None:
        live.active = handle.getName()
        live.indices = (list(live.names).index(live.active),)

    def post(work: Any, where: str) -> None:
        queued.append(work)

    def getter(context: object) -> Any:
        return SimpleNamespace(invoke=live.invoke)

    def prop(name: str, value: object) -> tuple[str, object]:
        return name, value

    def bind(name: str, namespace: dict[str, Any]) -> None:
        loaded = method(SOURCE, "SheetList", name, namespace)

        def bound(*arguments: object) -> Any:
            return loaded(owner, *arguments)

        setattr(owner, name, bound)

    owner.controller.setActiveSheet = Mock(side_effect=set_active)
    owner.rows = [SheetRow(name, active=name == live.active) for name in live.names]
    owner._handles = dict(zip(live.names, live.handles, strict=True))
    owner._monitor.check = lambda: owner._monitor.generation
    owner._main = SimpleNamespace(post=post)
    owner._selection = Selection(function(SOURCE, "_current", {"Ref": Ref}))
    owner._selection.take(["Alfa"], owner._handles, owner.names())
    owner.geometry = lambda: RowGeometry(0, ROW, len(owner.rows))
    owner._queue_selection, owner.refresh = Mock(), Mock()
    owner.restore_view = Mock(return_value=True)
    owner._activating, owner._activation_input = False, 0
    # The release's read of the count, against what is accounted for (#307).
    owner._unowned = owner._input_seen = owner._accounted = 0
    owner._drag_release = False
    owner._unclaimed = False
    owner._intake = INTAKE.CHANGES
    bind("_unread", {"_Intake": INTAKE})
    owner.context, owner.frame, owner.peer = object(), object(), object()
    owner.dispatch, owner.show_error = Mock(), Mock()
    selected = function(
        "src/sheet_manager/uno_calc.py",
        "selected_tabs",
        {"selected_tabs_method": getter},
    )
    bind("post", {})
    bind("_pressed_sheet_in_place", {"_Press": Any})
    bind("_activate_pressed", {"Any": Any})
    bind(
        "activate",
        {
            "Any": Any,
            "selected_tabs": selected,
            "dispatch": owner.dispatch,
            "prop": prop,
            "show_error": owner.show_error,
            "tr": str,
        },
    )
    bind("mouse_released", {"LEFT": 1, "RIGHT": 2, "SHIFT": 1, "MOD1": 2})
    mouse = source_class(
        SOURCE,
        "_Mouse",
        {
            "unohelper": SimpleNamespace(Base=type("Base", (), {})),
            "XMouseListener": type("XMouseListener", (), {}),
            "_guarded": function(SOURCE, "_guarded", {"report": _report}),
        },
    )
    return owner, live, mouse(owner), queued


def release_on(owner: Any, live: Any, listener: Any, name: str, clicks: int) -> None:
    """Hold a left press on the row of `name`, then release it there through the listener."""
    row = list(live.names).index(name)
    press = source_class(SOURCE, "_Press", {"dataclass": dataclass, "Any": Any})
    owner._press = press(row, 0, name, owner._handles[name], 0, clicks=clicks)
    listener.mouseReleased(SimpleNamespace(Buttons=1, X=10, Y=row * ROW + ROW // 2))
    assert owner._pointer_depth == 0


def test_a_double_click_activates_its_sheet_only_in_posted_work() -> None:
    """#269: VCL runs mouse listeners without the solar mutex, which the tab getter never takes.

    The release itself narrows the picks; the activation, which reads Calc's tabs before and
    after `setActiveSheet`, waits for the posted work, which holds the mutex.
    """
    owner, live, listener, queued = click_list()
    release_on(owner, live, listener, "Bravo", clicks=2)
    live.invoke.assert_not_called()
    owner.controller.setActiveSheet.assert_not_called()
    assert owner._selection.names() == ["Bravo"]
    owner._queue_selection.assert_called()
    assert len(queued) == 1
    queued.pop()()
    owner.controller.setActiveSheet.assert_called_once_with(owner._handles["Bravo"])
    live.invoke.assert_called()
    assert (live.active, owner._activation_input, owner._activating) == ("Bravo", 1, False)
    owner.dispatch.assert_not_called()  # Bravo became Calc's only selected tab.
    owner.show_error.assert_not_called()
    assert not queued


def test_a_double_clicks_posted_activation_does_nothing_once_the_list_is_disposed() -> None:
    """Closing the document disposes the list and detaches its monitor, whose check raises."""
    owner, live, listener, queued = click_list()
    release_on(owner, live, listener, "Bravo", clicks=2)
    owner._disposed = True
    owner._monitor.check = Mock(side_effect=RuntimeError("detached"))
    queued.pop()()
    owner._monitor.check.assert_not_called()
    live.invoke.assert_not_called()
    owner.controller.setActiveSheet.assert_not_called()
    assert live.active == "Alfa" and not queued


def test_activation_does_nothing_once_the_list_is_disposed() -> None:
    """Enter's queued activation reaches `activate` itself, which checks disposal first."""
    owner, live, _, queued = click_list()
    owner._disposed = True
    owner._monitor.check = Mock(side_effect=RuntimeError("detached"))
    owner.activate("Bravo")
    live.invoke.assert_not_called()
    owner.controller.setActiveSheet.assert_not_called()
    assert live.active == "Alfa" and not queued


class ClosedControl:
    """A control after `dispose`: every call fails, as a disposed toolkit control's do."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def call(*arguments: object) -> Any:
            self.calls.append(name)
            raise RuntimeError(f"{name} on a disposed control")

        return call


def bind_source(owner: Any, name: str, namespace: dict[str, Any]) -> None:
    """Give `owner` the shipped `SheetList` method `name`, with its globals in `namespace`."""
    loaded = method(SOURCE, "SheetList", name, namespace)

    def bound(*arguments: object, **keywords: object) -> Any:
        return loaded(owner, *arguments, **keywords)

    setattr(owner, name, bound)


def run_posted(work: Any, where: str) -> None:
    """Run posted work as `MainThread` does, through `uno_calc`'s shipped callback.

    Its `report` is the test's `_report`, so a failure that the extension would log on stderr
    fails the test.
    """
    callback = source_class(
        "src/sheet_manager/uno_calc.py",
        "_Callback",
        {
            "unohelper": SimpleNamespace(Base=type("Base", (), {})),
            "XCallback": type("XCallback", (), {}),
            "report": _report,
        },
    )
    callback(work, where).notify(None)


def close_list(owner: Any, closed: str, checked: Mock | None = None) -> None:
    """Dispose the list through the shipped `dispose`, as closing the document or sidebar does.

    Closing the document also detaches its structure monitor, whose check then raises.
    """
    owner._refreshes, owner._notice_timer, owner._notice_token = Mock(), None, None
    owner._scroll, owner._cleanup = 0, contextlib.ExitStack()
    bind_source(owner, "dispose", {})
    owner.dispose()
    if closed == "document" and checked is not None:
        checked.side_effect = RuntimeError("The sheet structure monitor has been disposed")


@pytest.mark.parametrize("closed", ["document", "sidebar"])
@pytest.mark.parametrize("key", ["Return", "Menu", "type-ahead"])
def test_a_keys_queued_work_does_nothing_once_the_list_is_disposed(key: str, closed: str) -> None:
    """#282: a key's queued work can run after `dispose`, which does not revoke it.

    Closing the document or the sidebar right after the key disposes the list, and with the
    document its structure monitor, whose check then raises. The work runs through the shipped
    key handler, `queue_input` and `MainThread`'s callback, so a read of the picks, the monitor
    or the closed tree before the disposal check is reported as the key's failure.
    """
    from sheet_manager.keys import (
        CONTEXTMENU,
        RETURN,
        SHIFT,
        SPACE,
        TAB,
        A,
        KeyRoute,
        TypeAhead,
        button_route,
        find_prefix,
        route_key,
    )
    from sheet_manager.sheet_list import ordered

    owner, live, _, queued = click_list()
    owner.tree, owner.peer = ClosedControl(), ClosedControl()
    owner._shown, owner._selection_write_pending, owner._context_target = ("Alfa",), False, None
    owner._type_ahead, owner._cursor = TypeAhead(), "Alfa"
    owner.claim_window, owner._open_menu = Mock(), Mock()
    owner.owns_keys = owner.owns_tree_keys = lambda: True
    checked = Mock(side_effect=owner._monitor.check)
    owner._monitor.check = checked
    for name, namespace in (
        ("note_input", {}),
        ("queue_input", {}),
        ("selected_names", {"ordered": ordered}),
        ("_take_tree_selection", {}),
        ("_current_picks", {"Ref": Ref}),
        ("_picks_at", {"Ref": Ref}),
        ("_ref", {"Ref": Ref}),
        ("_focus_row", {}),
        ("_move_tree_cursor", {"SINGLE": 0, "MULTI": 2}),
        ("activate_selection", {}),
        ("open_menu_for_keyboard", {}),
        ("type_ahead", {"time": time, "find_prefix": find_prefix}),
    ):
        bind_source(owner, name, namespace)
    owner.names = lambda: list(live.shown)
    pressed = method(
        "src/sheet_manager/uno_keys.py",
        "ListKeyHandler",
        "keyPressed",
        {
            "route_key": route_key,
            "KeyRoute": KeyRoute,
            "TAB": TAB,
            "SHIFT": SHIFT,
            "SPACE": SPACE,
            "button_route": button_route,
        },
    )
    code, char = {"Return": (RETURN, "\r"), "Menu": (CONTEXTMENU, ""), "type-ahead": (A, "a")}[key]
    handler = SimpleNamespace(_list=owner, _consumed={})
    assert pressed(handler, SimpleNamespace(KeyCode=code, KeyChar=char, Modifiers=0)) is True
    assert len(queued) == 1
    work = queued.pop()

    owner._disposed = True
    if closed == "document":
        checked.side_effect = RuntimeError("The sheet structure monitor has been disposed")
    where = {"Return": "activating a sheet", "Menu": "the sheet tab menu"}.get(key, key)
    run_posted(work, where)
    checked.assert_not_called()
    assert owner.tree.calls == owner.peer.calls == []
    owner._open_menu.assert_not_called()
    live.invoke.assert_not_called()
    owner.controller.setActiveSheet.assert_not_called()
    assert live.active == "Alfa" and not queued


@pytest.mark.parametrize("closed", ["document", "sidebar"])
def test_a_queued_selection_write_does_nothing_once_the_list_is_disposed(closed: str) -> None:
    """#285: the tree write that clicks and selection keys queue can run after `dispose`.

    `_queue_selection` posts `_flush_selection`, which checks the structure monitor and writes
    the tree. Closing the document or the sidebar in between disposes the list. The write runs
    through the shipped posting callback, so a check of the monitor or a call on the closed tree
    is reported as a failure of "showing the selection".
    """
    owner, live, _, queued = click_list()
    owner.tree, owner.peer = ClosedControl(), ClosedControl()
    owner._nodes = [object() for _ in live.shown]
    owner._shown, owner._selection_write_pending, owner._selection_scroll = ("Alfa",), False, False
    checked = Mock(side_effect=owner._monitor.check)
    owner._monitor.check = checked
    for name, namespace in (
        ("_queue_selection", {}),
        ("_flush_selection", {}),
        ("_show_selection", {}),
        ("_write_outside_refresh", {"Callable": Callable}),
        ("_apply_selection", {}),
        ("_move_tree_cursor", {"SINGLE": 0, "MULTI": 2}),
    ):
        bind_source(owner, name, namespace)
    owner._queue_selection(scroll=True)  # As a mouse listener or a selection key leaves it.
    assert len(queued) == 1
    close_list(owner, closed, checked)
    run_posted(queued.pop(), "showing the selection")
    checked.assert_not_called()
    assert owner.tree.calls == owner.peer.calls == []
    owner.refresh.assert_not_called()
    assert not queued


MENU_CHOICES = {"Delete": 3, "Show": 1, "Rename Sheets": 6, "Move to top": 20001, "Help": 20006}


@pytest.mark.parametrize("closed", ["document", "sidebar"])
@pytest.mark.parametrize("chosen", list(MENU_CHOICES))
def test_a_menu_command_chosen_just_before_the_list_closes_does_not_run(
    chosen: str, closed: str
) -> None:
    """#285: the menu posts its completion as the popup closes; it can run after `dispose`.

    If the list closes during the popup, `post` refuses the completion (#63). If it closes after
    the popup and before the completion, the command chosen for the list's targets does not run
    either: the document is gone, or the closed list could not show its refusal or failure. The
    completion still ends the menu's state. The keyboard menu opens it through the shipped
    `_open_menu`; the stand-in for `SheetMenu.run` checks `unchanged()` first, as it does.
    """
    owner, live, _, queued = click_list()
    owner.tree, owner.peer = ClosedControl(), ClosedControl()
    checked = Mock(side_effect=owner._monitor.check)
    owner._monitor.check = checked
    observed = SimpleNamespace(
        sheets=[SimpleNamespace(name=name) for name in live.names], handles=live.handles
    )
    ran: list[str] = []

    def run(item: int, observed: object, picked: list[str], unchanged: Any) -> str:
        if not unchanged():
            return "stale"
        ran.append(f"command {item} on {picked}")
        return ""

    def snapshot(document: object) -> Any:
        return observed

    owner._menu = SimpleNamespace(
        is_open=False, show=Mock(return_value=MENU_CHOICES[chosen]), run=Mock(side_effect=run)
    )
    shell = Mock()
    owner.context = SimpleNamespace(
        ServiceManager=SimpleNamespace(createInstanceWithContext=Mock(return_value=shell))
    )
    owner.frame = SimpleNamespace(getContainerWindow=Mock())
    owner._observed, owner._busy, owner._menu_context = observed, False, False
    owner._context_target, owner._generation = None, 0
    current = function(SOURCE, "_current", {"Ref": Ref})
    show_sheets, rename_dialog, apply_order = Mock(), Mock(), Mock()
    for name, namespace in (
        (
            "_open_menu",
            {
                "Ref": Ref,
                "snapshot": snapshot,
                "_current": current,
                "DisposedException": LookupError,
            },
        ),
        (
            "_menu_action",
            {
                "MOVE_IDS": {20001: "top", 20002: "up", 20003: "down", 20004: "bottom"},
                "HELP": 20006,
                "RENAME_SHEETS": 6,
                "SHOW": 1,
                "COMMANDS": {2: ".uno:Insert", 3: ".uno:Remove", 4: ".uno:RenameTable"},
                "show_sheets": show_sheets,
                "show_error": owner.show_error,
                "tr": str,
            },
        ),
        (
            "_rename",
            {
                "Batch": Mock(),
                "RenameDialog": rename_dialog,
                "apply_renames": Mock(),
                "is_current": Mock(return_value=True),
                "preflight": Mock(return_value=""),
                "show_error": owner.show_error,
                "tr": str,
            },
        ),
        ("_command_refused", {"show_error": owner.show_error, "tr": str}),
        (
            "_move_selection",
            {
                "_current": current,
                "plan_move": Mock(),
                "apply_order": apply_order,
                "show_error": owner.show_error,
                "tr": str,
            },
        ),
        ("_finish_menu", {}),
    ):
        bind_source(owner, name, namespace)
    owner._open_menu(10, 20, list(owner._selection.picked))  # As the menu key's work does.
    assert len(queued) == 1 and owner._menu_context and owner._activating
    close_list(owner, closed, checked)
    checked.reset_mock()
    run_posted(queued.pop(), "completing the sheet menu")
    checked.assert_not_called()
    assert ran == []
    show_sheets.assert_not_called()
    rename_dialog.assert_not_called()
    apply_order.assert_not_called()
    shell.execute.assert_not_called()
    owner.show_error.assert_not_called()
    assert owner.tree.calls == owner.peer.calls == []
    assert not owner._menu_context and not owner._activating and owner._context_target is None
    assert not queued


class FrameClosed(Exception):
    """Stands in for the `DisposedException` that a closed frame's `queryDispatch` raises."""


@pytest.mark.parametrize(
    "closed", ["nothing", "unsupported", "sidebar", "document", "closing", "reload"]
)
@pytest.mark.parametrize("command", [".uno:Undo", ".uno:Save"])
def test_a_forwarded_shortcut_reaches_only_the_view_it_was_typed_in(
    command: str, closed: str
) -> None:
    """#285: a shortcut typed in the list is dispatched by posted work, after a close maybe.

    It still runs after only the sidebar closed: the user typed it into this window. Once the
    document has closed or reloaded it is dropped, as LibreOffice drops a shortcut it queued for
    a frame that closed meanwhile (`svt::AcceleratorExecute`). Measured with 26.8.1.1: a closed
    frame has no controller and its `queryDispatch` raises; a reloaded one has a new controller
    and resolves the command against the new document. A frame that is still closing can have
    its controller and raise. After a save, only an open list takes the focus back (#23), and
    only when the save ran: with no dispatcher for it, nothing moved the focus.
    """
    from sheet_manager.keys import keeps_focus

    owner, _, _, queued = click_list()
    dispatcher = Mock()
    view = {"document": None, "reload": SimpleNamespace()}.get(closed, owner.controller)

    def query(url: Any, target: str, flags: int) -> Any:
        if closed in ("document", "closing"):
            raise FrameClosed("Frame disposed")
        return None if closed == "unsupported" else dispatcher

    def command_url(context: object, text: str) -> Any:
        return SimpleNamespace(Complete=text)

    def prop(name: str, value: object) -> tuple[str, object]:
        return name, value

    frame = SimpleNamespace(getController=lambda: view, queryDispatch=Mock(side_effect=query))
    owner.frame, owner.context, owner.tree = frame, object(), object()
    owner.owns_tree_keys = lambda: True
    query_command = function(
        "src/sheet_manager/uno_calc.py", "query_command", {"command_url": command_url}
    )
    for name, namespace in (
        ("run_command", {"keeps_focus": keeps_focus}),
        (
            "_forward",
            {"Any": Any, "query_command": query_command, "DisposedException": FrameClosed},
        ),
        ("_save_keeping_focus", {"prop": prop}),
    ):
        bind_source(owner, name, namespace)
    save = keeps_focus(command)
    owner.run_command(command)  # From the key handler, while the list is open.
    assert len(queued) == 1
    if closed not in ("nothing", "unsupported"):
        close_list(owner, closed)
    run_posted(queued.pop(), "a save shortcut" if save else "a shortcut")
    runs = closed in ("nothing", "sidebar")
    if runs:
        arguments = (("SynchronMode", True),) if save else ()
        dispatcher.dispatch.assert_called_once_with(SimpleNamespace(Complete=command), arguments)
    else:
        dispatcher.dispatch.assert_not_called()
    queried = ("nothing", "unsupported", "sidebar", "closing")
    assert frame.queryDispatch.called == (closed in queried)
    assert len(queued) == (1 if save and closed == "nothing" else 0)  # The focus restoration.


def test_a_double_clicks_posted_activation_refuses_after_a_refresh_at_a_newer_generation() -> None:
    """The posted work checks the generation its release verified, not the list's newer proof.

    Another thread deletes Bravo and renames as "Bravo" the sheet that Bravo's retained handle
    turned to (AGENTS.md, "Sheet identity"), so the pressed handle passes the name and
    visibility checks. The selection flush queued ahead of the activation then refreshes at
    the new generation, which drops the picks and proves the list there, as `_refresh` does.
    Activating would go to a sheet the user did not double-click.
    """
    owner, live, listener, queued = click_list()
    release_on(owner, live, listener, "Bravo", clicks=2)
    owner._monitor.generation = 1
    owner._selection.clear()
    owner._proven = 1
    assert live.handles[1].getName() == "Bravo"
    queued.pop()()
    owner.controller.setActiveSheet.assert_not_called()
    live.invoke.assert_not_called()
    assert queued == [owner.refresh]


def test_a_double_clicks_posted_activation_acts_only_on_the_pressed_handle() -> None:
    """A row now showing another sheet under the pressed name does not take the activation.

    Between the release and the posted work, the pressed sheet is renamed and the handle the
    list retains for "Bravo" is a new sheet's; the generation stays where the release saw it.
    """
    owner, live, listener, queued = click_list()
    release_on(owner, live, listener, "Bravo", clicks=2)
    live.handles[1].name = "Delta"
    owner._handles["Bravo"] = VisibleHandle("Bravo")
    queued.pop()()
    owner.controller.setActiveSheet.assert_not_called()
    live.invoke.assert_not_called()
    assert queued == [owner.refresh]


@pytest.mark.parametrize("change", ["rename", "hide", "insertion"])
def test_a_double_clicks_posted_activation_checks_the_pressed_sheet_when_it_runs(
    change: str,
) -> None:
    """A change between the release and the posted work refreshes instead of activating."""
    owner, live, listener, queued = click_list()
    release_on(owner, live, listener, "Bravo", clicks=2)
    if change == "rename":
        live.handles[1].name = "Delta"
    elif change == "hide":
        live.handles[1].IsVisible = False
    else:
        owner._monitor.generation = 1
    queued.pop()()
    owner.controller.setActiveSheet.assert_not_called()
    live.invoke.assert_not_called()
    assert queued == [owner.refresh]


def test_a_single_clicks_release_picks_its_sheet_and_posts_no_activation() -> None:
    owner, live, listener, queued = click_list()
    release_on(owner, live, listener, "Charlie", clicks=1)
    assert owner._selection.names() == ["Charlie"]
    assert not queued
    live.invoke.assert_not_called()
    owner.controller.setActiveSheet.assert_not_called()


class Workbook:
    """A document as the structure monitor reads it, which another program edits meanwhile.

    One read can host another program's edit: the read takes its value, then the edit runs on
    another thread and is reported to the monitor as LibreOffice reports a recorded change, the
    undo action before the modify notification. The test waits for that thread before the read
    returns, so the interleaving is exact.
    """

    RuntimeUID = "synthetic-workbook"
    IsUndoEnabled = True

    def __init__(self, names: tuple[str, ...]) -> None:
        self.names = list(names)
        self.locked = False  # Another program holds the undo manager's lock.
        self.titles: list[str] = []
        self.listener: Any = None
        self.edit: Callable[[], None] | None = None
        self.edit_at = ""

    def read(self, where: str, value: Any) -> Any:
        if self.edit is not None and where == self.edit_at:
            self.run_edit()
        return value

    def run_edit(self) -> None:
        edit, self.edit = self.edit, None
        assert edit is not None
        thread = threading.Thread(target=edit)
        thread.start()
        thread.join()

    def change(self, title: str, edit: Callable[[list[str]], None]) -> None:
        edit(self.names)
        self.titles.insert(0, title)
        self.listener.undoActionAdded(None)
        self.listener.modified(None)

    def getSheets(self) -> "Workbook":
        return self

    def getCount(self) -> int:
        return self.read("count", len(self.names))

    def getUndoManager(self) -> "Workbook":
        return self

    def getAllUndoActionTitles(self) -> tuple[str, ...]:
        return self.read("history", tuple(self.titles))

    def isLocked(self) -> bool:
        return self.read("quiet", self.locked)

    def hasControllersLocked(self) -> bool:
        return False

    def isActionLocked(self) -> bool:
        return False

    def isSetModifiedEnabled(self) -> bool:
        return True

    def addModifyListener(self, listener: Any) -> None:
        self.listener = listener

    def addUndoManagerListener(self, listener: Any) -> None:
        pass

    def addDocumentEventListener(self, listener: Any) -> None:
        pass


MONITOR = source_class(
    "src/sheet_manager/uno_structure.py",
    "StructureMonitor",
    {
        "unohelper": SimpleNamespace(Base=type("Base", (), {})),
        "XModifyListener": type("XModifyListener", (), {}),
        "XUndoManagerListener": type("XUndoManagerListener", (), {}),
        "XDocumentEventListener": type("XDocumentEventListener", (), {}),
        "StructureEvents": StructureEvents,
        "Quiet": Quiet,
        "History": History,
        "Any": Any,
        "Generator": Generator,
        "contextlib": contextlib,
        "_MONITORS": {},
    },
)


@pytest.mark.parametrize("during", ["count", "history", "quiet", "name"])
def test_another_programs_edit_during_a_release_leaves_its_later_edits_visible(during: str) -> None:
    """#284: VCL runs the release without the solar mutex (#269), so another program can
    change the document and report it while the release's own reads run.

    Another thread inserts a sheet during one of those reads: the structure monitor's sheet
    count, undo history or quiet state, or the pressed handle's name. If the release makes no
    such read, the edit follows the release. A monitor check whose count read came before the
    insertion, but whose update came after its report, would keep the old count, and so take
    the deletion of that sheet, which the other program makes during the next press, for no
    change at all. That press's generation would then still prove its handle, as a double
    click's posted activation trusts it to (#269). The posted check must see the deletion.
    """
    owner, live, listener, queued = click_list()
    book = Workbook(live.names)
    monitor = MONITOR(book)
    owner._monitor, owner._proven = monitor, monitor.generation
    owner._apply_selection = Mock()
    pressed = owner._handles["Bravo"]
    pressed.getName = lambda: book.read("name", pressed.name)
    book.edit_at = during
    book.edit = lambda: book.change("Insert Sheet", lambda names: names.append("Delta"))
    release_on(owner, live, listener, "Bravo", clicks=2)
    if book.edit is not None:
        book.run_edit()  # The release made no read of this kind.
    while queued:
        queued.pop(0)()
    owner.controller.setActiveSheet.assert_not_called()  # The insertion moved the generation.
    seen = monitor.generation  # As the next press captures it (`mouse_pressed`).
    book.edit = lambda: book.change("Delete Sheet", lambda names: names.remove("Delta"))
    book.run_edit()
    assert monitor.check() != seen


@pytest.mark.parametrize("during", ["count", "history", "quiet", "name"])
def test_another_programs_edit_during_a_drag_gesture_leaves_its_later_edits_visible(
    during: str,
) -> None:
    """#284: VCL fires the drag gesture with the solar mutex released, as it runs the release.

    Another thread inserts a sheet during one of the gesture's reads: the structure monitor's
    sheet count, undo history or quiet state, or the picked sheet's retained handle name. If the
    gesture makes no such read, the edit follows it. A monitor check whose count read came
    before the insertion, but whose update came after its report, would keep the old count, and
    so take the deletion of that sheet, which the other program makes before the list's posted
    work runs, for no change at all. A press's generation read meanwhile would then still prove
    its handle across the deletion. The monitor must see the deletion.
    """
    owner, _, live, _ = drag_list()
    book = Workbook(live.names)
    monitor = MONITOR(book)
    owner._monitor, owner._proven = monitor, monitor.generation
    owner._observed.monitor, owner._observed.generation = monitor, monitor.generation
    picked = live.handles[0]
    picked.getName = lambda: book.read("name", picked.name)
    book.edit_at = during
    book.edit = lambda: book.change("Insert Sheet", lambda names: names.append("Delta"))
    owner.start_drag(object())
    if book.edit is not None:
        book.run_edit()  # The gesture made no read of this kind.
    seen = monitor.generation  # As the next press captures it (`mouse_pressed`).
    book.edit = lambda: book.change("Delete Sheet", lambda names: names.remove("Delta"))
    book.run_edit()
    assert monitor.check() != seen


def test_a_change_reported_while_the_gesture_reads_an_unpicked_handle_refuses_the_drag() -> None:
    """#284: `is_current_as_reported` compares the reported generation after its reads too.

    A change that another program reports while the gesture reads an unpicked sheet's retained
    handle name, after the picks were read, must refuse the drag and post a refresh, as a change
    reported before the reads does.
    """
    owner, _, live, queued = drag_list()
    book = Workbook(live.names)
    monitor = MONITOR(book)
    owner._monitor, owner._proven = monitor, monitor.generation
    owner._observed.monitor, owner._observed.generation = monitor, monitor.generation
    other = live.handles[1]
    other.getName = lambda: book.read("name", other.name)
    book.edit_at = "name"
    book.edit = lambda: book.change("Insert Sheet", lambda names: names.append("Delta"))
    owner.start_drag(object())
    assert book.edit is None, "the gesture did not read the unpicked handle's name"
    assert owner._drag is None and len(queued) == 1


def test_a_drag_on_a_snapshot_whose_monitor_was_detached_is_refused() -> None:
    """#284: a snapshot whose structure monitor was detached from its document is not current."""
    owner, _, live, queued = drag_list()
    book = Workbook(live.names)
    monitor = MONITOR(book)
    owner._monitor, owner._proven = monitor, monitor.generation
    owner._observed.monitor, owner._observed.generation = monitor, monitor.generation
    monitor._document = None
    owner.start_drag(object())
    assert owner._drag is None and len(queued) == 1


@pytest.mark.parametrize("lock", ["held", "released"])
def test_a_single_click_under_another_programs_lock_stands_only_if_nothing_changed(
    lock: str,
) -> None:
    """#284: the release reads the generation, so it does not see a lock that another program
    holds at a single click, and narrows the picks to the clicked sheet at once.

    The selection flush it posts checks the monitor. While the lock is still held, the check
    moves the generation, and the flush refreshes instead of showing the picks, so the refresh
    decides what can still be proved. Once the lock is released with nothing changed or
    reported, the check finds nothing and the click stands.
    """
    owner, live, listener, queued = click_list()
    book = Workbook(live.names)
    monitor = MONITOR(book)
    owner._monitor, owner._proven = monitor, monitor.generation
    owner._show_selection = Mock()  # The flush shows the picks through it (#257).
    owner._overtaken = Mock(return_value=False)  # Only the list changed the tree (#307).
    owner._selection_scroll = owner._selection_write_pending = False

    def bind(name: str) -> None:
        loaded = method(SOURCE, "SheetList", name, {})

        def bound(*arguments: object) -> Any:
            return loaded(owner, *arguments)

        setattr(owner, name, bound)

    bind("_queue_selection")
    bind("_flush_selection")
    book.locked = True
    release_on(owner, live, listener, "Bravo", clicks=1)
    assert owner._selection.names() == ["Bravo"]
    assert monitor.generation == owner._proven  # The release saw nothing.
    book.locked = lock == "held"
    assert len(queued) == 1
    queued.pop()()  # The selection flush.
    if lock == "held":
        owner.refresh.assert_called_once_with()
        owner._show_selection.assert_not_called()
    else:
        owner.refresh.assert_not_called()
        owner._show_selection.assert_called_once_with()
    assert owner._selection.names() == ["Bravo"] and not queued
