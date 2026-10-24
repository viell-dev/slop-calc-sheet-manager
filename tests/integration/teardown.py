"""Test clean-up that neither hides a failure nor waits on a stalled office. No UNO dependency.

The tests close Calc documents on Windows, and run UI steps, through callbacks on
LibreOffice's main thread (`main_thread.py`). When such a callback does not finish in time, the
main thread is stuck and its outcome is unknown (#50): no further callback is tried, the session
fails, and the runner stops its office instead of asking it to terminate, which would wait for
the stuck thread too (#40). An earlier failure stays the one raised, with the timeout as a note,
so that neither hides the other.
"""

from collections.abc import Callable, Iterable
from contextlib import suppress
from types import TracebackType
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


class Configured:
    """Apply an office setting for a `with` block, and restore it afterwards.

    Restoring is a UNO request that a stuck main thread could block for good, so after a stalled
    callback it is skipped: the profile is temporary, and the runner stops the office (#51). If
    the block failed and restoring fails too, the restore error becomes a note on the block's
    failure, which stays the one raised. A class rather than a generator, so that a UNO exception
    passes through unchanged (#41).
    """

    def __init__(self, apply: Callable[[], None], restore: Callable[[], None]) -> None:
        self._apply, self._restore = apply, restore

    def __enter__(self) -> None:
        try:
            self._apply()
        except BaseException as failure:
            self._restore_after(failure)
            raise

    def __exit__(
        self,
        kind: type[BaseException] | None,
        failure: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if failure is not None:
            self._restore_after(failure)
        elif not _stalled:
            self._restore()

    def _restore_after(self, failure: BaseException) -> None:
        if _stalled:
            return
        try:
            self._restore()
        except Exception as error:
            _note(failure, f"Restoring the office setting also failed: {error!r}")


def run_checks(
    checks: Iterable[tuple[str, Callable[[], object]]],
    documents: list[Any],
    close: Callable[[Any], None],
    label: str = "check",
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
            print(f"{label}:", name, flush=True)
            results[name] = check() or True
    except BaseException as failure:
        close_leftovers(documents, close, failure)
        raise
    close_leftovers(documents, close, None)
    return results
