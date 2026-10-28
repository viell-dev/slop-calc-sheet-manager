"""The list's queue closed inside its open popup leaves Calc's frame untouched (#63).

Panel disposal can close the list's queue while the menu's popup runs its nested loop. The menu
used to keep a dispatch interceptor on the frame while Calc's own popup was open, and its release
had to survive that. The menu now dispatches a chosen command itself, from the list's posted
completion; with the queue closed, that completion is dropped, and the frame keeps working.
"""

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


def check_menu_queue_disposal(book):
    context = book.lab.context
    owner = SimpleNamespace(_disposed=False, _main=MainThread(context))
    completed = []
    menu = SheetMenu(context, book.frame, book.document, book.controller)
    observed = snapshot(book.document)
    view = book.active(), book.calc_tabs()
    done = threading.Event()
    errors, chosen = [], []

    def open_menu():
        try:
            chosen.append(menu.show(book.window, 100, 100, observed, ["Bravo"]))
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            # As the list does: its completion goes through the list's own queue.
            SheetList.post(
                cast(SheetList, owner), lambda: completed.append(True), "menu completion"
            )
            done.set()

    MainThread(context).post(open_menu, "opening the disposal regression menu")
    try:
        book.lab.input.move(100, 100)
        wait_for(book.lab.input.popup_windows, "the menu for queue disposal")
        # These are exactly dispose()'s queue-lifetime flags. Keep the real popup's
        # anchor alive: destroying it is a separate, unsupported host experiment.
        owner._disposed = True
        owner._main.closed = True
        book.lab.input.tap("Escape")
        if not done.wait(10):
            message = "The menu callback did not return after Escape within 10 seconds"
            record_stalled_callback(message)
            raise TimeoutError(message)
        assert not errors, errors
        # A main-thread barrier observes anything already posted, without sleeps.
        on_main_thread(context, lambda: None)
        assert chosen == [None] and not completed, (chosen, completed)
        assert not menu.is_open and (book.active(), book.calc_tabs()) == view
        sheet = book.document.Sheets.getByName("Delta")
        book.controller.setActiveSheet(sheet)
        assert book.controller.select(sheet.getCellRangeByName("A1"))
        before = book.document.CurrentSelection.RangeAddress
        assert (before.StartColumn, before.StartRow) == (0, 0)
        assert dispatch(context, book.frame, ".uno:GoToCell", (prop("ToPoint", "B2"),))
        address = book.document.CurrentSelection.RangeAddress
        assert (address.StartColumn, address.StartRow) == (1, 1), "Frame dispatch stopped working"
        return {"disposed_queue": True, "ordinary_frame_dispatch": True}
    finally:
        if not stalled_callbacks() and book.lab.input.popup_windows():
            book.lab.input.tap("Escape")
