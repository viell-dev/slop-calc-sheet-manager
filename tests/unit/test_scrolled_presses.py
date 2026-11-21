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
does once four rows fit, and which paints where VCL would (`wheel`). The invariant: a press, its
release, its double click, its menu and a drag act only on the sheet the tree showed under the
pointer when the user pressed, or refuse.
"""

from collections.abc import Callable
from typing import Any

import pytest

from sheet_manager.keys import DOWN, END, HOME
from tests.unit.list_peer import (
    RIGHT,
    Book,
    bind_drag,
    click,
    cursor,
    move_to_top,
    native_press,
    picks,
    queued_click,
    record_activations,
    record_menus,
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


def in_view(owner: Any) -> list[str]:
    return owner.names()[owner.tree.start : owner.tree.start + 4]


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


def down_from_delta(owner: Any) -> None:
    """Delta clicked; Down then moves the cursor to Echo, just below the view."""
    click(owner, row("Delta"))
    owner.tree_key(DOWN, 0)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "keys, pressed, scrolled_in",
    [
        pytest.param(end, "Charlie", "Golf", id="End"),
        pytest.param(down_from_delta, "Bravo", "Foxtrot", id="Down past the view"),
    ],
)
def test_a_keys_write_that_scrolls_before_a_presss_listener_acts_on_no_other_sheet(
    keys: Callable[[Any], None], pressed: str, scrolled_in: str, kind: str
) -> None:
    """Four rows fit, showing Alfa to Delta. A key moves the cursor below the view, and before
    its queued write runs the user clicks `pressed`'s line. The write shows the cursor, which
    scrolls the list to Echo to Hotel, and the listener mapped the line to `scrolled_in`: the
    click picked it, the double click activated it and the right click opened its menu. The write
    holds presses when it scrolls, so the press is refused."""
    owner = top()
    keys(owner)
    recorded = gesture(owner, pressed, kind)
    owner.run_queue()
    assert in_view(owner) == ["Echo", "Foxtrot", "Golf", "Hotel"]
    assert scrolled_in not in acted(owner, recorded, kind), f"{scrolled_in} was never pressed"
    assert acted(owner, recorded, kind) == []
    if kind != "right":
        assert picks(owner) == [] and move_to_top(owner) is None


def test_a_refused_press_after_a_keys_scroll_clears_the_keys_pick_with_the_notice() -> None:
    """End picked Hotel; the click on Charlie's line before the write is refused. Its native
    selection of Charlie was replaced by the write, so the picks go, with the notice, as a press
    held across a rebuild drops them (#293). The cursor stays on Hotel."""
    owner = top()
    end(owner)
    notices = len(owner.notices)
    queued_click(owner, row("Charlie"), 0)
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
    """End, and one of the write's reads of the position fails, before or after it scrolls, so it
    cannot tell where the rows went: every row is held. The listener's own read would still refuse
    the click on Charlie's line, but not a drag recognized before it, which dragged Hotel, the pick
    the write showed instead of the row the user pressed (#295). A failed read after the scroll
    holds by itself; one before it is followed by a read that finds the rows moved."""
    owner = top()
    dragged = bind_drag(owner)
    end(owner)
    native_press(owner, row("Charlie"))
    owner.faults.fail("getNodeRect", after=reads)
    work, _ = owner.queue.pop(0)
    work()  # The key's write.
    owner.start_drag(object())
    assert dragged == []
    assert owner.faults.failed == ["getNodeRect"]
    owner.run_queue()
    assert picks(owner) == []


def test_a_keys_write_whose_scroll_fails_leaves_the_press_alone() -> None:
    """Control. End, and the write's `makeNodeVisible` fails before it scrolls: the rows stay
    where the user pressed Charlie, and the press acts on Charlie."""
    owner = top()
    end(owner)
    owner.faults.fail("makeNodeVisible")
    queued_click(owner, row("Charlie"), 0)
    owner.run_queue()
    assert owner.faults.failed == ["makeNodeVisible"]
    assert in_view(owner) == NAMES[:4]
    assert picks(owner) == ["Charlie"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "painted",
    [
        pytest.param(False, id="listener first"),
        pytest.param(True, id="painted first"),
    ],
)
def test_the_wheel_between_a_press_and_its_listener_acts_on_no_other_sheet(
    painted: bool, kind: str
) -> None:
    """The user clicks Bravo's line, and before the listener runs the wheel scrolls the list by
    three rows, to Delta to Golf, with no list code running. The listener mapped the line to
    Echo: the click picked it, the double click activated it, the right click opened its menu.
    The listener now finds the rows at another position than the list saw, or VCL painted them
    first and the paint held every row; either way the press is refused."""
    owner = top()
    recorded = gesture(owner, "Bravo", kind)
    wheel(owner, 3, painted=painted)
    owner.run_queue()
    assert in_view(owner) == ["Delta", "Echo", "Foxtrot", "Golf"]
    assert "Echo" not in acted(owner, recorded, kind), "Echo was never pressed"
    assert acted(owner, recorded, kind) == [] and picks(owner) == []


def test_a_keys_write_that_scrolls_back_over_an_unseen_wheel_holds_the_press() -> None:
    """Alfa clicked, and Home pressed: its write is queued. The wheel scrolls the list to Delta
    to Golf, and the user clicks Echo there before VCL paints. Home's write then scrolls back to
    Alfa, where the list last saw the rows, and the listener mapped the click's line to Bravo.
    The write reads the position before it scrolls too, finds the rows elsewhere, and holds every
    row."""
    owner = top()
    click(owner, row("Alfa"))
    owner.tree_key(HOME, 0)
    wheel(owner, 3, painted=False)
    queued_click(owner, row("Echo"), 0)
    owner.run_queue()
    assert in_view(owner) == NAMES[:4]
    assert "Bravo" not in picks(owner), "Bravo was never pressed"
    assert picks(owner) == [] and move_to_top(owner) is None


def test_the_keyboard_menus_scroll_back_over_an_unseen_wheel_holds_the_press() -> None:
    """Alfa clicked, and the menu key pressed: its work, which scrolls the list to Alfa and opens
    the menu for it, is queued. The wheel scrolls the list to Delta to Golf, and the user
    right-clicks Echo there before VCL paints. The menu's scroll brings back the rows where the
    list last saw them, and the right click's listener targeted Bravo, under its line then. The
    menu's scroll holds presses as a key's write does."""
    owner = top()
    opened: list[str | None] = []

    def open_menu(x: int, y: int, refs: Any = None, seen: int | None = None) -> None:
        target = owner._context_target
        names = [ref.name for ref in refs] if refs else [target.name] if target else [None]
        opened.extend(names)

    owner._open_menu = open_menu
    click(owner, row("Alfa"))
    owner.post(owner.open_menu_for_keyboard, "the sheet tab menu")
    wheel(owner, 3, painted=False)
    queued_click(owner, row("Echo"), 0, button=RIGHT)
    owner.run_queue()
    assert in_view(owner) == NAMES[:4]
    assert "Bravo" not in opened, "Bravo was never pressed"
    assert opened == ["Alfa", None] and picks(owner) == ["Alfa"]


def test_a_double_click_before_the_wheel_activates_nothing() -> None:
    """Both clicks of a double click on Bravo's line are made before the wheel scrolls the list
    to Delta to Golf, and VCL has not painted yet when their listeners run. The first listener
    finds the rows elsewhere and holds every row; the second, whose press came before that, runs
    held too. Without that hold the second found the position the first had noted, and the
    double click activated Echo."""
    owner = top()
    activated = record_activations(owner)
    queued_click(owner, row("Bravo"), 0)
    queued_click(owner, row("Bravo"), 0, clicks=2)
    wheel(owner, 3, painted=False)
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


def test_a_press_before_the_paint_of_a_scroll_is_refused_once() -> None:
    """The cost of the rule. The wheel scrolls the list, and the user clicks Echo before VCL has
    painted the scrolled rows. The list cannot tell that press from one made before the scroll,
    so it is refused; the next click acts."""
    owner = top()
    wheel(owner, 3, painted=False)
    queued_click(owner, row("Echo"), 0)
    owner.run_queue()
    assert picks(owner) == []
    queued_click(owner, row("Echo"), 0)
    owner.run_queue()
    assert picks(owner) == ["Echo"]


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
    picks with the notice."""
    owner, dragged = drag_after_reorder("Delta")
    notices = len(owner.notices)
    assert dragged == []
    owner.run_queue()
    assert picks(owner) == [] and len(owner.notices) == notices + 1
    assert move_to_top(owner) is None


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


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda book: None, id="unchanged"),
        pytest.param(lambda book: setattr(book.sheet("Golf"), "color", 0x336699), id="recoloured"),
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


@pytest.mark.parametrize(
    "painted, wanted",
    [
        pytest.param(False, [["Delta"]], id="before the paint: drags Delta"),
        pytest.param(True, [], id="after the paint: refused"),
    ],
)
def test_a_drag_across_the_wheel_drags_the_pressed_sheet_or_nothing(
    painted: bool, wanted: list[list[str]]
) -> None:
    """The user presses Delta, the wheel scrolls the list, and the gesture follows. The tree
    keeps Delta selected wherever it scrolls, so the gesture drags Delta. Once VCL has painted
    the scrolled rows, presses are held, and the gesture starts nothing: a cost of the rule."""
    owner = top()
    dragged = bind_drag(owner)
    native_press(owner, row("Delta"))
    wheel(owner, 3, painted=painted)
    owner.start_drag(object())
    assert dragged == wanted
