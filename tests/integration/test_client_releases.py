"""The runner's wait for queued UNO releases covers the releases sent before it (#242).

Every session ends through `client_releases.settle_releases` before the runner asks the office
to terminate. This suite drops many dialog models, half inside an office main-thread callback
and half from the test's own thread, as checks drop sheet handles, and then requires the office
to have run every one of those releases when the wait returns.

The evidence is independent of the wait's own marker, whose signal is this process freeing an
object. The dialog model service wraps its model in toolkit's `OGeometryControlModel`, built on
cppu's `WeakAggComponentImplHelper`, which disposes itself on its last release; disposal calls
the listeners' `disposing`, a synchronous call from the office thread running that release. So
the office signals each witness while it runs that release, whatever order this process frees
objects in across PyUNO's threads, which need not be the office's. The marker's fixed-text model
frees its listeners without calling them. Both behaviours were measured on 26.8.2.2 and
26.2.1.2. One more model stays referenced and must stay unsignalled, so that a signal shows that
model's own release and not something the wait or the office did to every model.

Without the wait, 874 to 897 of 2,000 such models were still alive when the drops finished
(26.8.2.2 and 26.2.1.2), so a wait that returned early fails here. It needs no document and runs
in every integration session.
"""

import threading
import time

import unohelper
from client_releases import settle_releases
from com.sun.star.lang import XEventListener
from sheet_list_view import on_main_thread

COUNT = 1000  # Per thread; each witness is one queued release.
WITNESS_SERVICE = "com.sun.star.awt.UnoControlDialogModel"


class _Witness(unohelper.Base, XEventListener):
    def __init__(self, disposed: threading.Event) -> None:
        self._disposed = disposed

    def disposing(self, Source):
        self._disposed.set()


def witness(context, disposed: threading.Event) -> object:
    """Return a dialog model that sets `disposed` when the office runs its last release."""
    model = context.ServiceManager.createInstanceWithContext(WITNESS_SERVICE, context)
    model.addEventListener(_Witness(disposed))
    return model


def exercise(context, desktop, directory, output):
    events = [threading.Event() for _ in range(2 * COUNT)]
    kept = threading.Event()
    control = witness(context, kept)

    def drop_in_callback():
        models = [witness(context, event) for event in events[:COUNT]]
        del models

    on_main_thread(context, drop_in_callback, timeout=120)
    models = [witness(context, event) for event in events[COUNT:]]
    del models
    queued = sum(not event.is_set() for event in events)
    started = time.monotonic()
    unsettled = settle_releases(context, 60)
    waited = round(time.monotonic() - started, 3)
    assert unsettled is None, unsettled
    outstanding = sum(not event.is_set() for event in events)
    assert outstanding == 0, f"The office had not run {outstanding} of {len(events)} releases"
    assert not kept.is_set(), "The retained model was disposed, so the signal shows no release"
    del control  # Its release goes to the next wait.
    return {
        "releases": len(events),
        "still_queued_before_wait": queued,
        "wait_seconds": waited,
        "method": (
            "dialog models whose release the office signals as it runs it; none outstanding "
            "after the wait, and a retained model unsignalled"
        ),
    }
