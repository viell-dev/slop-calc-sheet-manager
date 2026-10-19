"""Close test documents on LibreOffice's main thread on Windows, as its user interface does.

A UNO call from the test process runs in the office on a bridge thread. On Windows, a bridge
thread that closes a Calc document releases LibreOffice's global lock while the main thread
destroys the toolbars' native drop-down windows, and the main thread can then run a pending
toolbar update on a controller being disposed, which crashes LibreOffice (#47). The user
interface closes documents on the main thread, where the lock is not released. So on Windows
these tests close Calc documents from inside an AsyncCallback notification: the office calls
notify() on its main thread, and URP runs the close made inside it nested on that thread.

Other platforms close directly: the lock is not released there, and on gtk3 a main-thread close
could run inside the nested main loop of a clipboard read (#30).
"""

import os
import threading

import unohelper
from com.sun.star.awt import XCallback

CLOSE_TIMEOUT = 60


class _Close(unohelper.Base, XCallback):
    def __init__(self, document):
        self._document = document
        self.done = threading.Event()
        self.error: Exception | None = None

    def notify(self, aData):
        try:
            self._document.close(True)
        except Exception as error:  # Reported by close_document on the test's own thread.
            self.error = error
        finally:
            self.done.set()


def close_document(context, document) -> None:
    """Close a Calc document as the user interface would: on the main thread on Windows."""
    if os.name != "nt":
        document.close(True)
        return
    call = _Close(document)
    callback = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.awt.AsyncCallback", context
    )
    callback.addCallback(call, None)
    if not call.done.wait(CLOSE_TIMEOUT):
        raise AssertionError(f"LibreOffice did not close the document within {CLOSE_TIMEOUT} s")
    if call.error is not None:
        # Re-raising the UNO exception here would hide it behind #41's traceback error.
        raise AssertionError(f"Closing the document failed: {call.error!r}")
