"""Calc and toolkit helpers shared by the panel's parts. Only the panel uses them."""

import _thread
import sys
import time
import traceback
from collections.abc import Callable

import uno
import unohelper
from com.sun.star.awt import XCallback
from com.sun.star.beans import PropertyValue
from com.sun.star.util import URL

from sheet_manager.sheet_list import SheetRow, tab_color

ERRORBOX = uno.Enum("com.sun.star.awt.MessageBoxType", "ERRORBOX")
BUTTONS_OK = uno.getConstantByName("com.sun.star.awt.MessageBoxButtons.BUTTONS_OK")


def report(where: str) -> None:
    """Log an unexpected error; a callback must never raise into LibreOffice."""
    print(f"Sheet Manager: {where} failed", file=sys.stderr)
    traceback.print_exc()


def prop(name, value):
    item = PropertyValue()
    item.Name, item.Value = name, value
    return item


class _Callback(unohelper.Base, XCallback):
    def __init__(self, function, where):
        self._function = function
        self._where = where

    def notify(self, data):
        try:
            self._function()
        except Exception:
            report(self._where)


def start_thread(function: Callable[[], None], where: str) -> None:
    """Run `function` on a new thread, without waiting for the thread to start.

    `threading.Thread.start` waits until the new thread runs. That thread's first Python steps
    can run the garbage collector, which can release UNO objects whose destructors wait for
    LibreOffice's main lock. Listeners and the main thread hold that lock, so a thread they
    started that way never started, and neither side went on: Calc hung. A thread started here
    waits for the lock instead, until its holder is done.
    """

    def run() -> None:
        try:
            function()
        except Exception:
            report(where)

    _thread.start_new_thread(run, ())


class Later:
    """Work posted after a delay, unless cancelled first."""

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class MainThread:
    """Run work later on LibreOffice's main thread, as a user event.

    Listener callbacks can arrive on other threads (the UNO bridge, a drag thread on Windows)
    and some run while LibreOffice is in the middle of a change, so they only post work here.
    """

    def __init__(self, context):
        self._async = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.awt.AsyncCallback", context
        )
        self.closed = False

    def post(self, function: Callable[[], None], where: str = "a deferred update") -> None:
        if not self.closed:
            self._async.addCallback(_Callback(function, where), None)

    def later(self, seconds: float, function: Callable[[], None], where: str) -> Later:
        """Post `function` after `seconds`. The waiting thread only posts (`start_thread`)."""
        handle = Later()

        def wait_then_post() -> None:
            time.sleep(seconds)
            if not handle.cancelled:
                self.post(function, where)

        start_thread(wait_then_post, where)
        return handle


def read_rows(controller, observed) -> list[SheetRow]:
    """The list's rows for a snapshot, read through its retained sheet handles."""
    try:
        active = controller.getActiveSheet().getName()
    except Exception:
        active = None
    rows: list[SheetRow] = []
    for sheet, handle in zip(observed.sheets, observed.handles, strict=True):
        rows.append(
            SheetRow(
                name=sheet.name,
                visible=bool(handle.IsVisible),
                active=sheet.name == active,
                protected=bool(handle.isProtected()),
                scenario=sheet.scenario,
                color=tab_color(handle.TabColor),
            )
        )
    return rows


def selected_tabs_method(context):
    """The reflected selected-tabs getter, reusable for controllers in this context.

    Invoke it on the UI thread: the native getter reads this view's mark data and can finish
    lazy view initialization. The target controller is supplied separately to each invoke.
    """
    reflection = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.reflection.CoreReflection", context
    )
    interface = reflection.forName("com.sun.star.sheet.XSelectedSheetsSupplier")
    return interface.getMethod("getSelectedSheets")


def selected_tabs(context, controller) -> list[int]:
    """Calc's selected sheet tabs. XSelectedSheetsSupplier is unpublished: use reflection."""
    result = selected_tabs_method(context).invoke(controller, ())
    return sorted(result[0])


def command_url(context, command: str):
    url = URL()
    url.Complete = command
    transformer = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.util.URLTransformer", context
    )
    return transformer.parseStrict(url)[1]


def dispatch(context, frame, command: str, arguments=()) -> bool:
    """Dispatch to this frame directly, as LibreOffice's shortcut handling does."""
    url = command_url(context, command)
    dispatcher = frame.queryDispatch(url, "", 0)
    if dispatcher is None:
        return False
    dispatcher.dispatch(url, tuple(arguments))
    return True


def select_tabs(context, frame, indices: list[int]) -> None:
    """Replace Calc's tab selection; the handler keeps or activates a selected visible sheet."""
    # The handler needs a typed sequence<long>; types-unopy does not declare uno.Any.
    typed = uno.Any("[]long", tuple(indices))  # pyright: ignore[reportAttributeAccessIssue]
    tables = prop("Tables", typed)
    dispatch(context, frame, ".uno:SelectTables", (tables, prop("SynchronMode", True)))


def show_error(peer, title: str, message: str) -> None:
    box = peer.getToolkit().createMessageBox(peer, ERRORBOX, BUTTONS_OK, title, message)
    box.execute()
    box.dispose()
