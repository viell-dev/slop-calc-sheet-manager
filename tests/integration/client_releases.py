"""Wait until the office has run the UNO releases this test process sent so far (#242).

When the test process drops its last reference to an office object, the UNO bridge sends a
one-way `release` request. LibreOffice sends every release under one dedicated bridge thread ID,
apart from all other calls (`Bridge::makeReleaseCall` in binaryurp), and the receiving office
runs them in order on one worker thread. So no synchronous call from any thread of this process
waits for them: a round trip right after dropping 10,000 sheet handles returned within 0.08 s,
from the test's thread and from an office main-thread callback alike (26.8.2.2). A check that
drops many handles just before the session ends therefore leaves the office still running
releases while it shuts down. Once shutdown has dropped the bridge's objects, each remaining
release fails with "URP: release unknown stub", and if the office calls exit() meanwhile, the
exception handling races with the UNO runtime's static destructors: the office crashed at exit
in a `cppu_threadpool` thread (`cppu::getCaughtException`) on 26.8.2.2, with and without the
extension, and left shutdown crash dumps on 26.2.6.3, with and without it.

`settle_releases` therefore sends one more release last: a toolkit control model holding a
listener of this process. When the office runs that release, it destroys the model, which
releases the listener, and the listener is freed here. Releases run in order, so by then every
release this process sent before has run. Garbage is collected first, so that releases held by
cyclic garbage are sent before the marker's.

Disposing the bridge also frees the listener, though the office ran nothing, so a freed listener
alone proves nothing. One synchronous call over the same bridge once it is freed,
`getServiceManager`, confirms that the bridge was still connected then: a disposed bridge does
not reconnect, and every call over it fails. A listener freed by a disconnection therefore fails
the wait instead of passing for a drain.

The barrier covers only releases sent before the marker. Releases sent during the wait are not
covered, such as those from a listener callback the office makes meanwhile. A session normally
ends with no documents open, so the office makes no such callbacks, but a check that fails
before closing its document leaves it open; such a session fails on that check anyway.

Call it after the session has dropped its last references, before asking the office to
terminate. It reports a failure as text and never raises: a UNO exception must not leave the
runner's generator-based session (#41). `tests/unit/test_client_releases.py` checks its time
limit and failure reports against a fake marker and context; the integration suite
`tests/integration/test_client_releases.py` checks the barrier against independent evidence.
"""

import gc
import threading
import time
import weakref

import unohelper
from com.sun.star.lang import XEventListener

# Any office object that holds its listeners and is destroyed with its last reference works.
# Control models have no other owner and release their listeners without calling them.
MARKER_SERVICE = "com.sun.star.awt.UnoControlFixedTextModel"


class _Marker(unohelper.Base, XEventListener):
    def disposing(self, Source):
        pass


def queue_marker(context, released: threading.Event) -> object:
    """Return an office object whose release, when the office runs it, sets `released`.

    The signal is registered only once the office holds the listener, so a marker that could not
    be queued is never taken for a released one.
    """
    marker = _Marker()
    model = context.ServiceManager.createInstanceWithContext(MARKER_SERVICE, context)
    model.addEventListener(marker)
    weakref.finalize(marker, released.set)
    return model


def settle_releases(context, timeout: float) -> str | None:
    """Wait until the office has run this process's releases; return None, or why not.

    Each step can block: collection runs Python finalizers, and the marker and the confirmation
    are UNO calls that a stuck office would not answer. So every step runs on one thread, which
    is left behind if a step never ends, and the whole wait ends after `timeout` seconds: the
    runner then stops the launcher it started (its whole process tree on Windows) instead of
    hanging (#40). The reason names the unfinished step.
    """
    deadline = time.monotonic() + timeout
    step = ["collecting garbage"]
    failures: list[str] = []
    settled = threading.Event()

    def settle() -> None:
        try:
            gc.collect()
            step[0] = "queuing the release marker"
            released = threading.Event()
            model = queue_marker(context, released)
            del model  # The last release this process sends before the office ends.
            step[0] = "waiting for the office to run the marker's release"
            if not released.wait(max(0.0, deadline - time.monotonic())):
                return
            step[0] = "confirming that the UNO bridge is still connected"
            context.getServiceManager()
        except Exception as error:
            failures.append(
                f"The wait for this process's UNO releases failed while {step[0]}: {error!r}"
            )
        settled.set()

    threading.Thread(target=settle, name="settle-releases", daemon=True).start()
    if not settled.wait(timeout):
        return (
            f"The wait for this process's UNO releases did not finish within {timeout:g} s; "
            f"it was {step[0]}"
        )
    return failures[0] if failures else None
