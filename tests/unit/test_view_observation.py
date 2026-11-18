"""Native-tab observation must not create picks from stale proof or overwrite newer input.

The observer is `uno_tabs.TabObserver`, loaded from source with its UNO exceptions replaced. Its
host is a fake list built from `SheetList`'s own `TabHost` methods, so these checks also cover
how the list pauses observation and follows Calc.
"""

import contextlib
import time
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.structure import VIEW_RESTORE_LIMIT, StructureEvents
from tests.unit.source_methods import method, source_class

SOURCE = "src/sheet_manager/uno_list.py"
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
    owner._take_tree_selection.assert_called_once_with(paint=False, defer=True)
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
    owner._identities_kept = Mock(return_value=kept)
    owner._drop_all_picks = Mock(return_value=True)

    def selected_names() -> list[str]:
        return []

    def carry(renamed: Any) -> bool:
        return False

    owner._selection = SimpleNamespace(carry=carry, names=selected_names)
    owner._shown = ()
    owner._apply_selection = Mock()
    owner._generation = 0
    owner._name_viewed = Mock()

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
