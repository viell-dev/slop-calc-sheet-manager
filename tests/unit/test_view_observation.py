"""Native-tab observation must not create picks from stale proof or overwrite newer input."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.unit.source_methods import method

SOURCE = "src/sheet_manager/uno_list.py"


def observer() -> tuple[Any, Any]:
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

    owner = SimpleNamespace(
        _disposed=False,
        _view_stopped=False,
        _busy=False,
        _restoring_cursor=False,
        _press=None,
        _drag=None,
        _menu=SimpleNamespace(is_open=False),
        _menu_context=False,
        _input=0,
        _view_input=0,
        _view_ack_pending=False,
        _view_state=("Alfa", frozenset({"Alfa"})),
        _view_names=frozenset(live.names),
        _view_generation=0,
        _proven=0,
        _monitor=SimpleNamespace(generation=0),
        _stale_since=None,
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
        _tabs_method=SimpleNamespace(invoke=Mock(side_effect=invoke)),
        _take_tree_selection=Mock(return_value=False),
        _select=Mock(),
        document_modified=Mock(),
    )
    remember = method(SOURCE, "SheetList", "_remember_view", {})
    observe = method(SOURCE, "SheetList", "_observe_view", {})

    def remember_view(active: str, tabs: tuple[str, ...]) -> None:
        remember(owner, active, tabs)

    owner._remember_view = remember_view
    owner._observe_view = lambda acknowledge=False: observe(owner, acknowledge)
    return owner, live


def test_tab_only_change_follows_once_without_rebuilding_or_consuming_monitor_evidence() -> None:
    owner, live = observer()
    owner._observe_view()
    owner._select.assert_not_called()
    live.indices = (0, 2)
    owner._observe_view()
    owner._select.assert_called_once_with(["Alfa", "Charlie"], "Alfa")
    owner._observe_view()
    assert owner._select.call_count == 1
    owner._status.show_tabs.assert_called_with(("Alfa", "Charlie"))


@pytest.mark.parametrize("newer", ["input", "acknowledgement", "pending_tree_selection"])
def test_newer_list_input_consumes_a_native_change_without_following_it_later(newer: str) -> None:
    owner, live = observer()
    live.indices = (0, 2)
    if newer == "input":
        owner._input += 1
    elif newer == "acknowledgement":
        owner._view_ack_pending = True
    else:
        owner._take_tree_selection.return_value = True
    owner._observe_view()
    owner._select.assert_not_called()
    owner._view_ack_pending = False
    owner._take_tree_selection.return_value = False
    owner._observe_view()
    owner._select.assert_not_called()
    live.indices = (0, 1)  # A later, distinct native change is followed normally.
    owner._observe_view()
    owner._select.assert_called_once_with(["Alfa", "Bravo"], "Alfa")


def test_acknowledgement_never_follows_its_own_native_change() -> None:
    owner, live = observer()
    live.indices = (0, 2)
    owner._observe_view(True)
    owner._observe_view()
    owner._select.assert_not_called()


def test_reordering_native_members_does_not_turn_independent_picks_into_calc_picks() -> None:
    owner, live = observer()
    owner._view_state = "Alfa", frozenset({"Alfa", "Charlie"})
    live.names = live.shown = ("Charlie", "Bravo", "Alfa")
    live.indices = (0, 2)
    owner._observe_view()
    owner._select.assert_not_called()
    owner._status.show_tabs.assert_called_once_with(("Charlie", "Alfa"))


@pytest.mark.parametrize("change", ["rename", "new_generation"])
def test_new_namespace_or_proof_establishes_a_baseline_without_picking_replacements(
    change: str,
) -> None:
    owner, live = observer()
    live.indices = (0, 1)
    if change == "rename":
        live.names = live.shown = ("Alfa", "Renamed", "Charlie")
    else:
        owner._monitor.generation = owner._proven = 1
    owner._observe_view()
    owner._select.assert_not_called()
    assert owner._view_state == ("Alfa", frozenset({"Alfa", live.names[1]}))


@pytest.mark.parametrize("kept", [False, True])
def test_refresh_seeds_the_new_proof_before_a_subsequent_tab_change(kept: bool) -> None:
    owner, live = observer()
    observed = SimpleNamespace(sheets=(), handles=())
    rows = [object()]
    owner._observed, owner.rows, owner._nodes = observed, rows, [object()]
    owner._monitor.generation = 1
    owner._monitor.check = lambda: 1
    owner._identities_kept = Mock(return_value=kept)
    owner._drop_all_picks = Mock(return_value=True)

    def selected_names() -> list[str]:
        return []

    owner._selection = SimpleNamespace(revalidate=lambda: False, names=selected_names)
    owner._shown = ()
    owner._apply_selection = Mock()

    def snapshot(document: Any) -> Any:
        return observed

    def read_rows(controller: Any, picture: Any) -> list[object]:
        return rows

    refresh = method(
        SOURCE, "SheetList", "_refresh", {"snapshot": snapshot, "read_rows": read_rows}
    )
    refresh(owner)
    assert owner._proven == owner._view_generation == 1
    assert owner._view_state == ("Alfa", frozenset({"Alfa"}))
    owner._select.assert_not_called()  # Seeding neither repopulates nor overwrites the picks.
    assert owner._drop_all_picks.call_count == int(not kept)
    live.indices = (0, 2)
    owner._observe_view()  # No sleep or intervening sample after the refreshed rows are ready.
    owner._select.assert_called_once_with(["Alfa", "Charlie"], "Alfa")


@pytest.mark.parametrize(
    "guard", ["busy", "restore", "press", "drag", "menu", "controllers", "actions"]
)
def test_unsafe_or_transient_view_never_reads_selected_tabs_or_tree_picks(guard: str) -> None:
    owner, live = observer()
    if guard == "controllers":
        live.controllers_locked = True
    elif guard == "actions":
        live.actions_locked = True
    elif guard == "menu":
        owner._menu.is_open = True
    else:
        attribute = {
            "busy": "_busy",
            "restore": "_restoring_cursor",
            "press": "_press",
            "drag": "_drag",
        }
        setattr(owner, attribute[guard], True)
    owner._observe_view()
    owner._tabs_method.invoke.assert_not_called()
    owner._take_tree_selection.assert_not_called()


@pytest.mark.parametrize("stale", ["generation", "row_order"])
def test_stale_rows_request_refresh_without_using_their_indices(stale: str) -> None:
    owner, live = observer()
    if stale == "generation":
        owner._monitor.generation = 1
    else:
        live.names = ("Charlie", "Bravo", "Alfa")
    owner._observe_view()
    owner.document_modified.assert_called_once_with()
    owner._tabs_method.invoke.assert_not_called()
    owner._select.assert_not_called()
    owner._stale_since = 1.0
    owner._observe_view()
    assert owner.document_modified.call_count == 1


def test_generation_change_during_the_native_getter_cannot_create_picks() -> None:
    owner, live = observer()

    def change(*args: object) -> tuple[tuple[int, ...]]:
        owner._monitor.generation += 1
        return (live.indices,)

    owner._tabs_method.invoke.side_effect = change
    owner._observe_view()
    owner._take_tree_selection.assert_not_called()
    owner._select.assert_not_called()


def test_listener_input_only_posts_one_acknowledgement_and_does_not_read_native_state() -> None:
    owner, live = observer()
    owner.post = Mock()
    owner._view_visible = Mock(return_value=True)
    note = method(SOURCE, "SheetList", "_note_view_input", {})
    acknowledge = method(
        SOURCE, "SheetList", "_acknowledge_view", {"DisposedException": ValueError}
    )
    owner._acknowledge_view = lambda: acknowledge(owner)
    note(owner)
    note(owner)
    owner._tabs_method.invoke.assert_not_called()
    assert owner.post.call_count == 1
    live.indices = (0, 2)
    owner.post.call_args.args[0]()
    owner._tabs_method.invoke.assert_called_once()
    owner._select.assert_not_called()
    assert not owner._view_ack_pending


@pytest.mark.parametrize("key", ["Return", "Menu", "type-ahead"])
def test_queued_key_intent_prevents_an_older_observation_from_replacing_its_picks(key: str) -> None:
    from sheet_manager.keys import (
        CONTEXTMENU,
        RETURN,
        SHIFT,
        SPACE,
        TAB,
        A,
        KeyRoute,
        route_key,
    )

    owner, live = observer()
    queued: list[Any] = []
    actions: list[str] = []

    def post(function: Any, where: str) -> None:
        queued.append(function)

    owner.post = post
    note = method(SOURCE, "SheetList", "_note_view_input", {})
    note_input = method(SOURCE, "SheetList", "note_input", {})
    queue = method(SOURCE, "SheetList", "queue_input", {})
    owner._note_view_input = lambda: note(owner)
    owner.note_input = lambda: note_input(owner)
    owner._acknowledge_view = Mock()

    def queue_input(function: Any, where: str) -> None:
        queue(owner, function, where)

    def type_ahead(char: str) -> None:
        actions.append("type-ahead")

    owner.queue_input = queue_input
    owner.activate_selection = lambda: actions.append("Return")
    owner.open_menu_for_keyboard = lambda: actions.append("Menu")
    owner.type_ahead = type_ahead
    owner.owns_keys = lambda: True
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
        },
    )
    code, char = {
        "Return": (RETURN, "\r"),
        "Menu": (CONTEXTMENU, ""),
        "type-ahead": (A, "a"),
    }[key]
    event = SimpleNamespace(KeyCode=code, KeyChar=char, Modifiers=SHIFT if "Shift" in key else 0)
    assert pressed(handler, event)
    assert owner._input == 1 and owner._view_ack_pending
    live.indices = (0, 2)
    owner._observe_view()  # Already queued ahead of the key's action.
    owner._select.assert_not_called()
    assert not actions
    queued[-1]()
    assert actions == [key]


def test_visibility_guards_native_deck_access_after_sidebar_removal() -> None:
    owner, _ = observer()
    deck = SimpleNamespace(isActive=Mock(side_effect=AssertionError("unsafe native dereference")))
    sidebar = SimpleNamespace(isVisible=lambda: False)
    owner.controller.getSidebar = lambda: sidebar
    owner.frame = SimpleNamespace(
        getController=lambda: owner.controller,
        getContainerWindow=lambda: SimpleNamespace(IsMinimized=False),
    )
    owner._view_controls = deck, object()
    visible = method(SOURCE, "SheetList", "_view_visible", {})
    assert not visible(owner)
    deck.isActive.assert_not_called()
    assert owner._view_controls is None


@pytest.mark.parametrize("state", ["collapsed", "inactive", "not_ready"])
def test_visibility_does_not_repeatedly_create_or_lay_out_hidden_native_panels(state: str) -> None:
    owner, _ = observer()
    panel = SimpleNamespace(isExpanded=lambda: state != "collapsed")
    panels = SimpleNamespace(getByName=Mock(return_value=panel))
    deck = SimpleNamespace(isActive=lambda: state != "inactive", getPanels=lambda: panels)
    decks = SimpleNamespace(getByName=Mock(return_value=deck))
    if state == "not_ready":
        decks.getByName.side_effect = LookupError("native sidebar context not ready")
    sidebar = SimpleNamespace(isVisible=lambda: True, getDecks=lambda: decks)
    owner.controller.getSidebar = lambda: sidebar
    owner.frame = SimpleNamespace(
        getController=lambda: owner.controller,
        getContainerWindow=lambda: SimpleNamespace(IsMinimized=False),
    )
    owner._view_controls = None
    visible = method(SOURCE, "SheetList", "_view_visible", {"NoSuchElementException": LookupError})
    assert not visible(owner)
    assert not visible(owner)
    assert panels.getByName.call_count == int(state == "collapsed")
    assert not owner._view_stopped


def test_replaced_controller_stops_observation_before_reading_its_old_sidebar() -> None:
    owner, _ = observer()
    owner.controller.getSidebar = Mock()
    owner.frame = SimpleNamespace(getController=lambda: object())
    visible = method(SOURCE, "SheetList", "_view_visible", {})
    assert not visible(owner)
    assert owner._view_stopped
    owner.controller.getSidebar.assert_not_called()


def test_an_old_queued_tick_cannot_clear_a_new_timer_or_create_a_second_chain() -> None:
    owner, _ = observer()
    current = object()
    owner._view_token, owner._view_timer = current, object()
    owner._main = SimpleNamespace(later=Mock(return_value=object()))
    owner._view_visible = Mock(return_value=True)
    owner._observe_view = Mock()
    schedule = method(SOURCE, "SheetList", "_schedule_view", {})

    def schedule_view(seconds: float) -> None:
        schedule(owner, seconds)

    owner._schedule_view = schedule_view
    tick = method(
        SOURCE,
        "SheetList",
        "_view_tick",
        {"VIEW_INTERVAL": 0.25, "HIDDEN_VIEW_INTERVAL": 1.0, "DisposedException": ValueError},
    )
    tick(owner, object())
    owner._view_visible.assert_not_called()
    tick(owner, current)
    owner._observe_view.assert_called_once_with(False)
    assert owner._main.later.call_count == 1
    replacement = owner._view_token, owner._view_timer
    tick(owner, current)
    assert (owner._view_token, owner._view_timer) == replacement
    assert owner._main.later.call_count == 1
