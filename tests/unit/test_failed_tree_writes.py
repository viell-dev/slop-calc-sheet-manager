"""Tree writes that fail partway, and native picks made against an earlier proof (#257, #265).

The real list runs over the simulated peer of `list_peer`, with one native call made to fail. No
native trigger is known for these failures; LibreOffice's tree calls have failed in practice
only while the control was being disposed. Each sequence ends with the next command, Move to Top
through the list's own handler, and the invariant is the one the safety rules state: a command
acts on exactly the sheets the user picked, or on none.
"""

from collections.abc import Callable
from typing import Any

import pytest

from tests.unit.list_peer import (
    DOWN,
    MOD1,
    RIGHT,
    SPACE,
    Book,
    NativeFailure,
    changed,
    click,
    cursor,
    focus_event,
    key,
    move_to_top,
    picks,
    press,
    sheet_list,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]


def bravo_with_cursor_on(target: str) -> Any:
    """Bravo picked by a click, and the keyboard cursor moved to the unpicked `target`."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    while cursor(owner) != target:
        key(owner, DOWN, MOD1)
    assert picks(owner) == ["Bravo"] and owner.tree.shown() == ["Bravo"]
    return owner


def recover(owner: Any) -> None:
    """Let the posted work and the refresh schedule's retries run."""
    owner.run_queue()
    owner.retry()
    owner.run_queue()


def sweep(
    setup: Callable[[], Any], step: Callable[[Any], None], expected: list[str]
) -> list[tuple[int, str, Any, Any]]:
    """Fail each native call that `step` makes, in turn, then press Move to Top twice.

    The first press comes at once, before any retry, and must move exactly `expected` or
    nothing; the second comes after the retries and must move exactly `expected`. A failure
    that leaves the new data model installed may drop the picks instead (#257, case 4), never
    move another sheet. Returns the calls whose sequence broke either rule.
    """
    owner = setup()
    start = len(owner.faults.calls)
    step(owner)
    calls = owner.faults.calls[start:]
    assert calls, "The step made no native call"
    broken: list[tuple[int, str, Any, Any]] = []
    for index, call in enumerate(calls):
        owner = setup()
        owner.faults.nth = len(owner.faults.calls) + index
        step(owner)
        owner.run_queue()
        assert owner.faults.failed == [call], (index, call, owner.faults.failed)
        first = move_to_top(owner)
        recover(owner)
        second = move_to_top(owner)
        allowed = (expected, None) if call == "DataModel installed" else (expected,)
        if first not in (expected, None) or second not in allowed:
            broken.append((index, call, first, second))
        elif owner.rows != owner.book.rows():
            broken.append((index, call, "rows", owner.book.rows()))
    return broken


def rename_echo(owner: Any) -> None:
    owner.book.rename("Echo", "Kilo")
    changed(owner)
    owner.retry(limit=1)


def test_every_failed_call_of_a_rebuild_leaves_no_partial_pick() -> None:
    """Case 1 and its siblings: a refresh that replaces the nodes writes Bravo with the cursor on
    the unpicked Delta. Failing `clearSelection` right after Delta's `select` left Delta selected,
    and Move to Top moved it."""
    assert sweep(lambda: bravo_with_cursor_on("Delta"), rename_echo, ["Bravo"]) == []


def test_every_failed_call_of_a_key_write_leaves_no_partial_pick() -> None:
    """Case 7: Ctrl+Down to the unpicked Hotel writes Hotel's `select`, then `clearSelection`,
    then Bravo's `addSelection`. A failed clear left Hotel selected for the intake to take."""
    assert (
        sweep(lambda: bravo_with_cursor_on("Golf"), lambda o: key(o, DOWN, MOD1), ["Bravo"]) == []
    )


def test_every_failed_call_of_a_moved_single_pick_leaves_no_partial_pick() -> None:
    """Down moves the only pick from Bravo to Charlie; a failed `select` left Bravo selected,
    and the intake took the pick the key had just replaced."""

    def setup() -> Any:
        owner = sheet_list(Book(list(NAMES)))
        click(owner, 1)
        return owner

    assert sweep(setup, lambda o: key(o, DOWN), ["Charlie"]) == []


def three_picks() -> Any:
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    for _ in range(2):
        key(owner, DOWN, MOD1)
        key(owner, SPACE, MOD1)
    assert picks(owner) == ["Bravo", "Charlie", "Delta"]
    return owner


def test_every_failed_call_of_a_write_with_several_picks_leaves_no_partial_pick() -> None:
    """A failed `addSelection` left part of the picks for the intake: a smaller set of sheets."""
    assert sweep(three_picks, rename_echo, ["Bravo", "Charlie", "Delta"]) == []


def test_every_failed_call_of_a_lost_proof_clear_leaves_no_dropped_pick() -> None:
    """A replacement drops every pick; a failed clear left Bravo for the intake to take back."""

    def replace(owner: Any) -> None:
        owner.book.replace("Bravo")
        changed(owner)
        owner.retry(limit=1)

    def setup() -> Any:
        owner = sheet_list(Book(list(NAMES)))
        click(owner, 1)
        return owner

    owner = setup()
    replace(owner)
    assert picks(owner) == [] and move_to_top(owner) is None
    for index in range(len(owner.faults.calls)):
        owner = setup()
        start = len(owner.faults.calls)
        owner.faults.nth = start + index
        replace(owner)
        if not owner.faults.failed:
            break  # Past the step's last call.
        assert move_to_top(owner) is None, owner.faults.failed
        recover(owner)
        assert move_to_top(owner) is None, owner.faults.failed
        assert owner.tree.shown() == []


def test_case_1_a_failed_clear_in_a_rebuild_does_not_pick_the_cursor() -> None:
    owner = bravo_with_cursor_on("Delta")
    owner.faults.fail("clearSelection")
    rename_echo(owner)
    assert owner.faults.failed == ["clearSelection"]
    recover(owner)
    assert move_to_top(owner) == ["Bravo"]
    assert owner.book.names()[0] == "Bravo"


def test_case_2_a_failed_model_assignment_after_a_lost_proof_keeps_no_old_selection() -> None:
    """An assistive pick of Delta awaits intake; others rename Delta to Temp and Echo to Delta,
    which loses the proof without moving the generation, and the new model is refused. The
    intake took the old row named Delta under the handle of the sheet now named Delta."""
    owner, _, echo = renamed_window(assistive="Delta")
    assert move_to_top(owner) is None
    recover(owner)
    assert move_to_top(owner) is None
    assert owner.book.sheets[0] is not echo and owner.book.names()[3:5] == ["Temp", "Delta"]


def test_case_3_a_failed_write_outside_a_refresh_is_retried() -> None:
    """Ctrl+Space adds Delta; the key's write fails at Bravo's `addSelection`. Nothing retried
    it, so the tree showed only Delta until the next input, and the intake took that."""
    owner = bravo_with_cursor_on("Delta")
    owner.faults.fail("addSelection")
    key(owner, SPACE, MOD1)
    assert owner.faults.failed == ["addSelection"]
    assert owner.timers, "No retry was scheduled"
    owner.retry()
    owner.run_queue()
    assert owner.tree.shown() == ["Bravo", "Delta"]
    assert move_to_top(owner) == ["Bravo", "Delta"]


def test_a_failed_repaint_after_a_complete_write_keeps_accessible_input() -> None:
    """Case 3's repaint alone: the tree and the list agree, so an assistive pick still counts."""
    owner = bravo_with_cursor_on("Delta")
    owner.faults.fail("invalidate")
    key(owner, SPACE, MOD1)
    assert owner.faults.failed == ["invalidate"]
    assert owner.tree.shown() == ["Bravo", "Delta"]
    owner.tree.assistive_select("Foxtrot")
    assert move_to_top(owner) == ["Bravo", "Delta", "Foxtrot"]


def colour_bravo(owner: Any) -> None:
    owner.book.sheet("Bravo").color = 0x336699
    changed(owner)
    owner.retry(limit=1)


def test_case_4_a_model_installed_before_its_setter_failed_does_not_stall_the_retries() -> None:
    """The setter shows the new model and then raises: the list keeps the old nodes, which
    LibreOffice's `getNodeRect` refuses, and every retry failed reading the scroll position."""
    owner = bravo_with_cursor_on("Delta")
    owner.faults.fail("DataModel installed")
    colour_bravo(owner)
    assert owner.faults.failed == ["DataModel installed"]
    recover(owner)
    assert owner.rows == owner.book.rows(), "The retried refresh never showed the colour"
    assert not owner._refreshes.stale
    assert move_to_top(owner) in (["Bravo"], None)


def renamed_window(assistive: str | None = None) -> tuple[Any, Any, Any]:
    """Others renamed Delta to Temp and Echo to Delta, and the refresh's model was refused."""
    owner = sheet_list(Book(list(NAMES)))
    delta, echo = owner.book.sheet("Delta"), owner.book.sheet("Echo")
    if assistive is not None:
        owner.tree.assistive_select(assistive)
    owner.book.rename("Delta", "Temp")
    owner.book.rename("Echo", "Delta")
    owner.faults.fail("DataModel")
    changed(owner)
    owner.retry(limit=1)
    assert owner.faults.failed == ["DataModel"]
    assert owner.names()[3:5] == ["Delta", "Echo"], "The old rows are still shown"
    return owner, delta, echo


def test_case_5_keys_on_rows_left_by_a_failed_rebuild_do_not_reach_the_renamed_sheet() -> None:
    """Down from the initial cursor reaches the row that showed Delta; its name now belongs to
    the former Echo, and Move to Top moved that sheet. That row's own handle names Temp now,
    so the pick drops out."""
    owner, _, echo = renamed_window()
    for _ in range(3):
        key(owner, DOWN)
    assert all(ref.token.sheet is not echo for ref in owner._selection.picked)
    assert move_to_top(owner) is None
    assert owner.book.sheets[0] is not echo


def test_case_5_a_right_press_and_a_focus_event_keep_the_sheet_the_row_showed() -> None:
    owner, delta, _ = renamed_window()
    press(owner, 3, RIGHT)
    target = owner._context_target
    assert target is not None and target.name == "Delta"
    assert target.token.sheet is delta, "The menu would act on the sheet that took the name"
    owner._context_target = None
    owner.run_queue()
    focus_event(owner, 3)
    assert owner._selection.cursor.token.sheet is delta


def test_265_an_assistive_pick_made_before_a_replacement_is_not_taken_after_it() -> None:
    """Steps of #265: click Bravo and unpick it, replace Bravo, select Charlie through
    accessibility, replace Charlie before the intake. The intake took the replacement."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    key(owner, SPACE, MOD1)
    assert picks(owner) == []
    owner.book.replace("Bravo")
    changed(owner)
    owner.retry(limit=1)
    owner.run_queue()
    owner.tree.assistive_select("Charlie")
    replacement = owner.book.replace("Charlie")
    notices = len(owner.notices)
    changed(owner)
    owner.retry(limit=1)
    assert move_to_top(owner) is None
    assert owner.book.sheets[0] is not replacement
    owner.run_queue()
    assert owner.tree.shown() == []
    assert len(owner.notices) == notices + 1, "Clearing the user's selection is not explained"


def test_a_stale_native_selection_is_cleared_after_the_tab_baseline() -> None:
    """The clear that #265 needs is a native write `main` did not make. If it fails, the
    refresh has already taken Calc's tabs as its baseline (#243's third review)."""
    owner = sheet_list(Book(list(NAMES)))
    owner.tree.assistive_select("Charlie")
    owner.book.replace("Charlie")
    owner.faults.fail("clearSelection")
    changed(owner)
    owner.retry(limit=1)
    assert owner.faults.failed == ["clearSelection"]
    assert owner._tabs.baselines[-1] == owner.book.generation
    assert move_to_top(owner) is None
    recover(owner)
    assert owner.tree.shown() == [] and move_to_top(owner) is None


def test_a_lost_proof_over_an_empty_tree_writes_nothing() -> None:
    """No redundant clear: one failing would be a failure `main` cannot have (#243, #236)."""
    owner = sheet_list(Book(list(NAMES)))
    owner.book.replace("Delta")
    start = len(owner.faults.calls)
    changed(owner)
    owner.retry(limit=1)
    assert "clearSelection" not in owner.faults.calls[start:]


def test_a_command_while_the_tree_may_show_another_selection_acts_on_none() -> None:
    """After a failed key write the tree shows Hotel alone; the user clears it through
    accessibility and presses Move to Top before any retry. The tree showed nothing, so
    nothing moves; Bravo, hidden by the failure, is not moved either."""
    owner = bravo_with_cursor_on("Golf")
    owner.faults.fail("clearSelection")
    key(owner, DOWN, MOD1)
    assert owner.tree.shown() == ["Hotel"]
    owner.tree.assistive_clear()
    assert move_to_top(owner) is None
    assert owner.book.names()[:2] == ["Alfa", "Bravo"]


@pytest.mark.parametrize(
    "call,after,first",
    [
        ("getModel", 0, ["Bravo"]),  # Before any selection call: the tree still shows Bravo.
        ("SelectionType", 0, ["Bravo"]),
        ("SelectionType", 1, ["Bravo"]),  # Restoring MULTI, after `select` showed every pick.
        ("select", 0, ["Bravo"]),  # It can leave Bravo alone or nothing: never another sheet.
    ],
)
def test_a_repeated_write_that_fails_keeps_the_picks_it_already_shows(
    call: str, after: int, first: list[str] | None
) -> None:
    """A write of the one pick the tree already shows, as a right press or a menu queues."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    owner.faults.fail(call, after=after)
    owner._queue_selection()
    owner.run_queue()
    assert owner.faults.failed == [call]
    assert move_to_top(owner) == first
    recover(owner)
    assert move_to_top(owner) == ["Bravo"]


def test_a_moved_single_pick_is_shown_once_its_row_is_selected() -> None:
    """Down moves the only pick to Charlie; restoring multiple selection fails after Charlie's
    `select`. The tree already shows the picks, so Move to Top moves Charlie at once."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    owner.faults.fail("SelectionType", after=1)
    key(owner, DOWN)
    assert owner.faults.failed == ["SelectionType"] and owner.tree.shown() == ["Charlie"]
    assert move_to_top(owner) == ["Charlie"]


def test_a_failed_clear_of_an_empty_tree_keeps_accessible_input() -> None:
    """With nothing picked, a write can only clear: if it fails, the tree is empty either way,
    so an assistive pick made afterwards is the user's, as on `main`."""
    owner = sheet_list(Book(list(NAMES)))
    owner.faults.fail("clearSelection")
    owner._queue_selection()
    owner.run_queue()
    assert owner.faults.failed == ["clearSelection"]
    owner.tree.assistive_select("Charlie")
    assert move_to_top(owner) == ["Charlie"]


def test_a_failed_type_ahead_write_does_not_bring_back_the_picks_it_replaced() -> None:
    """Typing "d" picks Delta alone, but its `select` fails and the tree still shows Bravo.
    Adding Foxtrot through accessibility then made Move to Top move Bravo and Foxtrot."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    owner.faults.fail("select")
    with pytest.raises(NativeFailure):
        owner.type_ahead("d")  # Posted by the key handler; a failure ends that work.
    assert picks(owner) == ["Delta"] and owner.tree.shown() == ["Bravo"]
    assert owner.timers, "No retry was scheduled"
    owner.tree.assistive_select("Foxtrot")
    assert move_to_top(owner) is None
    recover(owner)
    assert move_to_top(owner) == ["Delta"]


def test_a_partly_shown_native_selection_is_not_taken() -> None:
    """A rebuild shows a pending accessibility pick of Charlie and Delta again; adding Delta
    fails, so the tree shows Charlie alone, and the intake took that smaller set."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    owner.tree.assistive_only("Charlie")
    owner.tree.assistive_select("Delta")
    owner.faults.fail("addSelection", after=1)
    colour_bravo(owner)
    assert owner.faults.failed == ["addSelection"]
    owner.run_queue()
    assert move_to_top(owner) in (None, ["Charlie", "Delta"])
    recover(owner)
    assert move_to_top(owner) in (["Bravo"], ["Charlie", "Delta"])


def test_a_failed_model_assignment_keeps_a_newer_accessible_pick() -> None:
    """#236's sixth review, finding 2: the old model is still installed and correct, so an
    assistive pick made before the retry is the user's."""
    owner = bravo_with_cursor_on("Delta")
    owner.faults.fail("DataModel")
    owner.book.sheet("Delta").protected = True
    changed(owner)
    owner.retry(limit=1)
    assert owner.faults.failed == ["DataModel"]
    owner.tree.assistive_only("Charlie")
    recover(owner)
    assert move_to_top(owner) == ["Charlie"]


def test_an_own_rename_keeps_its_picks_across_a_failed_rebuild() -> None:
    """The list's own verified rename carries its picks; a refused model must not drop them."""
    owner = bravo_with_cursor_on("Delta")
    owner.book.rename("Bravo", "Mike")
    owner.faults.fail("DataModel")
    with pytest.raises(NativeFailure):
        owner.refresh({"Bravo": "Mike"})  # As `_rename` refreshes after its verified rename.
    assert picks(owner) == ["Mike"]
    recover(owner)
    assert picks(owner) == ["Mike"] and owner.tree.shown() == ["Mike"]
    assert move_to_top(owner) == ["Mike"]


@pytest.mark.parametrize("fault", ["clearSelection", "invalidate", None])
def test_retries_after_a_failed_write_are_bounded(fault: str | None) -> None:
    """A write that keeps failing is retried as a failed refresh is, then left to new input."""
    owner = bravo_with_cursor_on("Golf")
    if fault is not None:
        owner.faults.fail(fault, times=100)
    key(owner, DOWN, MOD1)
    ran = owner.retry(limit=50)
    assert ran <= 6
    assert not owner.timers or all(timer.cancelled for timer in owner.timers)
