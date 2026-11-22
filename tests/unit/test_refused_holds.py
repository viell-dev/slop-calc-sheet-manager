"""Held clicks that the list refuses, and the keyboard cursor they keep (#71).

A press on a picked row is decided by its release: in place, it narrows the picks to that sheet,
or a double click activates it. If a refresh during the press moved the pressed sheet away or
showed another sheet under its name, the release has no effect at all (#28), and the list writes
its own picks back. The tree's native release has already moved its cursor to the row under the
pointer before the list's mouse listener runs (#70). The list ignores native cursor events while
the press is held, so its own cursor is still where the user put it: on the pressed sheet, on a
newer typed pick, or wherever the keys took it, also outside the picks. The refusal keeps that
cursor while it is still its sheet, and Ctrl+Space then toggles the row the user sees it on. Only
a cursor whose sheet is gone falls back to a surviving pick, preferring the pressed sheet while
the press still identifies it.

The real list runs over the simulated peer of `list_peer`. Showing a cursor outside the picks
takes a write that selects the cursor's row and then clears the selection before adding the
picks. When a call between the two failed, the row stayed selected and the intake took it as the
user's pick, so Move to Top moved a sheet nobody picked (#243, #257). The failure tests fail each
native call of the release in turn, in its listener and in the work it queues, and the invariant
is the safety rules' one: a command acts on exactly the sheets the user picked, or on none. No
native trigger for these failures is known.
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.list_peer import (
    DOWN,
    END,
    LEFT,
    MOD1,
    SHIFT,
    SPACE,
    UP,
    A,
    Book,
    Handle,
    changed,
    click,
    cursor,
    focus_event,
    key,
    move_to_top,
    picks,
    press,
    queued_click,
    release,
    sheet_list,
)

NAMES = [
    "Alfa",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
    "India",
    "Juliett",
    "Kilo",
    "Lima",
]
# The rows once another window has moved Bravo to the seventh place, as the issue's steps do.
MOVED = [*NAMES[:1], *NAMES[2:7], "Bravo", *NAMES[7:]]
PRESSED = NAMES.index("Bravo")  # The pressed row, which shows Charlie after the move.
MIDDLE = 4  # com.sun.star.awt.MouseButton.MIDDLE


def refresh_now(owner: Any) -> None:
    """Another window's change, shown by the refresh that its notification schedules."""
    changed(owner)
    owner.retry()


def held_bravo(*others: str) -> Any:
    """Bravo picked by a click and `others` by Ctrl+clicks, then Bravo pressed again and held
    while another window moves it to row 6; the refresh shows the move (#71's reproduction)."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, PRESSED)
    for name in others:
        queued_click(owner, NAMES.index(name))
        owner.run_queue()
    press(owner, PRESSED)
    owner.run_queue()
    owner.book.move("Bravo", 6)
    refresh_now(owner)
    assert owner.names() == MOVED and owner._press is not None
    assert set(picks(owner)) == {"Bravo", *others}
    assert cursor(owner) == "Bravo" and owner.tree.cursor.DataValue == "Bravo"
    return owner


def late_release(owner: Any, row: int = PRESSED) -> None:
    """The release as LibreOffice delivers it, then the work it queues.

    The tree's native release selects the row under the pointer and moves its cursor there,
    which its accessibility event reports at once, while the press is still held; the list's
    mouse listener runs after that (#70). A native failure in the listener ends only the
    listener and is recorded as "a mouse release", as the list's own listener guard reports it
    (`list_peer.listen`).
    """
    node = owner.tree._installed()[row]
    owner.tree.selected, owner.tree.cursor = [node], node
    focus_event(owner, row)
    release(owner, row)
    owner.run_queue()


def shown_cursor(owner: Any) -> str | None:
    """The row the tree's own keyboard cursor is on, which Ctrl+Space toggles as the user sees."""
    node = owner.tree.cursor
    return node.DataValue if node is not None else None


def nothing(owner: Any) -> None:
    pass


def type_d(owner: Any) -> None:
    owner.post(lambda: owner.type_ahead("d"), "type-ahead")
    owner.run_queue()


def ctrl_down(owner: Any) -> None:
    key(owner, DOWN, MOD1)


def ctrl_up_to_delta(owner: Any) -> None:
    for _ in range(4):
        key(owner, UP, MOD1)


def held_ctrl_down(owner: Any) -> None:
    """Ctrl+Down held: the repeated keys arrive before their queued write runs."""
    for _ in range(4):
        owner.tree_key(DOWN, MOD1)
    owner.run_queue()


@pytest.mark.parametrize(
    "others,hold,restored,kept,toggled",
    [
        pytest.param((), nothing, ["Bravo"], "Bravo", [], id="pressed sheet"),
        pytest.param((), type_d, ["Delta"], "Delta", [], id="newer typed pick"),
        pytest.param((), ctrl_down, ["Bravo"], "Hotel", ["Bravo", "Hotel"], id="Ctrl+Down"),
        pytest.param(("Delta",), ctrl_up_to_delta, ["Delta", "Bravo"], "Delta", ["Bravo"],
                     id="another pick"),
        pytest.param((), held_ctrl_down, ["Bravo"], "Kilo", ["Bravo", "Kilo"], id="key repeat"),
    ],
)  # fmt: skip
def test_a_refused_release_keeps_the_cursor_the_user_left(
    others: tuple[str, ...],
    hold: Callable[[Any], None],
    restored: list[str],
    kept: str,
    toggled: list[str],
) -> None:
    """#71's reproduction and its controls. During the hold, the user gives the case's input,
    and the button goes up over the pressed row, which shows Charlie now. The refusal restores
    the picks, and both the list's cursor and the tree's stay where the input left them, rather
    than returning to the pressed sheet: Ctrl+Space then toggles that row, and Move to Top
    moves the result."""
    owner = held_bravo(*others)
    hold(owner)
    assert cursor(owner) == kept and shown_cursor(owner) == kept
    late_release(owner)
    assert owner._press is None and owner.failures == []
    assert set(picks(owner)) == set(restored) and owner.tree.shown() == restored
    assert cursor(owner) == kept and shown_cursor(owner) == kept
    key(owner, SPACE, MOD1)
    assert picks(owner) == toggled and owner.tree.shown() == toggled
    assert move_to_top(owner) == (toggled or None)


def test_a_refused_release_keeps_the_cursor_when_no_pick_survives() -> None:
    """Ctrl+Space unpicks Bravo during the hold and Ctrl+Down moves on to Hotel. Nothing is
    picked when the button goes up, and the cursor stays on Hotel, whose Ctrl+Space picks it."""
    owner = held_bravo()
    key(owner, SPACE, MOD1)
    ctrl_down(owner)
    late_release(owner)
    assert picks(owner) == [] and owner.tree.shown() == []
    assert cursor(owner) == "Hotel" and shown_cursor(owner) == "Hotel"
    key(owner, SPACE, MOD1)
    assert picks(owner) == ["Hotel"] and owner.tree.shown() == ["Hotel"]


@pytest.mark.parametrize(
    "keys,result",
    [
        pytest.param(((DOWN, 0),), ["India"], id="Down"),
        pytest.param(((DOWN, SHIFT),), ["Bravo", "Hotel", "India"], id="Shift+Down"),
        pytest.param(((DOWN, MOD1), (SPACE, MOD1)), ["Bravo", "India"], id="Ctrl+Down, Space"),
    ],
)
def test_keys_after_a_refused_release_continue_from_the_kept_cursor(
    keys: tuple[tuple[int, int], ...], result: list[str]
) -> None:
    """Ordinary movement and selection after the refusal start where the user left the cursor,
    Hotel, outside the picks; a range starts at the anchor the click on Bravo set."""
    owner = held_bravo()
    ctrl_down(owner)
    late_release(owner)
    for code, modifiers in keys:
        key(owner, code, modifiers)
    assert picks(owner) == result and owner.tree.shown() == result


def test_another_buttons_release_leaves_the_held_left_press_and_its_gate() -> None:
    """A release names only the button released (`ImplHandleSalMouseButtonUp`). A middle release
    while the left button is held must not end the left press: the native release that follows
    would otherwise reach the list's cursor before the left release's listener ran."""
    owner = held_bravo()
    ctrl_down(owner)
    held = owner._press
    release(owner, PRESSED, button=MIDDLE)
    owner.run_queue()
    assert owner._press is held
    focus_event(owner, PRESSED)  # Still ignored: the left button is down.
    assert cursor(owner) == "Hotel"
    late_release(owner)
    assert picks(owner) == ["Bravo"] and cursor(owner) == "Hotel"


@pytest.mark.parametrize("unpicked,lost", [(False, "Bravo"), (True, "Alfa")])
def test_a_refresh_during_the_hold_gives_a_lost_cursor_to_the_pressed_pick(
    unpicked: bool, lost: str
) -> None:
    """Alfa and Bravo are picked, and Bravo is held while another window moves it. Ctrl+Down
    takes the cursor to Hotel, and another window renames Hotel before the release. The refresh
    drops Hotel's ref while Bravo is still held and gives the cursor to the pressed sheet, which
    merely moved, or to the first pick once Ctrl+Space has unpicked Bravo. The refusal keeps the
    cursor that refresh wrote, as it would have chosen it itself."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 0)
    queued_click(owner, PRESSED)
    owner.run_queue()
    press(owner, PRESSED)
    owner.run_queue()
    owner.book.move("Bravo", 6)
    refresh_now(owner)
    if unpicked:
        key(owner, SPACE, MOD1)
    ctrl_down(owner)
    assert cursor(owner) == "Hotel"
    owner.book.rename("Hotel", "Hotel 2")
    refresh_now(owner)
    assert cursor(owner) == lost and shown_cursor(owner) == lost
    refused = owner._selection.cursor
    late_release(owner)
    assert picks(owner) == (["Alfa"] if unpicked else ["Alfa", "Bravo"])
    assert owner._selection.cursor is refused and shown_cursor(owner) == lost
    key(owner, SPACE, MOD1)
    assert picks(owner) == ([] if unpicked else ["Alfa"])


def test_a_voided_press_gives_its_same_name_replacement_no_cursor_preference() -> None:
    """Bravo, held, is replaced under its name, and the refresh drops every pick and voids the
    press. Ctrl+A then picks every sheet, the replacement Bravo among them, and Ctrl+End puts
    the cursor on Lima, which another window renames before the release. Neither that refresh
    nor the refusal may give the cursor to the replacement for the pressed sheet's name: the
    first pick takes it, and Ctrl+Space unpicks Alfa."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, PRESSED)
    press(owner, PRESSED)
    owner.run_queue()
    owner.book.replace("Bravo")
    refresh_now(owner)
    assert owner._press.voided and picks(owner) == []
    key(owner, A, MOD1)
    key(owner, END, MOD1)
    assert cursor(owner) == "Lima"
    owner.book.rename("Lima", "Lima 2")
    refresh_now(owner)
    assert cursor(owner) == "Alfa"
    late_release(owner)
    assert cursor(owner) == "Alfa" and shown_cursor(owner) == "Alfa"
    key(owner, SPACE, MOD1)
    assert picks(owner) == NAMES[1:-1]


def test_a_sheet_renamed_to_the_pressed_name_gets_no_cursor_preference() -> None:
    """While Bravo is held, others rename it to Bravo 2 and then Charlie to Bravo, one refresh
    each, so the proof holds and the press is not voided. Ctrl+A picks the renamed Charlie under
    the pressed name, and a rename of Lima drops the cursor. The press's handle reports Bravo 2,
    so the pick named Bravo is another sheet: the first pick takes the cursor."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 0)
    queued_click(owner, PRESSED)
    owner.run_queue()
    press(owner, PRESSED)
    owner.run_queue()
    owner.book.rename("Bravo", "Bravo 2")
    refresh_now(owner)
    owner.book.rename("Charlie", "Bravo")
    refresh_now(owner)
    key(owner, A, MOD1)
    key(owner, END, MOD1)
    owner.book.rename("Lima", "Lima 2")
    refresh_now(owner)
    assert not owner._press.voided
    assert cursor(owner) == "Alfa"
    late_release(owner)
    assert cursor(owner) == "Alfa" and shown_cursor(owner) == "Alfa"


def test_a_refused_release_before_a_refresh_proves_the_change_picks_nothing() -> None:
    """Ctrl+Down takes the cursor to Hotel, and another window then replaces Hotel under its
    name, an insertion and a deletion that no refresh has proved when the button goes up. A
    retained handle may then report its name for another sheet, so nothing the list held stands:
    the refresh that the release's queued write makes first drops every pick and the cursor, and
    no command acts on Hotel's replacement or on anything else."""
    owner = held_bravo()
    ctrl_down(owner)
    owner.book.replace("Hotel")
    late_release(owner)
    assert owner._proven == owner.book.generation
    assert picks(owner) == [] and cursor(owner) is None and owner.tree.shown() == []
    assert move_to_top(owner) is None
    owner.retry()
    assert move_to_top(owner) is None


@pytest.mark.parametrize("fails", [False, True], ids=["written", "its clear fails"])
def test_a_refused_release_after_a_second_lost_proof_clears_the_row_it_selected(
    fails: bool,
) -> None:
    """Bravo, held, is replaced under its name, and the refresh drops every pick and the cursor
    and voids the press, so the record says the tree shows nothing. Hotel is replaced too before
    the release, which the tree answers by selecting the pressed row, the replacement Bravo's.
    The refresh the release asks for has no pick left to drop and rows that read the same, so it
    writes nothing of its own. When the release's clear fails (#315), the record must not still say
    that the tree shows nothing: the intake took the replacement Bravo, and Move to Top moved a
    sheet nobody picked, on `main` too."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, PRESSED)
    press(owner, PRESSED)
    owner.run_queue()
    replacement = owner.book.replace("Bravo")
    refresh_now(owner)
    assert owner._press.voided and picks(owner) == [] and owner.tree.shown() == []
    assert owner._selection.cursor is None and owner._shown == ()
    owner.book.replace("Hotel")
    if fails:
        owner.faults.fail("clearSelection")
    late_release(owner)
    assert owner.faults.failed == (["clearSelection"] if fails else [])
    assert owner._proven == owner.book.generation
    assert move_to_top(owner) is None
    owner.retry()
    assert move_to_top(owner) is None
    assert owner.tree.shown() == [] and owner._current_picks() == []
    assert owner.book.sheets[1] is replacement and owner.book.moved == []


def test_a_refused_release_whose_two_writes_fail_leaves_the_released_row_to_no_one() -> None:
    """The one-pick form (#315): Bravo alone is picked and held while it moves, so the release's
    write and the one it queues both select Bravo's row again, writes that kept the record when
    the tree showed that pick. But the native release has selected Charlie's row, and when both
    selects fail, the intake took Charlie as a pick and Move to Top moved it, on `main` too."""
    owner = held_bravo()
    owner.faults.fail("select", times=2)
    late_release(owner)
    assert owner.faults.failed == ["select", "select"]
    assert owner.tree.shown() == ["Charlie"]
    assert move_to_top(owner) is None
    owner.retry()
    assert move_to_top(owner) is None
    assert "Charlie" not in picks(owner) and owner.book.moved == []


def test_a_pick_made_after_a_lost_proof_survives_a_refused_release() -> None:
    """The control: after the refresh that dropped the picks, Down picks the replacement Bravo
    at the proved generation, and the refused release keeps that newer pick."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, PRESSED)
    press(owner, PRESSED)
    owner.run_queue()
    replacement = owner.book.replace("Bravo")
    refresh_now(owner)
    key(owner, DOWN)
    late_release(owner)
    current = owner._current_picks()
    assert [ref.name for ref in current] == ["Bravo"]
    assert current[0].token is owner.book.handle(replacement)
    assert owner.tree.shown() == ["Bravo"] and move_to_top(owner) == ["Bravo"]


def test_a_failed_listener_write_still_keeps_the_cursor() -> None:
    """The listener's write fails at its first call, after the native release selected Charlie's
    row. The list's cursor is still the one the user left, Hotel, and the write the listener
    queued shows it; the record stays unknown in between, so nothing takes Charlie."""
    owner = held_bravo()
    ctrl_down(owner)
    owner.faults.fail("getModel")
    late_release(owner)
    assert owner.failures == ["a mouse release"]
    assert cursor(owner) == "Hotel" and shown_cursor(owner) == "Hotel"
    assert picks(owner) == ["Bravo"] and owner.tree.shown() == ["Bravo"]
    assert move_to_top(owner) == ["Bravo"]


def test_work_run_inside_the_listeners_write_keeps_its_cursor() -> None:
    """A UNO call in a mouse listener can let queued work run inside it (`_Mouse._handle`). Here
    type-ahead runs inside the refused release's `addSelection` and picks Echo, moving the cursor
    there. The listener puts back only the cursor it set for its own write, so Echo stays the
    cursor, as on `main`, rather than the older Hotel."""
    owner = held_bravo("Delta")
    ctrl_down(owner)
    add = owner.tree.addSelection
    ran: list[bool] = []

    def add_running_type_ahead(node: Any) -> None:
        add(node)
        if owner._pointer_depth and not ran:
            ran.append(True)
            owner.type_ahead("e")

    owner.tree.addSelection = add_running_type_ahead
    late_release(owner)
    assert ran and owner.failures == []
    assert picks(owner) == ["Echo"] and cursor(owner) == "Echo"
    assert shown_cursor(owner) == "Echo" and owner.tree.shown() == ["Echo"]


def test_a_voided_press_gives_a_sheet_under_its_name_no_cursor_preference() -> None:
    """Charlie, held, is deleted, so its handle turns to Bravo, which another window then renames
    Charlie: the press's handle reports the pressed name again. The refresh drops every pick and
    voids the press. Ctrl+A picks every sheet and Ctrl+End moves the cursor to Lima, which a
    rename drops. The pick under the pressed name is the renamed Bravo, not the pressed sheet, so
    the first pick takes the cursor, and the refusal keeps it."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 2)
    press(owner, 2)
    owner.run_queue()
    owner.book.delete("Charlie")
    owner.book.rename("Bravo", "Charlie")
    refresh_now(owner)
    assert owner._press.voided and owner._press.handle.getName() == "Charlie"
    key(owner, A, MOD1)
    key(owner, END, MOD1)
    owner.book.rename("Lima", "Lima 2")
    refresh_now(owner)
    assert cursor(owner) == "Alfa"
    late_release(owner, 2)
    assert cursor(owner) == "Alfa" and shown_cursor(owner) == "Alfa"


def unpicked_bravo_held() -> Any:
    """Bravo, picked and held, moves to row 6, and Ctrl+Space unpicks it: nothing is picked."""
    owner = held_bravo()
    key(owner, SPACE, MOD1)
    assert picks(owner) == [] and cursor(owner) == "Bravo" and owner.tree.shown() == []
    return owner


@pytest.mark.parametrize("after", [0, 1])
def test_a_failed_clear_after_a_refused_release_leaves_no_pick(after: int) -> None:
    """Then Charlie is replaced under its name, and the button goes up over Charlie's row before
    the refresh, which the tree answers by selecting it. One clear of the tree fails: the first
    the release makes, or the next (`after`). Neither the retry nor the next command may take
    Charlie, the replacement, as the user's pick."""
    owner = unpicked_bravo_held()
    owner.book.replace("Charlie")
    owner.faults.fail("clearSelection", after=after)
    late_release(owner)
    assert owner.faults.failed == ["clearSelection"]
    owner.retry()
    assert owner._current_picks() == []
    assert picks(owner) == [] and owner.tree.shown() == []
    assert move_to_top(owner) is None


def test_a_failed_model_assignment_after_a_refused_release_leaves_no_pick() -> None:
    """Then another window inserts a sheet, and the button goes up over Charlie's row before the
    refresh. That refresh rebuilds the rows, and its new data model is refused, which leaves the
    old tree. Neither the next command nor the retry may take Charlie, a sheet the user only
    released the refused click over."""
    owner = unpicked_bravo_held()
    owner.book.insert("Mike", len(NAMES))
    owner.faults.fail("DataModel")
    late_release(owner)
    assert owner.faults.failed == ["DataModel"]
    assert owner._current_picks() == [] and move_to_top(owner) is None
    owner.retry()
    assert owner._current_picks() == [] and move_to_top(owner) is None
    assert picks(owner) == [] and owner.tree.shown() == []


def moved(owner: Any) -> list[str] | str | None:
    """Move to Top's result, with the moved sheets in row order as `expected` names them."""
    result = move_to_top(owner)
    if isinstance(result, list):
        return [name for name in owner.names() if name in result]
    return result


def bravo_hotel() -> Any:
    """Bravo picked and held while it moves, and Ctrl+Down to the unpicked Hotel."""
    owner = held_bravo()
    ctrl_down(owner)
    return owner


def no_pick_hotel() -> Any:
    """Bravo picked and held while it moves, unpicked, and Ctrl+Down to Hotel."""
    owner = unpicked_bravo_held()
    ctrl_down(owner)
    return owner


def other_pick_delta() -> Any:
    """Bravo and Delta picked, Bravo held while it moves, and Ctrl+Up to Delta."""
    owner = held_bravo("Delta")
    ctrl_up_to_delta(owner)
    return owner


def charlie_replaced() -> Any:
    """Bravo picked and held while it moves, Ctrl+Down to Hotel, and Charlie, whose row the
    button goes up over, replaced under its name before any refresh."""
    owner = bravo_hotel()
    owner.book.replace("Charlie")
    return owner


@pytest.mark.parametrize(
    "setup,expected",
    [
        pytest.param(bravo_hotel, ["Bravo"], id="cursor outside the picks"),
        pytest.param(no_pick_hotel, [], id="no pick survives"),
        pytest.param(other_pick_delta, ["Delta", "Bravo"], id="cursor on another pick"),
        pytest.param(charlie_replaced, [], id="released over a replacement"),
    ],
)
def test_each_failed_call_of_a_refused_release_leaves_no_wrong_pick(
    setup: Callable[[], Any], expected: list[str]
) -> None:
    """#243's last review: with the cursor kept outside the picks, the queued write selects the
    cursor's row and then clears it. A failed clear, or a failed restore of multiple selection,
    left that row selected, the intake took it, and Move to Top moved Hotel, which the user never
    picked. Each native call of the release, in its listener and in the work it queues, fails in
    turn here. If the tree then shows exactly the picks, Move to Top moves them, at once or after
    one refusal; otherwise the list cannot tell part of its write from a selection made since,
    so it refuses, and the picks are dropped and the tree cleared (#257). Hotel never moves."""
    owner = setup()
    start = len(owner.faults.calls)
    late_release(owner)
    calls = owner.faults.calls[start:]
    assert calls and owner.failures == []
    broken: list[tuple[object, ...]] = []
    for index, call in enumerate(calls):
        owner = setup()
        owner.faults.nth = len(owner.faults.calls) + index
        late_release(owner)
        assert owner.faults.failed == [call], (index, call, owner.faults.failed)
        shown = owner.tree.shown()
        want = (expected or None) if shown == expected else None
        first = moved(owner)
        owner.run_queue()
        owner.retry()
        owner.run_queue()
        second = moved(owner)
        if first not in (want, None) or second != want:
            broken.append((index, call, shown, first, second))
        elif want is None and (picks(owner) or owner.tree.shown()):
            broken.append((index, call, shown, picks(owner), owner.tree.shown()))
    assert broken == []


@pytest.mark.parametrize(
    "others,hold",
    [
        pytest.param((), ctrl_down, id="cursor outside the picks"),
        pytest.param(("Delta",), ctrl_up_to_delta, id="cursor on another pick"),
        pytest.param((), held_ctrl_down, id="key repeat"),
    ],
)
def test_the_refused_release_listener_makes_the_same_calls_as_for_the_pressed_sheet(
    others: tuple[str, ...], hold: Callable[[Any], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mouse listener runs without LibreOffice's solar mutex, and it may only read the tree,
    the handles and the document and write a refused release's picks back (`SheetList`,
    AGENTS.md "Listeners"). Keeping the cursor adds no call there: the listener writes the picks
    with the tree's cursor on one of them and reads the same handles, as for a cursor left on
    the pressed sheet, and the queued write moves the tree's cursor to the list's. Only that
    posted write makes the clear an unpicked cursor's row needs, and a failure there leaves the
    record unknown (#257)."""
    reads: list[str] = []
    read = Handle.getName

    def counted(handle: Handle) -> str:
        reads.append(handle.sheet.name)
        return read(handle)

    monkeypatch.setattr(Handle, "getName", counted)

    def listener_calls(hold: Callable[[Any], None]) -> tuple[list[str], int]:
        owner = held_bravo(*others)
        hold(owner)
        calls, handles = len(owner.faults.calls), len(reads)
        node = owner.tree._installed()[PRESSED]
        owner.tree.selected, owner.tree.cursor = [node], node
        owner.mouse_released(SimpleNamespace(Buttons=LEFT, X=0, Y=owner.tree.line(PRESSED)))
        return owner.faults.calls[calls:], len(reads) - handles

    assert listener_calls(hold) == listener_calls(nothing)


def test_a_cursor_lost_after_the_last_refresh_goes_to_the_pressed_pick() -> None:
    """Alfa and Bravo are picked, Bravo is held while another window moves it, and Ctrl+Down
    takes the cursor to Hotel. Another window renames Hotel, and the button goes up before the
    refresh: the release finds the cursor's sheet gone and gives the cursor to the pressed
    pick, as before #71, and the refresh after it keeps that."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 0)
    queued_click(owner, PRESSED)
    owner.run_queue()
    press(owner, PRESSED)
    owner.run_queue()
    owner.book.move("Bravo", 6)
    refresh_now(owner)
    ctrl_down(owner)
    owner.book.rename("Hotel", "Hotel 2")
    changed(owner)
    late_release(owner)
    assert cursor(owner) == "Bravo" and shown_cursor(owner) == "Bravo"
    owner.retry()
    assert set(picks(owner)) == {"Alfa", "Bravo"} and cursor(owner) == "Bravo"
    key(owner, SPACE, MOD1)
    assert picks(owner) == ["Alfa"]
