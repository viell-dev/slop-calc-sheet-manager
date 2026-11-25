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
showed the same name in every row list since then acts, unless the list may show its rows at
another position; a refused left press picks nothing and drops the picks, which its native effect
superseded in the tree, with the notice; a refused right press opens no menu and keeps the picks.

The scroll tests let only four rows fit (`scrolled`), so that the peer's tree scrolls as
LibreOffice's does: its restore cannot always show the old top row at the top, and a press's
position then maps to another row.
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
    record_activations,
    record_menus,
    sheet_list,
    wheel,
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


def test_a_second_rebuild_keeps_holding_the_rows_the_first_one_changed() -> None:
    """Delta picked; another window moves Charlie below Echo, and two refreshes are queued; the
    user clicks Delta's row before either runs. After the first refresh, another window renames
    Hotel, so the second rebuilds again but leaves Echo where the first put it, in the clicked
    row. Comparing only the second rebuild's rows, the hold kept that row, and the listener picked
    Echo, which the user never pressed."""
    owner = picked("Delta")
    notices = len(owner.notices)
    reorder(owner)
    post_refresh(owner)
    queued_click(owner, PRESSED, 0)
    work, _ = owner.queue.pop(0)
    work()  # The first refresh: Echo is shown in Delta's old row.
    owner.book.rename("Hotel", "Zulu")
    owner.run_queue()
    assert owner.names()[PRESSED] == "Echo" and owner.names()[-1] == "Zulu"
    refused(owner, notices)


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


@pytest.mark.parametrize("ending", ["retried refresh", "next rebuild"])
def test_a_hold_whose_end_could_not_be_posted_ends_with_the_next_refresh(ending: str) -> None:
    """Delta picked; the reordering refresh's post of the hold's end fails, which fails the
    refresh, so presses stay held. The refresh's retry finds the rows as the failed refresh left
    them and does not rebuild; it, or a later rebuild after another window colours Golf, posts
    that end. A click on Echo, now in Delta's old row, then picks Echo, and a Shift+click on Golf
    extends the range. The end used to be posted only by a rebuild, so after the retry every
    Shift+click and every click on a row the reorder changed stayed refused until one ran. Had
    the list recorded the end as posted before posting it, nothing would post it again."""
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
    assert owner.failures == ["refreshing the sheet list"]
    queued_click(owner, PRESSED, 0)
    owner.run_queue()
    assert picks(owner) == []
    if ending == "retried refresh":
        assert owner.retry() == 1
    else:
        recolour(owner)
        owner.run_queue()
    queued_click(owner, PRESSED, 0)
    owner.run_queue()
    assert picks(owner) == ["Echo"]
    queued_click(owner, row("Golf"), SHIFT)
    owner.run_queue()
    extended = ["Echo", "Charlie", "Foxtrot", "Golf"]
    assert picks(owner) == extended and move_to_top(owner) == extended


def click_golf(owner: Any) -> None:
    queued_click(owner, row("Golf"), 0)


def ctrl_click_bravo(owner: Any) -> None:
    queued_click(owner, row("Bravo"))


@pytest.mark.parametrize(
    "gesture, wanted",
    [
        pytest.param(click_golf, ["Golf"], id="plain click"),
        pytest.param(ctrl_click_bravo, [], id="Ctrl+click"),
    ],
)
def test_a_press_on_a_row_the_reorder_left_alone_is_not_held_by_the_press_hold(
    gesture: Callable[[Any], None], wanted: list[str]
) -> None:
    """Delta picked; another window moves Charlie below Echo, which leaves Alfa, Bravo, Foxtrot,
    Golf and Hotel in their rows, and the user clicks Golf, or Ctrl+clicks Bravo, before the
    refresh runs. Those rows showed the same sheets before and after, so the press hold maps the
    press to its row. The refresh also finds the press's native effect in the tree, a selection
    its intake has not taken, which it cannot tell from one made through accessibility: it drops
    Delta, which it would otherwise write over that selection, with the notice, and holds
    toggles (#280, #291). So the plain click picks Golf, and the Ctrl+click is refused as a held
    toggle, which still moves the cursor to Bravo, where a press the press hold refused would
    move nothing."""
    owner = picked("Delta")
    notices = len(owner.notices)
    reorder(owner)
    gesture(owner)
    owner.run_queue()
    assert picks(owner) == wanted and owner.tree.shown() == wanted
    assert cursor(owner) == ("Golf" if wanted else "Bravo")
    assert len(owner.notices) == notices + 1
    assert move_to_top(owner) == (wanted or None)


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
    keeps its sheet, before the refresh runs. Every row fits, so the restore leaves the list where
    it was, as the rebuild's second read of the position finds. A top row that moved can scroll a
    scrolled list (`test_a_change_of_the_top_row_of_a_scrolled_list_holds_every_row`), and the
    rule holds every row from before the new rows show, so the click is refused. This pins the
    rule where it costs a click."""
    owner = picked("Delta")
    owner.book.move("Alfa", 1)
    post_refresh(owner)
    queued_click(owner, row("Foxtrot"), 0)
    owner.run_queue()
    assert owner.names()[row("Foxtrot")] == "Foxtrot"
    assert picks(owner) == [] and move_to_top(owner) is None


def scrolled(names: list[str] = NAMES, wide: int | None = None) -> Any:
    """A list where four rows fit, which the user has scrolled to its end and sees painted; a
    label longer than `wide` characters shows a horizontal scrollbar, which takes one of those
    rows."""
    owner = sheet_list(Book(list(names)))
    owner.tree.visible, owner.tree.wide = 4, wide
    wheel(owner, len(names))
    owner.run_queue()
    return owner


def in_view(owner: Any) -> list[str]:
    """The rows the tree shows now, from the top of the view."""
    fit = owner.tree._in_view()
    return owner.names()[owner.tree.start : owner.tree.start + fit]


def delete(owner: Any, name: str) -> None:
    """Another window deletes `name`, and the list's refresh for it is queued."""
    owner.book.delete(name)
    post_refresh(owner)


def acted_on(owner: Any, gesture: str) -> list[str]:
    """The user clicks Foxtrot's row, as `gesture`, before the queued refresh runs: the sheets
    the press picked, activated or targeted a menu at."""
    activated, targets = record_activations(owner), record_menus(owner)
    if gesture == "plain":
        queued_click(owner, row("Foxtrot"), 0)
    elif gesture == "double":
        queued_click(owner, row("Foxtrot"), 0, clicks=2)
    else:
        queued_click(owner, row("Foxtrot"), 0, button=RIGHT)
    owner.run_queue()
    return [*picks(owner), *activated, *(target for target in targets if target is not None)]


@pytest.mark.parametrize("gesture", ["plain", "double", "right"])
@pytest.mark.parametrize("deleted", ["Hotel", "Golf"])
def test_a_deletion_that_shortens_a_list_scrolled_to_its_end_holds_every_row(
    deleted: str, gesture: str
) -> None:
    """The user has scrolled to the end, where Echo, Foxtrot, Golf and Hotel show. Another window
    deletes Hotel, the last sheet, or Golf, and the user clicks Foxtrot before the refresh runs.
    Seven rows cannot show Echo at the top of four: the restore's last rows fill the view from
    Delta, which puts Echo on Foxtrot's line. Echo kept its row, and so did every row once the
    last sheet went, so no row was held: the plain click picked Echo, which Move to Top then
    moved, the double click activated Echo, and the right click opened the menu for Echo. The
    rebuild reads the position again after the restore and holds every row."""
    owner = scrolled()
    assert in_view(owner) == ["Echo", "Foxtrot", "Golf", "Hotel"]
    delete(owner, deleted)
    assert acted_on(owner, gesture) == []
    assert in_view(owner)[:2] == ["Delta", "Echo"]
    assert picks(owner) == [] and move_to_top(owner) is None


def test_a_ctrl_click_after_such_a_deletion_picks_nothing() -> None:
    """As above, Hotel deleted, with a Ctrl+click on Foxtrot. The deletion makes the list drop
    its picks, which holds toggles (#288), so the Ctrl+click picked nothing before either."""
    owner = scrolled()
    delete(owner, "Hotel")
    queued_click(owner, row("Foxtrot"))
    owner.run_queue()
    assert picks(owner) == [] and move_to_top(owner) is None


def recolour_bravo(owner: Any) -> None:
    owner.book.sheet("Bravo").color = 0x336699
    post_refresh(owner)


def rename_bravo(owner: Any) -> None:
    owner.book.rename("Bravo", "Zulu")
    post_refresh(owner)


def scroll_to_top_and_delete_hotel(owner: Any) -> None:
    wheel(owner, 0)
    owner.run_queue()
    delete(owner, "Hotel")


@pytest.mark.parametrize(
    "change, pressed",
    [
        pytest.param(recolour_bravo, "Foxtrot", id="Bravo recoloured"),
        pytest.param(rename_bravo, "Foxtrot", id="Bravo renamed above the view"),
        pytest.param(scroll_to_top_and_delete_hotel, "Bravo", id="Hotel deleted, top in view"),
    ],
)
def test_a_rebuild_that_keeps_a_scrolled_lists_position_leaves_the_press_alone(
    change: Callable[[Any], None], pressed: str
) -> None:
    """Controls. Scrolled to the end, another window colours Bravo or renames it, above the view;
    or, scrolled to the top, deletes Hotel, which the restore can show without moving the top
    row. The user clicks a row that keeps its sheet before the refresh runs, and the click picks
    it. Counting every shorter list as scrolled would refuse the last."""
    owner = scrolled()
    change(owner)
    queued_click(owner, row(pressed), 0)
    owner.run_queue()
    assert picks(owner) == [pressed] and owner.tree.shown() == [pressed]
    assert move_to_top(owner) == [pressed]


def test_a_rename_that_removes_the_horizontal_scrollbar_holds_every_row() -> None:
    """Alfa's name is too long for the list, so a horizontal scrollbar takes a row's height and
    three rows fit; the user has scrolled to the end, where Foxtrot, Golf and Hotel show. Another
    window renames that sheet Alfa, and the user clicks Golf before the refresh runs. With the
    scrollbar gone four rows fit, and the restore's last rows fill the view from Echo, which puts
    Foxtrot on Golf's line. The list keeps its length and Foxtrot its row, so neither the top-row
    rule nor counting a shorter list as scrolled holds it, and the click picked Foxtrot, which
    the user never pressed. The rebuild's second read of the position holds every row."""
    names = ["Alfa, the quarterly summary", *NAMES[1:]]
    owner = scrolled(names, wide=12)
    assert in_view(owner) == ["Foxtrot", "Golf", "Hotel"]
    owner.book.rename(names[0], "Alfa")
    post_refresh(owner)
    queued_click(owner, row("Golf"), 0)
    owner.run_queue()
    assert in_view(owner) == ["Echo", "Foxtrot", "Golf", "Hotel"]
    assert picks(owner) == [] and move_to_top(owner) is None


def move_echo_above_delta(owner: Any) -> None:
    owner.book.move("Echo", row("Delta"))
    post_refresh(owner)


def rename_echo(owner: Any) -> None:
    owner.book.rename("Echo", "Zulu")
    post_refresh(owner)


@pytest.mark.parametrize(
    "change, shown",
    [
        pytest.param(move_echo_above_delta, "Foxtrot", id="moved up a row"),
        pytest.param(rename_echo, "Charlie", id="renamed"),
    ],
)
def test_a_change_of_the_top_row_of_a_scrolled_list_holds_every_row(
    change: Callable[[Any], None], shown: str
) -> None:
    """Scrolled to the end, Echo at the top. Another window moves Echo above Delta, or renames it,
    and the user clicks Golf before the refresh runs. The restore shows Echo at the top from
    Delta's old row, or, with no Echo to show, the new rows from the first. Golf's line then
    shows Foxtrot or Charlie, whose rows kept their sheets, and the click picked it. A top row
    that moved or went holds every row."""
    owner = scrolled()
    change(owner)
    queued_click(owner, row("Golf"), 0)
    owner.run_queue()
    assert in_view(owner)[2] == shown
    assert picks(owner) == [] and move_to_top(owner) is None


@pytest.mark.parametrize("call", ["getNodeRect", "makeNodeVisible"])
def test_a_rebuild_that_cannot_keep_the_scroll_position_holds_every_row(call: str) -> None:
    """Scrolled to the end; another window colours Bravo, and the refresh's rebuild cannot read
    the tree's scroll position (`getNodeRect`) or restore it (`makeNodeVisible`), so the new rows
    show from the first. The user's click on Foxtrot, made before, lands on Bravo's line, and it
    picked Bravo. It is refused."""
    owner = scrolled()
    owner.faults.fail(call)
    recolour_bravo(owner)
    queued_click(owner, row("Foxtrot"), 0)
    owner.run_queue()
    assert owner.faults.failed == [call]
    assert in_view(owner)[1] == "Bravo"
    assert picks(owner) == [] and move_to_top(owner) is None


def test_a_restored_position_that_cannot_be_read_holds_every_row() -> None:
    """As after Hotel's deletion above, but the rebuild's second read of the position fails: it
    cannot tell where the restore left the rows, so every row is held. (Without that read, the
    failure is the listener's own read, which refuses the click too.)"""
    owner = scrolled()
    owner.faults.fail("getNodeRect", after=1)
    delete(owner, "Hotel")
    queued_click(owner, row("Foxtrot"), 0)
    owner.run_queue()
    assert owner.faults.failed == ["getNodeRect"]
    assert picks(owner) == [] and move_to_top(owner) is None


def test_a_rebuild_that_fails_after_its_restore_still_holds_the_rows_it_moved() -> None:
    """As after Hotel's deletion above, but the rebuild's write of the selection fails after the
    restore left the rows further up, which fails the refresh. The second read of the position
    follows any failure once the new rows show, so the click on Foxtrot is refused rather than
    taken for Echo."""
    owner = scrolled()
    owner.faults.fail("clearSelection")
    delete(owner, "Hotel")
    queued_click(owner, row("Foxtrot"), 0)
    owner.run_queue()
    assert owner.faults.failed == ["clearSelection"]
    assert "refreshing the sheet list" in owner.failures
    assert in_view(owner)[:2] == ["Delta", "Echo"]
    assert picks(owner) == [] and move_to_top(owner) is None
