"""The runner's wait for queued UNO releases covers every release sent before it (#242).

Every session ends through `client_releases.settle_releases` before the runner asks the office
to terminate. This suite drops many release markers, half inside an office main-thread callback
and half from the test's own thread, as checks drop sheet handles, and then requires every one of
them to have been released by the office when the wait returns. Without the wait, about half of
1,000 dropped markers were still queued when the callback returned (26.8.2.2), so a wait that
returned early fails here. It needs no document and runs in every integration session.
"""

import threading
import time

from client_releases import queue_marker, settle_releases
from sheet_list_view import on_main_thread

COUNT = 1000  # Per thread; each marker is one queued release.


def exercise(context, desktop, directory, output):
    events = [threading.Event() for _ in range(2 * COUNT)]

    def drop_in_callback():
        markers = [queue_marker(context, event) for event in events[:COUNT]]
        del markers

    on_main_thread(context, drop_in_callback, timeout=120)
    markers = [queue_marker(context, event) for event in events[COUNT:]]
    del markers
    queued = sum(not event.is_set() for event in events)
    started = time.monotonic()
    unsettled = settle_releases(context, 60)
    waited = round(time.monotonic() - started, 3)
    assert unsettled is None, unsettled
    outstanding = sum(not event.is_set() for event in events)
    assert outstanding == 0, f"{outstanding} of {len(events)} releases had not run"
    return {
        "releases": len(events),
        "still_queued_before_wait": queued,
        "wait_seconds": waited,
        "method": "markers whose release frees a listener; none outstanding after the wait",
    }
