"""Tree writes that fail partway, and native picks made against an earlier proof (#257, #265).

The real list runs over the simulated peer of `list_peer`, with one native call made to fail. No
native trigger is known for these failures; LibreOffice's tree calls have failed in practice
only while the control was being disposed. Each sequence ends with the next command, Move to Top
through the list's own handler, and the invariant is the one the safety rules state: a command
acts on exactly the sheets the user picked last, or on none. A selection made through
accessibility counts as picked: neither part of a write nor older picks may replace it.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.unit.list_peer import (
    DOWN,
    MOD1,
    RIGHT,
    SHIFT,
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
    release,
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


def failing_each_call(
    setup: Callable[[], Any], step: Callable[[Any], None]
) -> Iterator[tuple[int, str, Any]]:
    """Each native call that `step` makes, made to fail in turn on a fresh `setup()`.

    Yields the call's index and name, and the list after the step and its posted work, before
    any retry. The peer's checkpoints after an effect ("select done" and the like) count as
    calls here, so a call is also failed after it changed the tree.
    """
    owner = setup()
    start = len(owner.faults.calls)
    step(owner)
    calls = owner.faults.calls[start:]
    assert calls, "The step made no native call"
    for index, call in enumerate(calls):
        owner = setup()
        owner.faults.nth = len(owner.faults.calls) + index
        step(owner)
        owner.run_queue()
        assert owner.faults.failed == [call], (index, call, owner.faults.failed)
        yield index, call, owner


def sweep(
    setup: Callable[[], Any], step: Callable[[Any], None], expected: list[str]
) -> list[tuple[int, str, Any, Any, Any]]:
    """Fail each native call that `step` makes, in turn, then press Move to Top twice.

    The first press comes at once, before any retry, and the second after the retries. What
    the tree shows just after the failure decides them. If it shows exactly `expected`, the
    second press moves exactly those sheets, and the first moves them too or refuses, as when
    the failed refresh left a rename unread. If it shows anything else, the list cannot tell
    part of its write from a selection made since, such as through accessibility, so both
    refuse, and the picks are dropped and the tree cleared (#257). Returns the calls whose
    sequence broke the rule.
    """
    broken: list[tuple[int, str, Any, Any, Any]] = []
    for index, call, owner in failing_each_call(setup, step):
        shown = owner.tree.shown()
        want = expected if shown == expected else None
        first = move_to_top(owner)
        recover(owner)
        second = move_to_top(owner)
        if first not in (want, None) or second != want:
            broken.append((index, call, shown, first, second))
        elif want is None and (picks(owner) or owner.tree.shown()):
            broken.append((index, call, shown, picks(owner), owner.tree.shown()))
        elif owner.rows != owner.book.rows():
            broken.append((index, call, shown, "rows", owner.book.rows()))
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
    """The tree shows the unpicked cursor's row Delta alone. That could also be a selection
    made since through accessibility, so the list takes neither Delta nor Bravo back: it drops
    the picks, says so, and clears the tree."""
    owner = bravo_with_cursor_on("Delta")
    notices = len(owner.notices)
    owner.faults.fail("clearSelection")
    rename_echo(owner)
    assert owner.faults.failed == ["clearSelection"]
    assert owner.tree.shown() == ["Delta"]
    recover(owner)
    assert move_to_top(owner) is None
    assert owner.book.names()[:4] == ["Alfa", "Bravo", "Charlie", "Delta"]
    assert picks(owner) == [] and owner.tree.shown() == []
    assert cursor(owner) == "Delta", "The cursor still proves its sheet"
    assert len(owner.notices) == notices + 1


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
    it, so the tree showed only Delta until the next input, and the intake took that. The
    retry now settles it: the tree does not show the picks, so they are dropped and cleared."""
    owner = bravo_with_cursor_on("Delta")
    owner.faults.fail("addSelection")
    key(owner, SPACE, MOD1)
    assert owner.faults.failed == ["addSelection"]
    assert owner.tree.shown() == ["Delta"]
    assert owner.timers, "No retry was scheduled"
    owner.retry()
    owner.run_queue()
    assert owner.tree.shown() == [] and picks(owner) == []
    assert move_to_top(owner) is None


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
    notices = len(owner.notices)
    owner.faults.fail("clearSelection")
    changed(owner)
    owner.retry(limit=1)
    assert owner.faults.failed == ["clearSelection"]
    assert owner._tabs.baselines[-1] == owner.book.generation
    assert move_to_top(owner) is None
    recover(owner)
    assert owner.tree.shown() == [] and move_to_top(owner) is None
    assert len(owner.notices) == notices + 1, "The clearing is told once, not again on settling"


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
    assert move_to_top(owner) is None
    assert owner.book.names()[:2] == ["Alfa", "Bravo"] and owner.tree.shown() == []


def test_a_partly_shown_native_selection_is_not_taken() -> None:
    """A rebuild shows a pending accessibility pick of Charlie and Delta again; adding Delta
    fails, so the tree shows Charlie alone, and the intake took that smaller set. The picks it
    replaced, Bravo, must not come back either: the user selected Charlie and Delta last."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    owner.tree.assistive_only("Charlie")
    owner.tree.assistive_select("Delta")
    notices = len(owner.notices)
    owner.faults.fail("addSelection", after=1)
    colour_bravo(owner)
    assert owner.faults.failed == ["addSelection"]
    owner.run_queue()
    assert owner.tree.shown() == ["Charlie"]
    assert move_to_top(owner) is None
    recover(owner)
    assert move_to_top(owner) is None
    assert owner.book.names()[:4] == NAMES[:4] and owner.tree.shown() == []
    assert len(owner.notices) == notices + 1, "Clearing the user's selection is not explained"


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


def echo_then_assistive(selected: list[str]) -> Callable[[], Any]:
    """Echo picked by a click, the cursor on the unpicked Foxtrot, and then `selected` made
    through accessibility, waiting for the intake; an empty `selected` clears the tree."""

    def setup() -> Any:
        owner = sheet_list(Book(list(NAMES)))
        click(owner, 4)
        key(owner, DOWN, MOD1)
        if selected:
            owner.tree.assistive_only(selected[0])
            for name in selected[1:]:
                owner.tree.assistive_select(name)
        else:
            owner.tree.assistive_clear()
        return owner

    return setup


def colour_golf(owner: Any) -> None:
    owner.book.sheet("Golf").color = 0x993366
    changed(owner)
    owner.retry(limit=1)


@pytest.mark.parametrize("call", ["SelectionType", "getModel"])
def test_a_pending_assistive_clear_is_not_undone_by_a_failed_rebuild(call: str) -> None:
    """Review finding 1: Echo picked, the cursor on Foxtrot, and the selection cleared through
    accessibility. A colour rebuild's write failed before its first selection call; the list
    recorded the new model's empty tree as written, and Move to Top moved Echo at once."""
    owner = echo_then_assistive([])()
    owner.faults.fail(call, after=1 if call == "getModel" else 0)  # After the model's own.
    colour_golf(owner)
    assert owner.faults.failed == [call]
    assert move_to_top(owner) is None
    recover(owner)
    assert move_to_top(owner) is None
    assert owner.book.names()[:5] == NAMES[:5] and picks(owner) == []


def test_a_failed_rebuild_write_leaves_no_pick_the_tree_does_not_show() -> None:
    """The same without accessibility: the head moved Echo while the tree showed nothing
    selected. The tree does not show the picks, so they are dropped, with the notice."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 4)
    key(owner, DOWN, MOD1)
    notices = len(owner.notices)
    owner.faults.fail("SelectionType")
    colour_golf(owner)
    assert owner.faults.failed == ["SelectionType"] and owner.tree.shown() == []
    assert move_to_top(owner) is None
    recover(owner)
    assert move_to_top(owner) is None
    assert owner.book.names()[:5] == NAMES[:5] and len(owner.notices) == notices + 1


@pytest.mark.parametrize("selected", [[], ["Charlie"], ["Charlie", "Delta"]])
def test_every_failed_call_of_a_rebuild_keeps_a_pending_assistive_selection_over_the_picks(
    selected: list[str],
) -> None:
    """Fail each native call of a colour rebuild while an accessibility selection waits for the
    intake. Without a failure Move to Top acts on that selection; with one, it acts on that
    selection or on none, never on Echo, the pick the user replaced."""
    setup = echo_then_assistive(selected)
    control = setup()
    colour_golf(control)
    assert move_to_top(control) == (selected or None)
    allowed = (selected or None, None)
    broken: list[tuple[int, str, Any, Any]] = []
    for index, call, owner in failing_each_call(setup, colour_golf):
        first = move_to_top(owner)
        recover(owner)
        second = move_to_top(owner)
        if first not in allowed or second not in allowed:
            broken.append((index, call, first, second))
    assert broken == []


def test_an_assistive_pick_shown_again_in_full_before_a_failure_is_not_replaced() -> None:
    """Review finding 2: Alfa picked, Echo selected through accessibility; a colour rebuild
    shows Echo again, and that `addSelection` fails after its effect. The tree showed Echo, yet
    the retry wrote Alfa back and Move to Top moved it."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 0)
    owner.tree.assistive_only("Echo")
    owner.faults.fail("addSelection done")
    colour_golf(owner)
    assert owner.faults.failed == ["addSelection done"] and owner.tree.shown() == ["Echo"]
    assert move_to_top(owner) is None
    recover(owner)
    assert move_to_top(owner) is None
    assert owner.book.names() == NAMES and owner.tree.shown() == []


def test_a_pending_assistive_pick_shown_again_is_taken_if_only_the_repaint_fails() -> None:
    """The control: the re-shown selection is complete when only its repaint fails, so the
    intake takes it as the user's, as `main` does."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 0)
    owner.tree.assistive_only("Echo")
    owner.faults.fail("invalidate", after=1)  # The rebuild's own repaint succeeds.
    colour_golf(owner)
    assert owner.faults.failed == ["invalidate"] and owner.tree.shown() == ["Echo"]
    assert move_to_top(owner) == ["Echo"]


def subset_after_failed_write(owner: Any) -> None:
    """Bravo, Charlie and Delta picked; Ctrl+Down to the unpicked Echo, and the write's last
    `addSelection` fails, so the tree shows Bravo and Charlie; then Bravo alone is selected
    through accessibility."""
    owner.faults.fail("addSelection", after=2)
    key(owner, DOWN, MOD1)
    assert owner.faults.failed == ["addSelection"]
    owner.tree.assistive_only("Bravo")


def select_golf(owner: Any) -> None:
    owner.tree.assistive_only("Golf")


def clear_tree(owner: Any) -> None:
    owner.tree.assistive_clear()


@pytest.mark.parametrize(
    "after",
    [pytest.param(select_golf, id="another row"), pytest.param(clear_tree, id="cleared")],
)
def test_an_assistive_selection_after_a_failed_write_is_not_replaced_by_older_picks(
    after: Callable[[Any], None],
) -> None:
    """Review finding 2, made after: Bravo picked, Ctrl+Down's write fails at its clear, so the
    tree shows the cursor's row Delta; then the user selects through accessibility. The list
    wrote Bravo back and moved it. It cannot tell this selection from part of its write, so it
    takes neither: it drops the picks, with the notice, and acts on none."""
    owner = bravo_with_cursor_on("Charlie")
    owner.faults.fail("clearSelection")
    key(owner, DOWN, MOD1)
    assert owner.faults.failed == ["clearSelection"] and owner.tree.shown() == ["Delta"]
    notices = len(owner.notices)
    after(owner)
    assert move_to_top(owner) is None
    recover(owner)
    assert move_to_top(owner) is None
    assert owner.book.names() == NAMES and owner.tree.shown() == []
    assert len(owner.notices) == notices + 1


def test_an_assistive_selection_of_exactly_the_picks_after_a_failed_write_is_acted_on() -> None:
    """The control: selecting Bravo alone through accessibility leaves the tree showing exactly
    the picks, which the user then sees and chose last, so Move to Top moves Bravo at once."""
    owner = bravo_with_cursor_on("Charlie")
    owner.faults.fail("clearSelection")
    key(owner, DOWN, MOD1)
    owner.tree.assistive_only("Bravo")
    assert move_to_top(owner) == ["Bravo"]


def test_an_assistive_subset_after_a_failed_write_does_not_bring_back_the_whole_set() -> None:
    owner = three_picks()
    subset_after_failed_write(owner)
    assert move_to_top(owner) is None
    recover(owner)
    assert move_to_top(owner) is None
    assert owner.book.names() == NAMES


def test_an_assistive_pick_after_a_failed_lost_proof_clear_is_not_taken() -> None:
    """#265's clear fails, then Echo is selected through accessibility: neither the replaced
    Charlie nor Echo is taken; the next write clears the tree."""
    owner = sheet_list(Book(list(NAMES)))
    owner.tree.assistive_only("Charlie")
    replacement = owner.book.replace("Charlie")
    owner.faults.fail("clearSelection")
    changed(owner)
    owner.retry(limit=1)
    assert owner.faults.failed == ["clearSelection"]
    owner.tree.assistive_only("Echo")
    assert move_to_top(owner) is None
    recover(owner)
    assert move_to_top(owner) is None
    assert owner.book.sheets[0] is not replacement and owner.tree.shown() == []


def multi_pick_shown() -> Any:
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    key(owner, DOWN, MOD1)
    key(owner, DOWN, MOD1)
    key(owner, SPACE, MOD1)
    assert owner.tree.shown() == ["Bravo", "Delta"]
    return owner


def bravo() -> Any:
    return bravo_with_cursor_on("Bravo")


def write_again(owner: Any) -> None:
    owner._queue_selection()


def down(owner: Any) -> None:
    key(owner, DOWN)


def shift_down(owner: Any) -> None:
    key(owner, DOWN, SHIFT)


@pytest.mark.parametrize(
    "setup,fault,step,expected",
    [
        pytest.param(
            multi_pick_shown,
            "select",
            write_again,
            ["Bravo", "Delta"],
            id="repeated write, select fails before any effect",
        ),
        pytest.param(
            bravo,
            "select done",
            down,
            ["Charlie"],
            id="moved single pick, select fails after its effect",
        ),
        pytest.param(
            bravo,
            "addSelection done",
            shift_down,
            ["Bravo", "Charlie"],
            id="range, the last addSelection fails after its effect",
        ),
    ],
)
def test_a_failed_write_that_left_the_tree_showing_the_picks_acts_at_once(
    setup: Callable[[], Any], fault: str, step: Callable[[Any], None], expected: list[str]
) -> None:
    """Review finding 3: the tree shows exactly the picks after the failure, so the next
    intake knows the record again and Move to Top acts without refusing first."""
    owner = setup()
    owner.faults.fail(fault)
    step(owner)
    owner.run_queue()
    assert owner.faults.failed == [fault] and owner.tree.shown() == expected
    assert owner._shown is None
    assert move_to_top(owner) == expected


def test_enter_while_the_tree_may_show_another_selection_acts_on_none() -> None:
    """`_current_picks`, behind Enter, the keyboard menu and drags, returns no picks while
    the record is still unknown after the intake, as when an owned write is still queued."""
    owner = bravo_with_cursor_on("Golf")
    owner.faults.fail("clearSelection")
    key(owner, DOWN, MOD1)
    assert owner._shown is None and owner.tree.shown() == ["Hotel"]
    owner._selection_write_pending = True  # A key's coalesced write, queued.
    assert owner._current_picks() == []
    assert owner.tree.shown() == ["Bravo"], "The picks are written for the next command"


def test_a_command_while_the_intake_waits_over_an_unknown_record_refuses_once() -> None:
    """`queue_move` reads the tree first, which settles an unknown record, so its own check of
    the record decides only while the intake waits, here for a queued write: the tree may still
    show part of the failed one, the cursor's row Hotel. The queued write shows the picks, and
    the next command acts on them."""
    owner = bravo_with_cursor_on("Golf")
    owner.faults.fail("clearSelection")
    key(owner, DOWN, MOD1)
    assert owner._shown is None and owner.tree.shown() == ["Hotel"]
    owner._queue_selection()  # A key's coalesced write, queued.
    assert move_to_top(owner) is None
    assert owner.tree.shown() == ["Bravo"], "The queued write showed the picks"
    assert move_to_top(owner) == ["Bravo"]


def test_a_held_press_over_a_lost_proof_keeps_its_native_row_from_the_intake() -> None:
    """A native press shows Bravo before its listener; Bravo is replaced under its own name.
    The refresh's clear and the queued write's clear both fail, and a drag then starts. The
    tree's Bravo row must not be taken for the replacement."""
    owner = sheet_list(Book(list(NAMES)))
    node = owner.tree.node("Bravo")
    owner.tree.selected, owner.tree.cursor = [node], node  # The native press, before its listener.
    press(owner, 1)  # The listener: the press is held, its write queued.
    replacement = owner.book.replace("Bravo")
    owner.faults.fail("clearSelection", times=2)
    with pytest.raises(NativeFailure):
        owner.refresh()
    owner.run_queue()  # The queued write; its clear fails too.
    assert owner.faults.failed == ["clearSelection", "clearSelection"]
    owner._press = None  # As `start_drag` begins.
    assert all(ref.token.sheet is not replacement for ref in owner._current_picks())


def test_an_own_batch_rename_keeps_its_picks_across_a_failed_rebuild() -> None:
    """Two of the list's own renames at once: a retry after the refused model compares with
    the renamed snapshot, which a plain refresh could not prove from the old one."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    key(owner, DOWN, MOD1)
    key(owner, DOWN, MOD1)
    key(owner, SPACE, MOD1)
    owner.book.rename("Bravo", "Mike")
    owner.book.rename("Delta", "November")
    owner.faults.fail("DataModel")
    with pytest.raises(NativeFailure):
        owner.refresh({"Bravo": "Mike", "Delta": "November"})
    recover(owner)
    assert picks(owner) == ["Mike", "November"]
    assert move_to_top(owner) == ["Mike", "November"]


def test_a_cleared_native_selection_over_followed_tabs_is_dropped_silently() -> None:
    """The picks follow Calc's tabs, not the user, and the tree's selection was cleared through
    accessibility. A lost proof then drops nothing the user picked or still sees: no notice."""
    owner = sheet_list(Book(list(NAMES)))
    owner.follow_tabs(["Bravo", "Charlie"], "Bravo")
    owner.run_queue()
    assert owner.tree.shown() == ["Bravo", "Charlie"] and not owner._user_picks
    owner.tree.assistive_clear()
    owner.book.replace("Delta")
    notices = len(owner.notices)
    changed(owner)
    owner.retry(limit=1)
    owner.run_queue()
    assert picks(owner) == [] and len(owner.notices) == notices


def test_a_failed_read_of_a_pending_assistive_pick_leaves_it_to_the_intake() -> None:
    """A refresh that keeps the rows reads a pending accessibility pick twice: its intake posts
    the take, and it reads the selection again for a rebuild or a lost proof. The second read
    failing ends the refresh before it changes anything, so the posted intake still takes it."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    owner.tree.assistive_only("Delta")
    owner.faults.fail("getSelection", after=1)
    with pytest.raises(NativeFailure):
        owner.refresh()
    assert owner.faults.failed == ["getSelection"]
    owner.run_queue()  # The deferred intake.
    assert move_to_top(owner) == ["Delta"]


@pytest.mark.parametrize(
    "assistive", [pytest.param(["Echo"], id="Echo"), pytest.param([], id="cleared")]
)
def test_a_kept_rows_refresh_leaves_a_waiting_assistive_selection_over_reordered_picks(
    assistive: list[str],
) -> None:
    """Review round two's plain-mode case, without any failure: Bravo and Delta are picked,
    and others move Delta to the top, so the picks' order differs from the rows'. A selection
    made through accessibility then waits for the intake. A refresh that keeps the rows wrote
    Bravo and Delta over it for that order, and Move to Top moved them; `main` shows the
    selection again. Kept rows still show it, so the refresh now leaves it to the intake."""
    owner = multi_pick_shown()
    owner.book.move("Delta", 0)
    changed(owner)
    owner.retry(limit=1)
    assert owner.tree.shown() == ["Delta", "Bravo"] and picks(owner) == ["Bravo", "Delta"]
    if assistive:
        owner.tree.assistive_only(assistive[0])
    else:
        owner.tree.assistive_clear()
    changed(owner)  # A change that keeps the rows, such as a cell edit.
    owner.retry(limit=1)
    owner.run_queue()
    assert owner.tree.shown() == assistive
    assert move_to_top(owner) == (assistive or None)


def bravo_left_unknown() -> Any:
    """Bravo picked, the cursor on Delta; a colour rebuild writes Bravo, and its last
    `addSelection` fails after its effect: the tree shows Bravo, the record is unknown."""
    owner = bravo_with_cursor_on("Delta")
    owner.faults.fail("addSelection done")
    colour_golf(owner)
    assert owner.faults.failed == ["addSelection done"] and owner.tree.shown() == ["Bravo"]
    assert owner._shown is None
    return owner


def sample_tabs(owner: Any) -> None:
    """The tab observer's sample, which asks for the intake (`pending_native_picks`)."""
    owner._take_tree_selection(paint=False, defer=True)
    owner.run_queue()


def test_rows_left_selected_after_dropped_picks_are_cleared_before_the_next_click() -> None:
    """Review round two's after-mode case: Charlie alone is selected through accessibility
    after the failure, and the tab sample's intake drops Bravo, with the notice. The tree kept
    showing Charlie until a later write, so a Ctrl+click meant to deselect it picked Charlie,
    which Move to Top then moved. The intake now queues the write that clears the tree, so that
    Ctrl+click selects Charlie on a tree that showed nothing, and Charlie is the user's pick."""
    owner = bravo_left_unknown()
    owner.tree.assistive_only("Charlie")
    notices = len(owner.notices)
    sample_tabs(owner)
    assert picks(owner) == [] and len(owner.notices) == notices + 1
    assert owner.tree.shown() == [], "A row the list does not hold stayed selected"
    assert owner._shown == () and cursor(owner) == "Delta"
    node = owner.tree.node("Charlie")
    owner.tree.selected = [*owner.tree.selected, node]  # The native Ctrl+press toggles it on.
    press(owner, 2, modifiers=MOD1)
    owner.run_queue()
    release(owner, 2)
    owner.run_queue()
    assert picks(owner) == ["Charlie"] and owner.tree.shown() == ["Charlie"]
    assert move_to_top(owner) == ["Charlie"]


def test_an_assistive_pick_after_picks_dropped_over_an_empty_tree_is_taken() -> None:
    """When the tree shows nothing after the failure, the intake drops the picks and the tree
    then shows exactly them, none: a selection made next through accessibility is the user's
    latest, and is taken rather than cleared by the retried write."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 4)
    key(owner, DOWN, MOD1)
    owner.faults.fail("SelectionType")
    colour_golf(owner)
    assert owner.faults.failed == ["SelectionType"] and owner.tree.shown() == []
    sample_tabs(owner)
    assert picks(owner) == [] and owner._shown == ()
    owner.tree.assistive_only("Delta")
    assert move_to_top(owner) == ["Delta"]
