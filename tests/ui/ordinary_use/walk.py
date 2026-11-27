"""A random walk of ordinary sheet-list input at human speed, compared with `model.Model`.

Runs inside the repository's Linux lab image with LibreOffice's Python, under the private Xvfb
display that `session.sh` starts. It reuses the repository's lab (`tests/ui/lab.py`), workbook
fixture (`tests/ui/workbook.py`) and XTEST input (`tests/ui/xinput.py`), and observes only public
UNO: the panel's tree, its footer notice, the move buttons, the document and its undo manager.

Each step draws one input from a seeded RNG (or takes the next one from `--replay`), performs it
with real input, waits for the list's work to run and paint, and compares the tree's selection,
the tree's rows, the document's order, the viewed sheet and Calc's tabs with the model, and that
no notice or dialog appeared. Every step is a JSON line in `steps.jsonl`. After a mismatch the
walk takes a screenshot, resets (Esc, waits out the notice, takes the document's order as the
new baseline and clicks the first row) and continues.
"""

import argparse
import json
import os
import random
import sys
import time
import traceback
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
ROOT = Path("/work")
sys.path[:0] = [
    str(HARNESS),
    str(ROOT / "tests" / "ui"),
    str(ROOT / "tests" / "integration"),
    str(ROOT / "src"),
]

import sheet_list_view as view  # noqa: E402
from com.sun.star.lang import IllegalArgumentException  # noqa: E402
from lab import Lab  # noqa: E402
from model import MOD1, SHIFT, Model  # noqa: E402
from run import office_session  # noqa: E402
from teardown import note_progress, stalled_callbacks  # noqa: E402
from workbook import NATO, Workbook, native_dialog  # noqa: E402
from xinput import LEFT, MIDDLE, RIGHT  # noqa: E402

SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Appearance">
<prop oor:name="LibreOfficeTheme" oor:op="fuse"><value>1</value></prop>
<prop oor:name="ApplicationAppearance" oor:op="fuse"><value>1</value></prop></item>
<item oor:path="/org.openoffice.Office.UI/ColorScheme">
<prop oor:name="CurrentColorScheme" oor:op="fuse">
<value>COLOR_SCHEME_LIBREOFFICE_LIGHT</value></prop>
</item></oor:items>"""

MODS = {0: (), MOD1: ("Control_L",), SHIFT: ("Shift_L",), MOD1 | SHIFT: ("Control_L", "Shift_L")}
CLICK_MODS = ([0, MOD1, SHIFT, MOD1 | SHIFT], [45, 25, 22, 8])
KINDS = [
    ("click", 30),
    ("gutter", 8),
    ("below", 2),
    ("double", 4),
    ("right", 3),
    ("middle", 2),
    ("key", 14),
    ("drag", 9),
    ("button", 6),
    ("shortcut", 6),
    ("undo", 4),
    ("rename", 3),
    ("wheel", 4),
]
KEYS = [
    (("Up", 0), 3),
    (("Down", 0), 3),
    (("Up", SHIFT), 2),
    (("Down", SHIFT), 2),
    (("Up", MOD1), 1.5),
    (("Down", MOD1), 1.5),
    (("Up", MOD1 | SHIFT), 1),
    (("Down", MOD1 | SHIFT), 1),
    (("Home", 0), 1),
    (("End", SHIFT), 0.7),
    (("space", MOD1), 1.5),
    (("a", MOD1), 0.7),
]
SHORTCUTS = [(("Up", "up"), 3), (("Down", "down"), 3), (("Home", "top"), 1), (("End", "bottom"), 1)]
GUTTER_X = (5, 8, 12, 16, 18)


def sheet_names(count):
    return NATO[: min(count, len(NATO))] + [f"Sheet {n}" for n in range(len(NATO) + 1, count + 1)]


class Walk:
    def __init__(self, lab, book, output, seed, sheets):
        self.lab, self.book, self.output = lab, book, output
        self.tree, self.context = book.tree, lab.context
        self.rng = random.Random(seed)
        self.count = sheets
        self.model = Model(book.order(), book.active())
        self.notice = view.footer_text(book.panel, "Why the sheet list")
        self.timeout = 10 if sheets <= 100 else 30
        self.steps = 0
        self.renames = 0
        self.mismatches = []
        self.history = []
        self.log = open(output / "steps.jsonl", "a", encoding="utf-8")
        size = self.tree.getOutputSize()
        self.width = size.Width
        self.below_gap = self.measure_below()

    # Geometry

    def node(self, row):
        return view.root(self.tree).getChildAt(row)

    def rect(self, row):
        for attempt in range(20):
            try:
                return self.tree.getNodeRect(self.node(row))
            except IllegalArgumentException:  # A rebuild replaced the rows meanwhile.
                time.sleep(0.2)
        return self.tree.getNodeRect(self.node(row))

    def visible(self, row, margin=0):
        rect = self.rect(row)
        height = self.tree.getOutputSize().Height
        return rect.Y >= margin * rect.Height and rect.Y + rect.Height <= height - margin * rect.Height

    def show(self, row):
        """Scroll `row` into view if it is not; True if the view scrolled."""
        if self.visible(row):
            return False
        for attempt in range(20):
            try:
                self.tree.makeNodeVisible(self.node(row))
                break
            except IllegalArgumentException:
                time.sleep(0.2)
        time.sleep(0.3)
        view.on_main_thread(self.context, lambda: None)
        time.sleep(0.3)
        return True

    def show_with_margin(self, row, margin=3):
        scrolled = False
        for other in (max(0, row - margin), min(self.count - 1, row + margin), row):
            scrolled = self.show(other) or scrolled
        return scrolled

    def first_visible(self):
        rect = self.rect(0)
        return max(0, -(rect.Y - 3) // max(1, rect.Height))

    def measure_below(self):
        """The pixels between the last row and the tree's bottom edge when scrolled to the end."""
        self.show(self.count - 1)
        rect = self.rect(self.count - 1)
        gap = self.tree.getOutputSize().Height - (rect.Y + rect.Height)
        self.show(0)
        return gap

    def point(self, row, x, fraction):
        rect = self.rect(row)
        return x, rect.Y + int(rect.Height * fraction)

    # Drawing an input

    def pick_row(self):
        if self.rng.random() < 0.7:
            row = self.model.row(self.model.cursor) + self.rng.randint(-12, 12)
            return max(0, min(self.count - 1, row))
        return self.rng.randrange(self.count)

    def label_x(self):
        return self.rng.randint(28, max(40, min(self.width - 30, 200)))

    def draw(self):
        model = self.model
        eligible = {
            "below": self.below_gap >= 6,
            "drag": bool(model.picked),
            "button": bool(model.picked),
            "shortcut": bool(model.picked),
            "undo": model.can_undo(),
        }
        kinds = [(kind, weight) for kind, weight in KINDS if eligible.get(kind, True)]
        kind = self.rng.choices([k for k, _ in kinds], [w for _, w in kinds])[0]
        rng = self.rng
        if kind in ("click", "gutter"):
            mods = rng.choices(*CLICK_MODS)[0]
            x = self.label_x() if kind == "click" else rng.choice(GUTTER_X)
            return {"kind": kind, "row": self.pick_row(), "mods": mods, "x": x,
                    "frac": round(rng.uniform(0.3, 0.7), 2)}
        if kind == "below":
            return {"kind": kind, "mods": rng.choices(*CLICK_MODS)[0], "x": self.label_x()}
        if kind in ("double", "right", "middle"):
            return {"kind": kind, "row": self.pick_row(), "x": self.label_x(),
                    "frac": round(rng.uniform(0.3, 0.7), 2)}
        if kind == "key":
            code, mods = rng.choices([k for k, _ in KEYS], [w for _, w in KEYS])[0]
            return {"kind": kind, "key": code, "mods": mods}
        if kind == "drag":
            rows = sorted(model.row(name) for name in model.picked)
            source = rng.choice(rows)
            how = rng.choice(["on_source", "cancel", "drop"])
            if how == "on_source":
                target, fraction = source, rng.choice([0.25, 0.75])
            elif how == "cancel":
                target, fraction = source + rng.choice([-1, 1]) * rng.randint(2, 6), 0.5
            else:
                target = source + rng.choice([-1, 1]) * rng.randint(1, 8)
                fraction = rng.choice([0.25, 0.75])
            target = max(0, min(self.count - 1, target))
            return {"kind": kind, "how": how, "row": source, "target": target, "frac": fraction,
                    "x": self.label_x()}
        if kind == "button":
            return {"kind": kind, "action": rng.choice(["top", "up", "down", "bottom"])}
        if kind == "shortcut":
            key, action = rng.choices([k for k, _ in SHORTCUTS], [w for _, w in SHORTCUTS])[0]
            return {"kind": kind, "key": key, "action": action}
        if kind == "undo":
            return {"kind": kind}
        if kind == "rename":
            if model.picked and rng.random() < 0.5:
                row = model.row(rng.choice(sorted(model.picked)))
            else:
                row = self.pick_row()
            return {"kind": kind, "row": row}
        return {"kind": "wheel", "down": rng.random() < 0.5, "ticks": rng.randint(1, 4)}

    # Performing an input, and what the model expects of it

    def perform(self, step):
        """Give the input with real input; update the model; return notes for the log."""
        book, model, kind = self.book, self.model, step["kind"]
        pointer = book.pointer
        notes = {}
        if "row" in step:
            step["name"] = model.order[step["row"]]
        if kind in ("click", "gutter"):
            notes["scrolled"] = self.show(step["row"])
            x, y = self.point(step["row"], min(step["x"], self.width - 10), step["frac"])
            pointer.click(x, y, modifiers=MODS[step["mods"]])
            model.click(step["row"], step["mods"])
        elif kind == "below":
            notes["scrolled"] = self.show(self.count - 1)
            rect = self.rect(self.count - 1)
            gap = self.tree.getOutputSize().Height - (rect.Y + rect.Height)
            notes["gap"] = gap
            pointer.click(min(step["x"], self.width - 10), rect.Y + rect.Height + gap // 2,
                          modifiers=MODS[step["mods"]])
        elif kind == "double":
            notes["scrolled"] = self.show(step["row"])
            x, y = self.point(step["row"], min(step["x"], self.width - 10), step["frac"])
            pointer.click(x, y, pause=0.02)
            pointer.click(x, y)
            model.double(step["row"])
        elif kind == "right":
            notes["scrolled"] = self.show(step["row"])
            x, y = self.point(step["row"], min(step["x"], self.width - 10), step["frac"])
            before = self.lab.input.popup_windows()
            pointer.click(x, y, button=RIGHT, pause=0.6)
            notes["menu_opened"] = bool(self.lab.input.popup_windows() - before)
            self.lab.input.tap("Escape", pause=0.5)
            notes["menu_left_open"] = bool(self.lab.input.popup_windows() - before)
        elif kind == "middle":
            notes["scrolled"] = self.show(step["row"])
            x, y = self.point(step["row"], min(step["x"], self.width - 10), step["frac"])
            pointer.click(x, y, button=MIDDLE)
        elif kind == "key":
            notes["focus_before"] = bool(self.tree.hasFocus())
            self.lab.input.tap(step["key"], MODS[step["mods"]], pause=0.6)
            model.key(step["key"], step["mods"])
        elif kind == "drag":
            notes.update(self.drag(step))
        elif kind == "button":
            notes.update(self.button(step))
        elif kind == "shortcut":
            notes["focus_before"] = bool(self.tree.hasFocus())
            notes["moved"] = model.move(step["action"])
            self.lab.input.tap(step["key"], ("Alt_L",), pause=0.6)
        elif kind == "undo":
            notes["focus_before"] = bool(self.tree.hasFocus())
            self.lab.input.tap("z", ("Control_L",), pause=0.6)
            model.undo_move()
        elif kind == "rename":
            self.renames += 1
            old = model.order[step["row"]]
            base = old.split(" ~")[0]
            new = f"{base} ~{self.renames}"
            step["new"] = new
            book.document.getSheets().getByIndex(step["row"]).setName(new)
            model.rename(step["row"], new)
            time.sleep(0.3)
        elif kind == "wheel":
            first = self.first_visible()
            rows = max(1, self.tree.getOutputSize().Height // max(1, self.rect(0).Height))
            row = min(self.count - 1, first + rows // 2)
            x, y = self.point(row, 60, 0.5)
            pointer.wheel(x, y, down=step["down"], ticks=step["ticks"])
            notes["first_visible"] = [first, self.first_visible()]
        else:
            raise ValueError(kind)
        return notes

    def drag(self, step):
        model, pointer = self.model, self.book.pointer
        source, target = step["row"], step["target"]
        notes = {"scrolled": self.show_with_margin(target)}
        notes["scrolled"] = self.show_with_margin(source) or notes["scrolled"]
        if not self.visible(target, margin=1):
            notes["target_hidden"] = True
        x = min(step["x"], self.width - 10)
        start = self.point(source, x, 0.5)
        end = self.point(target, x, step["frac"])
        notes["points"] = [start, end]
        pointer.press(*start)
        pointer.glide(start, (start[0], start[1] + 12))
        pointer.glide((start[0], start[1] + 12), end)
        time.sleep(0.4)
        if step["how"] == "cancel":
            self.lab.input.tap("Escape", pause=0.3)
        pointer.release()
        time.sleep(1.0)
        model.press_drag(source)
        if step["how"] != "cancel":
            gap = target + (1 if step["frac"] >= 0.5 else 0)
            notes["gap"] = gap
            notes["moved"] = model.move("drop", gap)
        return notes

    def button(self, step):
        model, book = self.model, self.book
        buttons = view.move_buttons(book.panel)
        control = buttons[step["action"].capitalize()]
        expected = bool(model.picked) and model.target(step["action"]) != model.order
        deadline = time.monotonic() + 3
        while bool(control.isEnabled()) != expected and time.monotonic() < deadline:
            time.sleep(0.1)
        notes = {"enabled": bool(control.isEnabled()), "enabled_expected": expected}
        book.click_control(control)
        notes["moved"] = model.move(step["action"])
        return notes

    # Observing and comparing

    def observe(self, full):
        book = self.book
        seen = {
            "picks": book.selection(),
            "order": book.order(),
            "notice": self.notice.getText(),
            "active": book.active(),
        }
        if full:
            seen["tree"] = view.names(self.tree)
            seen["tabs"] = book.calc_tabs()
            seen["dialog"] = bool(native_dialog(book))
            seen["focus"] = bool(self.tree.hasFocus())
            seen["undo_steps"] = len(book.undo_titles())
        return seen

    def differences(self, seen, full):
        model = self.model
        wrong = []
        if seen["picks"] != model.picks():
            wrong.append("picks")
        if seen["order"] != model.order:
            wrong.append("order")
        if seen["notice"]:
            wrong.append("notice")
        if seen["active"] != model.active:
            wrong.append("active")
        if full:
            if seen["tree"] != model.order:
                wrong.append("tree_rows")
            if seen["tabs"] != [model.active]:
                wrong.append("tabs")
            if seen["dialog"]:
                wrong.append("dialog")
        return wrong

    def settle(self, rows=False):
        """Wait for the list's work, then a quiet half second; the full observation.

        With `rows`, after a rename or a move, the wait includes the list's refresh showing the
        rows: at 1,000 sheets the document changes at once and the rate-limited refresh later.
        """
        view.on_main_thread(self.context, lambda: None)
        deadline = time.monotonic() + self.timeout
        while True:
            seen = self.observe(False)
            done = not self.differences(seen, False)
            if done and rows:
                done = view.names(self.tree) == self.model.order
            if done or time.monotonic() > deadline:
                break
            time.sleep(0.15)
        time.sleep(0.5)
        view.on_main_thread(self.context, lambda: None)
        return self.observe(True)

    def record(self, entry):
        self.log.write(json.dumps(entry) + "\n")
        self.log.flush()

    # The walk

    def start(self):
        """Pick the first row with a plain click: the walk's start and its reset state."""
        self.show(0)
        x, y = self.point(0, 60, 0.5)
        self.book.pointer.click(x, y)
        self.model.click(0, 0)
        seen = self.settle()
        wrong = self.differences(seen, True)
        self.record({"step": "start", "expected": self.model.state(), "seen": brief(seen),
                     "wrong": wrong})
        return not wrong

    def step(self, item, index):
        note_progress()
        started = time.monotonic()
        before = self.observe(False)
        late = self.differences(before, False)
        if late:  # A change after the previous step's check: the previous step's.
            self.mismatch(index - 1, {"kind": "late"}, before, late, {})
            if not self.reset(index):
                return False
        undo_before = len(self.book.undo_titles())
        error = None
        try:
            notes = self.perform(item)
        except Exception:
            error = traceback.format_exc()
            notes = {}
        seen = self.settle(rows=bool(notes.get("moved")) or item["kind"] in ("rename", "undo"))
        wrong = self.differences(seen, True)
        if item["kind"] in ("button", "shortcut", "drag") and "moved" in notes:
            wanted = undo_before + (1 if notes["moved"] else 0)
            if seen["undo_steps"] != wanted:
                wrong.append("undo_steps")
        if item["kind"] == "undo" and seen["undo_steps"] != undo_before - 1:
            wrong.append("undo_steps")
        if item["kind"] == "button" and notes.get("enabled") != notes.get("enabled_expected"):
            wrong.append("button_enabled")
        if notes.get("menu_left_open"):
            wrong.append("menu_left_open")
        if error:
            wrong.append("harness_error")
        entry = {
            "step": index,
            "input": item,
            "notes": notes,
            "expected": self.model.state(),
            "seen": brief(seen),
            "wrong": wrong,
            "seconds": round(time.monotonic() - started, 2),
        }
        if error:
            entry["error"] = error
        if notes.get("moved") or item["kind"] in ("undo", "rename") or wrong:
            entry["expected_order"] = self.model.order
            entry["seen_order"] = seen["order"]
            if seen["tree"] != seen["order"]:
                entry["seen_tree"] = seen["tree"]
        self.record(entry)
        self.history.append(entry)
        self.steps = index
        if wrong:
            self.mismatch(index, item, seen, wrong, notes)
            return self.reset(index)
        return True

    def mismatch(self, index, item, seen, wrong, notes):
        name = f"mismatch-{index:04d}"
        try:
            self.lab.screenshot(name)
        except Exception:
            pass
        self.mismatches.append({
            "step": index,
            "input": item,
            "wrong": wrong,
            "expected": self.model.state(),
            "seen": brief(seen),
            "notes": notes,
            "screenshot": f"{name}.png",
            "last_steps": [h["input"] for h in self.history[-12:]],
        })
        print(f"MISMATCH at step {index}: {wrong} after {item}", flush=True)

    def reset(self, index):
        """Clear the input and the notice, take the document's order, click the first row."""
        lab = self.lab
        lab.input.release_held()
        if native_dialog(self.book):
            lab.screenshot(f"dialog-{index:04d}")
            lab.input.tap("Return", pause=0.6)
        lab.input.tap("Escape", pause=0.4)
        deadline = time.monotonic() + 16
        while self.notice.getText() and time.monotonic() < deadline:
            time.sleep(0.3)
        self.model.resync(self.book.order(), self.book.active())
        ok = self.start()
        self.record({"step": f"reset-after-{index}", "ok": ok})
        if not ok:
            print(f"Reset after step {index} failed; ending the run", flush=True)
        return ok


def brief(seen):
    """The observation without the long lists, which the step logs separately."""
    return {key: value for key, value in seen.items() if key not in ("order", "tree")}


def walk(lab, output, arguments):
    names = sheet_names(arguments.sheets)
    started = time.monotonic()
    book = Workbook(lab, f"walk-{arguments.sheets}", names)
    opened = round(time.monotonic() - started, 1)
    lab.screenshot("panel")
    summary = {
        "vcl": arguments.vcl,
        "sheets": arguments.sheets,
        "seed": arguments.seed,
        "steps_planned": arguments.steps,
        "workbook_seconds": opened,
    }
    walker = Walk(lab, book, output, arguments.seed, arguments.sheets)
    summary["tree_width"] = walker.width
    summary["below_gap"] = walker.below_gap
    summary["calibrations"] = lab.calibrations

    def save():
        summary["steps_completed"] = walker.steps
        summary["mismatches"] = walker.mismatches
        summary["mismatch_count"] = len(walker.mismatches)
        summary["walk_seconds"] = round(time.monotonic() - walk_started, 1)
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")

    walk_started = time.monotonic()
    if not walker.start():
        summary["start_failed"] = True
        save()
        return summary
    if arguments.replay:
        items = json.loads(Path(arguments.replay).read_text("utf-8"))
    else:
        items = None
    total = len(items) if items is not None else arguments.steps
    for index in range(1, total + 1):
        item = dict(items[index - 1]) if items is not None else walker.draw()
        for key in ("name", "new"):
            item.pop(key, None)
        if not walker.step(item, index):
            summary["ended_early"] = index
            break
        if index % 10 == 0:
            save()
            print(f"step {index}: {len(walker.mismatches)} mismatches", flush=True)
        if stalled_callbacks():
            summary["stalled"] = stalled_callbacks()[0]
            break
    save()
    lab.screenshot("end")
    # Content: only Alfa's A1 holds anything, as the fixture made it.
    sheets = book.document.getSheets()
    content = []
    for index in range(sheets.getCount()):
        sheet = sheets.getByIndex(index)
        cursor = sheet.createCursor()
        cursor.gotoEndOfUsedArea(False)
        address = cursor.getRangeAddress()
        if (address.EndColumn, address.EndRow) != (0, 0) or (
            sheet.getCellByPosition(0, 0).getString() not in ("", "keep")
        ):
            content.append(sheet.getName())
    keep = [sheets.getByIndex(i).getName() for i in range(sheets.getCount())
            if sheets.getByIndex(i).getCellByPosition(0, 0).getString() == "keep"]
    summary["content_unexpected"] = content
    summary["content_keep"] = keep
    save()
    book.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vcl", choices=["gtk3", "gen"], default="gtk3")
    parser.add_argument("--sheets", type=int, default=60)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--replay", help="A JSON list of inputs to give instead of drawing them")
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(ROOT / "tests" / "ui") + os.pathsep + os.environ["PATH"]
    os.environ["SHEET_MANAGER_URI_LOG"] = str(output / "opened-uris.txt")
    result = {"vcl": arguments.vcl}
    failed = False
    try:
        with office_session(
            arguments.program.resolve(),
            arguments.oxt.resolve(),
            output,
            result,
            headless=False,
            vcl=arguments.vcl,
            settings=SETTINGS,
        ) as (context, desktop, directory):
            lab = Lab(context, desktop, directory, output)
            result["walk"] = walk(lab, output, arguments)
    except Exception:
        result["error"] = traceback.format_exc()
        print(result["error"], flush=True)
        failed = True
    logs = "".join(p.read_text("utf-8", "replace") for p in output.glob("soffice-*.log"))
    result["extension_errors"] = logs.count("Sheet Manager: ")
    (output / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n", "utf-8")
    walk_result = result.get("walk", {})
    print(json.dumps({k: v for k, v in walk_result.items() if k not in ("mismatches", "calibrations")},
                     indent=2), flush=True)
    print("extension_errors", result["extension_errors"], "error" in result, flush=True)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
