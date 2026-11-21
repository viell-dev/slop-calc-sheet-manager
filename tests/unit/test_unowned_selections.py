"""Selection changes of the tree that the list did not make, counted before any intake (#294).

A selection made through accessibility (`XAccessibleSelection`) reaches no owned handler, so the
list learns of it only when its queued intake next reads the tree. Before that, input acted
against the older picks: a Ctrl+click toggled its row, and a Ctrl+Shift+click added its range,
against picks that lacked the selection, and a Ctrl key's or a right press's write showed the
older picks over it, for a command to act on. The toolkit's selection listener counts every
row's change that the list's own writes did not make (`tree_selection_changed`), and the count
taken when the tree last showed exactly the picks tells what the list has not taken: a Ctrl
press acts only when its own change is all of it, a Ctrl+Shift press only when its range's rows
are, and Space, a Ctrl key and a right press only when there is none.

The real list runs over the simulated peer of `list_peer`, whose tree notifies that listener
once per changed row inside the changing call, as measured on #294, and whose `queued_click`
queues a click's listeners behind the work already posted, as VCL does (#269). `sample` is the
tab observer's sample, which finds a waiting selection and defers its intake (#85).
"""

import threading
from typing import Any

import pytest

from tests.unit.list_peer import (
    DOWN,
    MOD1,
    RIGHT,
    SHIFT,
    SPACE,
    Book,
    changed,
    click,
    cursor,
    key,
    move_to_top,
    picks,
    press,
    queued_click,
    sheet_list,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]
INTAKE = "taking native list selection after queued input"


def row(name: str) -> int:
    return NAMES.index(name)


def fresh() -> Any:
    return sheet_list(Book(list(NAMES)))


def picked(*names: str) -> Any:
    """A click on the first, Ctrl+clicks on the others, each run to the end."""
    owner = fresh()
    click(owner, row(names[0]))
    for name in names[1:]:
        queued_click(owner, row(name))
        owner.run_queue()
    assert picks(owner) == list(names) and owner.tree.shown() == list(names)
    return owner


def sample(owner: Any) -> None:
    """The tab observer's sample (`pending_native_picks`), whose deferred intake is posted."""
    owner._take_tree_selection(paint=False, defer=True)


def unaccounted(owner: Any) -> int:
    return owner._unowned - owner._accounted


def ahead_of_the_intake(owner: Any) -> None:
    """Run the queued mouse listeners ahead of a queued intake, as VCL can when it adds them to a
    callback event of the window still queued (`VCLXWindowImpl::callBackAsync`)."""
    listeners = [item for item in owner.queue if item[1].startswith("a mouse")]
    others = [item for item in owner.queue if not item[1].startswith("a mouse")]
    owner.queue[:] = listeners + others


def right_press(owner: Any, name: str) -> list[str]:
    """A right press on `name` and what its menu targets when the release opens it, as
    `_open_menu` chooses them; the menu then closes without a command, as `_finish_menu` ends."""
    press(owner, row(name), RIGHT)
    owner.run_queue()
    target = owner._context_target
    targets = picks(owner) if target.name in picks(owner) else [target.name]
    owner._context_target = None
    owner._show_selection()
    owner.run_queue()
    return targets


# Before any intake has read the tree (#294's first table).


def test_a_ctrl_click_on_an_assistive_selection_before_any_intake_picks_nothing() -> None:
    """Bravo selected through accessibility, and a Ctrl+click on Bravo, shown selected, meant to
    deselect it, before any intake has read the tree. The listener toggled Bravo into the picks,
    which lacked it, and Move to Top moved the sheet the user had just deselected. The tree
    changed twice since it showed the picks, not only by the click, so the listener picks
    nothing."""
    owner = fresh()
    owner.tree.assistive_only("Bravo")
    assert unaccounted(owner) == 1
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert move_to_top(owner) is None


def test_the_same_with_the_sample_between_the_toggle_and_its_listener() -> None:
    """The click undid the accessibility selection before the tab sample looked, so the sample
    finds the tree showing exactly the picks, none, and defers nothing: the listener then
    toggled Bravo on. Both changes stay unaccounted, so the listener picks nothing."""
    owner = fresh()
    owner.tree.assistive_only("Bravo")
    queued_click(owner, row("Bravo"))
    sample(owner)
    assert owner._deferred is None and unaccounted(owner) == 2
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and move_to_top(owner) is None


def test_a_sample_that_finds_the_picks_shown_leaves_a_queued_click_its_own_change() -> None:
    """Nothing picked; a Ctrl+click on Bravo is handled natively, the selection is cleared
    through accessibility, the tab sample finds the tree showing exactly the picks, none, and
    Charlie is then added through accessibility, all before the click's listener. Had the sample
    accounted for the click's change, the listener would have taken Charlie's for its own and
    toggled Bravo on, and Move to Top moved the sheet the user had cleared, as `main` does. The
    sample accounts for nothing, so the listener picks nothing."""
    owner = fresh()
    queued_click(owner, row("Bravo"))
    owner.tree.assistive_clear()
    sample(owner)
    owner.tree.assistive_select("Charlie")
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user cleared, was picked"
    assert picks(owner) == [] and move_to_top(owner) is None


def test_a_ctrl_shift_click_after_an_assistive_clear_does_not_add_to_the_cleared_picks() -> None:
    """Alfa and Bravo picked, the selection cleared through accessibility, and a Ctrl+Shift+click
    on Delta adds Bravo to Delta in the tree, from its cursor. The listener added the list's
    range to the picks: Move to Top moved Alfa, which the user had cleared, with Bravo to Delta.
    The tree changed by more than the range's rows, so the press is refused as a toggle is,
    with the notice."""
    owner = picked("Alfa", "Bravo")
    owner.tree.assistive_clear()
    notices = len(owner.notices)
    queued_click(owner, row("Delta"), MOD1 | SHIFT)
    assert owner.tree.shown() == ["Bravo", "Charlie", "Delta"]
    owner.run_queue()
    assert "Alfa" not in picks(owner), "Alfa, which the user cleared, was kept"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Delta"
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


@pytest.mark.parametrize(
    "modifiers",
    [pytest.param(MOD1, id="Ctrl+Down"), pytest.param(MOD1 | SHIFT, id="Ctrl+Shift+Down")],
)
def test_a_ctrl_key_before_any_intake_does_not_show_the_older_picks_again(modifiers: int) -> None:
    """Alfa picked, then Echo selected alone through accessibility, and Ctrl+Down before any
    intake: the key keeps the picks, so its write showed Alfa again over Echo, and Move to Top
    moved Alfa; Ctrl+Shift+Down added a range to it. The key picks nothing and drops Alfa, with
    the notice, and the cursor moves, as after an intake has seen the selection (#291)."""
    owner = picked("Alfa")
    owner.tree.assistive_only("Echo")
    notices = len(owner.notices)
    key(owner, DOWN, modifiers)
    assert "Alfa" not in picks(owner), "Alfa, which the user replaced, was kept"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


@pytest.mark.parametrize(
    "modifiers", [pytest.param(0, id="Space"), pytest.param(MOD1, id="Ctrl+Space")]
)
def test_space_on_an_assistive_selection_before_any_intake_picks_nothing(modifiers: int) -> None:
    """Nothing picked, the cursor on Bravo, and Bravo selected through accessibility: Space,
    meant to deselect Bravo, toggled it on against the picks, and Move to Top moved it."""
    owner = fresh()
    key(owner, DOWN, MOD1)
    assert cursor(owner) == "Bravo" and picks(owner) == []
    owner.tree.assistive_select("Bravo")
    key(owner, SPACE, modifiers)
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_an_assistive_clear_after_ctrl_clicks_in_flight_leaves_nothing_picked() -> None:
    """Nothing picked; Ctrl+clicks on Bravo and on Foxtrot are handled natively, and the
    selection is cleared through accessibility before their listeners run. Both listeners
    toggled their rows on, and Move to Top moved the two sheets the user had cleared."""
    owner = fresh()
    queued_click(owner, row("Bravo"))
    queued_click(owner, row("Foxtrot"))
    owner.tree.assistive_clear()
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_an_assistive_selection_after_a_ctrl_click_in_flight_is_not_added_to() -> None:
    """Alfa picked; a Ctrl+click on Charlie is handled natively, and Echo is selected alone
    through accessibility before its listener runs. The listener added Charlie to Alfa, though
    the tree showed Echo alone, and Move to Top moved Alfa and Charlie."""
    owner = picked("Alfa")
    queued_click(owner, row("Charlie"))
    owner.tree.assistive_only("Echo")
    notices = len(owner.notices)
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Charlie"
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


# After an intake has seen the selection, before it takes it (#294's second table).


def anchored_at_echo() -> Any:
    """Alfa picked by a click, and Ctrl+Down four times to Echo: the list's range anchor stays on
    Alfa, while its write leaves the tree's cursor, from which the tree makes its anchor, on
    Echo."""
    owner = picked("Alfa")
    for _ in range(4):
        key(owner, DOWN, MOD1)
    assert cursor(owner) == "Echo" and owner.tree.cursor is owner.tree.node("Echo")
    assert owner._selection.anchor.name == "Alfa"
    return owner


@pytest.mark.parametrize("sampled", [pytest.param(False, id="before"), pytest.param(True, id="seen")])
def test_a_ctrl_shift_click_over_an_assistive_selection_does_not_add_older_picks(
    sampled: bool,
) -> None:
    """Echo then selected alone through accessibility; a Ctrl+Shift+click on Golf adds Foxtrot
    and Golf in the tree, from its anchor on Echo, so it shows Echo to Golf, and the tab sample
    may see that before the listener runs. The listener added the list's range from Alfa to the
    picks: Move to Top moved Alfa to Golf. The count shows changes outside the range's rows, so
    the press is refused, with the notice."""
    owner = anchored_at_echo()
    owner.tree.assistive_only("Echo")
    queued_click(owner, row("Golf"), MOD1 | SHIFT)
    assert owner.tree.shown() == ["Echo", "Foxtrot", "Golf"]
    if sampled:
        sample(owner)
    notices = len(owner.notices)
    owner.run_queue()
    assert "Alfa" not in picks(owner), "Alfa, which the user replaced, was kept"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


@pytest.mark.parametrize("sampled", [pytest.param(False, id="before"), pytest.param(True, id="seen")])
def test_a_right_press_does_not_write_the_older_picks_over_an_assistive_selection(
    sampled: bool,
) -> None:
    """Alfa picked, then Echo selected alone through accessibility, and a right press on Golf,
    before or after the tab sample has seen the selection. The press's write showed Alfa again
    before the menu opened, and Move to Top moved Alfa. The press drops Alfa, with the notice,
    so the write clears the tree, and the menu still targets Golf."""
    owner = picked("Alfa")
    owner.tree.assistive_only("Echo")
    if sampled:
        sample(owner)
    notices = len(owner.notices)
    assert right_press(owner, "Golf") == ["Golf"]
    assert "Alfa" not in picks(owner), "Alfa, which the user replaced, was written again"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


def test_a_listener_run_ahead_of_the_deferred_intake_does_not_toggle_against_older_picks() -> None:
    """Alfa picked; Bravo added through accessibility, and the tab sample defers the intake; a
    Ctrl+click deselects Bravo, and VCL runs its listener ahead of that intake, as it can by
    adding it to a callback event of the window still queued. The record judged the listener
    as pressed before the intake looked, and it toggled Bravo into the picks: Move to Top moved
    Alfa and Bravo. The count holds both changes, so the listener picks nothing."""
    owner = picked("Alfa")
    owner.tree.assistive_select("Bravo")
    sample(owner)
    queued_click(owner, row("Bravo"))
    ahead_of_the_intake(owner)
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


# A refresh that shows a waiting selection again (`_show_native`).


def shown_again(added: str) -> Any:
    """Alfa picked, `added` added through accessibility, and a colour change's refresh rebuilds
    the rows, shows that selection again and defers the intake, which stays queued."""
    owner = picked("Alfa")
    owner.tree.assistive_select(added)
    owner.book.sheet("Hotel").color = 0x336699
    owner.post(owner.refresh, "refreshing the sheet list")
    work, _ = owner.queue.pop(0)
    work()
    assert owner.tree.shown() == ["Alfa", added] and picks(owner) == ["Alfa"]
    assert unaccounted(owner) == 1, "The rebuild accounted for the selection it showed again"
    return owner


def test_a_right_press_after_a_refresh_showed_a_waiting_selection_again_drops_the_picks() -> None:
    """The right press reads no record: after the refresh, its write showed Alfa alone again,
    and Move to Top moved it."""
    owner = shown_again("Bravo")
    right_press(owner, "Golf")
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_ctrl_shift_click_after_a_refresh_showed_a_waiting_selection_again_is_refused() -> None:
    """Nor does a Ctrl+Shift press: Foxtrot added through accessibility, and a Ctrl+Shift+click
    on Delta adds Bravo to Delta in the tree and in the picks alike, while the tree also showed
    Foxtrot, and VCL runs the listener ahead of the deferred intake. The range's rows are not
    all that the list has not taken, so the press is refused; `main` picked Alfa to Delta, its
    write cleared Foxtrot, and the intake, finding the press since it looked, took nothing."""
    owner = shown_again("Foxtrot")
    queued_click(owner, row("Delta"), MOD1 | SHIFT)
    ahead_of_the_intake(owner)
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


# Controls: the same results as on `main`.


def test_ctrl_clicks_toggle_as_before() -> None:
    owner = picked("Bravo", "Delta")
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert picks(owner) == ["Delta"] and owner.tree.shown() == ["Delta"]
    assert move_to_top(owner) == ["Delta"]


def test_a_ctrl_shift_click_adds_its_range_as_before() -> None:
    """Bravo picked; a Ctrl+Shift+click on Echo adds Charlie to Echo, three rows in both the tree
    and the picks."""
    owner = picked("Bravo")
    queued_click(owner, row("Echo"), MOD1 | SHIFT)
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Charlie", "Delta", "Echo"] == owner.tree.shown()
    assert move_to_top(owner) == ["Bravo", "Charlie", "Delta", "Echo"]


def test_a_ctrl_shift_range_over_an_assistively_selected_row_is_added() -> None:
    """Alfa picked, Charlie added through accessibility, and a Ctrl+Shift+click on Delta: the
    tree adds Bravo and Delta, and the list's range adds Bravo, Charlie and Delta, which together
    are every change the list has not taken, so the tree shows exactly what the list picks."""
    owner = picked("Alfa")
    owner.tree.assistive_select("Charlie")
    queued_click(owner, row("Delta"), MOD1 | SHIFT)
    owner.run_queue()
    assert picks(owner) == ["Alfa", "Bravo", "Charlie", "Delta"] == owner.tree.shown()
    assert move_to_top(owner) == ["Alfa", "Bravo", "Charlie", "Delta"]


def test_a_ctrl_double_click_toggles_twice_as_before() -> None:
    """Alfa picked; a Ctrl+double-click on Charlie. The tree toggles Charlie at the first press
    and takes its double-click path at the second, which changes nothing; the listeners toggle
    Charlie twice, so the picks keep Alfa alone, as on `main`, and the write shows them."""
    owner = picked("Alfa")
    queued_click(owner, row("Charlie"))
    queued_click(owner, row("Charlie"), clicks=2)
    assert owner.tree.shown() == ["Alfa", "Charlie"]
    owner.run_queue()
    assert picks(owner) == ["Alfa"] and owner.tree.shown() == ["Alfa"]
    assert move_to_top(owner) == ["Alfa"]


def test_an_assistive_selection_taken_before_a_ctrl_click_is_toggled_against() -> None:
    """Bravo selected through accessibility, and the intake takes it, which accounts for it; a
    Ctrl+click on Delta then adds Delta."""
    owner = fresh()
    owner.tree.assistive_only("Bravo")
    sample(owner)
    owner.run_queue()
    assert picks(owner) == ["Bravo"] and unaccounted(owner) == 0
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Delta"] and move_to_top(owner) == ["Bravo", "Delta"]


def test_a_plain_click_after_an_assistive_selection_picks_its_row() -> None:
    """A plain press replaces the selection natively and in the picks, as on `main`."""
    owner = picked("Alfa")
    owner.tree.assistive_only("Echo")
    queued_click(owner, row("Golf"), 0)
    owner.run_queue()
    assert picks(owner) == ["Golf"] == owner.tree.shown() and unaccounted(owner) == 0
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Golf"] and move_to_top(owner) == ["Bravo", "Golf"]


def test_keys_that_set_the_selection_let_keys_typed_ahead_act() -> None:
    """Alfa picked, Echo selected alone through accessibility, then Down and Ctrl+Down before the
    write: Down sets the picks to Bravo, which its write shows over Echo, so Ctrl+Down moves the
    cursor and keeps Bravo, as on `main`."""
    owner = picked("Alfa")
    owner.tree.assistive_only("Echo")
    owner.tree_key(DOWN, 0)
    owner.tree_key(DOWN, MOD1)
    owner.run_queue()
    assert picks(owner) == ["Bravo"] == owner.tree.shown() and cursor(owner) == "Charlie"
    assert move_to_top(owner) == ["Bravo"]


def test_the_lists_own_writes_and_rebuilds_are_not_counted() -> None:
    """Writes of the picks, a key's, a refresh's rebuild and a write that clears the tree, change
    the tree's selection without leaving anything unaccounted, so Ctrl+clicks still toggle."""
    owner = picked("Alfa", "Charlie")
    notified = owner.tree.notified
    key(owner, DOWN, SHIFT)
    owner.book.sheet("Golf").color = 0x336699
    changed(owner)
    owner.retry()
    assert owner.tree.notified > notified and unaccounted(owner) == 0
    queued_click(owner, row("Echo"))
    owner.run_queue()
    assert picks(owner) == ["Charlie", "Delta", "Echo"] and move_to_top(owner) == picks(owner)


def test_a_change_another_thread_makes_during_a_write_is_counted() -> None:
    """An assistive client's selection, made on its own thread while the list's write on the main
    thread is between two of its calls, is someone else's change: it stays unaccounted, so a
    Ctrl+click after it picks nothing."""
    owner = picked("Alfa")
    add = owner.tree.addSelection

    def add_while_a_client_selects(node: Any) -> None:
        add(node)
        client = threading.Thread(target=owner.tree.assistive_select, args=("Golf",))
        client.start()
        client.join()

    owner.tree.addSelection = add_while_a_client_selects
    owner._selection.choose("Charlie", owner._handles, owner.names(), toggle=True)
    owner._show_selection()
    owner.tree.addSelection = add
    assert owner.tree.shown() == ["Alfa", "Charlie", "Golf"] and unaccounted(owner) == 1
    queued_click(owner, row("Echo"))
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None


# Costs: refusals where `main` acts correctly, each within one pass of the main thread's queue.


def test_a_write_between_a_ctrl_click_and_its_listener_refuses_the_toggle() -> None:
    """Alfa and Bravo picked; a Ctrl+click deselects Bravo, and the list's coalesced write runs
    before its listener, which shows Bravo again: the listener finds nothing of its own left,
    and cannot tell this from an intake that took its toggle already, so it picks nothing.
    `main` toggles Bravo off, as the user meant."""
    owner = picked("Alfa", "Bravo")
    queued_click(owner, row("Bravo"))
    owner.queue.insert(0, (owner._show_selection, "showing the selection"))
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_ctrl_click_before_a_plain_clicks_write_refuses_the_toggle() -> None:
    """Alfa picked; a plain click on Charlie and a Ctrl+click on Echo are both handled natively
    before the first listener runs. The plain press's own changes are not the Ctrl press's, so
    its listener picks nothing; `main` picks Charlie and Echo."""
    owner = picked("Alfa")
    queued_click(owner, row("Charlie"), 0)
    queued_click(owner, row("Echo"))
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None


def test_a_ctrl_shift_click_from_another_anchor_than_the_tree_is_refused() -> None:
    """Without assistive technology: Alfa picked, Ctrl+Down four times to Echo, and a
    Ctrl+Shift+click on Golf. The tree adds Foxtrot and Golf from its anchor on Echo, while the
    list's range from Alfa adds Bravo to Golf, so the counts differ and the press is refused;
    `main` picks Alfa to Golf."""
    owner = anchored_at_echo()
    queued_click(owner, row("Golf"), MOD1 | SHIFT)
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None
