"""Paint and screen-reader research using the repository's private XTEST lab."""
import json
import platform
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / folder) for folder in ("tests/ui", "tests/integration", "src")]
from run_windows_ui import SETTINGS, WindowsLab
from winput import WinInput
from rename_dialog import find_dialog, identities, identify, open_dialog, wait_closed
from run import office_session, wait_for
from workbook import Workbook
from worker_m_controls import button, rename_candidates, sidebar_after, sidebar_before, stock_dialog

MODE = sys.argv[1]
OUT = (root / "test-results" / "windows-desktop" / MODE).resolve()
OUT.mkdir(parents=True, exist_ok=True)
PROGRAM = Path(r"C:\Program Files\LibreOffice\program")
PACKAGE = next((root / "dist").glob("*.oxt"))
NAMES = [
    "Overview",
    "North region quarterly Actuals",
    "South region quarterly Actuals",
    "East region quarterly Budget",
    "Control",
]
REFERENCE = NAMES[3]
record = {"mode": MODE}

def save():
    (OUT / "result.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def marker(text):
    print(f"{time.time():.3f} {text}", flush=True)
    if MODE == "nvda":
        time.sleep(1.7)

def set_text(text):
    lab.input.tap("a", ("Control_L",), pause=0.1)
    for char in text:
        key = "space" if char == " " else char.lower()
        modifiers = ("Shift_L",) if char.isupper() else ()
        lab.input.tap(key, modifiers, pause=0.02)

def bounds(window):
    box = window.getPosSize()
    return [box.X, box.Y, box.Width, box.Height]

def focus_state(dialog):
    root = dialog.window.getProperty("XAccessible").getAccessibleContext()
    import uno
    focused = uno.getConstantByName("com.sun.star.accessibility.AccessibleStateType.FOCUSED")
    def visit(node, depth):
        if node.getAccessibleStateSet() & focused:
            return (node.getAccessibleRole(), node.getAccessibleName())
        if depth:
            for i in range(node.getAccessibleChildCount()):
                child = node.getAccessibleChild(i).getAccessibleContext()
                found = visit(child, depth - 1)
                if found:
                    return found
        return None
    return visit(root, 4)

try:
    real_input = WinInput()
    record["desktop"] = real_input.desktop()
    assert record["desktop"]["session"] != 0 and record["desktop"]["input_desktop"]
    record["platform"] = platform.platform()
    record["vcl"] = "win"
    with office_session(
        PROGRAM, PACKAGE, OUT, record, headless=False, vcl="win", settings=SETTINGS
    ) as (
        context, desktop, directory
    ):
        lab = WindowsLab(context, desktop, directory, OUT, real_input)
        marker("Open workbook and deck")
        book = Workbook(lab, "Synthetic accessibility workbook", NAMES)
        identify(book, NAMES)
        def workbook():
            return {
                "order": book.order(), "identities": identities(book), "viewed": book.active(),
                "tabs": book.calc_tabs(), "picks": book.selection(), "undo": book.undo_titles(),
                "a1": book.document.getSheets().getByIndex(0).getCellRangeByName("A1").String,
                "modified": book.document.isModified(),
            }
        try:
            sidebar, sidebar_events = sidebar_before(book, record)
            marker("Focus viewed row")
            book.click(0)
            marker("Pick North and South by Down then Shift+Down")
            lab.input.tap("Down", pause=0.6)
            marker("North row picked")
            lab.input.tap("Down", ("Shift_L",), pause=0.6)
            marker("Report NVDA focus on the selected sidebar row via Insert+Tab")
            lab.input.tap("Tab", ("Insert",), pause=0.5)
            wait_for(lambda: book.selection() == NAMES[1:3], "two independent picks")
            marker("North and South picked")
            sidebar_after(book, record, sidebar, sidebar_events)
            record["before"] = workbook()
            assert record["before"]["tabs"] == [NAMES[0]]
            assert record["before"]["viewed"] == NAMES[0]
            acc = book.tree.getProperty("XAccessible").getAccessibleContext()
            record["tree"] = {
                "name": acc.getAccessibleName(), "bounds": bounds(book.tree),
                "row_height": book.tree.getProperty("RowHeight"),
            }
            lab.screenshot("sidebar-picked")

            marker("Open context menu via Menu and choose Rename Sheets via keyboard")
            dialog = open_dialog(book, NAMES[1:3], lambda: lab.input.tap("Menu", pause=0.4))
            record["opened"] = dialog.state()
            record["dialog_bounds"] = bounds(dialog.window)
            record["status_bounds"] = bounds(dialog.status)
            record["controls"] = dialog.labels()
            record["open_focus"] = focus_state(dialog)
            lab.screenshot("rename-find")
            marker("Find focused, enter search text and press Enter in Find")
            set_text("Actuals")
            wait_for(lambda: dialog.text(dialog.find) == "Actuals", "search text in Find")
            lab.input.tap("Return", pause=0.5)
            assert find_dialog(book) is not None
            record["after_enter"] = workbook()
            assert record["after_enter"] == record["before"]
            assert dialog.state() == record["opened"]

            marker("Tab to Replace with, enter Forecast, activate Replace All by Alt+A")
            lab.input.tap("Tab")
            set_text("Forecast")
            wait_for(lambda: dialog.text(dialog.replace) == "Forecast", "replacement text")
            lab.input.tap("a", ("Alt_L",), pause=0.5)
            wait_for(lambda: dialog.state()["rename_enabled"], "valid proposals")
            record["valid"] = dialog.state()
            lab.screenshot("rename-valid")
            marker("Move focus to New name via Alt+N and type an existing unpicked sheet name")
            lab.input.tap("n", ("Alt_L",))
            set_text(REFERENCE)
            wait_for(lambda: "already named" in dialog.state()["status"], "duplicate refusal")
            record["duplicate"] = dialog.state()
            record["duplicate_focus"] = focus_state(dialog)
            assert not record["duplicate"]["rename_enabled"]
            record["disabled_rename"] = button(dialog.buttons["Rename"])
            lab.screenshot("rename-duplicate")
            if MODE == "nvda":
                rename_candidates(book, dialog, record, marker)
            marker("Duplicate refusal settled, Tab once and then Shift+Tab")
            lab.input.tap("Tab", pause=0.5)
            record["focus_after_tab"] = focus_state(dialog)
            lab.input.tap("Tab", ("Shift_L",), pause=0.5)
            record["focus_after_reverse_tab"] = focus_state(dialog)

            if MODE == "nvda":
                marker("NVDA report current focus via Insert+Tab")
                lab.input.tap("Tab", ("Insert",), pause=0.5)
                marker("Focus Sheets preview with Alt+S")
                lab.input.tap("s", ("Alt_L",), pause=0.6)
                record["preview_focus"] = focus_state(dialog)
                marker("Read the next proposal and then return to the refused proposal")
                lab.input.tap("Down", pause=1)
                lab.input.tap("Up", pause=1)
                marker("Report NVDA focus on the refused proposal via Insert+Tab")
                lab.input.tap("Tab", ("Insert",), pause=0.5)

            marker("Esc to workbook")
            lab.input.tap("Escape", pause=0.5)
            wait_closed(book)
            wait_for(lambda: book.selection() == NAMES[1:3], "picks restored")
            record["after_escape"] = workbook()
            assert record["after_escape"] == record["before"]
            lab.screenshot("workbook-after-escape")
            stock_dialog(book, record, marker, MODE == "nvda")
            record["passed"] = True
        except BaseException:
            lab.screenshot("failure")
            raise
        finally:
            if find_dialog(book) is not None:
                lab.input.tap("Escape", pause=0.5)
                wait_closed(book)
            book.close()
finally:
    save()
