"""Dragging rows to move sheets, a drop in place, Escape during a drag, autoscroll and the wheel.

`drag` presses on a row, glides 12 pixels down and then to a fraction of the target row, and
releases, all with real pointer input. A drop is one undo step that keeps the view and the picks;
a drop in place or a cancelled drag changes nothing. The list scrolls while a drag is held at its
bottom edge, and with the wheel.
"""

import time

import sheet_list_view as view
from workbook import MOVES, NAMES, wait_until
from xinput import RIGHT

from sheet_manager.reorder import Sheet, target_order
from sheet_manager.uno_calc import select_tabs


def drag(book, source, target, fraction, *, hold=0.0, cancel=False, shot=None):
    start = book.point(source)
    end = book.point(target, fraction)
    book.pointer.press(*start)
    book.pointer.glide(start, (start[0], start[1] + 12))
    book.pointer.glide((start[0], start[1] + 12), end)
    time.sleep(0.4 + hold)
    if shot:
        book.lab.screenshot(shot)
    if cancel:
        book.lab.input.tap("Escape", pause=0.3)
    book.pointer.release()
    time.sleep(1.0)


def check_drag_two_sheets(book, fraction, gap):
    select_tabs(book.lab.context, book.frame, [0, 2, 3])
    wait_until(lambda: book.calc_tabs() == NAMES[:1] + NAMES[2:4], "a native Calc group")
    book.click(2)
    book.click(5, modifiers=("Control_L",))
    wait_until(lambda: book.selection() == [NAMES[2], NAMES[5]], "two separate rows selected")
    before, undo_before = book.order(), book.undo_titles()
    active, tabs = book.active(), book.calc_tabs()
    sheets = [Sheet(name) for name in before]
    expected = list(target_order(sheets, [NAMES[2], NAMES[5]], "drop", gap))
    drag(book, 5, 12, fraction, shot=f"drag-gap-{gap}")
    wait_until(lambda: book.order() != before, "the drop to move the sheets")
    after, undo_after = book.order(), book.undo_titles()
    evidence = {
        "gap": gap,
        "fraction_of_row": fraction,
        "before": before[:16],
        "after": after[:16],
        "expected": expected[:16],
        "undo_added": undo_after[: len(undo_after) - len(undo_before)],
        "selection": book.selection(),
        "active": [active, book.active()],
        "calc_tabs": [tabs, book.calc_tabs()],
    }
    assert after == expected, evidence
    assert len(undo_after) == len(undo_before) + 1 and undo_after[0] == "Move Sheets", evidence
    assert book.active() == active and set(book.calc_tabs()) == set(tabs), evidence
    wait_until(lambda: book.selection() == [NAMES[2], NAMES[5]], "the moved rows to stay selected")
    book.document.getUndoManager().undo()
    wait_until(lambda: book.order() == before, "one undo to restore the order")
    evidence["undo_restored"] = True
    return evidence


def check_drop_in_place_and_escape(book):
    book.click(6)
    before, undo_before = book.order(), book.undo_titles()
    drag(book, 6, 6, 0.8)
    in_place = book.order() == before and book.undo_titles() == undo_before
    drag(book, 6, 15, 0.5, cancel=True, shot="drag-escape")
    cancelled = book.order() == before and book.undo_titles() == undo_before
    evidence = {"dropped_in_place_unchanged": in_place, "escape_unchanged": cancelled}
    assert in_place and cancelled, evidence
    return evidence


def check_clicks_after_a_drag(book):
    """A drag leaves its picks, and the next click with a modifier, or right click, acts (#356).

    The plain press of a drag on a selected row leaves VCL's selection engine waiting for the
    button's release. After a drop it never comes, so the engine acts on the next release instead:
    it toggled off a Ctrl+click's row, selected a Shift+click's row alone, and left nothing after
    a Ctrl+Shift+click, and the list took that for someone else's selection and cleared its picks.
    After Esc the release comes, selects the pressed row alone, and the list kept only that one.
    """
    evidence = {}
    picked, source, end = [NAMES[3], NAMES[4]], 4, 11
    gestures = {"ctrl": ("Control_L",), "shift": ("Shift_L",), "both": ("Control_L", "Shift_L")}
    for how in ("dropped", "in_place", "cancelled"):
        for gesture, modifiers in (*gestures.items(), ("right", None)):
            before = book.order()
            book.click(3)
            book.click(source, modifiers=("Control_L",))
            wait_until(lambda: book.selection() == picked, "two rows selected")
            target = source if how == "in_place" else 8
            drag(book, source, target, 0.75, cancel=how == "cancelled")
            order = before
            if how == "dropped":
                wait_until(lambda b=before: book.order() != b, "the drop to move the sheets")
                order = book.order()
            time.sleep(0.6)
            case = f"{how}_{gesture}"
            evidence[case] = {"after_drag": book.selection(), "order": order[:12]}
            assert evidence[case]["after_drag"] == [n for n in order if n in picked], evidence
            if modifiers is None:
                entries = book.entries(picked)
                book.pointer.click(*book.point(order.index(picked[1])), button=RIGHT)
                book.choose(MOVES["bottom"], entries)
                wanted = [n for n in order if n not in picked] + [n for n in order if n in picked]
                wait_until(lambda w=wanted: book.order() == w, f"{case}: both picks at the bottom")
                book.document.getUndoManager().undo()
                wait_until(lambda o=order: book.order() == o, f"{case}: the menu's move undone")
            else:
                book.click(end, modifiers=modifiers)
                first, last = sorted((order.index(NAMES[source]), end))
                chosen = {order[end]} if gesture == "ctrl" else set(order[first : last + 1])
                if gesture != "shift":
                    chosen |= set(picked)
                wanted = [name for name in order if name in chosen]
                try:
                    wait_until(lambda w=wanted: book.selection() == w, f"{case}: {wanted}")
                except AssertionError as error:
                    error.add_note(f"The list shows {book.selection()}; {evidence}")
                    raise
                time.sleep(1.0)
                evidence[case]["after_click"] = book.selection()
                assert evidence[case]["after_click"] == wanted, evidence
            if how == "dropped":
                book.document.getUndoManager().undo()
            wait_until(lambda b=before: view.names(book.tree) == b, f"{case}: the order restored")
            time.sleep(0.6)
    return evidence


def check_autoscroll(book):
    book.click(0)
    book.show_row(0)
    time.sleep(0.3)
    first = book.first_visible()
    height = book.tree.getOutputSize().Height
    start = book.point(0)
    book.pointer.press(*start)
    book.pointer.glide(start, (start[0], start[1] + 12))
    book.pointer.glide((start[0], start[1] + 12), (start[0], height - 3))
    heights = [height]
    deadline = time.monotonic() + 6
    while book.first_visible() <= first + 3 and time.monotonic() < deadline:
        current_height = book.tree.getOutputSize().Height
        if current_height != heights[-1]:
            # A timed footer can expire during the slow glide. Follow the actual bottom
            # edge once when it moves, then leave the pointer stationary to test scrolling.
            heights.append(current_height)
            book.pointer.at(start[0], current_height - 3)
        time.sleep(0.2)
    scrolled = book.first_visible()
    book.lab.screenshot("drag-autoscroll")
    book.lab.input.tap("Escape", pause=0.3)
    book.pointer.release()
    time.sleep(0.8)
    evidence = {
        "first_visible": [first, scrolled],
        "order_unchanged": book.order() == NAMES,
        "viewport_heights": heights,
    }
    assert scrolled > first + 3 and book.order() == NAMES, evidence
    return evidence


def check_wheel(book):
    book.show_row(0)
    time.sleep(0.3)
    first = book.first_visible()
    x, y = book.point(3)
    book.pointer.wheel(x, y, down=True, ticks=5)
    down = book.first_visible()
    book.pointer.wheel(x, y, down=False, ticks=10)
    up = book.first_visible()
    evidence = {"first_visible": [first, down, up]}
    assert down > first and up == first, evidence
    return evidence
