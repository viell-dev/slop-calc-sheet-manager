"""Probe: a drag of a picked row dropped on its own row, with a large selection (run 4's mismatch).

Uses the walk's helpers. Each trial sets up a selection with real input, optionally lets the office
run this process's pending UNO releases and sit idle, then gives the walk's on-source drag (press,
12 px down, back to 75 % of the row, 0.4 s, release) and reads the picks. `PressProbe` times when
the tree's listeners heard the press and release, from the XTEST press.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import walk  # noqa: E402  (sets sys.path for the repository modules)
from client_releases import settle_releases  # noqa: E402
from lab import Lab  # noqa: E402
from run import office_session  # noqa: E402
from workbook import PressProbe, Workbook  # noqa: E402

import sheet_list_view as view  # noqa: E402


def trial(w, probe, selection, quiet, far_pause, source, label, hold=0.4, offset=0):
    book, model = w.book, w.model
    # The selection, by real input, as the walk makes one.
    w.show(0)
    x, y = w.point(0, 60, 0.5)
    book.pointer.click(x, y)
    model.click(0, 0)
    if isinstance(selection, int):  # The last `selection` rows: a click and Shift+End.
        first = w.count - selection
        source = first + selection // 2
        w.show(first)
        x, y = w.point(first, 60, 0.5)
        book.pointer.click(x, y)
        model.click(first, 0)
        book.lab.input.tap("End", ("Shift_L",), pause=0.6)
        model.key("End", 1)
    elif selection == "range":  # A click on row 155 and Shift+End: rows 155 to the end.
        first = min(155, w.count // 3)
        w.show(first)
        x, y = w.point(first, 60, 0.5)
        book.pointer.click(x, y)
        model.click(first, 0)
        book.lab.input.tap("End", ("Shift_L",), pause=0.6)
        model.key("End", 1)
    elif selection == "two":
        w.show(source)
        x, y = w.point(source, 60, 0.5)
        book.pointer.click(x, y)
        model.click(source, 0)
        x, y = w.point(source + 2, 60, 0.5)
        book.pointer.click(x, y, modifiers=("Control_L",))
        model.click(source + 2, 2)
    elif selection == "all":
        book.lab.input.tap("a", ("Control_L",), pause=0.6)
        model.key("a", 2)
    seen = w.settle()
    assert not w.differences(seen, True), ("setup", w.differences(seen, True))
    target = source + offset
    w.show_with_margin(source)
    w.show_with_margin(target)
    start = w.point(source, 53, 0.5)
    end = w.point(target, 53, 0.75)
    release_wait = None
    if quiet:
        started = time.monotonic()
        error = settle_releases(w.context, 60)
        release_wait = round(time.monotonic() - started, 2)
        if error:
            print("settle_releases:", error, flush=True)
        time.sleep(2.0)
    heard = len(probe.heard)
    pointer = book.pointer
    if hold < 0:  # Measure: how long the main thread takes to answer after a still press.
        pressed = time.monotonic()
        pointer.press(*start)
        view.on_main_thread(w.context, lambda: None)
        answered = time.monotonic() - pressed
        while not any(k == "pressed" for k, _ in probe.heard[heard:]):
            time.sleep(0.01)
        view.on_main_thread(w.context, lambda: None)
        after_listener = time.monotonic() - pressed
        pointer.release()
        time.sleep(1.0)
        model.click(source, 0)
        seen = w.settle()
        events = [(kind, round(at - pressed, 3)) for kind, at in probe.heard[heard:]]
        result = {"label": label, "picked": selection, "busy_first_answer": round(answered, 3),
                  "busy_after_listener": round(after_listener, 3), "heard": events,
                  "wrong": w.differences(seen, True)}
        print(json.dumps(result), flush=True)
        model.picked = set(seen["picks"])
        model.order = list(seen["order"])
        return result
    pressed = time.monotonic()
    pointer.press(*start)
    if far_pause == 0.01:  # The same wiggle at a person's pace: 0.5 s out, 0.25 s back.
        pointer.glide(start, (start[0], start[1] + 12), pause=0.12)
        pointer.glide((start[0], start[1] + 12), end, pause=0.12)
        far_pause = None
    else:
        pointer.glide(start, (start[0], start[1] + 12))
    if far_pause is None:
        pass
    elif far_pause >= 1:  # Away to `far_pause` rows below, a pause, then to the end point.
        via = w.point(source + int(far_pause), 53, 0.5)
        pointer.glide((start[0], start[1] + 12), via, pause=0.03)
        time.sleep(0.5)
        pointer.glide(via, end, pause=0.03)
    elif far_pause < 0:  # The wiggle, still for -far_pause s, then a 2 px nudge and back.
        pointer.glide((start[0], start[1] + 12), end)
        time.sleep(-far_pause)
        pointer.at(end[0], end[1] + 2, 0.1)
        pointer.at(*end)
    else:
        if far_pause:
            time.sleep(far_pause)
        pointer.glide((start[0], start[1] + 12), end)
    time.sleep(hold)
    released = time.monotonic()
    pointer.release()
    time.sleep(1.0)
    model.press_drag(source)
    moved = model.move("drop", target + 1)
    seen = w.settle(rows=moved)
    events = [(kind, round(at - pressed, 3)) for kind, at in probe.heard[heard:]]
    result = {
        "label": label,
        "sheets": w.count,
        "selection": selection,
        "picked": len(model.picked),
        "quiet": quiet,
        "release_wait": release_wait,
        "far_pause": far_pause,
        "hold": hold,
        "offset": offset,
        "moved": moved,
        "release_after": round(released - pressed, 3),
        "heard": events,
        "seen_picks": len(seen["picks"]),
        "wrong": w.differences(seen, True),
        "notice": seen["notice"],
    }
    print(json.dumps(result), flush=True)
    if result["wrong"]:
        w.lab.screenshot(f"probe-{label}")
        deadline = time.monotonic() + 16
        while w.notice.getText() and time.monotonic() < deadline:
            time.sleep(0.3)
    model.picked = set(seen["picks"])  # Continue from what the list shows.
    model.order = list(seen["order"])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vcl", default="gtk3")
    parser.add_argument("--sheets", type=int, default=1000)
    parser.add_argument("--plan", required=True, help="JSON list of [selection, quiet, far_pause, hold, offset]")
    parser.add_argument("--repeat", type=int, default=1)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    plan = json.loads(arguments.plan)
    results = {"vcl": arguments.vcl, "trials": []}
    with office_session(
        arguments.program.resolve(), arguments.oxt.resolve(), output, results,
        headless=False, vcl=arguments.vcl, settings=walk.SETTINGS,
    ) as (context, desktop, directory):
        lab = Lab(context, desktop, directory, output)
        book = Workbook(lab, f"probe-{arguments.sheets}", walk.sheet_names(arguments.sheets))
        w = walk.Walk(lab, book, output, 0, arguments.sheets)
        probe = PressProbe()
        book.tree.addMouseListener(probe)
        source = min(549, arguments.sheets - 5)
        for round_ in range(arguments.repeat):
            for index, (selection, quiet, far_pause, hold, offset) in enumerate(plan):
                label = f"{round_}-{index}-{selection}-{'quiet' if quiet else 'busy'}-{hold}-{offset}"
                try:
                    results["trials"].append(trial(
                        w, probe, selection, quiet, far_pause, source, label, hold, offset))
                except Exception as error:
                    results["trials"].append({"label": label, "error": repr(error)})
                    print(label, repr(error), flush=True)
                    lab.input.release_held()
                    lab.input.tap("Escape", pause=0.4)
        book.tree.removeMouseListener(probe)
        book.close()
    (output / "probe.json").write_text(json.dumps(results, indent=2, default=str), "utf-8")


if __name__ == "__main__":
    main()
