"""Presses whose rows a refresh changed before the list's mouse listener ran (#293).

The tree handles a press as soon as LibreOffice gets it, on the rows it shows then. The list's
mouse listener runs later, queued behind the work already posted (#269), and finds the pressed row
from the event's position in the rows the list shows when it runs. A refresh queued ahead of the
listener that changes which sheet a row shows, as after another window moved a sheet, put another
sheet at that position, and the listener acted on it: a plain click picked it, a Ctrl+click
toggled it, a Shift+click extended the range to it, a double click activated it, and a right click
opened the sheet tab menu for it. No failure is needed.

The real list runs over the simulated peer of `list_peer`, whose `queued_click` queues a click's
listeners as VCL does. The invariant: a press, its release and a double click act only on the
sheet the tree showed under the pointer when the user pressed, or refuse. A press on a row that
showed the same name in every row list since then acts; a refused left press picks nothing and
drops the picks, which its native effect superseded in the tree, with the notice; a refused right
press opens no menu and keeps the picks.
"""

from collections.abc import Callable
from typing import Any

import pytest

from tests.unit.list_peer import (
    MOD1,
    RIGHT,
    SHIFT,
    Book,
    NativeFailure,
    click,
    cursor,
    move_to_top,
    picks,
    press,
    queued_click,
    sheet_list,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]
# Delta's row. Once another window moves Charlie below Echo, it shows Echo.
PRESSED = NAMES.index("Delta")


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


def reorder(owner: Any) -> None:
    """Another window moves Charlie below Echo, and the list's refresh for it is queued: the
    rows become Alfa, Bravo, Delta, Echo, Charlie, ..., so Delta's row shows Echo."""
    owner.book.move("Charlie", row("Echo"))
    post_refresh(owner)


def recolour(owner: Any) -> None:
    """Another window colours Golf: the refresh rebuilds the rows, each in its place."""
    owner.book.sheet("Golf").color = 0x336699
    post_refresh(owner)


def switch(owner: Any) -> None:
    """Calc shows Hotel: the refresh rebuilds the rows to move the current-sheet arrow."""
    owner.book.active = owner.book.sheet("Hotel")
    post_refresh(owner)


def unchanged(owner: Any) -> None:
    """A refresh that finds the rows as they were."""
    post_refresh(owner)


def record_activations(owner: Any) -> list[str]:
    """The sheets a double click's posted activation is asked to activate (`_activate_pressed`)."""
    activated: list[str] = []
    owner._activate_pressed = lambda name, handle, generation: activated.append(handle.getName())
    return activated


def record_menus(owner: Any) -> list[str | None]:
    """The target of each sheet tab menu that a right click's release asks for (`_open_menu`)."""
    targets: list[str | None] = []

    def open_menu(x: int, y: int, refs: Any = None, seen: int | None = None) -> None:
        target = owner._context_target
        targets.append(None if target is None else target.token.getName())

    owner._open_menu = open_menu
    return targets


def refused(owner: Any, notices: int) -> None:
    """The press picked nothing, the picks went with the notice, and Move to Top refuses."""
    assert "Echo" not in picks(owner), "Echo, which the user never pressed, was picked"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


@pytest.mark.parametrize(
    "names, modifiers",
    [
        pytest.param(("Delta",), 0, id="plain click, meant to pick Delta"),
        pytest.param(("Delta",), MOD1, id="Ctrl+click, meant to deselect Delta"),
        pytest.param(("Bravo", "Delta"), MOD1, id="Ctrl+click, meant to deselect Delta of two"),
        pytest.param(("Bravo",), SHIFT, id="Shift+click, meant to pick Bravo to Delta"),
    ],
)
def test_a_reordering_refresh_before_a_presss_listener_acts_on_no_other_sheet(
    names: tuple[str, ...], modifiers: int
) -> None:
    """`names` picked; another window moves Charlie below Echo, and the refresh is queued; the
    user presses the row that still shows Delta. The refresh runs first and puts Echo there, and
    the listener acted on Echo, which the user never pressed: the plain click picked Echo, the
    Ctrl+click kept Delta and added Echo, and the Shift+click picked Bravo to Echo. Move to Top
    then moved Echo. The press now picks nothing, and the picks it superseded in the tree go with
    the notice."""
    owner = picked(*names)
    notices = len(owner.notices)
    reorder(owner)
    queued_click(owner, PRESSED, modifiers)
    owner.run_queue()
    refused(owner, notices)


def test_a_reordering_refresh_before_a_double_clicks_listeners_activates_nothing() -> None:
    """Delta clicked; another window moves Charlie below Echo, and the refresh is queued before
    the second click of the user's double click on Delta. The listeners picked and activated
    Echo, which the user never pressed. Nothing is activated now."""
    owner = picked("Delta")
    activated = record_activations(owner)
    notices = len(owner.notices)
    reorder(owner)
    queued_click(owner, PRESSED, 0, clicks=2)
    owner.run_queue()
    assert activated == []
    refused(owner, notices)


def test_a_reordering_refresh_before_a_right_clicks_listeners_opens_no_menu() -> None:
    """Delta picked; another window moves Charlie below Echo, and the refresh is queued before
    the user right-clicks Delta. The press listener made Echo the menu's target, and the menu's
    commands, Delete Sheet among them, would act on Echo. No menu opens now, and Delta stays
    picked."""
    owner = picked("Delta")
    targets = record_menus(owner)
    notices = len(owner.notices)
    reorder(owner)
    queued_click(owner, PRESSED, 0, button=RIGHT)
    owner.run_queue()
    assert targets == [None]
    assert picks(owner) == ["Delta"] and owner.tree.shown() == ["Delta"]
    assert len(owner.notices) == notices


def plain(owner: Any) -> tuple[list[str], list[str]]:
    queued_click(owner, PRESSED, 0)
    owner.run_queue()
    return picks(owner), ["Delta"]


def ctrl(owner: Any) -> tuple[list[str], list[str]]:
    queued_click(owner, PRESSED, MOD1)
    owner.run_queue()
    return picks(owner), ["Bravo", "Delta"]


def shift(owner: Any) -> tuple[list[str], list[str]]:
    queued_click(owner, PRESSED, SHIFT)
    owner.run_queue()
    return picks(owner), ["Bravo", "Charlie", "Delta"]


def double(owner: Any) -> tuple[list[str], list[str]]:
    activated = record_activations(owner)
    queued_click(owner, PRESSED, 0, clicks=2)
    owner.run_queue()
    return activated, ["Delta"]


def right(owner: Any) -> tuple[list[str | None], list[str]]:
    targets = record_menus(owner)
    queued_click(owner, PRESSED, 0, button=RIGHT)
    owner.run_queue()
    return targets, ["Delta"]


@pytest.mark.parametrize(
    "gesture",
    [
        pytest.param(plain, id="plain click"),
        pytest.param(ctrl, id="Ctrl+click"),
        pytest.param(shift, id="Shift+click"),
        pytest.param(double, id="double click"),
        pytest.param(right, id="right click"),
    ],
)
@pytest.mark.parametrize(
    "refresh",
    [
        pytest.param(recolour, id="recoloured"),
        pytest.param(switch, id="another sheet shown"),
        pytest.param(unchanged, id="unchanged"),
    ],
)
def test_a_refresh_that_keeps_the_rows_before_a_presss_listener_leaves_the_press_alone(
    refresh: Callable[[Any], None], gesture: Callable[[Any], tuple[list[Any], list[str]]]
) -> None:
    """Bravo picked; a refresh queued before the user's press on Delta keeps every sheet in its
    row, whether it rebuilds the rows or not. The press acts on Delta, as the user saw it."""
    owner = picked("Bravo")
    notices = len(owner.notices)
    refresh(owner)
    got, wanted = gesture(owner)
    assert got == wanted
    assert len(owner.notices) == notices


def test_a_press_after_the_reordering_refresh_acts_on_the_sheet_its_row_shows() -> None:
    """The refresh runs before the user presses: the tree then shows Echo in Delta's old row, and
    a click there picks Echo. Move to Top moves it."""
    owner = picked("Delta")
    reorder(owner)
    owner.run_queue()
    assert owner.names()[PRESSED] == "Echo"
    queued_click(owner, PRESSED, 0)
    owner.run_queue()
    assert picks(owner) == ["Echo"] and owner.tree.shown() == ["Echo"]
    assert move_to_top(owner) == ["Echo"]


def test_presses_act_again_once_work_posted_after_the_refresh_has_run() -> None:
    """After a refused press, the user clicks Echo, now in Delta's old row, and then Ctrl+clicks
    Golf: both act."""
    owner = picked("Delta")
    reorder(owner)
    queued_click(owner, PRESSED, 0)
    owner.run_queue()
    assert picks(owner) == []
    queued_click(owner, PRESSED, 0)
    owner.run_queue()
    queued_click(owner, row("Golf"))
    owner.run_queue()
    assert picks(owner) == ["Echo", "Golf"]
    assert move_to_top(owner) == ["Echo", "Golf"]


def test_the_end_of_an_earlier_reorder_does_not_end_a_later_one() -> None:
    """Delta picked. Another window moves Charlie below Echo, and a refresh is queued, and another
    refresh behind it. The first shows Echo in Delta's old row, and the user clicks there; then
    another window moves Echo to the top before the second refresh runs, which puts Delta back in
    that row. The end of the first refresh's hold, posted before the press, runs before its
    listener; with one flag for every hold it ended the second's too, and the listener picked
    Delta, which the user did not press."""
    owner = picked("Delta")
    reorder(owner)
    post_refresh(owner)
    work, _ = owner.queue.pop(0)
    work()  # The first refresh: Echo is shown in Delta's old row.
    assert owner.names()[PRESSED] == "Echo"
    queued_click(owner, PRESSED, 0)
    owner.book.move("Echo", 0)
    owner.run_queue()
    assert owner.names()[PRESSED] == "Delta"
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_listener_run_ahead_of_the_refreshs_release_is_held() -> None:
    """The cost of the rule. The refresh has run, and the user clicks Echo, now in Delta's old
    row. VCL can run that click's listener ahead of work posted before the press, in a callback
    event of the tree's window that was still queued (`VCLXWindowImpl::callBackAsync`), so ahead
    of the refresh's release. The list cannot tell such a press from one handled before the
    refresh: it picks nothing, and the user clicks again."""
    owner = picked("Delta")
    notices = len(owner.notices)
    reorder(owner)
    work, _ = owner.queue.pop(0)
    work()  # The refresh, whose release is now queued.
    press(owner, PRESSED)  # The listener, run before that release.
    owner.run_queue()
    refused(owner, notices)


@pytest.mark.parametrize("call", ["getNodeRect", "makeNodeVisible"])
def test_a_rebuild_that_may_not_keep_the_scroll_position_holds_presses(call: str) -> None:
    """Nothing picked; another window colours Golf, and the refresh's rebuild cannot read the
    tree's scroll position (`getNodeRect`) or restore it (`makeNodeVisible`). The new model may
    then show its rows at another position than the old ones, so a press made before is refused,
    as after a reorder. The simulated tree does not scroll; this pins the rule."""
    owner = sheet_list(Book(list(NAMES)))
    owner.book.sheet("Golf").color = 0x336699
    owner.faults.fail(call)
    post_refresh(owner)
    queued_click(owner, PRESSED, 0)
    owner.run_queue()
    assert owner.faults.failed == [call]
    assert picks(owner) == [] and cursor(owner) is None


def test_a_hold_whose_end_could_not_be_posted_ends_with_the_next_rebuild() -> None:
    """Delta picked; the reordering refresh's post of the hold's end fails, so presses stay held.
    The next rebuild, after another window colours Golf, holds nothing new, but posts that end:
    a click there picks the sheet its row shows. Had the list recorded the end as posted before
    posting it, nothing would post it again, and every press would be refused until another
    reorder."""
    owner = picked("Delta")
    post = owner.post

    def failing(work: Callable[[], None], where: str) -> None:
        if where == "accepting presses again" and not owner.faults.failed:
            owner.faults.failed.append(where)
            raise NativeFailure(where)
        post(work, where)

    owner.post = failing
    reorder(owner)
    owner.run_queue()
    assert owner.faults.failed == ["accepting presses again"]
    queued_click(owner, PRESSED, 0)
    owner.run_queue()
    assert picks(owner) == []
    recolour(owner)
    owner.run_queue()
    queued_click(owner, PRESSED, 0)
    owner.run_queue()
    assert picks(owner) == ["Echo"] and move_to_top(owner) == ["Echo"]


@pytest.mark.parametrize(
    "gesture, wanted",
    [
        pytest.param(lambda owner: queued_click(owner, row("Golf"), 0), ["Golf"], id="plain click"),
        pytest.param(
            lambda owner: queued_click(owner, row("Bravo")), ["Bravo", "Delta"], id="Ctrl+click"
        ),
    ],
)
def test_a_press_on_a_row_the_reorder_left_alone_acts(
    gesture: Callable[[Any], None], wanted: list[str]
) -> None:
    """Delta picked; another window moves Charlie below Echo, which leaves Alfa, Bravo, Foxtrot,
    Golf and Hotel in their rows, and the user clicks Golf, or Ctrl+clicks Bravo, before the
    refresh runs. Those rows showed the same sheets before and after, so the press acts."""
    owner = picked("Delta")
    notices = len(owner.notices)
    reorder(owner)
    gesture(owner)
    owner.run_queue()
    assert picks(owner) == wanted and owner.tree.shown() == wanted
    assert len(owner.notices) == notices
    assert move_to_top(owner) == wanted


def test_a_double_or_right_click_on_a_row_the_reorder_left_alone_acts() -> None:
    """As above, a double click on Golf activates Golf, and a right click on Hotel opens the menu
    for Hotel and keeps Delta picked."""
    owner = picked("Delta")
    activated = record_activations(owner)
    reorder(owner)
    queued_click(owner, row("Golf"), 0, clicks=2)
    owner.run_queue()
    assert activated == ["Golf"] and picks(owner) == ["Golf"]
    owner = picked("Delta")
    targets = record_menus(owner)
    reorder(owner)
    queued_click(owner, row("Hotel"), 0, button=RIGHT)
    owner.run_queue()
    assert targets == ["Hotel"] and picks(owner) == ["Delta"]


def test_a_shift_click_on_a_row_the_reorder_left_alone_is_refused() -> None:
    """Delta picked, the range anchor on it; another window moves Charlie below Echo, and the user
    Shift+clicks Golf before the refresh runs, on rows where that range holds Delta, Echo,
    Foxtrot and Golf. The listener extended the range over the rows the refresh shows and also
    picked Charlie, which the user's range never held. A range runs through rows that may have
    changed, so a Shift press is refused while presses are held."""
    owner = picked("Delta")
    notices = len(owner.notices)
    reorder(owner)
    queued_click(owner, row("Golf"), SHIFT)
    owner.run_queue()
    assert "Charlie" not in picks(owner), "Charlie, outside the user's range, was picked"
    assert picks(owner) == [] and len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


def test_a_reorder_that_moves_the_top_row_holds_every_row() -> None:
    """Another window moves Alfa, the top row, below Bravo, and the user clicks Foxtrot, whose row
    keeps its sheet, before the refresh runs. Restoring the scroll position puts Alfa back at the
    top, which would scroll a scrolled list by a row, so no row is known to show what it showed
    and the click is refused. The simulated tree does not scroll; this pins the rule."""
    owner = picked("Delta")
    owner.book.move("Alfa", 1)
    post_refresh(owner)
    queued_click(owner, row("Foxtrot"), 0)
    owner.run_queue()
    assert owner.names()[row("Foxtrot")] == "Foxtrot"
    assert picks(owner) == [] and move_to_top(owner) is None
