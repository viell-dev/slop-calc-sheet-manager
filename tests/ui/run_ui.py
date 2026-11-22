"""Real-input tests of the sheet list: XTEST mouse, wheel, and keys under Xvfb.

Run inside the Linux test image with LibreOffice's bundled Python, normally through
``tools/linux_integration.py <lane> --ui``. Each VCL plugin gets its own private office and
profile. The tests drive only real X input and observe only public UNO: the panel's
``XPanel.getDialog()`` window, its child tree control, the document, and its undo manager.

This runner owns the Linux setup and the list of checks, in order. The checks are in the
``*_checks.py`` modules beside it, ``rename_dialog.py``, ``menu_lifetime.py`` and
``native_help.py``; ``workbook.py`` holds the shared workbook fixture and the rules every check
follows, ``lab.py`` the Xvfb lab, and ``check_loop.py`` the loop that ``run_windows_ui.py``
(#114) shares. Add a check to the module of its subject and register it here, and in
``run_windows_ui.py`` when the Windows desktop can run it.

Linux UI profiles enable the built-in Light theme before creating documents/lists (#166).
Keep that startup condition: native disabled-button labels failed there, while theme-off
profiles hid the defect. The independent button pixel checks reject the solid foreground mask.
"""

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "tests" / "integration"), str(ROOT / "src")]

from check_loop import run_named  # noqa: E402
from drag_checks import (  # noqa: E402
    check_autoscroll,
    check_drag_two_sheets,
    check_drop_in_place_and_escape,
    check_wheel,
)
from focus_checks import (  # noqa: E402
    check_cursor_across_refresh,
    check_keys_stay_in_list,
    check_native_cursor_positions,
    check_other_document,
    check_save_prompts_keep_focus,
    check_selected_press_cursor,
    check_shortcuts,
    check_single_tap_after_client_pause,
)
from lab import Lab  # noqa: E402
from menu_checks import (  # noqa: E402
    check_context_delete_targets,
    check_context_insert_targets_row,
    check_context_preserves_view_and_picks,
    check_context_rename_targets_row,
    check_help_menu,
    check_menu_hidden_only,
    check_menu_keyboard,
    check_menu_mixed_visibility,
    check_menu_right_click,
)
from menu_lifetime import check_menu_queue_disposal  # noqa: E402
from move_checks import (  # noqa: E402
    check_move_controls,
    check_move_edges_and_refusal,
    check_move_focus_and_queued_navigation,
    check_moves_after_inactive_frame,
    check_undo_own_move,
)
from native_help import check_header as check_header_help  # noqa: E402
from paint_checks import (  # noqa: E402
    check_document_colors,
    check_row_paint_long_names,
    check_row_paint_scroll,
)
from rename_dialog import check_keyboard as check_rename_keyboard  # noqa: E402
from rename_dialog import check_mouse as check_rename_mouse  # noqa: E402
from rename_dialog import check_other_row as check_rename_other_row  # noqa: E402
from rename_dialog import check_replace_conflict as check_rename_replace_conflict  # noqa: E402
from rename_dialog import check_stale as check_rename_stale  # noqa: E402
from run import office_session  # noqa: E402
from selection_checks import (  # noqa: E402
    check_assistive_selection_then_ctrl_input,
    check_click_activates,
    check_clicks_after_scrolls,
    check_ctrl_clicks_after_a_ctrl_shift_range,
    check_ctrl_shift_click_after_ctrl_keys,
    check_ctrl_shift_selection,
    check_margin_drag_keeps_sidebar_docked,
    check_plain_click_ends_group,
    check_selection_notice,
    check_tab_selection_sync,
    check_viewed_sheet_name,
)
from stale_state_checks import (  # noqa: E402
    check_actions_refused_while_lock_held,
    check_click_hidden_before_refresh,
    check_drop_after_replacement,
    check_drop_refused_after_unrecorded_batch,
    check_newer_pick_survives_voided_press,
    check_newer_selection_kept,
    check_picks_dropped_when_sheets_change,
    check_press_then_change,
    check_reload_accepts_real_input,
    check_save_keeps_picks,
)
from workbook import NAMES, Workbook  # noqa: E402


def configure_desktop_opener(output):
    # The office inherits these only inside the private test process/profile.
    os.environ["PATH"] = str(HERE) + os.pathsep + os.environ["PATH"]
    os.environ["SHEET_MANAGER_URI_LOG"] = str(output / "opened-uris.txt")


def run_checks(lab, output, only=()):
    book = Workbook(lab, "synthetic", NAMES)
    lab.screenshot("panel")
    checks = [
        ("move_menu", lambda: check_move_controls(book, False)),
        ("move_buttons", lambda: check_move_controls(book, False, buttons=True)),
        ("move_shortcuts", lambda: check_move_controls(book, True)),
        ("moves_after_inactive_frame", lambda: check_moves_after_inactive_frame(book)),
        ("move_edges_and_refusal", lambda: check_move_edges_and_refusal(book)),
        ("move_focus_and_queued_navigation", lambda: check_move_focus_and_queued_navigation(book)),
        ("click_activates", lambda: check_click_activates(book)),
        ("margin_drag_keeps_sidebar_docked", lambda: check_margin_drag_keeps_sidebar_docked(book)),
        ("ctrl_shift_selection", lambda: check_ctrl_shift_selection(book)),
        ("viewed_sheet_name", lambda: check_viewed_sheet_name(book)),
        ("row_paint_scroll", lambda: check_row_paint_scroll(book)),
        ("document_colors", lambda: check_document_colors(book)),
        ("tab_selection_sync", lambda: check_tab_selection_sync(book)),
        ("selection_notice", lambda: check_selection_notice(book)),
        (
            "ctrl_clicks_after_a_ctrl_shift_range",
            lambda: check_ctrl_clicks_after_a_ctrl_shift_range(book),
        ),
        (
            "assistive_selection_then_ctrl_input",
            lambda: check_assistive_selection_then_ctrl_input(book),
        ),
        (
            "ctrl_shift_click_after_ctrl_keys",
            lambda: check_ctrl_shift_click_after_ctrl_keys(book),
        ),
        ("undo_own_move", lambda: check_undo_own_move(book)),
        ("drag_two_sheets_above_midpoint", lambda: check_drag_two_sheets(book, 0.25, 12)),
        ("drag_two_sheets_below_midpoint", lambda: check_drag_two_sheets(book, 0.75, 13)),
        ("drop_in_place_and_escape", lambda: check_drop_in_place_and_escape(book)),
        ("autoscroll", lambda: check_autoscroll(book)),
        ("wheel", lambda: check_wheel(book)),
        ("clicks_after_scrolls", lambda: check_clicks_after_scrolls(book)),
        ("keys_stay_in_list", lambda: check_keys_stay_in_list(book)),
        ("shortcuts_reach_calc", lambda: check_shortcuts(book)),
        ("menu_right_click", lambda: check_menu_right_click(book)),
        ("menu_keyboard", lambda: check_menu_keyboard(book)),
        ("context_preserves_view_and_picks", lambda: check_context_preserves_view_and_picks(book)),
        ("context_rename_targets_row", lambda: check_context_rename_targets_row(book)),
        ("context_insert_targets_row", lambda: check_context_insert_targets_row(book)),
        ("context_delete_targets", lambda: check_context_delete_targets(book)),
        ("rename_sheets_keyboard", lambda: check_rename_keyboard(book)),
        ("rename_sheets_mouse", lambda: check_rename_mouse(book)),
        ("rename_sheets_other_row", lambda: check_rename_other_row(book)),
        ("rename_sheets_replace_conflict", lambda: check_rename_replace_conflict(book)),
        ("rename_sheets_stale", lambda: check_rename_stale(book)),
        ("menu_queue_disposal", lambda: check_menu_queue_disposal(book)),
        ("help_menu", lambda: check_help_menu(book)),
        ("header_help", lambda: check_header_help(book)),
        ("menu_hidden_only", lambda: check_menu_hidden_only(book)),
        ("menu_mixed_visibility", lambda: check_menu_mixed_visibility(book)),
        ("reload_accepts_real_input", lambda: check_reload_accepts_real_input(book)),
        ("plain_click_ends_group", lambda: check_plain_click_ends_group(book)),
        ("single_tap_after_client_pause", lambda: check_single_tap_after_client_pause(book)),
        ("cursor_across_refresh", lambda: check_cursor_across_refresh(book)),
        ("native_cursor_positions", lambda: check_native_cursor_positions(book)),
        ("selected_press_cursor", lambda: check_selected_press_cursor(book)),
        ("drop_after_replacement", lambda: check_drop_after_replacement(book)),
        ("press_then_change", lambda: check_press_then_change(book)),
        ("newer_pick_survives_voided_press", lambda: check_newer_pick_survives_voided_press(book)),
        ("picks_dropped_when_sheets_change", lambda: check_picks_dropped_when_sheets_change(book)),
        (
            "drop_refused_after_unrecorded_batch",
            lambda: check_drop_refused_after_unrecorded_batch(book),
        ),
        ("save_keeps_picks", lambda: check_save_keeps_picks(book)),
        ("save_prompts_keep_focus", lambda: check_save_prompts_keep_focus(lab)),
        ("actions_refused_while_lock_held", lambda: check_actions_refused_while_lock_held(book)),
        ("click_hidden_before_refresh", lambda: check_click_hidden_before_refresh(book)),
        ("newer_selection_kept", lambda: check_newer_selection_kept(book)),
        ("other_document", lambda: check_other_document(lab, book)),
        ("row_paint_long_names", lambda: check_row_paint_long_names(lab)),
    ]
    results = run_named(lab, book, output, checks, only)
    book.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("test-results/ui"))
    parser.add_argument("--vcl", action="append", choices=["gtk3", "gen"])
    parser.add_argument("--ui", action="store_true", help="Accepted from the container session")
    parser.add_argument("--check", action="append", help="Run only this check (repeatable)")
    parser.add_argument(
        "--backtrace", action="store_true", help="Linux only: use LibreOffice's gdb wrapper"
    )
    arguments = parser.parse_args()
    summary = {}
    failed = False
    for vcl in arguments.vcl or ["gtk3", "gen"]:
        output = (arguments.output / f"ui-{vcl}").resolve()
        output.mkdir(parents=True, exist_ok=True)
        for stale in output.glob("stall-*"):  # An earlier run's stall evidence (#45).
            stale.unlink()
        configure_desktop_opener(output)
        result: dict[str, object] = {"vcl": vcl}
        summary[vcl] = result
        try:
            with office_session(
                arguments.program.resolve(),
                arguments.oxt.resolve(),
                output,
                result,
                headless=False,
                backtrace=arguments.backtrace,
                vcl=vcl,
                # Match the theme-enabled GTK3 route that hid disabled labels (#166).
                settings="""<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Appearance">
<prop oor:name="LibreOfficeTheme" oor:op="fuse"><value>1</value></prop>
<prop oor:name="ApplicationAppearance" oor:op="fuse"><value>1</value></prop></item>
<item oor:path="/org.openoffice.Office.UI/ColorScheme">
<prop oor:name="CurrentColorScheme" oor:op="fuse">
<value>COLOR_SCHEME_LIBREOFFICE_LIGHT</value></prop>
</item></oor:items>""",
            ) as (context, desktop, directory):
                lab = Lab(context, desktop, directory, output)
                result["list_calibrations"] = lab.calibrations  # Filled in place (#301).
                checks = run_checks(lab, output, arguments.check or ())
                result["checks"] = {name: check["pass"] for name, check in checks.items()}
                failed = failed or not all(result["checks"].values())
        except Exception:
            result["error"] = traceback.format_exc()
            failed = True
        logs = "".join(p.read_text("utf-8", "replace") for p in output.glob("soffice-*.log"))
        result["extension_errors"] = logs.count("Sheet Manager: ")
        failed = failed or bool(result["extension_errors"])
    text = json.dumps(summary, indent=2) + "\n"
    (arguments.output / "ui-results.json").write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
