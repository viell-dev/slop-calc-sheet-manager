"""The runner's wait for queued UNO releases ends in time and reports why it stopped (#242).

`client_releases` imports UNO, so `settle_releases` is read from its source and run against a
fake marker and a fake component context. A stuck office, or a blocked garbage collection, must
end the wait within its limit instead of hanging the runner (#40), and a disconnected bridge
must not pass for a drained one. The integration suite `test_client_releases.py` checks the real
marker in a live office.
"""

import ast
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).resolve().parents[2] / "tests" / "integration" / "client_releases.py"
TIMED_OUT = "The wait for this process's UNO releases did not finish within 0.3 s; it was "


class Collector:
    def __init__(self, order: list[str]) -> None:
        self._order = order

    def collect(self) -> int:
        self._order.append("collect")
        return 0


class BlockedCollector:
    """A collection held by a finalizer that does not return."""

    def collect(self) -> int:
        time.sleep(3)
        return 0


class Context:
    """The bridge's component context; `getServiceManager` is a round trip over the bridge.

    `released` is the marker's signal, once queued, so that a call can record whether the
    marker had been released when it was made.
    """

    def __init__(self, error: Exception | None = None, delay: float = 0) -> None:
        self.released: threading.Event | None = None
        self.calls: list[bool] = []
        self._error = error
        self._delay = delay

    def getServiceManager(self) -> object:
        self.calls.append(self.released is not None and self.released.is_set())
        time.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return object()


def settle_with(queue_marker: Callable[[Any, threading.Event], object], gc: Any = None) -> Any:
    """`settle_releases` from its source, with `queue_marker` and optionally `gc` replaced."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "settle_releases"
    )
    namespace: dict[str, Any] = {
        "gc": gc or Collector([]),
        "threading": threading,
        "time": time,
        "queue_marker": queue_marker,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["settle_releases"]


def released_after(seconds: float) -> Callable[[Any, threading.Event], object]:
    """A marker whose release the office runs after `seconds`."""

    def queue_marker(context: Any, released: threading.Event) -> object:
        context.released = released
        threading.Timer(seconds, released.set).start()
        return object()

    return queue_marker


def test_the_wait_ends_when_the_marker_is_released() -> None:
    context = Context()
    started = time.monotonic()
    assert settle_with(released_after(0.2))(context, 5) is None
    assert 0.2 <= time.monotonic() - started < 5
    assert context.calls == [True], "Confirm the bridge once, after the marker's release"


def test_garbage_is_collected_before_the_marker_is_queued() -> None:
    # Releases held by cyclic garbage must be sent before the marker's.
    order: list[str] = []

    def queue_marker(context: Any, released: threading.Event) -> object:
        order.append("marker")
        released.set()
        return object()

    assert settle_with(queue_marker, Collector(order))(Context(), 5) is None
    assert order == ["collect", "marker"]


def test_a_blocked_garbage_collection_ends_the_wait_within_its_limit() -> None:
    # Collection runs Python finalizers, and one that blocks must not delay forced shutdown.
    started = time.monotonic()
    reason = settle_with(released_after(0), BlockedCollector())(Context(), 0.3)
    assert time.monotonic() - started < 2, "The wait must not wait for a blocked collection"
    assert reason == TIMED_OUT + "collecting garbage"


def test_a_stuck_office_ends_the_wait_within_its_limit() -> None:
    def queue_marker(context: Any, released: threading.Event) -> object:
        time.sleep(3)  # An office that does not answer the UNO call creating the marker
        return object()

    started = time.monotonic()
    reason = settle_with(queue_marker)(Context(), 0.3)
    assert time.monotonic() - started < 2, "The wait must not wait for a stuck call"
    assert reason == TIMED_OUT + "queuing the release marker"


def test_an_office_that_never_runs_the_release_ends_the_wait() -> None:
    context = Context()
    reason = settle_with(lambda context, released: object())(context, 0.3)
    assert reason == TIMED_OUT + "waiting for the office to run the marker's release"
    assert context.calls == [], "An unreleased marker confirms nothing"


def test_a_marker_that_cannot_be_queued_is_reported_at_once() -> None:
    def queue_marker(context: Any, released: threading.Event) -> object:
        raise RuntimeError("Binary URP bridge disposed during call")

    started = time.monotonic()
    reason = settle_with(queue_marker)(Context(), 30)
    assert time.monotonic() - started < 2
    assert reason == (
        "The wait for this process's UNO releases failed while queuing the release marker: "
        "RuntimeError('Binary URP bridge disposed during call')"
    )


def test_a_bridge_disposed_after_registration_is_not_taken_for_a_drain() -> None:
    # Disposing the bridge drops the office's reference to the marker's listener, which frees
    # it here exactly as the office's release of the marker would, though nothing ran.
    def queue_marker(context: Any, released: threading.Event) -> object:
        context.released = released
        released.set()  # The bridge drops the listener while it disposes itself.
        return object()

    context = Context(RuntimeError("Binary URP bridge already disposed"))
    started = time.monotonic()
    reason = settle_with(queue_marker)(context, 30)
    assert time.monotonic() - started < 2
    assert context.calls == [True]
    assert reason == (
        "The wait for this process's UNO releases failed while confirming that the UNO bridge "
        "is still connected: RuntimeError('Binary URP bridge already disposed')"
    )


def test_a_confirmation_that_does_not_return_ends_the_wait_within_its_limit() -> None:
    started = time.monotonic()
    reason = settle_with(released_after(0))(Context(delay=3), 0.3)
    assert time.monotonic() - started < 2
    assert reason == TIMED_OUT + "confirming that the UNO bridge is still connected"
