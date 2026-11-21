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
    SHIFT,
    SPACE,
    UP,
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


def run_the_deferred_intake(owner: Any) -> None:
    """Run the queued intake now, as posting or reading UNO inside a handler can let it run."""
    for index, (work, where) in enumerate(owner.queue):
        if where == "taking native list selection after queued input":
            del owner.queue[index]
            work()
            return


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


@pytest.mark.parametrize("modifiers", [pytest.param(0, id="click"), pytest.param(MOD1, id="Ctrl")])
def test_a_reorder_over_a_waiting_selection_drops_the_picks_and_holds_a_press_on_a_moved_row(
    modifiers: int,
) -> None:
    """#280 with #293's press hold: Alfa picked, then Echo selected alone through accessibility;
    another view moves Delta to the top, its refresh is queued, and a click or Ctrl+click on
    Bravo is handled natively before that refresh runs. The refresh drops Alfa, which the waiting
    selection superseded, with the notice, and its rebuild holds presses. Bravo's row now shows
    Alfa, so the click's listener picks nothing, and Move to Top refuses rather than act on
    Alfa, the sheet now under the pointer."""
    owner = alfa_then(["Echo"])
    notices = len(owner.notices)
    move_delta_to_the_top(owner.book)
    owner.post(owner.refresh, "refreshing the sheet list")
    queued_click(owner, row("Bravo"), modifiers)
    owner.run_queue()
    assert owner.names()[row("Bravo")] == "Alfa"
    assert "Alfa" not in picks(owner), "Alfa, now under the pointer, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


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


def test_cursor_keys_after_a_failed_write_keep_space_held() -> None:
    """A key while the record is unknown keeps the hold its failure made, which holds Space too
    (#288). Bravo picked, the cursor moved to the unpicked Delta, and that write fails at its
    `clearSelection`, so the tree shows Delta alone, which the list does not hold. Ctrl+Up and
    Ctrl+Down, typed before their write, move the cursor away and back; Ctrl+Space with the cursor
    on Delta, meant to deselect it, would pick Delta if a key's hold replaced the failure's."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Bravo"))
    key(owner, DOWN, MOD1)
    owner.faults.fail("clearSelection")
    key(owner, DOWN, MOD1)
    assert owner._shown is None and owner.tree.shown() == ["Delta"] and cursor(owner) == "Delta"
    owner.tree_key(UP, MOD1)
    owner.tree_key(DOWN, MOD1)
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert "Delta" not in picks(owner), "Delta, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


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


def test_a_deferred_intake_that_runs_inside_the_press_listener_does_not_free_the_toggle() -> None:
    """Posting or reading UNO can let queued work run inside a mouse listener (`_Mouse._handle`).
    Alfa picked, Echo then selected alone through accessibility, and a Ctrl+click deselects Echo
    natively before the tab sample defers the intake. If that intake runs while the press's
    listener posts its window claim, it clears its record and, finding the press's input, takes
    nothing; a listener that read the record after that call toggled Echo against Alfa, and Move
    to Top moved Alfa and Echo. The listener reads the record once, before any UNO call."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Alfa"))
    select_through_accessibility(owner, ["Echo"])
    queued_click(owner, row("Echo"))
    sample(owner)
    owner.claim_window = lambda: run_the_deferred_intake(owner)
    owner.run_queue()
    assert "Echo" not in picks(owner), "Echo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Echo"
    assert move_to_top(owner) is None


def test_a_deferred_intake_that_runs_inside_the_key_handler_does_not_free_ctrl_space() -> None:
    """The key handler's counterpart: nothing picked, the cursor on Bravo, Bravo selected through
    accessibility, and the tab sample defers the intake. If that intake runs while Ctrl+Space's
    handler posts its input's acknowledgement, it clears its record and takes nothing; a handler
    that read the record after that call toggled Bravo on, and Move to Top moved the sheet the
    user meant to deselect. The handler reads the record once, before posting."""
    owner = sheet_list(Book(list(NAMES)))
    key(owner, DOWN, MOD1)
    select_through_accessibility(owner, ["Bravo"])
    sample(owner)
    owner._tabs.note_input = lambda: run_the_deferred_intake(owner)
    key(owner, SPACE, MOD1)
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert move_to_top(owner) is None


def test_a_deferred_intake_that_runs_inside_the_key_handler_does_not_free_ctrl_down() -> None:
    """The same for a cursor key with Ctrl: Alfa picked, then Echo selected alone through
    accessibility, and the tab sample defers the intake. If that intake runs while Ctrl+Down's
    handler posts its acknowledgement, a handler that read the record after that call kept Alfa,
    and its write showed Alfa again over Echo for Move to Top to move."""
    owner = alfa_then(["Echo"])
    sample(owner)
    owner._tabs.note_input = lambda: run_the_deferred_intake(owner)
    key(owner, DOWN, MOD1)
    assert "Alfa" not in picks(owner), "Alfa, which the user replaced, was kept"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert move_to_top(owner) is None


def test_a_refused_ctrl_click_tells_of_the_waiting_selection_with_picks_that_follow_calc() -> None:
    """The picks follow Calc's tabs, Bravo and Charlie, rather than the user, so dropping them
    alone is silent; Echo is then added through accessibility, a Ctrl+click adds Delta natively,
    and the tab sample defers the intake before the click's listener. The listener cannot account
    for Echo and picks nothing, and its write clears the four rows the tree showed, Echo the
    user's own: the notice tells of them."""
    owner = sheet_list(Book(list(NAMES)))
    owner.follow_tabs(["Bravo", "Charlie"], "Bravo")
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Charlie"] and not owner._user_picks
    owner.tree.assistive_select("Echo")
    queued_click(owner, row("Delta"))
    sample(owner)
    notices = len(owner.notices)
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Delta"
    assert len(owner.notices) == notices + 1, "The rows the tree showed went without the notice"
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
    "start, toggled, expected",
    [
        pytest.param(["Bravo"], "Bravo", [], id="deselects"),
        pytest.param(["Bravo"], "Delta", ["Bravo", "Delta"], id="selects"),
        pytest.param(["Bravo", "Delta"], "Bravo", ["Delta"], id="deselects one of two"),
    ],
)
def test_a_ctrl_click_whose_own_toggle_the_deferred_intake_saw_still_toggles(
    start: list[str], toggled: str, expected: list[str]
) -> None:
    """The control: Bravo, or Bravo and Delta, picked; a Ctrl+click toggles `toggled` natively,
    and the tab sample runs before its listener, as #85 recorded, and defers the intake. The
    tree differs from the picks only by that toggle, so the listener toggles as on `main`."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row(start[0]))
    for name in start[1:]:
        queued_click(owner, row(name))
        owner.run_queue()
    assert picks(owner) == start
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


def test_ctrl_space_on_a_deferred_assistive_selection_drops_the_picks() -> None:
    """The same with Alfa picked: the cursor moved to Bravo, Bravo added through accessibility,
    and the tab sample defers the intake. Ctrl+Space, meant to deselect Bravo, toggled it on
    against the picks, and Move to Top moved Alfa and Bravo. It picks nothing and drops Alfa,
    with the notice, as a held toggle does (#288)."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Alfa"))
    key(owner, DOWN, MOD1)
    assert cursor(owner) == "Bravo" and picks(owner) == ["Alfa"]
    owner.tree.assistive_select("Bravo")
    sample(owner)
    notices = len(owner.notices)
    key(owner, SPACE, MOD1)
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert len(owner.notices) > notices
    assert move_to_top(owner) is None


@pytest.mark.parametrize(
    "modifiers",
    [pytest.param(MOD1, id="Ctrl+Down"), pytest.param(MOD1 | SHIFT, id="Ctrl+Shift+Down")],
)
def test_a_ctrl_cursor_key_on_a_deferred_assistive_selection_does_not_keep_older_picks(
    modifiers: int,
) -> None:
    """Alfa picked, then Echo selected alone through accessibility, and the tab sample defers the
    intake. Ctrl+Down keeps the picks and Ctrl+Shift+Down adds a range to them: the key's write
    showed Alfa again over Echo, or Alfa and Bravo, and Move to Top moved them, though the user
    had replaced Alfa. As Ctrl+Space does, the key picks nothing and drops Alfa, with the
    notice, and the cursor moves."""
    owner = alfa_then(["Echo"])
    sample(owner)
    notices = len(owner.notices)
    key(owner, DOWN, modifiers)
    assert "Alfa" not in picks(owner), "Alfa, which the user replaced, was kept"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


def test_a_ctrl_click_after_a_ctrl_cursor_key_on_a_deferred_selection_picks_nothing() -> None:
    """Nothing picked: Bravo selected through accessibility, the tab sample defers the intake,
    Ctrl+Down moves the cursor, and a Ctrl+click on Bravo deselects it natively before the key's
    write. The intake, finding the key since its deferral, took nothing, and the listener
    toggled Bravo into the empty picks: Move to Top moved Bravo, which the user had deselected.
    The key holds toggles, as Ctrl+Space does, so the listener picks nothing."""
    owner = sheet_list(Book(list(NAMES)))
    select_through_accessibility(owner, ["Bravo"])
    sample(owner)
    owner.tree_key(DOWN, MOD1)
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Bravo"
    assert move_to_top(owner) is None


@pytest.mark.parametrize(
    "code",
    [pytest.param(SPACE, id="Ctrl+Space"), pytest.param(DOWN, id="Ctrl+Down")],
)
def test_a_ctrl_key_between_a_ctrl_clicks_toggle_and_its_listener_picks_nothing(code: int) -> None:
    """The cost of holding those keys: Bravo picked, a Ctrl+click adds Delta natively, the tab
    sample defers the intake before the click's listener, as #85 recorded, and Ctrl+Space or
    Ctrl+Down is typed before that listener runs. After Ctrl+Down, `main` picks Bravo and Delta,
    as the user saw them. The key cannot tell the click's toggle from an accessibility
    selection, so it drops the picks, with the notice, and the click's listener is held: the
    user selects again."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Bravo"))
    queued_click(owner, row("Delta"))
    sample(owner)
    notices = len(owner.notices)
    owner.tree_key(code, MOD1)
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


def test_ctrl_space_after_a_refused_ctrl_key_and_a_cursor_key_does_not_pick_the_row() -> None:
    """Keys typed after a refusal, before its write: Echo picked, Golf added through
    accessibility, and the tab sample defers the intake. Ctrl+Down is refused and drops Echo,
    with the notice, but the tree still shows Echo and Golf; Ctrl+Up then moved the cursor back
    to Echo and lowered the refusal's hold to one that left Space free, so Ctrl+Space, meant to
    deselect Echo, picked it, and Move to Top moved it. A key leaves a hold that holds Space as
    it is, so Ctrl+Space picks nothing."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Echo"))
    owner.tree.assistive_select("Golf")
    sample(owner)
    owner.tree_key(DOWN, MOD1)
    owner.tree_key(UP, MOD1)
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert "Echo" not in picks(owner), "Echo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Echo"
    assert move_to_top(owner) is None


def test_ctrl_keys_to_a_waiting_row_and_ctrl_space_do_not_pick_it() -> None:
    """The plain keyboard path to the same case: Alfa picked, Echo selected alone through
    accessibility, the tab sample, then Ctrl+Down four times to Echo and Ctrl+Space to deselect
    it, all before any write. The first Ctrl+Down is refused and drops Alfa; the second lowered
    the hold, and Ctrl+Space picked Echo."""
    owner = alfa_then(["Echo"])
    sample(owner)
    for _ in range(4):
        owner.tree_key(DOWN, MOD1)
    assert cursor(owner) == "Echo"
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert "Echo" not in picks(owner), "Echo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_ctrl_space_after_a_click_refused_behind_a_key_does_not_pick_the_deselected_row() -> None:
    """The same without assistive technology: Alfa picked, and Shift+Down picks Alfa and Bravo;
    a Ctrl+click on Delta is handled natively before that write, so its listener, run after the
    write, is held and drops both picks, while the tree shows Alfa and Bravo until the refusal's
    own write. Ctrl+Up twice moves the cursor to Bravo and lowered the hold; Ctrl+Space, meant to
    deselect Bravo, picked it, and Move to Top moved it."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Alfa"))
    owner.tree_key(DOWN, SHIFT)
    queued_click(owner, row("Delta"))
    for _ in range(3):  # The key's write, then the click's two listeners.
        work, _where = owner.queue.pop(0)
        work()
    assert picks(owner) == [] and owner.tree.shown() == ["Alfa", "Bravo"]
    owner.tree_key(UP, MOD1)
    owner.tree_key(UP, MOD1)
    assert cursor(owner) == "Bravo"
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_ctrl_space_before_the_write_of_a_refusal_that_found_no_picks_picks_nothing() -> None:
    """A refusal that finds no picks holds Space too: nothing picked, the cursor on Bravo, Bravo
    selected through accessibility, and the tab sample defers the intake. Ctrl+Down is refused,
    which ends the record, and Ctrl+Up moves the cursor back; Ctrl+Space before the refusal's
    write, meant to deselect Bravo, would pick it under a hold that left Space free."""
    owner = sheet_list(Book(list(NAMES)))
    key(owner, DOWN, MOD1)
    select_through_accessibility(owner, ["Bravo"])
    sample(owner)
    owner.tree_key(DOWN, MOD1)
    owner.tree_key(UP, MOD1)
    assert cursor(owner) == "Bravo" and owner.tree.shown() == ["Bravo"]
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_keys_typed_after_a_refusal_before_its_write_leave_ctrl_space_held() -> None:
    """The cost of keeping Space held after a refusal until its write, where the keys meant a
    set the list could have picked. Nothing picked; Bravo and Delta selected through
    accessibility; the tab sample; Ctrl+Space is refused; Down picks Bravo alone, Ctrl+Down moves
    the cursor to Charlie, and Ctrl+Space, all before the refusal's write: `main` picks Bravo and
    Charlie, as the keys mean. The tree still shows Bravo and Delta, so Ctrl+Space picks nothing
    and drops Bravo, with the notice."""
    owner = sheet_list(Book(list(NAMES)))
    select_through_accessibility(owner, ["Bravo", "Delta"])
    sample(owner)
    owner.tree_key(SPACE, MOD1)
    owner.tree_key(DOWN, 0)
    owner.tree_key(DOWN, MOD1)
    assert picks(owner) == ["Bravo"] and cursor(owner) == "Charlie"
    notices = len(owner.notices)
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) > notices
    assert move_to_top(owner) is None


def test_a_range_key_after_a_refused_toggle_before_its_write_leaves_ctrl_space_held() -> None:
    """The same cost through a range: Alfa picked, then Echo selected alone through
    accessibility; a Ctrl+click deselects Echo natively, the tab sample defers the intake before
    its listener, and the listener is refused and drops Alfa. Before its write, Ctrl+Shift+Down
    adds Echo and Foxtrot, and Ctrl+Space takes Foxtrot out again, so the keys mean Echo. The
    tree still shows the refused click, so Ctrl+Space picks nothing."""
    owner = alfa_then(["Echo"])
    queued_click(owner, row("Echo"))
    sample(owner)
    for _ in range(2):  # The click's two listeners; the intake and the write stay queued.
        work, _where = owner.queue.pop(0)
        work()
    assert picks(owner) == [] and cursor(owner) == "Echo"
    owner.tree_key(DOWN, MOD1 | SHIFT)
    assert picks(owner) == ["Echo", "Foxtrot"]
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_three_ctrl_clicks_around_a_sample_do_not_pick_the_row_deselected_last() -> None:
    """Several presses in flight, no assistive technology, nothing picked: Ctrl+clicks on Alfa
    and on Delta select them natively, the tab sample defers the intake, and a Ctrl+click on
    Alfa deselects it again, all before the first listener runs, so the tree shows Delta. The
    first two listeners cannot account for the rows the intake found and pick nothing, and the
    intake, which finds input since its deferral, takes nothing. Those refusals found no picks
    to drop and held nothing, so the third listener toggled Alfa into the empty picks: Move to
    Top moved Alfa, the sheet the user deselected last. A refused toggle holds toggles until its
    write shows the picks, as a drop does, and the notice tells of the rows that write clears."""
    owner = sheet_list(Book(list(NAMES)))
    queued_click(owner, row("Alfa"))
    queued_click(owner, row("Delta"))
    sample(owner)
    queued_click(owner, row("Alfa"))
    assert owner.tree.shown() == ["Delta"]
    owner.run_queue()
    assert "Alfa" not in picks(owner), "Alfa, which the user deselected last, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Alfa"
    assert len(owner.notices) == 1, "Delta, which the tree showed selected, went without the notice"
    assert move_to_top(owner) is None


def test_a_second_ctrl_click_on_a_row_added_to_an_assistive_selection_does_not_pick_it() -> None:
    """Nothing picked: Charlie selected through accessibility, a Ctrl+click adds Echo, the tab
    sample defers the intake, and a second Ctrl+click on Echo deselects it, so the tree shows
    Charlie. The first listener picks nothing, which held nothing, and the second toggled Echo
    into the empty picks: Move to Top moved Echo, which the user had deselected."""
    owner = sheet_list(Book(list(NAMES)))
    select_through_accessibility(owner, ["Charlie"])
    queued_click(owner, row("Echo"))
    sample(owner)
    queued_click(owner, row("Echo"))
    assert owner.tree.shown() == ["Charlie"]
    owner.run_queue()
    assert "Echo" not in picks(owner), "Echo, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Echo"
    assert len(owner.notices) == 1, (
        "Charlie, which the tree showed selected, went without the notice"
    )
    assert move_to_top(owner) is None


def test_a_third_ctrl_click_is_not_picked_alone_after_two_refused_ones() -> None:
    """Nothing picked: Ctrl+clicks on Alfa and on Delta, the tab sample, and a Ctrl+click on
    Golf, so the tree shows Alfa, Delta and Golf. The first two listeners pick nothing, and the
    third picked Golf alone, silently: Move to Top moved a set the user did not see."""
    owner = sheet_list(Book(list(NAMES)))
    queued_click(owner, row("Alfa"))
    queued_click(owner, row("Delta"))
    sample(owner)
    queued_click(owner, row("Golf"))
    assert owner.tree.shown() == ["Alfa", "Delta", "Golf"]
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Golf"
    assert len(owner.notices) == 1, "The rows the user selected went without the notice"
    assert move_to_top(owner) is None


def test_a_ctrl_click_before_the_write_of_a_refused_ctrl_space_picks_nothing() -> None:
    """Nothing picked: Bravo and Delta selected through accessibility, and the tab sample
    defers the intake. Ctrl+Space picks nothing, and the intake, which finds the key since its
    deferral, takes nothing; a Ctrl+click on Delta, shown selected, deselects it natively
    before the key's write, so the tree shows Bravo. The refused key held nothing, and the
    listener toggled Delta into the empty picks: Move to Top moved Delta."""
    owner = sheet_list(Book(list(NAMES)))
    select_through_accessibility(owner, ["Bravo", "Delta"])
    sample(owner)
    owner.tree_key(SPACE, MOD1)
    work, where = owner.queue.pop(0)
    assert where == "taking native list selection after queued input"
    work()
    queued_click(owner, row("Delta"))
    assert owner.tree.shown() == ["Bravo"]
    owner.run_queue()
    assert "Delta" not in picks(owner), "Delta, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def in_flight() -> list[Any]:
    """Ctrl+clicks in flight: each start, click sequence and place of the tab sample among the
    clicks, leaving out an accessibility selection that the clicks before the sample undo, so
    that the sample finds the tree showing exactly the picks, none: no intake has then read
    that selection, which is #294's case and acts as on `main`."""
    starts: list[tuple[str, list[str], list[str]]] = [
        ("nothing picked", [], []),
        ("Bravo picked", ["Bravo"], []),
        ("Bravo and Delta through accessibility", [], ["Bravo", "Delta"]),
    ]
    sequences: list[tuple[str, ...]] = [
        ("Bravo", "Delta"),
        ("Alfa", "Delta", "Alfa"),
        ("Alfa", "Delta", "Golf"),
        ("Bravo", "Delta", "Bravo"),
        ("Delta", "Delta", "Delta"),
        ("Alfa", "Bravo", "Alfa", "Delta"),
    ]
    cases: list[Any] = []
    for start, picked, assistive in starts:
        for clicks in sequences:
            for sampled in range(len(clicks) + 1):
                tree = set(assistive)
                for name in clicks[:sampled]:
                    tree ^= {name}
                if assistive and not tree:
                    continue
                label = f"{start}, {', '.join(clicks)}, sample after {sampled}"
                cases.append(pytest.param(picked, assistive, clicks, sampled, id=label))
    return cases


@pytest.mark.parametrize("picked, assistive, clicks, sampled", in_flight())
def test_ctrl_clicks_in_flight_around_a_sample_end_with_what_the_tree_showed_or_nothing(
    picked: list[str], assistive: list[str], clicks: tuple[str, ...], sampled: int
) -> None:
    """Several Ctrl+clicks handled natively before any of their listeners runs, with the tab
    sample after `sampled` of them, so that an intake has read the tree before the listeners
    act. The list then picks the rows the tree showed when the user stopped, or nothing, with
    the notice if the tree showed rows, never a set the user did not see."""
    owner = sheet_list(Book(list(NAMES)))
    for name in picked:
        click(owner, row(name))
    if assistive:
        select_through_accessibility(owner, assistive)
    for index, name in enumerate(clicks):
        if index == sampled:
            sample(owner)
        queued_click(owner, row(name))
    if sampled == len(clicks):
        sample(owner)
    seen = owner.tree.shown()
    notices = len(owner.notices)
    owner.run_queue()
    assert picks(owner) in ([], seen), f"The tree showed {seen}"
    assert owner.tree.shown() == picks(owner)
    if seen and not picks(owner):
        assert len(owner.notices) > notices, "The rows the user saw went without the notice"
    assert move_to_top(owner) == (picks(owner) or None)


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
