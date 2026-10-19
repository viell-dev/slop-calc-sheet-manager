"""Test clean-up that neither hides a failure nor waits on a stalled office. No UNO dependency.

On Windows the tests close Calc documents, and run some steps, through callbacks on
LibreOffice's main thread (`main_thread.py`). When such a callback does not finish in time, the
main thread is stuck and its outcome is unknown (#50): no further callback is tried, the session
fails, and the runner stops its office instead of asking it to terminate, which would wait for
the stuck thread too (#40). An earlier failure stays the one raised, with the timeout as a note,
so that neither hides the other.
"""

from collections.abc import Callable, Iterable
from contextlib import suppress
from typing import Any

_stalled: list[str] = []


def start_session() -> None:
    """Forget stalled callbacks of an earlier office session in this process."""
    _stalled.clear()


def record_stalled_callback(message: str) -> None:
    """Note that a main-thread callback did not finish; the session then fails."""
    _stalled.append(message)


def stalled_callbacks() -> list[str]:
    return list(_stalled)


def _note(error: BaseException, message: str) -> None:
    with suppress(Exception):  # A PyUNO exception may refuse new attributes (#41).
        error.add_note(message)


def close_leftovers(
    documents: list[Any], close: Callable[[Any], None], failure: BaseException | None
) -> None:
    """Close and forget each document in `documents`, unless a callback has stalled.

    `failure` is the exception ending the block that left them open, or None. After a stall,
    nothing more is closed. A stall or a close that fails is raised when nothing else is, as a
    TimeoutError or an AssertionError; if `failure` is already propagating, it is added to that
    failure as a note instead, so that neither hides the other.
    """
    problems: list[str] = []
    while documents and not _stalled:
        document = documents.pop()
        try:
            close(document)
        except TimeoutError as error:
            if not _stalled:  # The closer normally records its own timeout.
                _stalled.append(str(error))
        except Exception as error:
            problems.append(f"Closing a document that was left open failed: {error!r}")
    if _stalled:
        problems.append(
            f"LibreOffice's main thread stopped running callbacks ({_stalled[0]}); "
            f"{len(documents)} other document(s) were left for the runner to stop"
        )
    if not problems:
        return
    if failure is not None:
        for problem in problems:
            _note(failure, problem)
        return
    # Raise the stall if there was one; otherwise the first failed close. A re-raised UNO
    # exception would hit #41, so a failed close is reported by its text.
    raised = TimeoutError(problems[-1]) if _stalled else AssertionError(problems[0])
    for problem in problems[:-1] if _stalled else problems[1:]:
        _note(raised, problem)
    raise raised


def run_checks(
    checks: Iterable[tuple[str, Callable[[], object]]],
    documents: list[Any],
    close: Callable[[Any], None],
) -> dict[str, object]:
    """Run named checks in order, then close the documents they left open.

    Each check closes its own documents and removes them from `documents`, so after a failure
    only what the failed check opened is left; a painted office would otherwise ask to save
    those when the runner terminates it (#40).
    """
    results: dict[str, object] = {}
    try:
        for name, check in checks:
            if _stalled:
                break  # No check runs against a stuck office; the clean-up below raises.
            print("sheet list check:", name, flush=True)
            results[name] = check() or True
    except BaseException as failure:
        close_leftovers(documents, close, failure)
        raise
    close_leftovers(documents, close, None)
    return results
