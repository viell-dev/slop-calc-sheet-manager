"""The simulated peer's mouse listener is the list's own, guard included (#312).

LibreOffice calls the list's mouse handlers through `_Mouse._handle`, which raises the pointer
depth, runs the handler under `_guarded`, and lowers the depth and queues the selection write as
it returns. A native failure inside `mouse_pressed` or `mouse_released` is therefore reported and
ends only that handler. `list_peer` loads `_Mouse` and `_guarded` from `uno_list.py` and runs the
handlers through them, so that tests and the review fuzzers built on the peer see such a failure
as LibreOffice does, rather than having it escape to their caller. The peer records the failure in
`failures`, where `run_queue` records one that ends posted work, and raises any exception that is
not a simulated native failure: that is a defect of the list or of a test.
"""

from typing import Any

import pytest

from tests.unit.list_peer import (
    Book,
    click,
    move_to_top,
    picks,
    press,
    queued_click,
    release,
    sheet_list,
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
