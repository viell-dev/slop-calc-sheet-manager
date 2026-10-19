"""A stalled main-thread callback fails the suite and never hides an earlier failure (#50)."""

from collections.abc import Iterator

import pytest

from tests.integration.teardown import (
    close_leftovers,
    record_stalled_callback,
    run_checks,
    stalled_callbacks,
    start_session,
)


@pytest.fixture(autouse=True)
def fresh_session() -> Iterator[None]:
    start_session()
    yield
    start_session()


class Office:
    """Closes fake documents; one can time out as close_document does, others can be broken."""

    def __init__(self, stall_at: str | None = None, broken: tuple[str, ...] = ()) -> None:
        self.stall_at, self.broken = stall_at, broken
        self.attempts: list[str] = []
        self.closed: list[str] = []

    def close(self, document: str) -> None:
        self.attempts.append(document)
        if document == self.stall_at:
            record_stalled_callback(f"{document} did not close")
            raise TimeoutError(f"{document} did not close")
        if document in self.broken:
            raise RuntimeError(f"{document} is disposed")
        self.closed.append(document)


def fail() -> object:
    raise AssertionError("check failed")


def test_passing_checks_return_their_results_after_closing_leftovers() -> None:
    office = Office()
    checks = [("one", lambda: None), ("two", lambda: "value")]
    assert run_checks(checks, ["left"], office.close) == {"one": True, "two": "value"}
    assert office.closed == ["left"]


def test_cleanup_only_timeout_fails_the_suite_and_stops_closing() -> None:
    office = Office(stall_at="second")
    documents = ["first", "second"]
    with pytest.raises(TimeoutError, match="main thread stopped running callbacks"):
        run_checks([("one", lambda: True), ("two", lambda: True)], documents, office.close)
    assert office.attempts == ["second"], "No close may follow a timeout"
    assert documents == ["first"]
    assert stalled_callbacks() == ["second did not close"]


def test_earlier_failure_stays_raised_when_cleanup_times_out() -> None:
    office = Office(stall_at="left")
    ran: list[str] = []
    checks = [("one", lambda: ran.append("one")), ("two", fail), ("three", lambda: ran.append("3"))]
    with pytest.raises(AssertionError, match="check failed") as caught:
        run_checks(checks, ["left"], office.close)
    assert ran == ["one"]
    notes = caught.value.__notes__
    assert any("main thread stopped running callbacks" in note for note in notes), notes
    assert stalled_callbacks() == ["left did not close"]


def test_no_close_is_tried_after_a_stall_inside_a_check() -> None:
    office = Office()

    def stalls() -> object:
        record_stalled_callback("work did not finish")
        raise AssertionError("work did not finish")

    with pytest.raises(AssertionError, match="work did not finish"):
        run_checks([("stalls", stalls)], ["a", "b"], office.close)
    assert office.attempts == []


def test_a_stall_that_a_check_swallowed_still_fails_the_suite() -> None:
    ran: list[str] = []

    def swallows() -> object:
        record_stalled_callback("a close timed out")  # Recorded by close_document, then caught.
        return True

    checks = [("swallows", swallows), ("later", lambda: ran.append("later"))]
    with pytest.raises(TimeoutError, match="a close timed out"):
        run_checks(checks, [], Office().close)
    assert ran == [], "No check may run against a stuck office"


def test_a_failed_leftover_close_is_raised_after_the_other_closes() -> None:
    office = Office(broken=("broken",))
    documents = ["kept", "broken", "other"]
    with pytest.raises(AssertionError, match="broken is disposed"):
        close_leftovers(documents, office.close, None)
    assert office.closed == ["other", "kept"] and documents == []


def test_a_failed_close_during_a_failure_becomes_its_note() -> None:
    failure = AssertionError("check failed")
    close_leftovers(["broken"], Office(broken=("broken",)).close, failure)
    assert "broken is disposed" in failure.__notes__[0]


def test_an_unrecorded_timeout_still_stops_cleanup() -> None:
    attempts: list[str] = []

    def close(document: str) -> None:
        attempts.append(document)
        raise TimeoutError("late")

    with pytest.raises(TimeoutError):
        close_leftovers(["a", "b"], close, None)
    assert attempts == ["b"] and stalled_callbacks() == ["late"]


def test_a_new_session_forgets_earlier_stalls() -> None:
    record_stalled_callback("earlier session")
    start_session()
    assert stalled_callbacks() == []
    assert run_checks([("one", lambda: True)], [], Office().close) == {"one": True}
