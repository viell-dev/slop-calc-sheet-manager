"""When the list refreshes: settling, a bounded wait, the cost-based rate limit, and closing."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sheet_manager.refresh_schedule import (
    REFRESH_COST_FACTOR,
    REFRESH_DELAY,
    REFRESH_MAX_WAIT,
    SHORTEST_WAIT,
    RefreshSchedule,
)
from tests.unit.source_methods import method


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def schedule() -> tuple[RefreshSchedule, Clock, list[tuple[float, Any]], Mock]:
    clock = Clock()
    timers: list[tuple[float, Any]] = []
    due = Mock()

    def later(seconds: float, work: Any, where: str) -> Any:
        timer = SimpleNamespace(cancel=Mock())
        timers.append((seconds, work))
        return timer

    return RefreshSchedule(later, due, clock), clock, timers, due


def test_a_change_waits_for_a_pause_and_keeps_one_timer() -> None:
    refreshes, clock, timers, due = schedule()
    refreshes.changed()
    clock.now += 0.05
    refreshes.changed()  # A second change while the timer waits adds none.
    assert [seconds for seconds, _ in timers] == [REFRESH_DELAY]
    assert refreshes.stale and refreshes.pending
    assert refreshes.wait() == pytest.approx(REFRESH_DELAY)  # The newer change restarts it.
    clock.now += REFRESH_DELAY
    timers[0][1]()
    due.assert_called_once_with()
    assert not refreshes.pending and refreshes.wait() == 0.0


def test_continuous_changes_refresh_after_the_bounded_wait() -> None:
    refreshes, clock, _, _ = schedule()
    refreshes.changed()
    for _ in range(int(REFRESH_MAX_WAIT / 0.1) + 1):
        clock.now += 0.1
        refreshes.changed()  # Never quiet for REFRESH_DELAY.
    assert refreshes.wait() <= 0.0


def test_slow_refreshes_scale_the_pause_and_rate_limit_the_next_one() -> None:
    refreshes, clock, timers, _ = schedule()

    def slow() -> None:
        clock.now += 0.5

    refreshes.measure(slow)
    assert refreshes.cost == pytest.approx(0.5) and not refreshes.stale
    assert refreshes.delay() == pytest.approx(REFRESH_COST_FACTOR * 0.5)
    # A switch right after a costly refresh waits out the rate limit instead of refreshing.
    assert not refreshes.activated(busy=False)
    assert timers[-1][0] == pytest.approx(REFRESH_COST_FACTOR * 0.5)
    clock.now += REFRESH_COST_FACTOR * 0.5
    timers[-1][1]()
    assert refreshes.activated(busy=False)  # Idle long enough, no timer: refresh now.


@pytest.mark.parametrize("why", ["busy", "timer"])
def test_a_switch_does_not_refresh_at_once_while_busy_or_scheduled(why: str) -> None:
    refreshes, _, timers, _ = schedule()
    if why == "timer":
        refreshes.schedule(1.0)
    assert not refreshes.activated(busy=why == "busy")
    assert refreshes.stale and len(timers) == 1
    assert timers[0][0] == (1.0 if why == "timer" else SHORTEST_WAIT)


def test_closing_cancels_the_timer_and_refuses_new_ones() -> None:
    timer = SimpleNamespace(cancel=Mock())
    later = Mock(return_value=timer)
    due = Mock()
    refreshes = RefreshSchedule(later, due)
    refreshes.changed()
    work = later.call_args.args[1]
    refreshes.close()
    timer.cancel.assert_called_once_with()
    work()  # Already queued when the list was disposed.
    due.assert_not_called()
    refreshes.changed()
    assert later.call_count == 1


def test_a_timer_after_a_successful_refresh_does_nothing() -> None:
    refreshes, _, timers, due = schedule()
    refreshes.changed()
    refreshes.measure(lambda: None)  # An activation refreshed meanwhile.
    timers[0][1]()
    due.assert_not_called()


def list_due(**state: Any) -> Any:
    owner = SimpleNamespace(
        _disposed=False,
        _busy=False,
        _monitor=SimpleNamespace(events=SimpleNamespace(replay=None)),
        _refreshes=SimpleNamespace(wait=Mock(return_value=0.0), schedule=Mock()),
        _run_refresh=Mock(),
    )
    for name, value in state.items():
        setattr(owner, name, value)
    method("src/sheet_manager/uno_list.py", "SheetList", "_timed_refresh", {"REPLAY_WAIT": 0.05})(
        owner
    )
    return owner


def test_the_list_refreshes_when_due_unless_busy() -> None:
    list_due()._run_refresh.assert_called_once_with()
    busy = list_due(_busy=True)  # A move refreshes the list itself when it ends.
    busy._run_refresh.assert_not_called()
    busy._refreshes.schedule.assert_not_called()


def test_the_list_waits_during_a_replay_and_while_changes_settle() -> None:
    replaying = list_due(_monitor=SimpleNamespace(events=SimpleNamespace(replay=1)))
    replaying._refreshes.schedule.assert_called_once_with(0.05)
    replaying._refreshes.wait.assert_not_called()  # No check may end an own move's proof (#91).
    replaying._run_refresh.assert_not_called()
    settling = list_due(_refreshes=SimpleNamespace(wait=Mock(return_value=0.3), schedule=Mock()))
    settling._refreshes.schedule.assert_called_once_with(0.3)
    settling._run_refresh.assert_not_called()
