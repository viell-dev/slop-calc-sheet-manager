"""Toggles that the tree applies at once and the list's listener applies later (#288).

A Ctrl+click toggles its row in the tree as soon as LibreOffice handles the press. The list's mouse
listener runs later, queued behind the work already posted (#85, #269), and toggles the same row
in the list's picks. When work queued ahead of it drops the picks, as a refresh that loses the
identity proof does without any failure, or as a failed refresh or the intake's settling does
after one, the listener toggled against the empty picks and picked the row the user had just
deselected; Move to Top then moved it. Space toggles the cursor's row as the tree shows it, which
a drop or a failed write can leave other than the picks.

The real list runs over the simulated peer of `list_peer`, whose `queued_click` queues the
listeners as VCL does. The invariant: a toggle never picks a row the tree showed selected when
the user toggled it, nor keeps one the user toggled off. While the tree may not show the picks, a
toggle picks nothing, drops any picks left with the notice, and asks for the write; toggles act
again once posted work runs after the tree shows the picks.
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
    A,
    Book,
    changed,
    click,
    cursor,
    key,
    move_to_top,
    picks,
    press,
    queued_click,
    release,
    sheet_list,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]


def row(name: str) -> int:
    return NAMES.index(name)


def picked(*names: str) -> Any:
    """A list with `names` picked by a click and Ctrl+clicks, each shown in the tree."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row(names[0]))
    for name in names[1:]:
        queued_click(owner, row(name))
        owner.run_queue()
    assert picks(owner) == list(names) and owner.tree.shown() == list(names)
    return owner


def post_refresh(owner: Any) -> None:
    owner.post(owner.refresh, "refreshing the sheet list")


def post_sample(owner: Any) -> None:
    """The tab observer's sample, which asks for the intake (`pending_native_picks`)."""
    owner.post(
        lambda: owner._take_tree_selection(paint=False, defer=True),
        "observing Calc's selected tabs",
    )


def run_next(owner: Any) -> None:
    """Run only the first piece of posted work."""
    work, _ = owner.queue.pop(0)
    work()


def deselected_nothing_picked(owner: Any, name: str) -> None:
    """The toggled row is not picked, nothing else is, and Move to Top refuses."""
    assert name not in picks(owner), f"{name}, which the user deselected, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_lost_proof_before_a_toggles_listener_picks_nothing() -> None:
    """No failure. Bravo picked; a refresh is queued because another view replaced Echo; a
    Ctrl+click on Bravo deselects it in the tree before that refresh runs. The refresh loses the
    identity proof and drops every pick, and the click's listener, which runs after it, toggled
    Bravo against the empty picks: Move to Top moved the sheet the user had just deselected.
    The listener now changes no pick. The cursor follows the click, as a toggle's does, so Space
    after the queue has run acts on Bravo, the row the native cursor is on."""
    owner = picked("Bravo")
    owner.book.replace("Echo")
    post_refresh(owner)
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert cursor(owner) == "Bravo"
    deselected_nothing_picked(owner, "Bravo")
    key(owner, SPACE, MOD1)
    assert picks(owner) == ["Bravo"] and owner.tree.shown() == ["Bravo"]


def test_a_lost_proof_before_a_toggles_listener_also_holds_a_waiting_native_selection() -> None:
    """No failure, no picks: Bravo and Delta are selected through accessibility, waiting for
    the intake, and a Ctrl+click deselects Bravo in the tree. A refresh queued ahead of the
    click's listener loses the proof and clears the selection the intake had not taken, with
    the notice (#265). The listener toggled Bravo against the empty picks and picked it."""
    owner = sheet_list(Book(list(NAMES)))
    owner.tree.assistive_only("Bravo")
    owner.tree.assistive_select("Delta")
    owner.book.replace("Echo")
    post_refresh(owner)
    queued_click(owner, row("Bravo"))
    notices = len(owner.notices)
    owner.run_queue()
    assert len(owner.notices) == notices + 1
    deselected_nothing_picked(owner, "Bravo")


def test_space_after_a_lost_proof_and_before_its_release_picks_nothing() -> None:
    """No failure. Alfa picked, with the cursor on it; a refresh that loses the proof drops it
    and the cursor, and a Space the user pressed while Alfa was shown selected is handled before
    the queued work. Space with no cursor toggles the first row, Alfa, on: the row the user meant
    to deselect."""
    owner = picked("Alfa")
    owner.book.replace("Echo")
    post_refresh(owner)
    run_next(owner)
    owner.tree_key(SPACE, MOD1)
    owner.run_queue()
    deselected_nothing_picked(owner, "Alfa")


@pytest.mark.parametrize(
    "names, toggled",
    [
        pytest.param(("Bravo",), "Bravo", id="one pick"),
        pytest.param(("Bravo", "Delta"), "Delta", id="two picks"),
    ],
)
def test_a_failed_refresh_before_a_toggles_listener_picks_nothing(
    names: tuple[str, ...], toggled: str
) -> None:
    """A colour change's refresh is queued, and a Ctrl+click deselects `toggled` in the tree. The
    refresh rebuilds the rows, keeps the tree's selection for the intake as one made since, and
    fails showing it again (`clearSelection`), so it drops the picks that selection superseded and
    queues the write that clears the tree. The listener toggled `toggled` against the empty picks
    and picked it; with two picks, Move to Top moved Delta, where the user kept only Bravo."""
    owner = picked(*names)
    owner.book.sheet("Alfa").color = 0x336699
    post_refresh(owner)
    owner.faults.fail("clearSelection")
    queued_click(owner, row(toggled))
    owner.run_queue()
    assert owner.faults.failed == ["clearSelection"]
    deselected_nothing_picked(owner, toggled)


def unknown_after_a_partial_write() -> tuple[Any, str]:
    """Alfa picked; Shift+Down adds Bravo, and that write's `addSelection` fails after its
    effect. The tree shows Alfa and Bravo, and the record is unknown."""
    owner = picked("Alfa")
    owner.faults.fail("addSelection done")
    key(owner, DOWN, SHIFT)
    assert owner._shown is None and owner.tree.shown() == ["Alfa", "Bravo"]
    return owner, "Bravo"


def unknown_after_a_write_with_no_effect() -> tuple[Any, str]:
    """A press on Alfa, Shift+Down while it is held, and the release, whose write of Alfa alone
    fails at `select` with no effect. The tree still shows Alfa, the pick, but the record is
    unknown."""
    owner = sheet_list(Book(list(NAMES)))
    press(owner, row("Alfa"))
    owner.run_queue()
    key(owner, DOWN, SHIFT)
    owner.faults.fail("select")
    release(owner, row("Alfa"))
    owner.run_queue()
    assert owner._shown is None and owner.tree.shown() == ["Alfa"] == picks(owner)
    return owner, "Alfa"


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param(unknown_after_a_partial_write, id="tree shows part"),
        pytest.param(unknown_after_a_write_with_no_effect, id="tree shows the picks"),
    ],
)
def test_settling_before_a_toggles_listener_picks_nothing(
    setup: Callable[[], tuple[Any, str]],
) -> None:
    """After a failed write, a Ctrl+click deselects a shown row in the tree, and the tab sample
    queued ahead of its listener settles the unknown record: the tree no longer shows exactly the
    picks, so they are dropped, with the notice. The listener toggled the row against the empty
    picks and picked it, also when the record was known again over an empty tree."""
    owner, toggled = setup()
    post_sample(owner)
    queued_click(owner, row(toggled))
    owner.run_queue()
    deselected_nothing_picked(owner, toggled)


def test_a_refresh_that_settles_and_writes_before_a_toggles_listener_picks_nothing() -> None:
    """The route the review's two rules on state left open. Every sheet picked with Ctrl+A;
    Ctrl+Down's write fails at its second `addSelection`, leaving Alfa and Bravo shown. A
    Ctrl+click deselects Bravo, and a refresh queued ahead of its listener settles the record,
    drops the picks, and then writes the empty picks itself, so the record is known again
    before the listener runs. The listener picked Bravo, and Move to Top moved it."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, row("Alfa"))
    key(owner, A, MOD1)
    owner.faults.fail("addSelection", after=1)
    key(owner, DOWN, MOD1)
    assert owner.tree.shown() == ["Alfa", "Bravo"] and len(picks(owner)) == len(NAMES)
    post_refresh(owner)
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    deselected_nothing_picked(owner, "Bravo")


def test_a_toggle_on_a_row_a_drop_left_selected_waits_for_the_write_after_it() -> None:
    """Bravo picked and the cursor on Delta; a rebuild's last `addSelection` fails after its
    effect, and Delta alone is then selected through accessibility. The tab sample's intake drops
    Bravo and queues the write that clears Delta. A Ctrl+click handled natively before that write
    deselects Delta, the row the user saw selected; its listener runs after the write, which
    leaves the record known. The listener toggled Delta against the empty picks and picked it.
    The hold ends only in work posted after that write, behind the listener."""
    owner = picked("Bravo")
    while cursor(owner) != "Delta":
        key(owner, DOWN, MOD1)
    owner.faults.fail("addSelection done")
    owner.book.sheet("Golf").color = 0x336699
    changed(owner)
    owner.retry(limit=1)
    assert owner._shown is None and owner.tree.shown() == ["Bravo"]
    owner.tree.assistive_only("Delta")
    owner._take_tree_selection(paint=False, defer=True)  # The sample, before its queue runs.
    assert picks(owner) == [] and owner.tree.shown() == ["Delta"]
    queued_click(owner, row("Delta"))
    owner.run_queue()
    deselected_nothing_picked(owner, "Delta")


def test_the_release_of_an_earlier_hold_does_not_end_a_later_one() -> None:
    """Bravo picked; Ctrl+Down's write fails at `select`, so toggles are held. The next write
    shows Bravo again and posts that hold's release, while a refresh is already queued ahead of
    it. A Ctrl+click deselects Bravo in the tree; its listener queues behind the release. The
    refresh then loses the proof and drops Bravo, a new hold. When the earlier release ran
    first, it ended the new hold too, and the listener picked Bravo."""
    owner = picked("Bravo")
    owner.faults.fail("select")
    key(owner, DOWN, MOD1)
    assert owner._shown is None and owner.tree.shown() == ["Bravo"]
    owner._queue_selection()
    post_refresh(owner)
    run_next(owner)  # The write: Bravo is shown again, and the hold's release is posted.
    assert owner._shown == ("Bravo",) and owner.tree.shown() == ["Bravo"]
    queued_click(owner, row("Bravo"))
    owner.book.replace("Echo")  # Before the queued refresh runs.
    owner.run_queue()
    deselected_nothing_picked(owner, "Bravo")


@pytest.mark.parametrize(
    "toggle",
    [
        pytest.param(lambda owner: key(owner, SPACE, MOD1), id="Ctrl+Space"),
        pytest.param(
            lambda owner: (queued_click(owner, row("Delta")), owner.run_queue()),
            id="Ctrl+click",
        ),
    ],
)
def test_a_toggle_after_a_failed_write_does_not_pick_the_row_it_left_selected(
    toggle: Callable[[Any], None],
) -> None:
    """Bravo picked, the cursor on Charlie; Ctrl+Down moves it to Delta, and that write selects
    Delta and then fails at `clearSelection`. The tree shows Delta alone, which the list does not
    hold, and the record is unknown. Ctrl+Space with the cursor there, or a Ctrl+click on Delta,
    meant to deselect it, toggled it on against the picks, and Move to Top moved Bravo and Delta.
    The rule for Space before this held only while nothing was picked. The toggle now picks
    nothing and drops Bravo, which the user did not see selected, with the notice."""
    owner = picked("Bravo")
    key(owner, DOWN, MOD1)
    owner.faults.fail("clearSelection")
    key(owner, DOWN, MOD1)
    assert owner._shown is None and owner.tree.shown() == ["Delta"] and cursor(owner) == "Delta"
    notices = len(owner.notices)
    toggle(owner)
    assert len(owner.notices) == notices + 1 and cursor(owner) == "Delta"
    deselected_nothing_picked(owner, "Delta")


def test_a_toggle_that_deselects_a_pick_after_a_failed_write_does_not_keep_it() -> None:
    """Alfa and Bravo picked and shown; Ctrl+Up's write fails at `select` with no effect, so the
    tree still shows both but the record is unknown. A Ctrl+click deselects Bravo. Changing no
    pick would keep Bravo, which the next write shows again and Move to Top moves: the row the
    user had just deselected. The toggle drops the picks instead, with the notice."""
    owner = picked("Alfa", "Bravo")
    owner.faults.fail("select")
    key(owner, UP, MOD1)
    assert owner._shown is None and owner.tree.shown() == ["Alfa", "Bravo"]
    queued_click(owner, row("Bravo"))
    owner.run_queue()
    assert cursor(owner) == "Bravo"
    deselected_nothing_picked(owner, "Bravo")


def test_toggles_act_again_once_a_write_shows_the_picks() -> None:
    """After a lost proof and its write, posted work ends the hold: a Ctrl+click then picks the
    row it selects in the tree, and Ctrl+Space toggles the cursor's row off."""
    owner = picked("Bravo")
    owner.book.replace("Echo")
    post_refresh(owner)
    owner.run_queue()
    assert picks(owner) == [] and owner._toggles_held is None
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == ["Delta"] and owner.tree.shown() == ["Delta"]
    key(owner, SPACE, MOD1)
    assert picks(owner) == [] and owner.tree.shown() == []


def failed_cursor_write_without_picks() -> Any:
    """No picks, the cursor on Alfa; Ctrl+Down's write selects Bravo and then fails, so the tree
    shows Bravo, which the list does not hold, and toggles are held."""
    owner = picked("Alfa")
    key(owner, SPACE, MOD1)
    owner.faults.fail("select done")
    key(owner, DOWN, MOD1)
    assert picks(owner) == [] and owner.tree.shown() == ["Bravo"] and owner._shown is None
    return owner


def test_type_ahead_that_shows_its_pick_ends_the_hold() -> None:
    """Type-ahead picks Delta alone and shows it; a Ctrl+click on Foxtrot then adds Foxtrot."""
    owner = failed_cursor_write_without_picks()
    owner.type_ahead("d")
    owner.run_queue()
    assert picks(owner) == ["Delta"] and owner.tree.shown() == ["Delta"]
    queued_click(owner, row("Foxtrot"))
    owner.run_queue()
    assert picks(owner) == ["Delta", "Foxtrot"]


def test_an_intake_that_finds_the_picks_shown_ends_the_hold() -> None:
    """A failed write left the tree showing exactly the picks, Alfa and Bravo; the tab sample's
    intake finds them shown and makes the record known without writing. A Ctrl+click on Charlie
    then adds Charlie."""
    owner, _ = unknown_after_a_partial_write()
    post_sample(owner)
    owner.run_queue()
    assert owner._shown == ("Alfa", "Bravo")
    queued_click(owner, row("Charlie"))
    owner.run_queue()
    assert picks(owner) == ["Alfa", "Bravo", "Charlie"]


@pytest.mark.parametrize(
    "modifiers",
    [
        pytest.param(0, id="plain"),
        pytest.param(SHIFT, id="Shift"),
        pytest.param(SHIFT | MOD1, id="Ctrl+Shift"),
    ],
)
def test_a_press_that_does_not_toggle_still_picks_while_toggles_are_held(modifiers: int) -> None:
    """A plain or Shift press sets the picks, and Ctrl+Shift adds a range to them, rather than
    toggling a row, so a drop before the listener cannot invert it: after a lost proof, a press on
    Delta still picks Delta."""
    owner = picked("Bravo")
    owner.book.replace("Echo")
    post_refresh(owner)
    queued_click(owner, row("Delta"), modifiers)
    owner.run_queue()
    assert picks(owner) == ["Delta"] and owner.tree.shown() == ["Delta"]
    assert move_to_top(owner) == ["Delta"]


def test_a_toggle_that_added_a_row_before_a_drop_changes_no_pick() -> None:
    """The cost of the rule. Bravo picked; a Ctrl+click adds Delta in the tree, and a refresh
    queued ahead of its listener loses the proof and drops Bravo. The listener cannot tell
    whether the tree showed Delta when the user toggled it, so it changes no pick either way,
    and the write clears the tree: the user picks Delta again."""
    owner = picked("Bravo")
    owner.book.replace("Echo")
    post_refresh(owner)
    queued_click(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == [] and cursor(owner) == "Delta"
