"""The runner's wait for queued UNO releases ends in time and reports why it stopped (#242).

`client_releases` imports UNO, so `settle_releases` is read from its source and run against a
fake marker. A stuck office must end the wait within its limit instead of hanging the runner
(#40). The integration suite `test_client_releases.py` checks the real marker in a live office.
"""

import ast
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).resolve().parents[2] / "tests" / "integration" / "client_releases.py"


class Collector:
    def __init__(self, order: list[str]) -> None:
        self._order = order

    def collect(self) -> int:
        self._order.append("collect")
        return 0


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
        "queue_marker": queue_marker,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["settle_releases"]


def test_the_wait_ends_when_the_marker_is_released() -> None:
    def queue_marker(context: Any, released: threading.Event) -> object:
        threading.Timer(0.2, released.set).start()  # The office runs the marker's release.
        return object()

    started = time.monotonic()
    assert settle_with(queue_marker)(None, 5) is None
    assert 0.2 <= time.monotonic() - started < 5


def test_garbage_is_collected_before_the_marker_is_queued() -> None:
    # Releases held by cyclic garbage must be sent before the marker's.
    order: list[str] = []

    def queue_marker(context: Any, released: threading.Event) -> object:
        order.append("marker")
        released.set()
        return object()

    assert settle_with(queue_marker, Collector(order))(None, 5) is None
    assert order == ["collect", "marker"]


def test_a_stuck_office_ends_the_wait_within_its_limit() -> None:
    def queue_marker(context: Any, released: threading.Event) -> object:
        time.sleep(3)  # An office that does not answer the UNO call creating the marker
        return object()

    started = time.monotonic()
    reason = settle_with(queue_marker)(None, 0.3)
    assert time.monotonic() - started < 2, "The wait must not wait for a stuck call"
    assert reason == "LibreOffice did not run this process's UNO releases within 0.3 s"


def test_an_office_that_never_runs_the_release_ends_the_wait() -> None:
    reason = settle_with(lambda context, released: object())(None, 0.3)
    assert reason == "LibreOffice did not run this process's UNO releases within 0.3 s"


def test_a_marker_that_cannot_be_queued_is_reported_at_once() -> None:
    def queue_marker(context: Any, released: threading.Event) -> object:
        raise RuntimeError("Binary URP bridge disposed during call")

    started = time.monotonic()
    reason = settle_with(queue_marker)(None, 30)
    assert time.monotonic() - started < 2
    assert reason == (
        "Could not queue the release marker: RuntimeError('Binary URP bridge disposed during call')"
    )
