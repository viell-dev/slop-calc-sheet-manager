"""Presses across a scroll the list did not see, and drags recognized before a press's listener.

The tree handles a press on the rows it shows then; the list's mouse listener runs later, queued
behind the work already posted (#269), and maps the event's position through the scroll position
the tree has when it runs. The tree can scroll in between without a rebuild (#299): a selection
key's queued write shows the cursor, and the wheel or the scrollbar scrolls it with no list code
running. The listener then picked, activated or targeted a menu at the sheet scrolled under the
pointer. A drag gesture can also be recognized before the press's listener, within VCL's handling
of the motion (#264); after a refresh that rebuilt the rows, the tree no longer showed the row the
press selected, and the gesture dragged the picks the rebuild wrote instead (#295).

The real list runs over the simulated peer of `list_peer`, whose tree scrolls as LibreOffice's
does once four rows fit. By reading LibreOffice's sources, the wheel and the scroll bar paint
within their own handling, so `wheel` paints at once, while a resize and another client's
`makeNodeVisible` only invalidate, so `resize` and `scroll_unseen` leave the paint for later. The
invariant: a press, its release, its double click, its menu and a drag act only on the sheet the
tree showed under the pointer when the user pressed, or refuse.
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from sheet_manager.keys import DOWN, END, HOME
from tests.unit.list_peer import (
    LEFT,
    RIGHT,
    Book,
    bind_drag,
    click,
    cursor,
    listen,
    move_to_top,
    native_press,
    picks,
    queued_click,
    record_activations,
    record_menus,
    resize,
    scroll_unseen,
    sheet_list,
    wheel,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]


def row(name: str) -> int:
    return NAMES.index(name)


def top() -> Any:
    """A list where four rows fit, showing Alfa to Delta."""
    owner = sheet_list(Book(list(NAMES)))
    owner.tree.visible = 4
    return owner


def end_view() -> Any:
    """As `top`, scrolled to the end by the wheel, which shows Echo to Hotel painted."""
    owner = top()
    wheel(owner, len(NAMES))
    owner.run_queue()
    return owner


def in_view(owner: Any) -> list[str]:
    return owner.names()[owner.tree.start : owner.tree.start + owner.tree._in_view()]


def gesture(owner: Any, pressed: str, kind: str) -> list[Any]:
    """The user's click on `pressed`'s line, as `kind`, its listeners queued: the sheets the
    press picked, activated or targeted a menu at, once the queue has run."""
    activated, targets = record_activations(owner), record_menus(owner)
    before = picks(owner)
    if kind == "plain":
        queued_click(owner, row(pressed), 0)
    elif kind == "double":
        queued_click(owner, row(pressed), 0, clicks=2)
    else:
        queued_click(owner, row(pressed), 0, button=RIGHT)
    return [before, activated, targets]


def acted(owner: Any, recorded: list[Any], kind: str) -> list[str]:
    before, activated, targets = recorded
    if kind == "right":
        return [target for target in targets if target is not None]
    return [*picks(owner), *activated] if picks(owner) != before or activated else []


KINDS = [
    pytest.param("plain", id="click"),
    pytest.param("double", id="double click"),
    pytest.param("right", id="right click"),
]


def end(owner: Any) -> None:
    """End: the cursor moves to Hotel at once, and the write that shows it is queued."""
    owner.tree_key(END, 0)


def alfa_then_end(owner: Any) -> None:
    """Alfa clicked; End then moves the cursor to Hotel, and its write is queued."""
    click(owner, row("Alfa"))
    end(owner)


def down_from_delta(owner: Any) -> None:
    """Delta clicked; Down then moves the cursor to Echo, just below the view."""
    click(owner, row("Delta"))
    owner.tree_key(DOWN, 0)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "keys, pressed, scrolled_in",
    [
        pytest.param(alfa_then_end, "Alfa", "Echo", id="End"),
        pytest.param(down_from_delta, "Delta", "Hotel", id="Down past the view"),
    ],
)
def test_a_keys_write_that_scrolls_before_a_presss_listener_acts_on_no_other_sheet(
    keys: Callable[[Any], None], pressed: str, scrolled_in: str, kind: str
) -> None:
    """Four rows fit, showing Alfa to Delta. A key moves the cursor below the view, and before
    its queued write runs the user clicks `pressed`'s line, the row the tree shows selected, so
    the press leaves the tree's selection as it was. The write shows the cursor, which scrolls the
    list to Echo to Hotel, and the listener mapped the line to `scrolled_in`: the click picked
    it, the double click activated it and the right click opened its menu. The write holds presses
    when it scrolls, so the press is refused. A press that selects another row before the write
    leaves the write nothing to show (#307, the next test)."""
    owner = top()
    keys(owner)
    recorded = gesture(owner, pressed, kind)
    owner.run_queue()
    assert in_view(owner) == ["Echo", "Foxtrot", "Golf", "Hotel"]
    assert scrolled_in not in acted(owner, recorded, kind), f"{scrolled_in} was never pressed"
    assert acted(owner, recorded, kind) == []
    if kind != "right":
        assert picks(owner) == [] and move_to_top(owner) is None


@pytest.mark.parametrize("kind", ["plain", "double"])
@pytest.mark.parametrize(
    "keys, pressed",
    [
        pytest.param(end, "Charlie", id="End"),
        pytest.param(down_from_delta, "Bravo", id="Down past the view"),
    ],
)
def test_a_press_that_selects_its_row_before_a_keys_write_acts_on_it(
    keys: Callable[[Any], None], pressed: str, kind: str
) -> None:
    """As above, but the click on `pressed`'s line selects that row in the tree before the
    key's write runs. The write would show the key's pick over a change made after the key, so it
    leaves the tree to the intake and does not scroll (#307). The click's listener then maps its
    line to the row the user pressed, and acts on it, with no notice."""
    owner = top()
    keys(owner)
    notices = len(owner.notices)
    recorded = gesture(owner, pressed, kind)
    owner.run_queue()
    assert in_view(owner) == NAMES[:4]
    assert acted(owner, recorded, kind) == [pressed] * (2 if kind == "double" else 1)
    assert owner.tree.shown() == [pressed] and len(owner.notices) == notices
    assert move_to_top(owner) == [pressed]


def test_a_refused_press_after_a_keys_scroll_clears_the_keys_pick_with_the_notice() -> None:
    """Alfa clicked, and End picked Hotel; the click on Alfa's line before the write is refused.
    The write replaced the tree's Alfa with Hotel and scrolled, so the picks go, with the notice,
    as a press held across a rebuild drops them (#293). The cursor stays on Hotel."""
    owner = top()
    alfa_then_end(owner)
    notices = len(owner.notices)
    queued_click(owner, row("Alfa"), 0)
    owner.run_queue()
    assert picks(owner) == [] and owner.tree.shown() == []
    assert len(owner.notices) == notices + 1
    assert cursor(owner) == "Hotel"


@pytest.mark.parametrize("kind", KINDS)
def test_a_keys_write_that_does_not_scroll_leaves_the_press_alone(kind: str) -> None:
    """Control. Alfa clicked; Down moves the cursor to Bravo, in view, and the user clicks
    Charlie's line before the write runs. The write does not scroll, so the press acts on
    Charlie."""
    owner = top()
    click(owner, row("Alfa"))
    owner.tree_key(DOWN, 0)
    recorded = gesture(owner, "Charlie", kind)
    owner.run_queue()
    assert in_view(owner) == NAMES[:4]
    assert acted(owner, recorded, kind) == ["Charlie"] * (2 if kind == "double" else 1)


def test_a_press_after_a_keys_scroll_acts_on_the_row_it_shows() -> None:
    """End's write has run and shows Echo to Hotel; the user clicks Golf, on Charlie's old line.
    The press acts on Golf: the write's hold ended with work posted after it."""
    owner = top()
    end(owner)
    owner.run_queue()
    queued_click(owner, row("Golf"), 0)
    owner.run_queue()
    assert picks(owner) == ["Golf"] and move_to_top(owner) == ["Golf"]


def test_a_type_ahead_that_scrolls_before_a_presss_listener_acts_on_no_other_sheet() -> None:
    """Typing E jumps to Echo in posted work, which scrolls the list to Echo to Hotel. A click on
    Bravo's line made before it picked Foxtrot. Its listener is held."""
    owner = top()
    owner.post(lambda: owner.type_ahead("e"), "typing ahead")
    queued_click(owner, row("Bravo"), 0)
    owner.run_queue()
    assert in_view(owner) == ["Echo", "Foxtrot", "Golf", "Hotel"]
    assert "Foxtrot" not in picks(owner)
    assert picks(owner) == [] and move_to_top(owner) is None


@pytest.mark.parametrize(
    "reads",
    [
        pytest.param(0, id="before the scroll"),
        pytest.param(1, id="after the scroll"),
    ],
)
def test_a_keys_write_that_cannot_read_its_scroll_holds_every_row(reads: int) -> None:
    """Alfa clicked, End, and one of the write's reads of the position fails, before or after it
    scrolls, so it cannot tell where the rows went: every row is held. The listener's own read
    would still refuse the press on Alfa's line, but not a drag recognized before it, which
    dragged Hotel, the pick the write showed instead of the row the user pressed (#295). A failed
    read after the scroll holds by itself; one before it is followed by a read that finds the rows
    moved. The press is on the row the tree shows selected, so the tree's selection stays as the
    key found it and the write runs (#307)."""
    owner = top()
    dragged = bind_drag(owner)
    alfa_then_end(owner)
    native_press(owner, row("Alfa"))
    owner.faults.fail("getNodeRect", after=reads)
    work, _ = owner.queue.pop(0)
    work()  # The key's write.
    owner.start_drag(object())
    assert dragged == []
    assert owner.faults.failed == ["getNodeRect"]
    owner.run_queue()
    assert picks(owner) == []


def test_a_keys_write_whose_scroll_fails_leaves_the_press_alone() -> None:
    """Control. Alfa clicked, End, and the write's `makeNodeVisible` fails before it scrolls: the
    rows stay where the user pressed Alfa, the row the tree showed selected, and the press acts on
    Alfa."""
    owner = top()
    alfa_then_end(owner)
    owner.faults.fail("makeNodeVisible")
    queued_click(owner, row("Alfa"), 0)
    owner.run_queue()
    assert owner.faults.failed == ["makeNodeVisible"]
    assert in_view(owner) == NAMES[:4]
    assert picks(owner) == ["Alfa"]


@pytest.mark.parametrize("kind", KINDS)
def test_the_wheel_between_a_press_and_its_listener_acts_on_no_other_sheet(kind: str) -> None:
    """The user clicks Bravo's line, and before the listener runs the wheel scrolls the list by
    three rows, to Delta to Golf, with no list code running. The listener mapped the line to
    Echo: the click picked it, the double click activated it, the right click opened its menu.
    VCL paints the scrolled rows within its handling of the wheel, and that paint holds every row,
    so the press is refused."""
    owner = top()
    recorded = gesture(owner, "Bravo", kind)
    wheel(owner, 3)
    owner.run_queue()
    assert in_view(owner) == ["Delta", "Echo", "Foxtrot", "Golf"]
    assert "Echo" not in acted(owner, recorded, kind), "Echo was never pressed"
    assert acted(owner, recorded, kind) == [] and picks(owner) == []


@pytest.mark.parametrize("kind", KINDS)
def test_a_resize_between_a_press_and_its_listener_acts_on_no_other_sheet(kind: str) -> None:
    """Scrolled to the end, Echo to Hotel. The user clicks Foxtrot's line, and before the listener
    runs the panel grows by a row, as when the selection notice goes: the last rows fill the taller
    view, which now starts at Delta, and VCL paints it later. The listener mapped the line to Echo.
    It finds the rows at another position than the list saw last, and refuses."""
    owner = end_view()
    recorded = gesture(owner, "Foxtrot", kind)
    resize(owner, 5)
    owner.run_queue()
    assert in_view(owner) == ["Delta", "Echo", "Foxtrot", "Golf", "Hotel"]
    assert "Echo" not in acted(owner, recorded, kind), "Echo was never pressed"
    assert acted(owner, recorded, kind) == [] and picks(owner) == []


@pytest.mark.parametrize("kind", KINDS)
def test_a_refresh_after_an_unpainted_scroll_still_holds_the_press(kind: str) -> None:
    """As above, and another window colours Golf, so a refresh is queued before the press. The
    refresh runs before the listener; it keeps every row and the position the resize left, and its
    second read is the first to see that position. Noting it without holding every row let the
    listener find the rows where the list last saw them: the click picked Echo, the double click
    activated Echo, and the right click opened its menu."""
    owner = end_view()
    owner.book.sheet("Golf").color = 0x336699
    owner.post(owner.refresh, "refreshing the sheet list")
    recorded = gesture(owner, "Foxtrot", kind)
    resize(owner, 5)
    owner.run_queue()
    assert in_view(owner) == ["Delta", "Echo", "Foxtrot", "Golf", "Hotel"]
    assert "Echo" not in acted(owner, recorded, kind), "Echo was never pressed"
    assert acted(owner, recorded, kind) == [] and picks(owner) == []


def test_a_hold_released_inside_the_press_listener_still_refuses_its_press() -> None:
    """As after a resize between a press and its listener, but the listener's own post of the
    hold's end runs at once, as queued work can when a native call dispatches events. The press is
    decided before that post, so it stays refused; reading the hold after the post found none, and
    the click picked Echo."""
    owner = end_view()
    queued_click(owner, row("Foxtrot"), 0)
    resize(owner, 5)
    post = owner.post

    def post_now(work: Callable[[], None], where: str) -> None:
        if where == "accepting presses again" and owner._pointer_depth:
            work()
        else:
            post(work, where)

    owner.post = post_now
    owner.run_queue()
    assert "Echo" not in picks(owner), "Echo was never pressed"
    assert picks(owner) == []


@pytest.mark.parametrize("button", [pytest.param(RIGHT, id="right"), pytest.param(LEFT, id="left")])
def test_a_keys_write_that_scrolls_back_over_an_unseen_scroll_holds_the_press(button: int) -> None:
    """Alfa clicked, and Home pressed: its write is queued. Another client's `makeNodeVisible`
    scrolls the list to Delta to Golf, which VCL paints later, and the user clicks Echo there.
    Home's write then scrolls back to Alfa, where the list last saw the rows, and the listener
    mapped the click's line to Bravo. The write reads the position before it scrolls too, finds
    the rows elsewhere, and holds every row, so a right click opens no menu. A left click selects
    Echo in the tree after the key, so the write leaves the tree to the intake and does not scroll
    back (#307); the listener's own read then finds the rows elsewhere and refuses the press."""
    owner = top()
    click(owner, row("Alfa"))
    owner.tree_key(HOME, 0)
    scroll_unseen(owner, 3)
    targets = record_menus(owner)
    queued_click(owner, row("Echo"), 0, button=button)
    owner.run_queue()
    if button == RIGHT:
        assert in_view(owner) == NAMES[:4]
        assert targets == [None], "The menu targeted a row the user never pressed"
    else:
        assert in_view(owner) == ["Delta", "Echo", "Foxtrot", "Golf"]
        assert "Bravo" not in picks(owner), "Bravo was never pressed"
        assert picks(owner) == [] and move_to_top(owner) is None


def test_the_keyboard_menus_scroll_back_over_an_unseen_scroll_holds_the_press() -> None:
    """Alfa clicked, and the menu key pressed: its work, which scrolls the list to Alfa and opens
    the menu for it, is queued. Another client scrolls the list to Delta to Golf, unpainted, and
    the user right-clicks Echo there. The menu's scroll brings back the rows where the list last
    saw them, and the right click's listener targeted Bravo, under its line then. The menu's
    scroll holds presses as a key's write does."""
    owner = top()
    opened: list[str | None] = []

    def open_menu(x: int, y: int, refs: Any = None, seen: int | None = None) -> None:
        target = owner._context_target
        names = [ref.name for ref in refs] if refs else [target.name] if target else [None]
        opened.extend(names)

    owner._open_menu = open_menu
    click(owner, row("Alfa"))
    owner.post(owner.open_menu_for_keyboard, "the sheet tab menu")
    scroll_unseen(owner, 3)
    queued_click(owner, row("Echo"), 0, button=RIGHT)
    owner.run_queue()
    assert in_view(owner) == NAMES[:4]
    assert "Bravo" not in opened, "Bravo was never pressed"
    assert opened == ["Alfa", None] and picks(owner) == ["Alfa"]


def test_a_double_click_before_a_resize_activates_nothing() -> None:
    """Scrolled to the end; both clicks of a double click on Foxtrot's line are made before the
    panel grows by a row, which VCL has not painted when their listeners run. The first listener
    finds the rows elsewhere and holds every row; the second, whose press came before that, runs
    held too. Without that hold the second found the position the first had noted, and the
    double click activated Echo."""
    owner = end_view()
    activated = record_activations(owner)
    queued_click(owner, row("Foxtrot"), 0)
    queued_click(owner, row("Foxtrot"), 0, clicks=2)
    resize(owner, 5)
    owner.run_queue()
    assert activated == [] and picks(owner) == []


@pytest.mark.parametrize("kind", KINDS)
def test_a_press_after_the_wheel_and_its_paint_acts_on_the_row_it_shows(kind: str) -> None:
    """Control. The wheel scrolls the list to Delta to Golf, VCL paints it, and the user then
    clicks Echo, on Bravo's old line: the press acts on Echo."""
    owner = top()
    wheel(owner, 3)
    owner.run_queue()
    recorded = gesture(owner, "Echo", kind)
    owner.run_queue()
    assert acted(owner, recorded, kind) == ["Echo"] * (2 if kind == "double" else 1)


def test_a_press_after_a_resize_before_its_paint_is_refused_once() -> None:
    """The cost of the rule. The panel grows by a row, which scrolls the list to Delta, and the
    user clicks Echo before VCL has painted the scrolled rows. The list cannot tell that press from
    one made before the resize, so it is refused; the next click acts."""
    owner = end_view()
    resize(owner, 5)
    queued_click(owner, row("Echo"), 0)
    owner.run_queue()
    assert picks(owner) == []
    queued_click(owner, row("Echo"), 0)
    owner.run_queue()
    assert picks(owner) == ["Echo"]


def test_a_change_of_the_row_height_between_a_press_and_its_listener_holds_every_row() -> None:
    """The user clicks Delta's line, and before the listener runs the rows get twice as tall, as
    after a change of font or display scaling, with the first row still at the top. The listener
    mapped the position to Bravo. The position the list compares includes the row height, so the
    press is refused."""
    owner = top()
    queued_click(owner, row("Delta"), 0)
    owner.tree.height = 2
    owner.run_queue()
    assert "Bravo" not in picks(owner), "Bravo was never pressed"
    assert picks(owner) == []


def test_a_press_after_a_failed_reads_hold_ends_acts() -> None:
    """Alfa clicked; Down moves the cursor to Bravo, in view, and the write's read of the position
    after its scroll, which did not move the rows, fails. Every row is held until work posted then
    has run, and the list keeps the position it saw last, where the rows still are, so a click on
    Charlie after that acts. Forgetting the position would refuse it."""
    owner = top()
    click(owner, row("Alfa"))
    owner.tree_key(DOWN, 0)
    owner.faults.fail("getNodeRect", after=1)
    owner.run_queue()
    assert owner.faults.failed == ["getNodeRect"]
    queued_click(owner, row("Charlie"), 0)
    owner.run_queue()
    assert picks(owner) == ["Charlie"]


def drag_after_reorder(pressed: str, picked: str = "Bravo") -> tuple[Any, list[list[str]]]:
    """`picked` clicked; another window moves Charlie below Echo, and the list's refresh for it
    is queued; the user presses `pressed`'s row, and the refresh runs before the drag gesture,
    which LibreOffice recognizes before the press's listener. Returns the list and the drags it
    started; the queue still holds the press's listener."""
    owner = sheet_list(Book(list(NAMES)))
    dragged = bind_drag(owner)
    click(owner, row(picked))
    owner.book.move("Charlie", row("Echo"))
    owner.post(owner.refresh, "refreshing the sheet list")
    native_press(owner, row(pressed))
    work, _ = owner.queue.pop(0)
    work()  # The refresh, which shows Echo in Delta's row and writes the picks.
    owner.start_drag(object())
    return owner, dragged


def test_a_drag_recognized_before_its_presss_listener_after_a_reorder_drags_nothing() -> None:
    """Bravo picked; the user presses Delta's row and drags. The refresh rebuilt the rows and
    wrote Bravo, so the tree no longer showed Delta selected, and the gesture dragged Bravo, which
    the user did not press: a drop then moved it. No drag starts while presses are held; the
    press's listener runs held, and its row now shows Echo, so it picks nothing and drops the
    picks with the notice. Since #296, the refresh also drops the picks that the press's native
    selection superseded (#280), which refuses this drag by itself; the next test is one that the
    drop does not reach."""
    owner, dragged = drag_after_reorder("Delta")
    notices = len(owner.notices)
    assert dragged == []
    owner.run_queue()
    assert picks(owner) == [] and len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


def test_a_drag_after_a_reorder_with_an_earlier_click_still_queued_drags_nothing() -> None:
    """Bravo picked. The user clicks Alfa and then presses Delta and drags, all before their
    listeners run; the first press's listener runs, then the refresh after another window moved
    Charlie below Echo, and the gesture comes before the rest. With the first click's release
    still queued, the refresh does not see the second press's native selection as one waiting
    for the intake, so it does not drop the picks (#280); its rebuild writes Alfa over Delta, and
    the gesture dragged Alfa, which the user did not press. No drag starts while presses are
    held."""
    owner = sheet_list(Book(list(NAMES)))
    dragged = bind_drag(owner)
    click(owner, row("Bravo"))
    tree = owner.tree

    def queued(handler: Callable[[Any], None], line: int) -> Callable[[], None]:
        event = SimpleNamespace(Buttons=LEFT, X=0, Y=line, Modifiers=0, ClickCount=1)
        return lambda: listen(owner, handler, event)

    alfa, delta = tree.node("Alfa"), tree.node("Delta")
    tree.selected, tree.cursor = [alfa], alfa  # The first press, as the tree handles it.
    owner.post(queued(owner.mouse_pressed, row("Alfa")), "a mouse press")
    owner.book.move("Charlie", row("Echo"))
    owner.post(owner.refresh, "refreshing the sheet list")
    owner.post(queued(owner.mouse_released, row("Alfa")), "a mouse release")
    tree.selected, tree.cursor = [delta], delta  # The second press, on Delta.
    owner.post(queued(owner.mouse_pressed, row("Delta")), "a mouse press")
    for _ in range(2):  # The first press's listener, then the refresh.
        work, _ = owner.queue.pop(0)
        work()
    owner.start_drag(object())
    assert dragged == [], "Alfa, which the user did not drag, was dragged"


def test_a_drag_on_a_row_the_reorder_left_alone_starts_nothing_but_the_press_picks() -> None:
    """As above on Golf's row, which the move left alone. The gesture dragged Bravo too. It now
    starts nothing, and the press's listener, held, picks Golf, which its row still shows."""
    owner, dragged = drag_after_reorder("Golf")
    assert dragged == []
    owner.run_queue()
    assert picks(owner) == ["Golf"]


def test_a_drag_from_a_picked_row_across_a_reorder_is_refused() -> None:
    """The cost of the rule. The user presses Bravo, the pick, and drags: the gesture dragged
    Bravo, the sheet pressed, but the list cannot tell this press from one on a row the rebuild
    changed, and starts nothing. The press's listener keeps Bravo, whose row kept it."""
    owner, dragged = drag_after_reorder("Bravo")
    assert dragged == []
    owner.run_queue()
    assert picks(owner) == ["Bravo"]


def no_change(book: Book) -> None:
    pass


def recolour_golf(book: Book) -> None:
    book.sheet("Golf").color = 0x336699


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(no_change, id="unchanged"),
        pytest.param(recolour_golf, id="recoloured"),
    ],
)
def test_a_drag_across_a_refresh_that_keeps_the_rows_drags_the_pressed_sheet(
    change: Callable[[Book], None],
) -> None:
    """Control. Bravo picked; a refresh that keeps every row, with or without a rebuild, runs
    between the press on Delta's row and the gesture: the drag carries Delta."""
    owner = sheet_list(Book(list(NAMES)))
    dragged = bind_drag(owner)
    click(owner, row("Bravo"))
    change(owner.book)
    owner.post(owner.refresh, "refreshing the sheet list")
    native_press(owner, row("Delta"))
    work, _ = owner.queue.pop(0)
    work()
    owner.start_drag(object())
    assert dragged == [["Delta"]]


def test_a_drag_across_a_keys_scroll_drags_nothing() -> None:
    """End picked Hotel, and the user presses Charlie and drags before the write runs. The write
    showed Hotel, so the gesture dragged Hotel, which the user did not press. The write scrolled,
    which holds presses, so no drag starts."""
    owner = top()
    dragged = bind_drag(owner)
    end(owner)
    native_press(owner, row("Charlie"))
    work, _ = owner.queue.pop(0)
    work()  # The key's write.
    owner.start_drag(object())
    assert dragged == []


def test_a_drag_across_a_type_aheads_scroll_drags_nothing() -> None:
    """Typing H jumps to Hotel in posted work, which picks Hotel, shows it and scrolls the list to
    Echo to Hotel. The user pressed Charlie before that and drags: the gesture dragged Hotel. The
    jump holds presses when it scrolls, so no drag starts."""
    owner = top()
    dragged = bind_drag(owner)
    owner.post(lambda: owner.type_ahead("h"), "typing ahead")
    native_press(owner, row("Charlie"))
    work, _ = owner.queue.pop(0)
    work()  # The jump.
    owner.start_drag(object())
    assert dragged == []


def wheel_three(owner: Any) -> None:
    wheel(owner, 3)


def grow_by_a_row(owner: Any) -> None:
    resize(owner, 5)


@pytest.mark.parametrize(
    "scroll, pressed, wanted",
    [
        pytest.param(wheel_three, "Delta", [], id="the wheel, painted at once: refused"),
        pytest.param(grow_by_a_row, "Foxtrot", [["Foxtrot"]], id="a resize: drags Foxtrot"),
    ],
)
def test_a_drag_across_a_scroll_drags_the_pressed_sheet_or_nothing(
    scroll: Callable[[Any], None], pressed: str, wanted: list[list[str]]
) -> None:
    """The user presses a row, the list scrolls, and the gesture follows before the press's
    listener. The tree keeps the pressed row selected wherever it scrolls, so the gesture drags it.
    The wheel paints within its own handling, which holds presses, so after the wheel the gesture
    starts nothing: a cost of the rule. A resize is painted later, so it holds nothing yet."""
    owner = top() if pressed == "Delta" else end_view()
    dragged = bind_drag(owner)
    native_press(owner, row(pressed))
    scroll(owner)
    owner.start_drag(object())
    assert dragged == wanted
