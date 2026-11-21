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

from sheet_manager.keys import A
from tests.unit.list_peer import (
    DOWN,
    MOD1,
    MOD2,
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
# Whether the tab sample has seen the selection when the input comes.
SAMPLED = [pytest.param(False, id="before"), pytest.param(True, id="seen")]


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


def test_a_refused_ctrl_click_tells_of_the_assistive_selection_its_write_clears() -> None:
    """Nothing picked; Echo selected through accessibility, and a Ctrl+click adds Golf before any
    intake. The click is refused, and its write clears Echo, which the user selected, with Golf:
    the notice tells of them, as it does once an intake has seen the selection (#291)."""
    owner = fresh()
    owner.tree.assistive_only("Echo")
    queued_click(owner, row("Golf"))
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) == 1, "Echo, which the tree showed selected, went without the notice"
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


@pytest.mark.parametrize("sampled", SAMPLED)
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


@pytest.mark.parametrize("sampled", SAMPLED)
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


# What the count cannot tell, which #291's record and holds still decide.
#
# The count does not say whose a change was. When the list takes or overwrites the tree between a
# press's native change and its listener, the press's own change is accounted for, and a change
# counted later looks like the press's own. These pass on `main` too; without the record's rules
# the listener toggled its row again.


def test_an_intake_that_took_a_clicks_toggle_still_holds_its_listener() -> None:
    """Bravo picked, Delta added through accessibility, and the tab sample defers the intake; a
    Ctrl+click adds Foxtrot natively, and the intake, queued ahead of its listener, takes Bravo,
    Delta and Foxtrot; Golf is then added through accessibility. Golf is the only change left
    unaccounted, which looks like the click's own, but the intake already took the click's
    toggle: toggling Foxtrot again dropped the sheet the user had just added. The intake found
    the tree changed since it looked and held toggles (#291), so the listener picks nothing."""
    owner = picked("Bravo")
    owner.tree.assistive_select("Delta")
    sample(owner)
    queued_click(owner, row("Foxtrot"))
    work, where = owner.queue.pop(0)
    assert where == INTAKE
    work()
    assert picks(owner) == ["Bravo", "Delta", "Foxtrot"]
    owner.tree.assistive_select("Golf")
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_write_that_erased_a_clicks_toggle_leaves_the_record_to_decide() -> None:
    """Bravo picked, Echo added through accessibility, a Ctrl+click adding Golf natively, and the
    tab sample, which defers the intake with the tree showing Bravo, Echo and Golf; a write
    queued earlier then shows Bravo alone, and Charlie is added through accessibility. Charlie
    looks like the click's own change, and toggling Golf picked a sheet the write had shown
    deselected. The record shows that the tree differed by more than the click's toggle, so
    the listener picks nothing (#291)."""
    owner = picked("Bravo")
    owner.tree.assistive_select("Echo")
    queued_click(owner, row("Golf"))
    sample(owner)
    owner._show_selection()
    assert owner.tree.shown() == ["Bravo"]
    owner.tree.assistive_select("Charlie")
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


# What VCL's selection engine changes for a press (#310's review; measured on #294).


def ranged_to_charlie() -> Any:
    """Alfa picked by a click, then a Ctrl+Shift+click on Charlie, which puts VCL's selection
    engine in add mode until a plain or a Shift press."""
    owner = picked("Alfa")
    queued_click(owner, row("Charlie"), MOD1 | SHIFT)
    owner.run_queue()
    assert picks(owner) == ["Alfa", "Bravo", "Charlie"] == owner.tree.shown()
    assert owner.tree.add_mode and owner._add_mode
    return owner


def test_a_ctrl_click_on_an_unselected_row_in_add_mode_toggles_as_before() -> None:
    """After the Ctrl+Shift+click, a Ctrl+click on Echo only moves the tree's cursor: in add mode
    the engine selects nothing. The listener expected one change and refused, dropping every
    pick; it now expects none and adds Echo, as on `main`. A Ctrl+click on a selected row still
    deselects it natively, and is still the press's own change."""
    owner = ranged_to_charlie()
    notified = owner.tree.notified
    queued_click(owner, row("Echo"))
    assert owner.tree.notified == notified, "The engine changed a row in add mode"
    owner.run_queue()
    assert picks(owner) == ["Alfa", "Bravo", "Charlie", "Echo"] == owner.tree.shown()
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert picks(owner) == ["Alfa", "Charlie", "Echo"] == owner.tree.shown()
    assert move_to_top(owner) == ["Alfa", "Charlie", "Echo"]


def test_a_plain_click_ends_add_mode() -> None:
    owner = ranged_to_charlie()
    queued_click(owner, row("Delta"), 0)
    owner.run_queue()
    assert not owner._add_mode and not owner.tree.add_mode
    queued_click(owner, row("Foxtrot"))
    owner.run_queue()
    assert picks(owner) == ["Delta", "Foxtrot"] == owner.tree.shown()


def test_ctrl_space_before_the_write_of_an_add_mode_ctrl_click_picks_nothing() -> None:
    """The add-mode Ctrl+click on Echo picks Echo, which the tree does not show until the write.
    Ctrl+Space typed before it, with the cursor on Echo, toggles what the user sees, an
    unselected row; toggling the picks would take Echo out. So, as after the second click of a
    Ctrl double click, toggles are held, Space included, until the write, and the key picks
    nothing."""
    owner = ranged_to_charlie()
    queued_click(owner, row("Echo"))
    for _ in range(2):  # The click's listeners; the write they ask for stays queued.
        work, where = owner.queue.pop(0)
        assert where.startswith("a mouse"), where
        work()
    assert "Echo" in picks(owner) and "Echo" not in owner.tree.shown()
    key(owner, SPACE, MOD1)
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_triple_ctrl_click_toggles_its_row_three_times() -> None:
    """Alfa, Bravo and Charlie picked; three quick Ctrl+clicks on Echo. The engine changes the
    selection only at a click count of 1, and each listener runs before the next press, as at
    normal speed: Echo on, off and on, as on `main`. The third listener expected one change and
    dropped every pick."""
    owner = picked("Alfa", "Bravo", "Charlie")
    for clicks in (1, 2, 3):
        queued_click(owner, row("Echo"), clicks=clicks)
        owner.run_queue()
    assert picks(owner) == ["Alfa", "Bravo", "Charlie", "Echo"] == owner.tree.shown()
    assert move_to_top(owner) == ["Alfa", "Bravo", "Charlie", "Echo"]


def test_a_ctrl_alt_click_toggles_its_row_as_before() -> None:
    """With Alt, the engine returns at once and changes nothing; the listener, which ignores
    Alt, toggles the row as on `main`."""
    owner = picked("Alfa")
    queued_click(owner, row("Charlie"), MOD1 | MOD2)
    assert owner.tree.shown() == ["Alfa"]
    owner.run_queue()
    assert picks(owner) == ["Alfa", "Charlie"] == owner.tree.shown()


# Changes that cancel out, and the points that account for changes.


def post_sample(owner: Any) -> None:
    """A tab sample, posted as the tab observer's timer posts it, behind the work queued."""
    owner.post(lambda: sample(owner), "observing Calc's selected tabs")


def cancelled_out(owner: Any, name: str) -> None:
    """Deselect a picked row and select it again through accessibility: two changes, and the
    tree shows the picks again."""
    others = [node for node in owner.tree.selected if node.DataValue != name]
    owner.tree.selected = others
    owner.tree.selected = [*others, owner.tree.node(name)]


def test_changes_that_cancel_out_are_accounted_for_by_two_quiet_samples() -> None:
    """Alfa and Bravo picked; Bravo deselected and selected again through accessibility. The tree
    shows the picks, but the two changes stayed unaccounted until the next input, however long
    after, which was refused: a Ctrl+click on Delta dropped every pick. Two tab samples in a row
    that find the tree showing the picks, with nothing counted and no input between them,
    account for them, so the Ctrl+click adds Delta, as on `main`."""
    owner = picked("Alfa", "Bravo")
    cancelled_out(owner, "Bravo")
    assert unaccounted(owner) == 2 and owner.tree.shown() == picks(owner)
    post_sample(owner)
    owner.run_queue()
    assert unaccounted(owner) == 2, "One sample alone accounted"
    post_sample(owner)
    owner.run_queue()
    assert unaccounted(owner) == 0
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == ["Alfa", "Bravo", "Delta"] == owner.tree.shown()
    assert move_to_top(owner) == ["Alfa", "Bravo", "Delta"]


def test_quiet_samples_do_not_account_for_a_queued_clicks_change() -> None:
    """The sequence that made the first version wrong, with its second sample posted as the
    timer posts it: a Ctrl+click on Bravo handled natively, the selection cleared through
    accessibility, a sample posted before the click's listener that finds the tree showing the
    picks, none, and Charlie then added through accessibility. The next sample is posted after
    the first ran, behind the listener, so nothing accounts for the click's change before it
    runs, and the listener, seeing more than its own change, picks nothing. Had one quiet sample
    accounted, it would have taken Charlie's change for its own and picked Bravo, which the user
    had cleared."""
    owner = fresh()
    queued_click(owner, row("Bravo"))
    owner.tree.assistive_clear()
    sample(owner)  # Posted before the click's listeners, so it runs ahead of them.
    post_sample(owner)
    owner.tree.assistive_select("Charlie")
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user cleared, was picked"
    assert picks(owner) == [] and move_to_top(owner) is None


def test_a_press_between_two_samples_keeps_them_from_accounting() -> None:
    """Alfa and Bravo picked; the first sample finds the tree showing them. A Ctrl+click on Bravo
    is then handled natively, Bravo is selected again through accessibility, and the next sample
    runs before the click's listener, as when the click came just before that sample was posted:
    it finds the tree showing the picks again, but with two more changes counted, so it accounts
    for nothing. Golf is then selected through accessibility. Had the sample accounted, the
    listener would have taken Golf's change for its own and toggled Bravo off, though the user
    saw it selected again; it picks nothing."""
    owner = picked("Alfa", "Bravo")
    sample(owner)
    queued_click(owner, row("Bravo"))
    owner.tree.assistive_select("Bravo")
    assert owner.tree.shown() == picks(owner)
    sample(owner)
    assert unaccounted(owner) == 2
    owner.tree.assistive_select("Golf")
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None


def test_an_assistive_change_after_quiet_samples_still_counts() -> None:
    owner = picked("Alfa", "Bravo")
    cancelled_out(owner, "Bravo")
    for _ in range(2):
        post_sample(owner)
        owner.run_queue()
    owner.tree.assistive_select("Golf")
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None


def test_a_rebuild_without_picks_accounts_for_the_changes_before_its_model() -> None:
    """Nothing picked; Echo selected and deselected through accessibility, and another view
    renames Hotel, so the refresh installs a new model, which shows nothing selected, exactly the
    picks. The rebuild's clear of the tree then fails, so its write accounts for nothing. A
    Ctrl+click on Delta after it adds Delta, as on `main`: the model replaced what the changes
    counted before it changed."""
    owner = fresh()
    owner.tree.assistive_only("Echo")
    owner.tree.assistive_clear()
    assert unaccounted(owner) == 2
    owner.book.rename("Hotel", "India")
    owner.faults.fail("clearSelection")
    changed(owner)
    owner.retry(limit=1)
    assert owner.faults.failed == ["clearSelection"]
    assert owner.names()[-1] == "India" and owner.tree.shown() == []
    assert unaccounted(owner) == 0
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == ["Delta"] and move_to_top(owner) == ["Delta"]


def test_a_settled_record_accounts_for_the_changes_before_the_intake() -> None:
    """Alfa picked; a Ctrl+click adds Charlie, and the write's last call fails after its effect,
    so the record is unknown though the tree shows the picks; Golf is then selected and
    deselected through accessibility. The intake settles the record from the tree, which shows
    the picks, and that accounts for the changes counted before it read the tree, so a Ctrl+click
    on Echo adds Echo, as on `main`."""
    owner = picked("Alfa")
    owner.faults.fail("addSelection done")
    queued_click(owner, row("Charlie"))
    owner.run_queue()
    assert owner.faults.failed == ["addSelection done"]
    assert owner._shown is None and owner.tree.shown() == ["Alfa", "Charlie"] == picks(owner)
    owner.tree.assistive_select("Golf")
    owner.tree.selected = [owner.tree.node("Alfa"), owner.tree.node("Charlie")]
    sample(owner)
    assert owner._shown == ("Alfa", "Charlie") and unaccounted(owner) == 0
    queued_click(owner, row("Echo"))
    owner.run_queue()
    assert picks(owner) == ["Alfa", "Charlie", "Echo"] == owner.tree.shown()


def test_ctrl_space_typed_after_ctrl_a_over_an_assistive_selection_acts() -> None:
    """Alfa picked and Echo selected alone through accessibility; Ctrl+A picks every row, and
    Ctrl+Space, typed before Ctrl+A's write, takes the cursor's row out again, as on `main`:
    Ctrl+A set the whole selection, which its write shows over those changes."""
    owner = picked("Alfa")
    owner.tree.assistive_only("Echo")
    owner.tree_key(A, MOD1)
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    assert picks(owner) == NAMES[1:] == owner.tree.shown()


def test_a_type_ahead_write_accounts_for_the_changes_it_replaced() -> None:
    """Alfa picked and Golf added through accessibility; a type-ahead to Echo picks Echo alone,
    and its write shows only Echo. A Ctrl+click on Charlie after it adds Charlie, as on
    `main`."""
    owner = picked("Alfa")
    owner.tree.assistive_select("Golf")
    owner.type_ahead("e")
    owner.run_queue()
    assert picks(owner) == ["Echo"] == owner.tree.shown() and unaccounted(owner) == 0
    queued_click(owner, row("Charlie"))
    owner.run_queue()
    assert picks(owner) == ["Charlie", "Echo"] and move_to_top(owner) == ["Charlie", "Echo"]


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


def test_ctrl_space_after_a_ctrl_double_click_before_its_write_does_not_pick_the_row() -> None:
    """Alfa picked; a Ctrl+double-click on Charlie, whose first press the tree toggles on and
    whose second it does not, and Ctrl+Space with the cursor there before the listeners' write,
    meant to deselect Charlie, which the tree shows selected. The listeners toggled Charlie twice,
    so the picks lacked it, and Ctrl+Space picked it: Move to Top moved Alfa and Charlie. The
    second listener holds toggles until its write shows the picks, so Ctrl+Space picks
    nothing."""
    owner = picked("Alfa")
    queued_click(owner, row("Charlie"))
    queued_click(owner, row("Charlie"), clicks=2)
    for _ in range(4):  # The four listeners; their write stays queued.
        work, where = owner.queue.pop(0)
        assert where.startswith("a mouse"), where
        work()
    assert picks(owner) == ["Alfa"] and owner.tree.shown() == ["Alfa", "Charlie"]
    key(owner, SPACE, MOD1)
    assert "Charlie" not in picks(owner), "Charlie, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


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


# A write of the list's between a Ctrl press and its listener (#44).


def test_a_write_between_a_ctrl_click_and_its_listener_toggles_as_before() -> None:
    """Alfa and Bravo picked; a Ctrl+click deselects Bravo, and the list's coalesced write runs
    before its listener, which shows Bravo again. The listener found nothing of its own left and
    picked nothing; the write overwrote that one change and nothing was counted since, so the
    listener takes it for its own and toggles Bravo off, as on `main`."""
    owner = picked("Alfa", "Bravo")
    queued_click(owner, row("Bravo"))
    owner.queue.insert(0, (owner._show_selection, "showing the selection"))
    owner.run_queue()
    assert picks(owner) == ["Alfa"] == owner.tree.shown()
    assert move_to_top(owner) == ["Alfa"]


def test_a_ctrl_click_after_a_plain_click_whose_listener_ran_first_toggles_as_before() -> None:
    """#44's integration sequence as VCL ran it with 26.8.2.2, headless: Delta picked; a double
    click on Bravo, whose first press's listener VCL ran at once, then a Ctrl+click on Delta,
    handled before that listener's write, which then ran before the other listeners. The write
    overwrote the Ctrl+click's change alone, so the Ctrl+click's listener toggles Delta, as on
    `main`; it found nothing of its own left and picked nothing."""
    owner = picked("Delta")

    def activate(*_: object) -> None:
        """The double click's activation, which the peer does not model."""

    owner._activate_pressed = activate
    queued_click(owner, row("Bravo"), 0)
    (press, _), first_release = owner.queue.pop(0), owner.queue.pop(0)
    press()  # It asks for the write, queued now.
    queued_click(owner, row("Bravo"), 0, clicks=2)
    queued_click(owner, row("Delta"))
    owner.queue.insert(1, first_release)  # VCL handled that release after the press's listener.
    assert [where for _, where in owner.queue[:2]] == ["showing the selection", "a mouse release"]
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Delta"] == owner.tree.shown()
    assert move_to_top(owner) == ["Bravo", "Delta"]


def test_two_quick_ctrl_clicks_toggle_both_when_the_first_write_lands_between() -> None:
    """Alfa picked; a Ctrl+click on Charlie, whose press's listener runs at once, and a Ctrl+click
    on Echo handled before Charlie's write, which shows the picks over Echo's change: both are
    picked, as on `main`."""
    owner = picked("Alfa")
    queued_click(owner, row("Charlie"))
    work, _ = owner.queue.pop(0)
    work()
    queued_click(owner, row("Echo"))
    owner.run_queue()
    assert picks(owner) == ["Alfa", "Charlie", "Echo"] == owner.tree.shown()
    assert move_to_top(owner) == ["Alfa", "Charlie", "Echo"]


def test_a_take_between_a_ctrl_click_and_its_listener_still_refuses() -> None:
    """Alfa and Bravo picked; a Ctrl+click deselects Bravo, and the list takes the tree's
    selection before the listener runs, as a command's intake does. The take includes the
    toggle, and toggling again would pick Bravo, which the user deselected, as on `main`: the
    listener picks nothing."""
    owner = picked("Alfa", "Bravo")
    queued_click(owner, row("Bravo"))
    owner._take_tree_selection()
    assert picks(owner) == ["Alfa"] and unaccounted(owner) == 0
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo, which the user deselected, was picked"
    assert picks(owner) == [] and move_to_top(owner) is None


def test_a_write_that_also_overwrote_an_assistive_change_still_refuses() -> None:
    """The write between the Ctrl+click and its listener also overwrote Golf, selected through
    accessibility after the click: two changes, not the press's own alone, so the listener picks
    nothing. `main` toggles Bravo off over the selection the user made last."""
    owner = picked("Alfa", "Bravo")
    queued_click(owner, row("Bravo"))
    owner.tree.assistive_select("Golf")
    owner.queue.insert(0, (owner._show_selection, "showing the selection"))
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None


# Costs: refusals where `main` acts correctly.


def test_a_ctrl_click_queued_behind_a_plain_click_toggles_as_before() -> None:
    """Alfa picked; a plain click on Charlie and a Ctrl+click on Echo are both handled natively
    before the first listener runs, as when the user clicks ahead while LibreOffice is busy. The
    plain press deselected Alfa and selected Charlie, as the record says the tree showed Alfa;
    its listener accounts for exactly those changes, so the Ctrl+click's listener sees its own
    change alone and picks Charlie and Echo, as on `main` (#44, #310's review)."""
    owner = picked("Alfa")
    queued_click(owner, row("Charlie"), 0)
    queued_click(owner, row("Echo"))
    owner.run_queue()
    assert picks(owner) == ["Charlie", "Echo"] == owner.tree.shown()
    assert move_to_top(owner) == ["Charlie", "Echo"]


def test_an_assistive_change_between_a_plain_and_a_ctrl_click_still_refuses() -> None:
    """The same, with Golf added through accessibility between the two presses: the plain
    press's listener accounts only for its own changes, so Golf's stays, and the Ctrl+click's
    listener, seeing two changes, picks nothing."""
    owner = picked("Alfa")
    queued_click(owner, row("Charlie"), 0)
    owner.tree.assistive_select("Golf")
    queued_click(owner, row("Echo"))
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_ctrl_shift_click_from_another_anchor_than_the_tree_is_refused() -> None:
    """Without assistive technology: Alfa picked, Ctrl+Down four times to Echo, and a
    Ctrl+Shift+click on Golf. The tree adds Foxtrot and Golf from its anchor on Echo, while the
    list's range from Alfa adds Bravo to Golf, so the counts differ and the press is refused;
    `main` picks Alfa to Golf."""
    owner = anchored_at_echo()
    queued_click(owner, row("Golf"), MOD1 | SHIFT)
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None
