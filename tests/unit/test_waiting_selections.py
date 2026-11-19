"""Selections the tree shows before the list has taken or written them (#280, #291).

Without any failure, the tree can show a selection that the list's picks do not hold yet: one
made through accessibility (`XAccessibleSelection`), which no owned handler sees and which waits
for the list's queued intake, and a key's change to the picks, which the list writes in queued
work. Until the intake takes the one, or the write shows the other, the older picks must not
become what a command acts on, and a toggle must not be applied against them:

- a refresh that renames or reorders the rows wrote the older picks over a waiting selection,
  and the intake then refused that selection, made against rows that have changed since (#280);
- a Ctrl+click handled natively in that window toggles its row in the tree as the user sees it,
  and its listener, run later from VCL's queue (#269), toggled the row against the picks: it
  picked the row the user had just deselected (#291), or dropped one the user had just picked.

The real list runs over the simulated peer of `list_peer`, whose `queued_click` queues a click's
listeners behind the work already posted, as VCL does. `sample` is the tab observer's sample,
which finds a waiting selection and defers its intake until queued input has run (#85).
"""

from collections.abc import Callable
from typing import Any

import pytest

from tests.unit.list_peer import (
    DOWN,
    MOD1,
    SPACE,
    Book,
    changed,
    click,
    cursor,
    key,
    move_to_top,
    picks,
    queued_click,
    sheet_list,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]


def row(name: str) -> int:
    return NAMES.index(name)


def select_through_accessibility(owner: Any, names: list[str]) -> None:
    """Select exactly `names` through accessibility, or clear the selection if there are none."""
    if not names:
        owner.tree.assistive_clear()
        return
    owner.tree.assistive_only(names[0])
    for name in names[1:]:
        owner.tree.assistive_select(name)


def sample(owner: Any) -> None:
    """The tab observer's sample (`pending_native_picks`), whose deferred intake is posted."""
    owner._take_tree_selection(paint=False, defer=True)


def refresh_after_others_change(owner: Any) -> None:
    """Another view's change, as the modify listener reports it, and the refresh it schedules."""
    changed(owner)
    owner.retry()


def alfa_then(assistive: list[str]) -> Any:
    """Alfa picked by a click, then `assistive` selected through accessibility, or the selection
    cleared, waiting for the intake."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Alfa"))
    select_through_accessibility(owner, assistive)
    assert picks(owner) == ["Alfa"] and owner.tree.shown() == assistive
    return owner


def move_delta_to_the_top(book: Book) -> None:
    book.move("Delta", 0)


def rename_bravo(book: Book) -> None:
    book.rename("Bravo", "Zulu")


def colour_golf(book: Book) -> None:
    book.sheet("Golf").color = 0x336699


def edit_a_cell(book: Book) -> None:
    """A change that keeps every sheet's name, place and colour."""


ASSISTIVE = [pytest.param(["Echo"], id="Echo"), pytest.param([], id="cleared")]


@pytest.mark.parametrize("assistive", ASSISTIVE)
@pytest.mark.parametrize(
    "change",
    [
        pytest.param(move_delta_to_the_top, id="reorder"),
        pytest.param(rename_bravo, id="rename"),
    ],
)
def test_a_refresh_that_renames_or_reorders_the_rows_drops_the_picks_it_cannot_show_over(
    change: Callable[[Book], None], assistive: list[str]
) -> None:
    """#280, no failure: Alfa picked, then Echo selected alone through accessibility, or the
    selection cleared, and before the intake takes it, another view moves Delta to the top or
    renames Bravo. The refresh rebuilt the rows and wrote Alfa again, and the intake then
    refused the waiting selection, made against rows that have changed since: Move to Top moved
    Alfa, the pick the user had replaced. The rebuild cannot show that selection again, so it
    drops the picks it superseded, with the notice, and writes none."""
    owner = alfa_then(assistive)
    notices = len(owner.notices)
    change(owner.book)
    refresh_after_others_change(owner)
    assert "Alfa" not in picks(owner), "The older pick replaced the waiting selection"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Alfa"
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None
    owner.retry()
    assert move_to_top(owner) is None and owner.book.moved == []


@pytest.mark.parametrize("assistive", ASSISTIVE)
@pytest.mark.parametrize(
    "change",
    [
        pytest.param(colour_golf, id="colour"),
        pytest.param(edit_a_cell, id="cell edit"),
    ],
)
def test_a_refresh_that_keeps_the_rows_names_leaves_a_waiting_selection_to_the_intake(
    change: Callable[[Book], None], assistive: list[str]
) -> None:
    """The controls: a tab colour change rebuilds the rows under the same names in the same
    order and shows the waiting selection again, and a cell edit keeps the rows. The intake
    takes the selection, so Move to Top moves Echo, or refuses after the clear, as on `main`."""
    owner = alfa_then(assistive)
    notices = len(owner.notices)
    change(owner.book)
    refresh_after_others_change(owner)
    assert picks(owner) == assistive and owner.tree.shown() == assistive
    assert len(owner.notices) == notices
    assert move_to_top(owner) == (assistive or None)


def test_a_ctrl_click_before_a_keys_write_does_not_pick_the_row_the_key_deselected() -> None:
    """#291's key route (scenario `k` of #292's review), no failure: Bravo picked, the cursor on
    it; Ctrl+Space takes Bravo out of the picks and queues its write, and before that write runs,
    a Ctrl+click on Bravo, which the tree still shows selected, deselects it natively. Its
    listener runs after the write and toggled Bravo against the picks the key had changed: it
    picked Bravo, and Move to Top moved the sheet the user had deselected twice. A key that
    changes the picks now holds toggles until posted work runs once its write shows them."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Bravo"))
    owner.tree_key(SPACE, MOD1)
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert move_to_top(owner) is None


def test_a_ctrl_click_before_a_keys_write_does_not_drop_the_row_the_key_picked() -> None:
    """The same route with the key adding a row: Bravo picked, the cursor moved to Delta, and
    Ctrl+Space adds Delta; before the write, a Ctrl+click on Delta, which the tree still shows
    unselected, selects it natively. The listener toggled Delta out of the picks again, and Move
    to Top moved Bravo alone, a set the user did not pick. Held, the click picks nothing and
    drops the picks, with the notice, as a held toggle does (#288)."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Bravo"))
    key(owner, DOWN, MOD1)
    key(owner, DOWN, MOD1)
    assert cursor(owner) == "Delta" and owner.tree.shown() == ["Bravo"]
    owner.tree_key(SPACE, MOD1)
    notices = len(owner.notices)
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Delta"
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


def test_a_ctrl_click_on_another_row_before_a_keys_write_picks_nothing() -> None:
    """The cost of the rule, where `main` acts correctly: Bravo picked, Ctrl+Space takes it out,
    and a Ctrl+click on Delta before the key's write selects Delta natively. The listener cannot
    tell whether the tree showed the key's change when the user clicked, so it picks nothing,
    and the user clicks Delta again."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Bravo"))
    owner.tree_key(SPACE, MOD1)
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Delta"
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == ["Delta"] and move_to_top(owner) == ["Delta"]


def test_keys_typed_before_their_write_still_act_on_the_picks_they_changed() -> None:
    """Keys are held only for presses: Ctrl+Space, Ctrl+Down and Ctrl+Space again, all handled
    before the coalesced write, take Bravo out and put Charlie in, as on `main`."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Bravo"))
    owner.tree_key(SPACE, MOD1)
    owner.tree_key(DOWN, MOD1)
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert picks(owner) == ["Charlie"] and owner.tree.shown() == ["Charlie"]
    owner.tree_key(SPACE, MOD1)
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert picks(owner) == ["Charlie"] and move_to_top(owner) == ["Charlie"]


@pytest.mark.parametrize(
    "assistive, notices",
    [
        pytest.param(["Bravo"], 0, id="Bravo"),
        pytest.param(["Bravo", "Delta"], 1, id="Bravo and Delta"),
    ],
)
def test_a_ctrl_click_on_an_assistive_selection_whose_intake_was_deferred_picks_nothing(
    assistive: list[str], notices: int
) -> None:
    """#291, no failure: Bravo, or Bravo and Delta, selected through accessibility, and the tab
    sample defers the intake until queued input has run. A Ctrl+click on Bravo, shown selected,
    deselects it natively before that intake runs; the intake then took the tree as the click
    left it, and the click's listener toggled Bravo again: Move to Top moved Bravo, with Delta.
    The intake finds the tree changed since it was deferred and holds toggles, so the listener
    picks nothing, and drops what the intake took, with the notice."""
    owner = sheet_list(Book(list(NAMES)))
    select_through_accessibility(owner, assistive)
    sample(owner)
    before = len(owner.notices)
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert len(owner.notices) == before + notices
    assert move_to_top(owner) is None


def test_a_ctrl_click_on_an_assistive_selection_a_refresh_showed_again_picks_nothing() -> None:
    """The same after a refresh: Alfa picked, then Bravo and Delta selected through
    accessibility; a colour change's refresh rebuilds the rows, shows that selection again and
    defers the intake. A Ctrl+click on Bravo before the intake runs: the listener toggled Bravo
    against what the intake had just taken, and Move to Top moved Bravo and Delta."""
    owner = alfa_then(["Bravo", "Delta"])
    colour_golf(owner.book)
    owner.post(owner.refresh, "refreshing the sheet list")
    work, _ = owner.queue.pop(0)
    work()  # The refresh alone; its deferred intake stays queued.
    assert owner.tree.shown() == ["Bravo", "Delta"] and picks(owner) == ["Alfa"]
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_listener_after_a_deferred_assistive_selection_picks_nothing() -> None:
    """#291 with the order #85 recorded: Bravo and Delta selected through accessibility; a
    Ctrl+click deselects Bravo natively, and the tab sample runs before its listener, deferring
    the intake behind it. The listener toggled Bravo against the picks, which lack the waiting
    selection: Move to Top moved Bravo, and Delta was lost. The tree the intake saw is not the
    picks with Bravo toggled, so the tree showed another selection when the user clicked: the
    listener picks nothing, and its write clears the tree."""
    owner = sheet_list(Book(list(NAMES)))
    select_through_accessibility(owner, ["Bravo", "Delta"])
    queued_click(owner, row("Bravo"))
    sample(owner)
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert move_to_top(owner) is None


@pytest.mark.parametrize(
    "toggled, expected",
    [
        pytest.param("Bravo", [], id="deselects"),
        pytest.param("Delta", ["Bravo", "Delta"], id="selects"),
    ],
)
def test_a_ctrl_click_whose_own_toggle_the_deferred_intake_saw_still_toggles(
    toggled: str, expected: list[str]
) -> None:
    """The control: Bravo picked; a Ctrl+click toggles `toggled` natively, and the tab sample
    runs before its listener, as #85 recorded, and defers the intake. The tree differs from the
    picks only by that toggle, so the listener toggles as on `main`."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Bravo"))
    queued_click(owner, row(toggled))
    sample(owner)
    owner.run_queue()
    assert picks(owner) == expected and owner.tree.shown() == expected
    assert move_to_top(owner) == (expected or None)


def test_two_ctrl_clicks_around_a_deferred_intake_both_toggle() -> None:
    """The control with two clicks: Bravo picked; Ctrl+clicks on Delta and on Foxtrot, with the
    tab sample between their native toggles, all before either listener. The first listener's
    toggle accounts for the tree the intake saw, and the second click was made on that tree, so
    both toggle, as on `main`."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Bravo"))
    queued_click(owner, row("Delta"))
    sample(owner)
    queued_click(owner, row("Foxtrot"))
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Delta", "Foxtrot"]
    assert move_to_top(owner) == ["Bravo", "Delta", "Foxtrot"]


def test_ctrl_space_on_an_assistive_selection_whose_intake_was_deferred_picks_nothing() -> None:
    """#291's class through Space: nothing picked, the cursor on Bravo, and Bravo selected
    through accessibility; the tab sample defers the intake. Ctrl+Space, meant to deselect Bravo,
    which the tree shows selected, toggled it on against the picks, and Move to Top moved it."""
    owner = sheet_list(Book(list(NAMES)))
    key(owner, DOWN, MOD1)
    assert cursor(owner) == "Bravo" and picks(owner) == []
    select_through_accessibility(owner, ["Bravo"])
    sample(owner)
    key(owner, SPACE, MOD1)
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_an_assistive_selection_the_intake_takes_leaves_toggles_free() -> None:
    """The control: Bravo and Delta selected through accessibility, and the intake takes them
    unchanged; a Ctrl+click on Foxtrot then adds Foxtrot."""
    owner = sheet_list(Book(list(NAMES)))
    select_through_accessibility(owner, ["Bravo", "Delta"])
    sample(owner)
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Delta"]
    queued_click(owner, row("Foxtrot"))
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Delta", "Foxtrot"]
    assert move_to_top(owner) == ["Bravo", "Delta", "Foxtrot"]


def test_an_assistive_selection_withdrawn_before_its_intake_leaves_toggles_free() -> None:
    """Bravo selected through accessibility, the intake deferred, and the selection cleared again
    through accessibility before it runs. The intake finds the tree changed since and holds
    toggles, but the tree then shows exactly the picks, none, so posted work ends the hold: a
    later Ctrl+click on Delta picks Delta."""
    owner = sheet_list(Book(list(NAMES)))
    select_through_accessibility(owner, ["Bravo"])
    sample(owner)
    select_through_accessibility(owner, [])
    owner.run_queue()
    assert picks(owner) == [] and owner._toggles_held is None
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == ["Delta"] and move_to_top(owner) == ["Delta"]
