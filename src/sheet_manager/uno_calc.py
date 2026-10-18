"""Calc and toolkit helpers shared by the panel's parts. Only the panel uses them."""

import sys
import threading
import traceback
from collections.abc import Callable

import uno
import unohelper
from com.sun.star.awt import XCallback
from com.sun.star.beans import PropertyValue
from com.sun.star.util import URL

from sheet_manager.sheet_list import SheetRow, tab_color
from sheet_manager.swatch import swatch_png

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

    def later(self, seconds: float, function: Callable[[], None], where: str) -> threading.Timer:
        # The timer thread only posts; it never calls into the toolkit itself.
        timer = threading.Timer(seconds, lambda: self.post(function, where))
        timer.daemon = True
        timer.start()
        return timer


def read_rows(document, controller) -> list[SheetRow]:
    sheets = document.getSheets()
    try:
        active = controller.getActiveSheet().getName()
    except Exception:
        active = None
    rows: list[SheetRow] = []
    for index in range(sheets.getCount()):
        sheet = sheets.getByIndex(index)
        name = sheet.getName()
        rows.append(
            SheetRow(
                name=name,
                visible=bool(sheet.IsVisible),
                active=name == active,
                protected=bool(sheet.isProtected()),
                scenario=bool(sheet.getIsScenario()),
                color=tab_color(sheet.TabColor),
            )
        )
    return rows


def selected_tabs(context, controller) -> list[int]:
    """Calc's selected sheet tabs. XSelectedSheetsSupplier is unpublished: use reflection."""
    reflection = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.reflection.CoreReflection", context
    )
    interface = reflection.forName("com.sun.star.sheet.XSelectedSheetsSupplier")
    result = interface.getMethod("getSelectedSheets").invoke(controller, ())
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
    tables = prop("Tables", uno.Any("[]long", tuple(indices)))
    dispatch(context, frame, ".uno:SelectTables", (tables, prop("SynchronMode", True)))


_swatches: dict[int | None, str] = {}


def swatch_url(context, color: int | None) -> str:
    """A file URL for the colour's swatch, in LibreOffice's own temporary directory.

    LibreOffice removes that directory when it exits, so the files do not outlive the process.
    """
    if color not in _swatches:
        temporary = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.io.TempFile", context
        )
        temporary.RemoveFile = False
        output = temporary.getOutputStream()
        output.writeBytes(uno.ByteSequence(swatch_png(color)))
        output.flush()
        output.closeOutput()
        _swatches[color] = temporary.Uri
    return _swatches[color]


def show_error(peer, title: str, message: str) -> None:
    box = peer.getToolkit().createMessageBox(peer, ERRORBOX, BUTTONS_OK, title, message)
    box.execute()
    box.dispose()
