"""Wait until the office has run every UNO release this test process has sent (#242).

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
release this process sent before has run. Collect garbage first, so that releases held by cyclic
garbage are sent before the marker's. Releases sent after the marker, such as from a listener
callback the office makes during the wait, are not covered; at the end of a session the office
has no documents open and makes none.

Call it after the session has dropped its last references, before asking the office to
terminate. It reports a failure as text and never raises: a UNO exception must not leave the
runner's generator-based session (#41). `tests/unit/test_client_releases.py` checks its time
limit and failure reports against a fake marker.
"""

import gc
import threading
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
    """Return an office object whose release, when the office runs it, sets `released`."""
    marker = _Marker()
    weakref.finalize(marker, released.set)
    model = context.ServiceManager.createInstanceWithContext(MARKER_SERVICE, context)
    model.addEventListener(marker)
    return model


def settle_releases(context, timeout: float) -> str | None:
    """Wait until the office has run this process's releases; return None, or why not.

    Creating the marker is itself a UNO call that a stuck office would not answer, so it runs
    on its own thread, which is left behind if the office never answers, and the whole wait
    ends after `timeout` seconds: the runner then stops the office instead of hanging (#40).
    """
    gc.collect()
    released = threading.Event()
    failures: list[str] = []

    def queue() -> None:
        try:
            model = queue_marker(context, released)
            del model  # The last release this process sends before the office ends.
        except Exception as error:
            failures.append(f"Could not queue the release marker: {error!r}")
            released.set()

    threading.Thread(target=queue, name="release-marker", daemon=True).start()
    if not released.wait(timeout):
        return f"LibreOffice did not run this process's UNO releases within {timeout:g} s"
    return failures[0] if failures else None
