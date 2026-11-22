"""The simulated peer's mouse listener, key handler and Move to Top are the list's own, guards
included (#312, #320).

LibreOffice calls the list's mouse handlers through `_Mouse._handle`, which raises the pointer
depth, runs the handler under `_guarded`, and lowers the depth and queues the selection write as
it returns. A native failure inside `mouse_pressed` or `mouse_released` is therefore reported and
ends only that handler. `list_peer` loads `_Mouse` and `_guarded` from `uno_list.py` and runs the
handlers through them, so that tests and the review fuzzers built on the peer see such a failure
as LibreOffice does, rather than having it escape to their caller. Keys and Move to Top reach the
list the same way, through the key handler (`uno_keys.ListKeyHandler.keyPressed`) and the move
button's action listener (`uno_moves.MoveButtons.actionPerformed`), which report a failure and
return. The peer records each failure in `failures`, where `run_queue` records one that ends
posted work, and raises any exception that is not a simulated native failure: that is a defect of
the list or of a test.
"""

from typing import Any

import pytest

from tests.unit.list_peer import (
    DOWN,
    MOD2,
    SPACE,
    Book,
    NativeFailure,
    click,
    key,
    move_to_top,
    picks,
    press,
    queued_click,
    release,
    sheet_list,
    type_key,
)

NAMES = ["Alfa", "Bravo", "Charlie", "Delta", "Echo"]


def posted(owner: Any) -> list[str]:
    """The work waiting in the posted-work queue, by what it was posted for."""
    return [where for _, where in owner.queue]


def test_a_native_failure_in_a_press_listener_ends_only_that_listener() -> None:
    """Bravo is picked, and the tree handles a press on Delta, selecting it; the press's
    listener then fails at its first native call, which reads where the rows show. The failure
    is reported once, the call returns with the pointer depth lowered, and the listener has
    queued the selection write as it returned. That write shows Bravo again over the native
    press, no press is kept, and the next click acts."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    delta = owner.tree.node("Delta")
    owner.tree.selected, owner.tree.cursor = [delta], delta  # The native press.
    owner.faults.fail("getNodeRect")
    press(owner, 3)
    assert owner.faults.failed == ["getNodeRect"] and owner.failures == ["a mouse press"]
    assert owner._pointer_depth == 0 and owner._press is None
    assert posted(owner) == ["showing the selection"]
    owner.run_queue()
    assert owner.failures == ["a mouse press"]
    assert picks(owner) == ["Bravo"] and owner.tree.shown() == ["Bravo"]
    click(owner, 3)
    assert picks(owner) == ["Delta"] and owner.tree.shown() == ["Delta"]


def test_a_native_failure_in_a_release_listener_ends_only_that_listener() -> None:
    """Bravo and Delta are picked, and a plain press on Bravo keeps both, so that they can be
    dragged together. The tree's native release selects Bravo alone, and the release's listener
    fails when it reads where the rows show, to tell whether the button went up in the pressed
    row. The failure is reported once, the press has ended, and the write the listener queued as
    it returned shows both picks again: the release narrowed nothing, and Move to Top moves the
    sheets the tree shows."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    queued_click(owner, 3)  # A Ctrl+click on Delta.
    owner.run_queue()
    press(owner, 1)
    owner.run_queue()
    assert owner._press is not None and picks(owner) == ["Bravo", "Delta"]
    owner.faults.fail("getNodeRect")
    release(owner, 1)
    assert owner.faults.failed == ["getNodeRect"] and owner.failures == ["a mouse release"]
    assert owner._pointer_depth == 0 and owner._press is None
    assert posted(owner) == ["showing the selection"]
    owner.run_queue()
    assert owner.failures == ["a mouse release"]
    assert picks(owner) == ["Bravo", "Delta"] and owner.tree.shown() == ["Bravo", "Delta"]
    assert move_to_top(owner) == ["Bravo", "Delta"]


def test_a_failure_in_a_queued_listener_is_reported_once() -> None:
    """A click whose listeners LibreOffice runs from its queue, as `queued_click` posts them: the
    press's listener fails, and the guard reports it, not the queue as well. The release's
    listener still runs, finds no press, and its write shows Bravo again over the native
    selection of Delta."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    queued_click(owner, 3, modifiers=0)
    owner.faults.fail("getNodeRect")
    owner.run_queue()
    assert owner.faults.failed == ["getNodeRect"] and owner.failures == ["a mouse press"]
    assert owner._pointer_depth == 0 and owner._press is None
    assert picks(owner) == ["Bravo"] and owner.tree.shown() == ["Bravo"]


def test_the_peer_raises_what_no_native_call_raises() -> None:
    """A failure other than a simulated native one is a defect of the list or of a test, which
    LibreOffice would report too. The peer raises it out of the listener, after the listener
    has lowered the pointer depth, and records nothing, so that no test passes over it."""
    owner = sheet_list(Book(list(NAMES)))

    def broken(node: Any) -> Any:
        raise LookupError("not a native failure")

    owner.tree.getNodeRect = broken
    with pytest.raises(LookupError, match="not a native failure"):
        press(owner, 1)
    assert owner.failures == [] and owner._pointer_depth == 0


def fail_next_acknowledgement(owner: Any, error: Exception) -> None:
    """Make the tab observer's next acknowledgement of the list's input fail, as its post to
    LibreOffice's main thread can (`TabObserver.note_input`, `AsyncCallback.addCallback`)."""
    note = owner._tabs.note_input

    def note_input() -> None:
        owner._tabs.note_input = note
        raise error

    owner._tabs.note_input = note_input


def test_a_native_failure_in_a_key_ends_only_that_key() -> None:
    """Bravo is picked, and Down's handling fails as the key notes the input, before it changes
    anything. The key handler reports the failure once and still consumes the key, as it tells
    LibreOffice; the picks and the tree are unchanged, and the next Down acts."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    fail_next_acknowledgement(owner, NativeFailure("addCallback"))
    assert key(owner, DOWN) is True
    assert owner.failures == ["the key handler"]
    assert picks(owner) == ["Bravo"] and owner.tree.shown() == ["Bravo"]
    assert key(owner, DOWN) is True
    assert owner.failures == ["the key handler"]
    assert picks(owner) == ["Charlie"] and owner.tree.shown() == ["Charlie"]


@pytest.mark.parametrize("fails", [False, True], ids=["control", "select fails"])
def test_a_native_failure_in_type_ahead_ends_only_that_work(fails: bool) -> None:
    """Typing "d" goes through the key handler, which notes the input and queues type-ahead
    (`queue_input`), and the key is consumed. Type-ahead picks Delta; when its write's `select`
    fails, that work ends, recorded once as "type-ahead", and the tree still shows Bravo."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    inputs = owner._input
    if fails:
        owner.faults.fail("select")
    assert type_key(owner, "d") is True
    assert owner._input > inputs and picks(owner) == ["Delta"]
    assert owner.failures == (["type-ahead"] if fails else [])
    assert owner.tree.shown() == (["Bravo"] if fails else ["Delta"])


def test_a_native_failure_in_move_to_top_ends_only_that_press() -> None:
    """Bravo is picked, and Move to Top's read of the tree's selection, before it queues the
    move, fails. The move button's listener reports the failure once; nothing moves, no message
    shows, and the next Move to Top moves Bravo."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    owner.faults.fail("getSelection")
    assert move_to_top(owner) == "failed"
    assert owner.faults.failed == ["getSelection"] and owner.failures == ["a move button"]
    assert owner.book.moved == [] and owner.errors == []
    assert move_to_top(owner) == ["Bravo"]
    assert owner.failures == ["a move button"]


def test_keys_and_move_to_top_raise_what_no_native_call_raises() -> None:
    """As for the mouse listeners, an exception that is not a simulated native failure is raised
    out of the key handler and the move button's listener, and nothing is recorded."""
    owner = sheet_list(Book(list(NAMES)))
    click(owner, 1)
    fail_next_acknowledgement(owner, LookupError("not a native failure"))
    with pytest.raises(LookupError, match="not a native failure"):
        key(owner, DOWN)

    def broken() -> Any:
        raise LookupError("not a native failure either")

    owner.tree.getSelection = broken
    with pytest.raises(LookupError, match="not a native failure either"):
        move_to_top(owner)
    assert owner.failures == [] and owner.book.moved == []


@pytest.mark.parametrize(
    "code,modifiers", [(SPACE, 0), (DOWN, MOD2)], ids=["Space", "Alt+Down"]
)
def test_key_takes_only_keys_the_handler_gives_the_tree(code: int, modifiers: int) -> None:
    """Plain Space means nothing in the list, and Alt+Down moves the picks: the key handler
    gives neither to the tree, so `key` refuses them before the handler sees them, rather than
    let a test's key mean something else than the test says."""
    owner = sheet_list(Book(list(NAMES)))
    inputs = owner._input
    with pytest.raises(AssertionError, match="is not a tree key"):
        key(owner, code, modifiers)
    assert owner._input == inputs
