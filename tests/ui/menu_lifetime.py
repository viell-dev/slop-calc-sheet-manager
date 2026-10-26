"""Native frame dispatch after the list's queue is closed inside a popup (#63)."""

import threading
import traceback
from types import SimpleNamespace
from typing import cast

from run import wait_for
from sheet_list_view import on_main_thread
from teardown import record_stalled_callback, stalled_callbacks

from sheet_manager.uno_calc import MainThread, dispatch, prop
from sheet_manager.uno_list import SheetList
from sheet_manager.uno_menu import SheetMenu
from sheet_manager.uno_reorder import snapshot


class MenuProbe(SheetMenu):
    def native(self, peer, observed, picked):
        return self._native(peer, 100, 100, observed, picked, lambda: True)


def check_native_guard_lifetime(book):
    context = book.lab.context
    owner = SimpleNamespace(_disposed=False, _main=MainThread(context))
    legacy_releases = []

    def post(work):
        # Retain a lost callback only for cleanup of the deliberately broken version;
        # the assertion observes dispatch before any such cleanup is attempted.
        legacy_releases.append(work)
        SheetList.post(cast(SheetList, owner), work, "native menu completion")

    refused = []
    menu = MenuProbe(
        context, book.frame, book.document, book.controller, post, lambda: refused.append(True)
    )
    assert menu.group_calc_tabs(["Bravo"])
    observed = snapshot(book.document)
    done = threading.Event()
    errors = []

    def open_menu():
        try:
            menu.native(book.window, observed, ["Bravo"])
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            done.set()

    MainThread(context).post(open_menu, "opening the disposal regression menu")
    try:
        book.lab.input.move(100, 100)
        wait_for(book.lab.input.popup_windows, "the native menu for queue disposal")
        # These are exactly dispose()'s queue-lifetime flags. Keep the real popup's
        # anchor alive: destroying it is a separate, unsupported host experiment.
        owner._disposed = True
        owner._main.closed = True
        book.lab.input.tap("Escape")
        if not done.wait(10):
            message = "Native menu callback did not return after Escape within 10 seconds"
            record_stalled_callback(message)
            raise TimeoutError(message)
        assert not errors, errors
        # A main-thread barrier observes the already-posted release, without sleeps.
        on_main_thread(context, lambda: None)
        sheet = book.document.Sheets.getByName("Delta")
        book.controller.setActiveSheet(sheet)
        assert book.controller.select(sheet.getCellRangeByName("A1"))
        before = book.document.CurrentSelection.RangeAddress
        assert (before.StartColumn, before.StartRow) == (0, 0)
        assert dispatch(context, book.frame, ".uno:GoToCell", (prop("ToPoint", "B2"),))
        address = book.document.CurrentSelection.RangeAddress
        assert (address.StartColumn, address.StartRow) == (1, 1), (
            "Disposed list retained a native dispatch guard",
            refused,
        )
        assert not refused, "The released guard must not receive ordinary commands"
        return {"disposed_queue": True, "ordinary_frame_dispatch": True}
    finally:
        if not stalled_callbacks():
            book.lab.input.tap("Escape")
            for release in legacy_releases:
                on_main_thread(context, release)
