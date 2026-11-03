"""Click the host's painted sidebar '?' in the fixed private Linux input lab (#81).

GTK's weld header is absent from the UNO accessible subtree. The default Linux lab header
places '?' 18 px left of the tree's right edge and 18 px above the panel's top. Use pointer
calibration for the panel origin (#9), never accessibility's global coordinates. This is a lab
layout, not a production dependency or a promise about arbitrary themes. Both gtk3 and gen run
it; Windows/Mac integration separately checks installed help registration and locale fallback.
"""

import uno
from sheet_list_view import on_main_thread, poll
from teardown import close_leftovers, stalled_callbacks
from test_help import HID, TITLE, read_help


def check_header(book):
    context, desktop = book.lab.context, book.lab.desktop
    assert TITLE in read_help(context, HID, "en-US")
    flags = uno.getConstantByName("com.sun.star.frame.FrameSearchFlag.ALL")
    before = (
        book.order(),
        book.active(),
        book.calc_tabs(),
        book.selection(),
        book.undo_titles(),
        book.document.isModified(),
    )
    tree = book.tree.getPosSize()
    origin_y = book.pointer.offset[1] - tree.Y
    point = book.pointer.offset[0] + tree.Width - 18, origin_y - 18
    book.lab.screenshot("header-help-before")
    failure: BaseException | None = None
    try:
        book.lab.input.move(*point)
        book.lab.input.button(1, True)
        book.lab.input.button(1, False)
        frame = poll(lambda: desktop.findFrame("OFFICE_HELP", flags), "the native help viewer")
        # The host creates the child frame before attaching its HTML controller.
        model = poll(
            lambda: frame.Controller.Model if frame.Controller is not None else None,
            "the native help controller",
        )
        text = poll(lambda: model.Text.String, "the registered topic's text")
        assert TITLE in text and "Picking rows alone does not group" in text, text
        url = model.URL
        assert f"/scalc/{HID}?" in url, url
        book.lab.screenshot("header-help-topic")
    except BaseException as error:
        failure = error
        raise
    finally:
        if not stalled_callbacks():
            task = desktop.findFrame("OFFICE_HELP_TASK", flags)
            if task is not None:
                close_leftovers(
                    [task], lambda item: on_main_thread(context, lambda: item.close(True)), failure
                )
            elif book.lab.input.modal_dialog():
                book.lab.input.tap("Escape", pause=0.5)
    after = (
        book.order(),
        book.active(),
        book.calc_tabs(),
        book.selection(),
        book.undo_titles(),
        book.document.isModified(),
    )
    assert before == after, (before, after)
    return {"topic": url, "text": text, "click": list(point), "document_unchanged": True}
