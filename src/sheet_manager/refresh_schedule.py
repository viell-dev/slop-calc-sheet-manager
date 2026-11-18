"""When the sheet list reads the sheets again: a cost-based rate limit with bounded retries.

Reading every sheet and rebuilding the tree costs main-thread time that grows with the number of
sheets. Bulk API changes, such as a 500-call move, send an event for each call, and refreshing on
each one slowed such a move on Windows from seconds to over a minute. So a change waits for a
pause of `REFRESH_DELAY`, or several times the last refresh's cost, but not longer than a bounded
wait during continuous changes; and no refresh starts until the list has been idle for several
times the last one's cost. A failed refresh leaves its changes pending and retries with a bounded
backoff, because a property change such as a tab colour moves neither the names nor the
structure generation, so nothing else would ask for it again (#186).

This class decides only when. `uno_list.SheetList`, its one owner, decides whether: a timed
refresh waits during Calc's replay of an Undo and is skipped while a move runs, which refreshes
when it ends.

Contract: use one instance per list. `changed` is the list's modify-listener entry point and can
run on the notifying thread (`uno_list.SheetList.document_modified`). There it records the
change's time and staleness (`_mark_stale`), computes the wait (`delay`) and calls `schedule`,
which, unless a timer is already pending or the schedule is closed, creates the timer through
`later` (`uno_calc.MainThread.later`): its worker waits on a thread of its own and then posts to
the main thread, as listeners may. No UNO call and no refresh runs on the notifying thread. The
timer's work (`_fire`, then the owner's `due`, which may call `measure`) and the remaining
methods run on LibreOffice's main thread. The class takes no lock: it relies on LibreOffice's main lock, which listeners and
the main thread hold (`uno_calc.start_thread`), to order `changed` against that work.

It owns the refresh timer and the timing state. At most one timer is pending; `close` cancels it
and refuses new ones, so a timer already queued when the list is disposed does nothing, and
`pending` is false from then on. `stale` holds from the first change not yet shown until a
refresh succeeds. It imports no UNO, so tests drive it with a fake clock and timers.
"""

import time
from collections.abc import Callable
from typing import Protocol

REFRESH_DELAY = 0.2  # Quiet time after a change before the list reads the sheets again.
REFRESH_COST_FACTOR = 4  # Wait at least this many times as long as the last refresh took.
REFRESH_MAX_WAIT = 2.0  # During continuous changes, refresh at least this often (scaled too).
REFRESH_RETRY = 0.5  # The first wait before retrying a failed refresh; it doubles each time,
REFRESH_RETRY_MAX = 8.0  # up to this,
REFRESH_RETRIES = 5  # and after this many failures in a row only a new change retries (#186).
SHORTEST_WAIT = 0.05


class Timer(Protocol):
    def cancel(self) -> None: ...


Later = Callable[[float, Callable[[], None], str], Timer]


class RefreshSchedule:
    def __init__(
        self,
        later: Later,
        due: Callable[[], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`later(seconds, work, where)` posts work to the main thread after a delay, as
        `uno_calc.MainThread.later` does. `due` runs when a scheduled refresh's time comes while
        changes are still unshown; it asks `wait` and decides whether to refresh now."""
        self._later = later
        self._due = due
        self._clock = clock
        self._timer: Timer | None = None
        self._closed = False
        self.changed_at = 0.0  # The last document change.
        self.stale_since: float | None = None  # The first change not yet shown.
        self.cost = 0.0  # How long the last refresh took.
        self.failures = 0  # Failed refreshes since the last one that succeeded.
        self.refreshed_at = 0.0  # When the last refresh ended.

    @property
    def stale(self) -> bool:
        return self.stale_since is not None

    @property
    def pending(self) -> bool:
        """Whether a refresh timer is waiting; never after `close`, which cancels it."""
        return self._timer is not None and not self._closed

    def close(self) -> None:
        self._closed = True
        if self._timer is not None:
            self._timer.cancel()

    def measure(self, refresh: Callable[[], None]) -> None:
        """Run a refresh, timing it; only a successful one marks the list current."""
        started = self._clock()
        try:
            refresh()
        except BaseException:
            self._failed()
            raise
        else:
            self.stale_since = None
            self.failures = 0
        finally:
            self.refreshed_at = self._clock()
            self.cost = self.refreshed_at - started

    def changed(self) -> None:
        """A document change: refresh once changes pause, or at the latest after a bounded wait.

        The one method a listener calls, possibly on another thread; it only records and posts.
        """
        now = self._clock()
        self.changed_at = now
        self._mark_stale(now)
        self.schedule(self.delay())

    def activated(self, busy: bool) -> bool:
        """A sheet switch: whether to refresh now, rather than when the rate limit allows.

        Now only when no refresh is scheduled, the list is not `busy`, and it has been idle for
        long enough; otherwise this schedules one.
        """
        now = self._clock()
        self._mark_stale(now)
        if self._timer is None and not busy and self.rate_wait(now) <= 0:
            return True
        self.schedule(self.rate_wait(now))
        return False

    def wait(self) -> float:
        """Seconds until a pending refresh may run: changes still settling, or the rate limit."""
        now = self._clock()
        delay = self.delay()
        quiet = now - self.changed_at
        waited = now - self.stale_since if self.stale_since is not None else 0.0
        settling = quiet < delay and waited < max(REFRESH_MAX_WAIT, delay * REFRESH_COST_FACTOR)
        return max(delay - quiet if settling else 0.0, self.rate_wait(now))

    def delay(self) -> float:
        return max(REFRESH_DELAY, REFRESH_COST_FACTOR * self.cost)

    def rate_wait(self, now: float) -> float:
        """How long until another refresh may run without hogging the main thread."""
        return self.refreshed_at + REFRESH_COST_FACTOR * self.cost - now

    def schedule(self, seconds: float) -> None:
        if self._timer is None and not self._closed:
            self._timer = self._later(
                max(seconds, SHORTEST_WAIT), self._fire, "refreshing the sheet list"
            )

    def _fire(self) -> None:
        self._timer = None
        if not self._closed and self.stale_since is not None:
            self._due()

    def _failed(self) -> None:
        """Keep the changes the failed refresh did not show pending, and retry them (#186).

        Retries back off and stop after `REFRESH_RETRIES` failures in a row, rather than report
        an error in a loop; a later document change or sheet switch then refreshes again.
        """
        self._mark_stale(self._clock())
        self.failures += 1
        if self.failures <= REFRESH_RETRIES:
            wait = REFRESH_RETRY * 2 ** (self.failures - 1)
            self.schedule(min(wait, REFRESH_RETRY_MAX))

    def _mark_stale(self, now: float) -> None:
        if self.stale_since is None:
            self.stale_since = now
