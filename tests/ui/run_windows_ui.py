"""Real-input tests of the sheet list on a visible Windows desktop, through SendInput (#114).

Run with LibreOffice's bundled Python on a disposable GitHub-hosted Windows runner, normally
through `.github/workflows/windows-desktop.yml`, which sets SHEET_MANAGER_REAL_DESKTOP=1. The
runner's job is in the active console session, so a visible LibreOffice receives real keyboard
and mouse input there; an agent shell in session 0 cannot run this suite. The input goes to the
real desktop: never run it on a person's computer.

The checks are `run_ui.py`'s and `rename_dialog.py`'s own, driven through `winput.WinInput`
instead of XTEST, so each behaviour has one statement on both platforms. Like them, they observe
only public UNO: the panel's `XPanel.getDialog()` window, its tree control, the document, and its
undo manager; Windows calls only find the office's popups and dialogs and take screenshots.

Rules for changing it:

- One private office with the `win` interface, a fresh profile whose only settings turn off the
  first-run dialogs, as the feasibility probe did, and the built OXT installed with `unopkg`.
  Startup alone is retried, by `office_session`; never a check.
- The workbook window is maximised to the live work area and every position is read from the
  window, the tree and the pointer calibration; the runner's screen is 1024×768 at 96 DPI today,
  which nothing here assumes.
- Calc documents are closed on LibreOffice's main thread (`main_thread.close_document`, #47), and
  the session fails on a failed check, an extension error in the office log, a nonzero exit, a
  forced shutdown, a fatal message or a crash dump, exactly as `run.py`'s sessions do.
- A check that is not reliable here is fixed or removed from `CHECKS` with its reason in the pull
  request, never retried until it passes.
"""

import argparse
import json
import platform
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "tests" / "integration"), str(ROOT / "src")]

import run_ui as ui  # noqa: E402
from main_thread import close_document  # noqa: E402
from rename_dialog import check_keyboard as check_rename_keyboard  # noqa: E402
from rename_dialog import check_mouse as check_rename_mouse  # noqa: E402
from run import office_session, property_value  # noqa: E402
from winput import RIGHT, WinInput  # noqa: E402

from sheet_manager.uno_menu import HIDE  # noqa: E402

# The probe's first-run settings: no Tip of the Day, no first-start dialog.
SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" \
xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Misc">\
<prop oor:name="ShowTipOfTheDay" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc">\
<prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
"""


class WindowsLab(ui.Lab):
    """`run_ui.Lab` on the real desktop: SendInput, GDI screenshots, the live work area."""

    def __init__(self, context, desktop, directory, output, real_input):
        self.context = context
        self.desktop = desktop
        self.directory = directory
        self.output = output
        self.input = real_input

    def place(self, window):
        """Maximise the window to the work area and wait until its size stops changing."""
        window.IsMaximized = True
        sizes = []

        def settled():
            size = window.getPosSize()
            sizes.append((size.X, size.Y, size.Width, size.Height))
            return window.IsMaximized and len(sizes) > 3 and len(set(sizes[-4:])) == 1

        ui.wait_until(settled, "the maximised window to settle")

    def screenshot(self, name):
        self.input.screenshot(self.output / f"{name}.png")

    def failure_evidence(self):
        return {
            "foreground": self.input.foreground(),
            "cursor": self.input.cursor(),
            "office_windows": self.input.inventory(),
        }


def check_hide_undo_after_other_document(lab, book):
    """Hide Sheet from the menu, then Ctrl+Z, Ctrl+Y and Ctrl+Z from the list (#108).

    Headless Windows lost this undo step when another document had been opened and closed and
    the workbook's frame was then activated through the API alone, which left no current Calc
    view. Here, as a user does, the first case comes back to the workbook with a real click.
    """
    sheets = book.document.getSheets()
    picked = [ui.NAMES[2], ui.NAMES[4]]
    undo = book.document.getUndoManager()
    other_path = lab.directory / "other-read-only.ods"
    evidence = {}

    def shown():
        return [bool(sheets.getByName(name).IsVisible) for name in picked]

    for label in ("after_other_document", "same_window"):
        if label == "after_other_document":
            if not other_path.exists():
                created = lab.desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
                created.storeAsURL(other_path.as_uri(), ())
                close_document(lab.context, created)
            other = lab.desktop.loadComponentFromURL(
                other_path.as_uri(), "_blank", 0, (property_value("ReadOnly", True),)
            )
            time.sleep(1.0)  # Let the window settle before closing it (#30).
            close_document(lab.context, other)
            time.sleep(0.5)
        book.click(2)  # A real click brings the workbook's window back.
        book.click(4, modifiers=("Control_L",))
        ui.wait_until(lambda: book.selection() == picked, "two rows picked")
        before = book.undo_titles()
        entries = book.entries(picked)
        book.pointer.click(*book.point(4), button=RIGHT, pause=0.5)
        book.choose(HIDE, entries)
        ui.wait_until(lambda: shown() == [False, False], "Hide Sheet to hide the picked sheets")
        added = book.undo_titles()[: len(book.undo_titles()) - len(before)]
        assert len(added) == 1, book.undo_titles()
        steps = {"hidden": shown(), "undo_added": added}
        book.focus_list()
        lab.input.tap("z", ("Control_L",), pause=0.6)
        ui.wait_until(lambda: shown() == [True, True], "Ctrl+Z to show the sheets again")
        steps["after_undo"] = {"shown": shown(), "redo": list(undo.getAllRedoActionTitles())}
        lab.input.tap("y", ("Control_L",), pause=0.6)
        ui.wait_until(lambda: shown() == [False, False], "Ctrl+Y to hide them again")
        lab.input.tap("z", ("Control_L",), pause=0.6)
        ui.wait_until(lambda: shown() == [True, True], "Ctrl+Z to show them once more")
        steps["undo_titles_after"] = book.undo_titles()
        steps["list_has_focus"] = bool(book.tree.hasFocus())
        assert steps["undo_titles_after"] == before, steps
        evidence[label] = steps
        undo.clear()
    return evidence


def checks_for(lab, book):
    """The Windows checks, in order: #114's gaps first, so that a crash loses the least."""
    return [
        ("click_activates", lambda: ui.check_click_activates(book)),
        ("ctrl_shift_selection", lambda: ui.check_ctrl_shift_selection(book)),
        ("keys_stay_in_list", lambda: ui.check_keys_stay_in_list(book)),
        ("shortcuts_reach_calc", lambda: ui.check_shortcuts(book)),
        ("move_shortcuts", lambda: ui.check_move_controls(book, True)),
        ("menu_right_click", lambda: ui.check_menu_right_click(book)),
        ("menu_keyboard", lambda: ui.check_menu_keyboard(book)),
        ("context_rename_targets_row", lambda: ui.check_context_rename_targets_row(book)),
        ("context_insert_targets_row", lambda: ui.check_context_insert_targets_row(book)),
        (
            "hide_undo_after_other_document",
            lambda: check_hide_undo_after_other_document(lab, book),
        ),
        ("rename_sheets_keyboard", lambda: check_rename_keyboard(book)),
        ("drag_two_sheets_above_midpoint", lambda: ui.check_drag_two_sheets(book, 0.25, 12)),
        ("drag_two_sheets_below_midpoint", lambda: ui.check_drag_two_sheets(book, 0.75, 13)),
        ("drop_in_place_and_escape", lambda: ui.check_drop_in_place_and_escape(book)),
        (
            "context_preserves_view_and_picks",
            lambda: ui.check_context_preserves_view_and_picks(book),
        ),
        ("context_delete_targets", lambda: ui.check_context_delete_targets(book)),
        ("rename_sheets_mouse", lambda: check_rename_mouse(book)),
        ("wheel", lambda: ui.check_wheel(book)),
        ("autoscroll", lambda: ui.check_autoscroll(book)),
    ]


def run_checks(lab, output, only=()):
    book = ui.Workbook(lab, "synthetic", ui.NAMES)
    lab.screenshot("panel")
    results = ui.run_named(lab, book, output, checks_for(lab, book), only)
    book.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("test-results/windows-desktop"))
    parser.add_argument("--check", action="append", help="Run only this check (repeatable)")
    arguments = parser.parse_args()
    output = (arguments.output / "ui-win").resolve()
    output.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {"vcl": "win", "os": platform.platform()}
    failed = False
    try:
        real_input = WinInput()
        desktop = real_input.desktop()
        result["desktop"] = desktop
        if desktop["session"] == 0 or not desktop["input_desktop"]:
            raise RuntimeError(f"No interactive desktop for real input: {desktop}")
        with office_session(
            arguments.program.resolve(),
            arguments.oxt.resolve(),
            output,
            result,
            headless=False,
            vcl="win",
            settings=SETTINGS,
        ) as (context, desktop_service, directory):
            lab = WindowsLab(context, desktop_service, directory, output, real_input)
            checks = run_checks(lab, output, arguments.check or ())
            result["checks"] = {name: check["pass"] for name, check in checks.items()}
            result["pointer_corrections"] = lab.input.pointer_corrections
            failed = not all(result["checks"].values())
    except Exception:
        result["error"] = traceback.format_exc()
        failed = True
    logs = "".join(p.read_text("utf-8", "replace") for p in output.glob("soffice-*.log"))
    result["extension_errors"] = logs.count("Sheet Manager: ")
    failed = failed or bool(result["extension_errors"])
    text = json.dumps({"win": result}, indent=2) + "\n"
    (arguments.output / "ui-results.json").write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
