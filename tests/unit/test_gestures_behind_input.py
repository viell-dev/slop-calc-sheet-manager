"""Drag gestures that come before their press's listener, behind other input (#304, #318).

VCL recognizes a drag gesture within its handling of the pointer's motion (#264), so the gesture
can come before its press's queued listener (#269). The gesture then carries the list's record of
the picks, or the tree's selection when the intake can take it. The record held other picks than
the sheet the user pressed when a selection key or type-ahead had picked before the press and its
write showed that pick after it, when an earlier click's listener ran between the press and the
gesture, and when the press's listener failed before it decided the press: the drag carried those
picks, and a drop moved them. No drag starts then.

- A plain cursor key, a Ctrl key that moves the cursor and type-ahead's jump hold range presses
  until work posted once a write has shown the cursor has run (#313, #326), and a key's picks
  that the tree does not show yet hold toggles until that write (#288). While such a hold waits
  for its write, or for its posted end, no drag starts, as while presses are held (#295).
- A plain press handled while toggles are held picks its row alone rather than keep the other
  picks for a drag: the tree may not have shown them when it handled the press.
- While a write of the picks is pending, the intake takes nothing, so the gesture would carry the
  record: none starts unless every change of the tree counted so far is accounted for (#294), as
  after the listener of this press when it ran first.
- A press whose listener failed, wherever the failure fell, is left undecided by the mouse
  listener's guard, so that neither the gesture nor the release acts on it (#318). Neither does
  the gesture of a press during which the list dropped every pick.

The real list runs over the simulated peer of `list_peer`, with `start_drag` bound and the
document's checks stubbed (`bind_drag`).
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.list_peer import (
    DOWN,
    END,
    HOME,
    LEFT,
    MOD1,
    SHIFT,
    SPACE,
    UP,
    A,
    Book,
    NativeFailure,
    bind_drag,
    click,
    key,
    listen,
    native_press,
    picks,
    queued_click,
    release,
    sheet_list,
    toggle_natively,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]


def row(name: str) -> int:
    return NAMES.index(name)


def clicked(name: str) -> tuple[Any, list[list[str]]]:
    owner = sheet_list(Book(list(NAMES)))
    dragged = bind_drag(owner)
    click(owner, row(name))
    assert picks(owner) == [name] == owner.tree.shown()
    return owner, dragged


def run_until(owner: Any, where: str) -> None:
    """Run the posted work up to and including the next item posted as `where`."""
    while owner.queue:
        work, posted = owner.queue.pop(0)
        work()
        if posted == where:
            return
    raise AssertionError(f"nothing posted as {where!r}")


def typed(owner: Any, char: str) -> None:
    """A character typed in the list: its key handler queues the type-ahead (`queue_input`),
    which runs when the queue next does."""
    code = A + ord(char) - ord("a")
    owner.key_handler.keyPressed(SimpleNamespace(KeyCode=code, Modifiers=0, KeyChar=char))


# A selection key's or type-ahead's pick (#304).


@pytest.mark.parametrize("written", [False, True], ids=["before-the-write", "after-the-write"])
@pytest.mark.parametrize(
    "keys,carried,after",
    [
        pytest.param([(DOWN, 0)], ["Charlie"], [["Delta"]], id="down"),
        pytest.param([(DOWN, SHIFT)], ["Bravo", "Charlie"], [["Delta"]], id="shift-down"),
        pytest.param([(DOWN, MOD1)], ["Bravo"], [["Delta"]], id="ctrl-down"),
        pytest.param(
            [(DOWN, MOD1 | SHIFT)], ["Bravo", "Charlie"], [["Delta"]], id="ctrl-shift-down"
        ),
        # The tree shows a toggle only at its write: the write that leaves it undone leaves the
        # record unknown, and no intake takes the tree (#307's `_unread`).
        pytest.param([(DOWN, MOD1), (SPACE, MOD1)], ["Bravo", "Charlie"], [], id="ctrl-space"),
        pytest.param([(A, MOD1)], NAMES, [["Delta"]], id="ctrl-a"),
    ],
)
def test_a_drag_across_a_selection_keys_write_drags_nothing(
    keys: list[tuple[int, int]], carried: list[str], after: list[list[str]], written: bool
) -> None:
    """Bravo picked; a selection key, after any keys shown before it, then a press on Delta's row
    and a drag before the press's listener, before or after the key's write. The gesture carried
    the key's picks, which the user did not press: before the write the intake takes nothing, and
    the write replaced the tree's Delta with them. Before the write no drag starts now. The write
    leaves the tree's Delta alone, since the press changed it after the key (#307), so after it
    the intake takes Delta and the drag carries the pressed sheet, or, after Ctrl+Space, nothing.
    The press's listener then decides the press."""
    owner, dragged = clicked("Bravo")
    *shown, (code, modifiers) = keys
    for earlier in shown:
        key(owner, *earlier)
    owner.tree_key(code, modifiers)
    native_press(owner, row("Delta"))
    if written:
        run_until(owner, "showing the selection")
    owner.start_drag(object())
    assert dragged == (after if written else []), f"dragged the key's picks, {carried}"
    owner.run_queue()
    assert "Delta" in picks(owner)


@pytest.mark.parametrize(
    "modifiers,shown",
    [pytest.param(0, ["Echo"], id="down"), pytest.param(SHIFT, ["Delta", "Echo"], id="shift-down")],
)
def test_a_drag_from_a_row_the_tree_showed_selected_across_a_keys_write_drags_nothing(
    modifiers: int, shown: list[str]
) -> None:
    """Bravo and Delta picked; Down or Shift+Down from Delta, then a press on Bravo's row, which
    the tree shows selected, so that it changes nothing until a drag or the release, and the
    key's write. That write is not left undone, since nothing changed after the key, and shows
    the key's picks over the selection the user pressed: a drag recognized before the press's
    listener carried them. It starts nothing while the hold waits for the write's posted end."""
    owner, dragged = clicked("Bravo")
    queued_click(owner, row("Delta"))
    owner.run_queue()
    owner.tree_key(DOWN, modifiers)
    press_keeping(owner, "Bravo")
    run_until(owner, "showing the selection")
    assert owner.tree.shown() == shown
    owner.start_drag(object())
    assert dragged == [], "dragged the key's picks, which the user did not press"


@pytest.mark.parametrize("written", [False, True], ids=["before-the-write", "after-the-write"])
def test_a_drag_across_a_ctrl_keys_write_that_moves_nothing_drags_the_pressed_sheet_or_nothing(
    written: bool,
) -> None:
    """Alfa picked; Ctrl+Home, which leaves the cursor and the anchor on Alfa and holds nothing,
    then a press on Delta and a drag before the press's listener. Before the key's write, the
    record still holds Alfa, which the intake cannot replace while the write is pending, and the
    press's own change is not accounted for yet: no drag starts. The write leaves the tree's
    Delta alone (#307), and the drag after it carries Delta."""
    owner, dragged = clicked("Alfa")
    owner.tree_key(HOME, MOD1)
    assert owner._ranges_held is None and owner._toggles_held is None
    native_press(owner, row("Delta"))
    if written:
        run_until(owner, "showing the selection")
    owner.start_drag(object())
    assert dragged == ([["Delta"]] if written else []), "dragged Alfa, not Delta"


@pytest.mark.parametrize("jumped", [False, True], ids=["before-the-jump", "after-the-jump"])
def test_a_drag_across_a_type_aheads_jump_drags_the_pressed_sheet_or_nothing(
    jumped: bool,
) -> None:
    """Bravo picked; "c" typed, then a press on Delta's row and a drag before the press's
    listener. Type-ahead jumps to Charlie in queued work and shows it at once, over the tree's
    Delta: a gesture after it dragged Charlie. It now starts nothing. One before the jump takes
    the tree's selection, which is the pressed sheet."""
    owner, dragged = clicked("Bravo")
    typed(owner, "c")
    native_press(owner, row("Delta"))
    if jumped:
        run_until(owner, "type-ahead")
    owner.start_drag(object())
    assert dragged == ([] if jumped else [["Delta"]])


def press_keeping(owner: Any, name: str) -> None:
    """A plain press as VCL's selection engine handles it: on a row the tree shows selected it
    changes nothing and waits for a drag (`SelectionEngine::SelMouseButtonDown`), and on another
    row it selects that row alone. Its listener is queued."""
    node = owner.tree.node(name)
    if node not in owner.tree.selected:
        owner.tree.selected = [node]
    owner.tree.cursor = node
    event = SimpleNamespace(
        Buttons=LEFT, X=0, Y=owner.tree.line(row(name)), Modifiers=0, ClickCount=1
    )
    owner.post(lambda: listen(owner, owner.mouse_pressed, event), "a mouse press")


def test_a_press_before_keys_write_does_not_keep_their_picks_for_a_drag() -> None:
    """Echo picked; Home and Shift+Down pick Alfa and Bravo, and the user presses Bravo, which the
    tree, still showing Echo, selects alone, before the keys' write. The press's listener ran
    after that write, found Bravo picked and kept Alfa for a drag, so a drag recognized once all
    of it had run carried Alfa, which the tree did not show selected when the user pressed. While
    toggles are held, the press picks its row alone."""
    owner, dragged = clicked("Echo")
    owner.tree_key(HOME, 0)
    owner.tree_key(DOWN, SHIFT)
    press_keeping(owner, "Bravo")
    owner.run_queue()
    assert picks(owner) == ["Bravo"] == owner.tree.shown()
    owner.start_drag(object())
    assert dragged == [["Bravo"]], "dragged Alfa, which the tree did not show selected"


def test_a_press_on_a_picked_row_after_the_keys_write_keeps_the_picks_for_a_drag() -> None:
    """Control: once the keys' write and its hold have ended, a press on a picked row keeps the
    other picks, and the drag carries them all."""
    owner, dragged = clicked("Echo")
    key(owner, HOME)
    key(owner, DOWN, SHIFT)
    assert picks(owner) == ["Alfa", "Bravo"] == owner.tree.shown()
    press_keeping(owner, "Bravo")
    owner.run_queue()
    owner.start_drag(object())
    assert dragged == [["Alfa", "Bravo"]]


@pytest.mark.parametrize(
    "picked,keys,pressed",
    [
        pytest.param(["Hotel"], [(END, SHIFT)], "Delta", id="shift-end-on-the-last-row"),
        pytest.param(["Hotel"], [(DOWN, MOD1 | SHIFT)], "Delta", id="ctrl-shift-down-at-the-end"),
        pytest.param(
            ["Charlie", "Delta"], [(UP, SHIFT)], "Foxtrot", id="shift-up-inside-the-picks"
        ),
    ],
)
def test_a_drag_across_the_write_of_a_key_that_holds_nothing_drags_the_pressed_sheet(
    picked: list[str], keys: list[tuple[int, int]], pressed: str
) -> None:
    """A key that leaves the picks as the tree shows them and holds no range presses, then a press
    on another row, the key's write and the gesture before the press's listener. The write showed
    the earlier picks over the press, and the drag carried them, on `main` and on #330 before
    #324. The press changed the tree after the key, so the write is left undone (#307), and the
    drag carries the pressed sheet (#330's review)."""
    owner, dragged = clicked(picked[0])
    for name in picked[1:]:
        queued_click(owner, row(name))
        owner.run_queue()
    for code, modifiers in keys:
        owner.tree_key(code, modifiers)
    assert picks(owner) == picked and owner._toggles_held is None and owner._ranges_held is None
    native_press(owner, row(pressed))
    run_until(owner, "showing the selection")
    owner.start_drag(object())
    assert dragged == [[pressed]], "dragged the earlier picks"


# An earlier click's listener between the press and the gesture (#304).


@pytest.mark.parametrize(
    "picked,earlier,modifiers,pressed",
    [
        pytest.param("Hotel", "Hotel", 0, "Golf", id="a-click-on-the-pick"),
        pytest.param("Delta", "Charlie", 0, "Bravo", id="a-click-on-another-row"),
        pytest.param("Delta", "Charlie", MOD1, "Bravo", id="a-ctrl-click"),
    ],
)
def test_a_drag_across_an_earlier_clicks_write_drags_the_pressed_sheet(
    picked: str, earlier: str, modifiers: int, pressed: str
) -> None:
    """A click whose listeners ran before the user pressed another row, then that click's write and
    the gesture before the press's listener. The write showed the click's picks over the press,
    and the drag carried them, on `main` and on #330 before #324. The press changed the tree after
    the click's listeners read the count, so the write is left undone (#307), and the drag
    carries the pressed sheet (#330's review)."""
    owner, dragged = clicked(picked)
    queued_click(owner, row(earlier), modifiers)
    run_until(owner, "a mouse release")
    native_press(owner, row(pressed))
    run_until(owner, "showing the selection")
    owner.start_drag(object())
    assert dragged == [[pressed]], "dragged the earlier click's picks"


@pytest.mark.parametrize(
    "listeners", ["a mouse press", "a mouse release"], ids=["its-press", "its-release"]
)
def test_a_drag_behind_an_earlier_clicks_listener_drags_nothing(listeners: str) -> None:
    """Bravo picked. The user clicks Alfa, then presses Delta and drags, all before the
    listeners run; Alfa's press listener, or that and its release's, runs before the gesture.
    It recorded Alfa and queued the write, so the intake took nothing, and the drag carried Alfa.
    The record cannot hold Delta's press while its change is unaccounted for: no drag starts."""
    owner, dragged = clicked("Bravo")
    queued_click(owner, row("Alfa"), 0)
    native_press(owner, row("Delta"))
    run_until(owner, listeners)
    owner.start_drag(object())
    assert dragged == [], "dragged Alfa, not Delta"


# A failed press listener (#318).


@pytest.mark.parametrize("written", [False, True], ids=["before-the-write", "after-the-write"])
def test_a_drag_after_a_failed_press_listener_drags_nothing(written: bool) -> None:
    """Bravo picked; a press on Delta's row, whose listener fails at its first native call, its
    read of where the rows show. The listener's guard queues the write of the picks. A drag before
    that write carried Bravo, the record, and one after it Bravo too, which the write had put back
    over the tree's Delta. The listener had decided nothing, so no drag starts; the release does
    nothing either. The native release selects Delta again after the write, a change newer than any
    input's, so the next write leaves it to the intake (#307), which takes Delta: the sheet the
    user clicked, and what the tree shows."""
    owner, dragged = clicked("Bravo")
    native_press(owner, row("Delta"))
    owner.faults.fail("getNodeRect")
    run_until(owner, "a mouse press")
    assert owner.failures == ["a mouse press"]
    if written:
        run_until(owner, "showing the selection")
        assert owner.tree.shown() == ["Bravo"]
    owner.start_drag(object())
    assert dragged == [], "dragged Bravo, not Delta"
    owner.run_queue()
    release(owner, row("Delta"))
    owner.run_queue()
    assert picks(owner) == ["Delta"] == owner.tree.shown()


def test_a_drag_after_a_press_listener_that_failed_after_deciding_drags_nothing() -> None:
    """Bravo and Delta picked and Hotel selected through accessibility; a Ctrl+press on Delta,
    which the tree deselects, and whose listener refuses it over Hotel's change. The refusal's
    post of the notice fails before the picks are dropped, so the listener had decided the press
    and kept Bravo and Delta, which the guard's write shows over the tree. Once that work and
    the toggle hold had ended, a drag carried them, Delta included, which the user had just
    deselected. The guard leaves the failed press undecided wherever the failure fell, and no
    drag starts (#330's review)."""
    owner, dragged = clicked("Bravo")
    queued_click(owner, row("Delta"))
    owner.run_queue()
    owner.tree.assistive_select("Hotel")
    post = owner.post

    def failing(work: Any, where: str) -> None:
        if where == "telling that the selection was cleared":
            raise NativeFailure("the notice's post")
        post(work, where)

    owner.post = failing
    toggle_natively(owner, row("Delta"))
    event = SimpleNamespace(
        Buttons=LEFT, X=0, Y=owner.tree.line(row("Delta")), Modifiers=MOD1, ClickCount=1
    )
    listen(owner, owner.mouse_pressed, event)
    owner.post = post
    assert owner.failures == ["a mouse press"]
    assert picks(owner) == ["Bravo", "Delta"], "the failure came before the picks were dropped"
    owner.run_queue()
    owner.start_drag(object())
    assert dragged == [], "dragged Delta, which the user had deselected"


def test_a_drag_from_a_press_during_which_every_pick_was_dropped_drags_nothing() -> None:
    """Bravo picked; a press on Delta, whose listener picks it, and then another window inserts a
    sheet, so the refresh cannot prove the sheets and drops every pick while the press is held,
    which voids it. Down, typed while the button is held, picks a row again, and once its write
    and holds have ended the gesture comes: it carried the key's pick, which the tree did not show
    when the user pressed. No drag starts for a voided press."""
    owner, dragged = clicked("Bravo")
    native_press(owner, row("Delta"))
    run_until(owner, "a mouse press")
    assert picks(owner) == ["Delta"]
    owner.book.insert("India", 0)
    owner.post(owner.refresh, "refreshing the sheet list")
    owner.run_queue()
    assert picks(owner) == [] and owner._press is not None and owner._press.voided
    owner.tree_key(DOWN, 0)
    owner.run_queue()
    assert picks(owner) and owner._ranges_held is None and owner._toggles_held is None
    owner.start_drag(object())
    assert dragged == [], "dragged the key's pick"


def test_a_click_after_a_failed_press_listener_acts() -> None:
    """Control: after the failed press's release, the next click picks its row, and a drag from
    it carries it."""
    owner, dragged = clicked("Bravo")
    native_press(owner, row("Delta"))
    owner.faults.fail("getNodeRect")
    owner.run_queue()
    release(owner, row("Delta"))
    owner.run_queue()
    click(owner, row("Echo"))
    assert picks(owner) == ["Echo"]
    native_press(owner, row("Echo"))
    owner.start_drag(object())
    assert dragged == [["Echo"]]


# Controls and costs.


def press_then(owner: Any, steps: Callable[[Any], None]) -> None:
    native_press(owner, row("Delta"))
    steps(owner)
    owner.start_drag(object())


def no_steps(owner: Any) -> None:
    pass


def listener(owner: Any) -> None:
    run_until(owner, "a mouse press")


def listener_and_write(owner: Any) -> None:
    owner.run_queue()


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(no_steps, id="before-the-listener"),
        pytest.param(listener, id="after-the-listener"),
        pytest.param(listener_and_write, id="after-the-write"),
    ],
)
def test_a_drag_drags_the_pressed_sheet(steps: Callable[[Any], None]) -> None:
    """Control: Bravo picked; a press on Delta and a drag, before the press's listener, after it
    and after its write: the drag carries Delta."""
    owner, dragged = clicked("Bravo")
    press_then(owner, steps)
    assert dragged == [["Delta"]]


def test_a_drag_after_keys_that_were_shown_drags_the_pressed_sheet() -> None:
    """Control: keys and a type-ahead whose writes and holds have ended hold no later drag."""
    owner, dragged = clicked("Bravo")
    key(owner, DOWN)
    key(owner, DOWN, MOD1)
    typed(owner, "e")
    owner.run_queue()
    assert owner._ranges_held is None and owner._toggles_held is None
    press_then(owner, no_steps)
    assert dragged == [["Delta"]]


def test_a_drag_of_a_ctrl_click_carries_the_picks_it_added_to() -> None:
    """Control: a Ctrl+click on Delta and a drag after its listener carry Bravo and Delta."""
    owner, dragged = clicked("Bravo")
    queued_click(owner, row("Delta"))
    run_until(owner, "a mouse press")
    owner.start_drag(object())
    assert dragged == [["Bravo", "Delta"]]


def test_a_drag_after_a_key_typed_while_the_button_is_held_drags_nothing() -> None:
    """Bravo picked; a press on Delta, whose listener picks it, and Down typed while the button is
    held, which picks Echo. The gesture before the key's write carried Echo, which the tree did
    not show when the user pressed; the key's holds refuse it."""
    owner, dragged = clicked("Bravo")
    native_press(owner, row("Delta"))
    run_until(owner, "a mouse press")
    owner.tree_key(DOWN, 0)
    assert picks(owner) == ["Echo"]
    owner.start_drag(object())
    assert dragged == [], "dragged the key's pick"


def test_a_plain_press_on_a_picked_row_during_a_range_hold_keeps_the_picks() -> None:
    """Control: Bravo and Delta picked; Ctrl+Down, which moves the cursor and holds range presses
    but leaves the picks as the tree shows them, so toggles are not held; a press on Bravo, which
    the tree shows selected, before the key's write. Its listener keeps both picks for a drag,
    and the drag after the writes carries them."""
    owner, dragged = clicked("Bravo")
    queued_click(owner, row("Delta"))
    owner.run_queue()
    owner.tree_key(DOWN, MOD1)
    assert owner._ranges_held is not None and owner._toggles_held is None
    press_keeping(owner, "Bravo")
    owner.run_queue()
    assert picks(owner) == ["Bravo", "Delta"]
    owner.start_drag(object())
    assert dragged == [["Bravo", "Delta"]]


def test_a_drag_whose_listener_ran_before_a_plain_keys_write_is_refused() -> None:
    """A cost: the user presses Delta, Down is typed before the press's listener, which runs
    before the key's write and picks Delta. The record holds the press, but the key's range hold
    lasts until its write: no drag starts."""
    owner, dragged = clicked("Bravo")
    native_press(owner, row("Delta"))
    owner.tree_key(DOWN, 0)
    run_until(owner, "a mouse press")
    assert picks(owner) == ["Delta"]
    owner.start_drag(object())
    assert dragged == []


def test_a_drag_after_a_shift_clicks_listener_before_its_write_is_refused() -> None:
    """A cost: Bravo picked, a Shift+click on Delta, and a drag after its press listener and
    before its write. The listener does not account for the Shift press's change, since the
    tree's range may not be the list's, so no drag starts until the write. After it, one does."""
    owner, dragged = clicked("Bravo")
    queued_click(owner, row("Delta"), SHIFT)
    run_until(owner, "a mouse press")
    owner.start_drag(object())
    assert dragged == []
    run_until(owner, "showing the selection")
    owner.start_drag(object())
    assert dragged == [["Bravo", "Charlie", "Delta"]]
