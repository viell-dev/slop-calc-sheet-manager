# Verification map

This map describes the maintained implementation on `main`: its promises, current checks and
known evidence limits. It is not a release-readiness receipt. The guide's notice identifies the
published baseline; behaviour absent from it remains marked **Unreleased**. Update this map when
a promise or its checks change. Commands and fixture safeguards belong in
[CONTRIBUTING.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/CONTRIBUTING.md#tests).
Record run results, deliberate-break experiments and review findings in the owning issue or PR.

## Where checks run

- **Checks:** Ruff, strict Pyright, unit tests and byte-for-byte reproducible builds, on Python
  3.12 and 3.14.
- **Integration:** official LibreOffice builds pinned in `ci/libreoffice.json`: the minimum,
  newest tested 26.2 and newest tested 26.8 on Linux, headless and painted gtk3; the Windows pin
  headless. A separate refusal lane tests the unsupported version.
- **Linux UI:** gtk3 and gen under private Xvfb displays in each required painted Linux job.
  Real XTEST input exercises native dispatch and drag behaviour that synthetic UNO input cannot.
- **Documentation:** guide build, offline feed combination and rendered synthetic-history checks.

These are required CI jobs on every PR and push to `main`; the workflow and pins are authoritative.
**Windows desktop** is a separate, non-required workflow using real `SendInput` on a visible
Windows Server 2025 desktop, the pinned `win` build and en-US layout. Its current evidence covers
one 1024×768 desktop at 96 DPI. It runs for affected PRs and by dispatch; its promotion conditions
are in [CONTRIBUTING.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/CONTRIBUTING.md#visible-windows-desktop).

No automated lane runs a screen reader. Native Wayland input, macOS, distribution packages,
Flatpak, Snap, Arm and other themes or scaling are not established by these checks. A focused
[human usability pass](./manual-tests.md) remains a separate release requirement.

## Installation, packaging and publication

| Promise | Current checks | Runs and limits |
| --- | --- | --- |
| Unsupported LibreOffice refuses installation and leaves nothing installed | `run.py:check_refusal` | Refusal lane; only the pinned unsupported build is tried. |
| Supported versions install; Calc and read-only workbooks get the deck, Writer does not | `tests/integration/run.py:exercise`, fresh-profile `unopkg add` | Integration; the installation dialog is not driven. |
| Panel size follows the sidebar and panel disposal follows document closure | `run.py` geometry and disposal assertions | Integration; compares growth, since gtk3 does not report the requested absolute height (#9). |
| Headless conversion works; removal leaves no deck, factory or installed payload | `run.py:check_lifecycle`, with presence controls before removal | Headless integration; one conversion direction, command-line removal. LibreOffice's staging copy under `user/extensions/tmp` is excluded. |
| Packages contain exactly the allowlisted files and build reproducibly | `test_build.py`, `tools/check.py` | Checks; two builds must match byte for byte. |
| Repeated compatibility, package and guide claims agree with their sources | `test_consistency.py` | Checks; prose still needs review. Historical versions and policy examples are independent of the source version. |
| Downloads and availability markers follow published history | `tools/check_release_page.py` | Documentation; empty history, preparation, publication and an older stable alongside a newer test build. Checks channel order, rendered OXT/checksum links and markers. Public bytes still need post-publication verification. |
| Stages are explicit; releases require exact-commit CI; tags, assets and feed history cannot regress | `test_release_data.py`, `test_github_release.py`, affected-PR release dry runs | Checks and Release workflow; mocks/dry runs do not create live tags or upload assets. A stage or green run does not establish feature completeness or human usability. |
| Compatible newer updates are offered and install correctly | `test_updates.py`, `tests/ui/update_dialog.py` | Provider/dependency checks in integration; real dialogs, download/install and same-profile restart in required painted Linux jobs, using gen and loopback feeds. See the [release verification boundary](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md#verification-boundary) for GUI, HTTPS and post-publication limits. |

## Sheet identity and synchronization

| Promise | Current checks | Runs and limits |
| --- | --- | --- |
| Picks and retained snapshots never transfer to a replacement sheet within the notification boundary | `test_selection.py` randomized sessions and broken controls; `test_reorder_identity.py`; `test_sheet_list.py:check_identity`; real-input structural-change, held-lock and stale-drop checks | Checks, integration and Linux UI. Covers same-count replacements, name reuse, recorded/unrecorded batches, locks, Undo/Redo, saves and shared-monitor lifetime. Entirely silenced, save-window-only and deliberately typed-input-shaped structural edits remain outside the [contract](./reordering.md). |
| Delayed observations and refreshes cannot overwrite newer input or activate stale rows | `test_view_observation.py`, `test_pointer_observation.py`, `test_assistive_selection.py`; integration stale-click cases; real-input `newer_selection_kept`, `press_then_change`, `newer_pick_survives_voided_press` | Checks, integration and Linux UI. Ordering adapters do not establish native visibility or selection behaviour. Held-press checks wait for the list's own listener via `Workbook.hold`; changes before it runs are ordered before the press (#134). |
| This window's native tabs and grouped-editing status follow without rebuilding rows or replacing independent picks | `test_sync_sheet_list.py:check_tabs`; observation unit tests; real-input synchronization checks | Integration, Checks and Linux UI. Tabs are sampled about every 0.25 seconds between interactions, not received as timestamped events. |
| Observation pauses while hidden and stays bound to the correct view through window changes and reload | `test_sync_sheet_list.py:check_hidden`, `check_views`, `check_reload`; `reload_accepts_real_input`; visibility/timer unit tests | Integration, Checks and Linux UI; minimize requires a painted session. Visibility is checked about once a second. Input during native initialization may still clear conservatively (#88). |
| Rows show each sheet's own order, viewed state, visibility, protection, scenarios and colour | Unit/integration `test_sheet_list.py`; `test_reorder_identity.py:check_confusable_names` | Checks and integration. Property changes rebuild the native model; rapid switches can lag (#22). |
| Names Calc confuses still use the picked sheet's handle; unsafe name-based moves are refused | `check_confusable_names` with `ﬁ`/`fi` and `I`/`ı`; `test_reorder.py:lookup_conflict` against an independent replay model | Integration and Checks. Exercises rows, Show, Hide, moves, per-call guards and batch rename. Only two measured pairs and English locales; scenario combinations and view reactivation coverage remain in [#128](https://github.com/viell-dev/slop-calc-sheet-manager/issues/128). Calc's own formula lookup remains defective (#113), and some moves are refused (#125). |

The structural monitor's guarantees, notification rules and unavoidable limits are specified in
[reordering.md](./reordering.md) and the `structure.py` docstring. Identity investigations and
negative controls are recorded in
[#19](https://github.com/viell-dev/slop-calc-sheet-manager/issues/19) and
[#113](https://github.com/viell-dev/slop-calc-sheet-manager/issues/113).

## Moves, commands and recovery

| Promise | Current checks | Runs and limits |
| --- | --- | --- |
| Plans keep scenario blocks whole and reach the target with the fewest calls | `test_reorder.py`: exhaustive permutations and scenario partitions through seven sheets, independent longest-common-subsequence oracle | Checks. |
| A move preserves the view and tabs and is one complete undo/redo step | `test_reorder.py`, `test_undo_moves.py`; real-input drag, move and `undo_own_move` checks | Integration and Linux UI. Nested undo groups and capacities 0, 1, 2 and 100 are covered. Native limits are tracked in #16 and #37. |
| Undo/Redo of a proved own move preserves independent picks and every window's view | `test_selection.py`, `test_selection.py:test_structure_events_own_replays`, `test_view_observation.py`, `test_undo_moves.py`, real-input `undo_own_move` | Checks, integration and Linux UI; no visible Windows replay or multi-step undo-list UI check. One-step history lacks room for markers. Foreign/hidden groups, intervening changes and unexpected notifications revoke proof. Opening another window can invalidate it. Restoration can briefly paint Calc's activation; after five seconds without restoration, sampling and following resume. |
| Partial failure rolls back and verifies the result without undoing the user's preceding action | Forwarding adapters in `test_reorder.py`, `test_adapter_failures.py`, `test_rename_sheets.py`; undo-stack and stall unit tests | Integration and Checks; failures before, after or instead of real mutations, ineffective undo, nested groups and a full 100-step stack. No injection seam ships. View-restoration warnings do not replace verified move/rollback results. A failed move before its first mutation loses earlier Redo history. |
| Unsafe permissions, stale targets and changed undo state refuse before mutation | Integration permission/identity checks; `test_move_menu.py`, `test_move_buttons.py`, `test_sheet_commands.py`; pure permission tests | Integration and Checks; includes protected/read-only/change-tracked documents, hidden sheets and undo limits. Controls and menus expose reasons where native rendering allows. |
| Opening/dismissing the menu preserves picks, tabs and view; chosen Calc commands act on exactly their targets | `test_sheet_commands.py`, `test_menu_targeting.py`, `test_menu_lifetime.py`; real-input `context_*` and keyboard-menu checks | Integration, Checks, Linux UI and Windows desktop. Checks again after grouping/callbacks. Refusals restore a provable prior view; after dispatch begins Calc stays on its targets, including cancelled or uncertain dialogs. Synthetic input cannot reach gtk3 native menus. |
| Closing the list queue inside a popup cancels completion and leaves Calc usable | `menu_lifetime.py:check_menu_queue_disposal`; menu lifetime unit tests | Linux UI and Checks. A test owner retains the popup anchor. Actual panel-peer destruction during the popup is unverified (#63). |
| Show is one undo step and verifies rollback | `test_sheet_list.py:check_show`, `test_adapter_failures.py:check_recorded_show`, hidden-only menu input | Integration and Linux UI. More targets than the configured undo capacity are refused. |

The marker protocol and its negative controls are recorded in
[#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91). Native command/dialog
investigations and deliberate target-check failures belong to
[#100](https://github.com/viell-dev/slop-calc-sheet-manager/issues/100) and
[#101](https://github.com/viell-dev/slop-calc-sheet-manager/issues/101).

## Batch rename

`test_rename.py` covers pure planning; `test_rename_sheets.py` exercises the packaged adapter.
The measured native naming rules and deliberate-break results are in
[#102](https://github.com/viell-dev/slop-calc-sheet-manager/issues/102).

| Promise | Current checks | Runs and limits |
| --- | --- | --- |
| Invalid/conflicting names are refused before changes | Unit naming/comparator cases, 51 measured pairs in both directions and seven Turkish-locale pairs; integration naming cases | Checks and integration. English and Turkish measurements only; each call's readback handles native refusals. The comparator deliberately refuses some pairs Calc accepts (ß/ss and the I/İ/i/ı family). |
| Swaps and cycles run safely | Fixed cases, 3,000 random batches replayed against a cycle-count oracle, 1,000-sheet cycle/chain | Checks. The random oracle covers case-insensitive ASCII. |
| Renames are one undo step, references follow, text does not, and the view stays | `check_swaps_and_cycles`, `check_capacities`, `check_other_window`, `check_main_thread` | Integration. Formulas, ranges, charts, literal/INDIRECT text, swaps and cycles; capacities 0, 1 and 2, including a 31-call cycle at 1. Configure undo before creating workbooks (#37). |
| Partial/native refusal rolls back and verifies; stale or protected targets refuse | `check_failures`, `check_native_refusal_after_search`, `check_stale_targets`, `check_menu_entry` | Integration. Includes failures around each real call, ineffective undo and a native refusal after Find & Replace (#112). |
| Own picks follow verified renames without passing to other sheets | Randomized selection tests and carry/refusal controls; `rename_sheets_keyboard`, `rename_sheets_mouse` | Checks, Linux UI and Windows desktop. Another window's list clears after a batch; covered by the model, not a second real list. |
| Dialog works by keyboard/mouse, Enter/Cancel apply nothing, changed targets refuse | `rename_sheets_keyboard`, `rename_sheets_mouse`, `rename_sheets_stale` | Linux UI; keyboard and mouse checks also Windows desktop. Stale-dialog input is not run on Windows. Wayland and screen-reader announcements remain unverified; status is a plain label. |

## Interaction and accessibility

| Promise | Current checks | Runs and limits |
| --- | --- | --- |
| Full-width clicks select; double-click/Enter activates and ends grouped editing | Integration selection/activation cases; real-input `click_activates`, `ctrl_shift_selection`, `plain_click_ends_group` | Integration, Linux UI and Windows desktop selection checks. Built-in commands retain Calc's grouping semantics. |
| Shift, Ctrl and Alt do not crash LibreOffice while the deck is shown | `run.py` presses real modifiers with `xdotool`; Windows desktop selection and shortcut checks use `SendInput`; both check office shutdown and dumps | Painted Linux integration and Windows desktop; modifiers are not pressed in the required headless Windows lane. |
| Drag/drop keeps order/view, marks the gap, scrolls, cancels and undoes once | Real-input midpoint, in-place, Esc, autoscroll, stale-drop and undo checks; reorder integration | Linux UI and integration; Windows desktop covers native OLE drag, cancel and scrolling, but not stale drops. Autoscroll follows viewport resizing after a notice expires, preserving its six-second budget and order checks (#90). |
| Move buttons, menu actions and Alt shortcuts preserve independent picks | `test_move_buttons.py`, `test_move_menu.py`, key/queued-operation unit tests; real-input `move_*` checks | Integration, Checks and Linux UI; Windows desktop covers Alt shortcuts, not button input or menu moves. |
| List/button keys cannot edit cells; shortcuts and focus traversal remain usable | `test_keys.py`; real-input `keys_stay_in_list`, `move_focus_and_queued_navigation`, `shortcuts_reach_calc`, `other_document`, `native_cursor_positions`, `cursor_across_refresh` | Checks and Linux UI. Windows desktop covers list keys/shortcuts, not the button, other-document or cursor probes. Input methods and screen-reader experience are unverified. |
| Ctrl+S returns focus to the list without taking it from a save dialog | Save-only routing unit test; `shortcuts_reach_calc`, `save_prompts_keep_focus` | Checks and Linux UI, plus basic save shortcut on Windows desktop. Save As cancellation and read-only error are automated on Linux. Keep Current Format retains focus while open, but its completion is not automated; Windows prompt paths and Wayland are unverified. |
| Cursor/range anchor survives rebuilds; refused held clicks preserve surviving picks | Retained-anchor and coalesced-intent unit tests; `cursor_across_refresh`, `native_cursor_positions`, `selected_press_cursor` | Checks and Linux UI. A refused hold need not retain an unpicked cursor position; no cursor is promised without surviving picks. |
| Selection notice expires after ten seconds without changing focus, picks or grouped warning | `test_selection_notice.py`, real-input `selection_notice` | Checks and Linux UI. Text fit was inspected at one GTK width; no automated font/width/DPI assertion, Windows notice check or screen-reader announcement check. |
| Dividers track native bounds and avoid scrollbars | `test_row_paint.py`, `row_paint_scroll`, `row_paint_long_names` | Checks and Linux UI; focused GTK 120-DPI evidence in #86. Synthetic short/long names and pinned themes; only the last lower divider may be omitted. Horizontal endpoint gestures are inspected in screenshots, not an asserted final position. Windows painting is unverified. |
| <Unreleased since="0.0.9" /> Accessible list name identifies the viewed sheet; external accessibility picks survive a rebuilding refresh | `test_accessibility.py:check_viewed_sheet`, `check_assistive_selection_before_rebuild`; pure assistive-selection tests; `viewed_sheet_name` | Integration, Checks, Linux UI and Windows desktop name check. Reads public UNO metadata/events; no screen reader or cross-process selection bridge runs. Name can lag with the arrow (#22). |
| <Unreleased since="0.0.9" /> Accessible hierarchy reaches the list and lists controls in visual order; margin drags leave the sidebar docked | `test_accessibility.py:check_hierarchy`, `run.py:drag_from_margins`, `margin_drag_keeps_sidebar_docked` | Integration, Linux UI and Windows desktop drag check. Disabled unnamed backdrop is last. gtk3 does not undock even without handling the press, so gen/win are needed to expose that regression. A one-off gtk3 AT-SPI probe found controls and focus/cursor/name events; no AT-SPI or IAccessible2 bridge probe runs in CI (#133). |
| Help hands the guide URI to the desktop | `help_menu` with real SystemShellExecute and a private URI recorder | Linux UI; checks handoff, not browser rendering or Windows URL handling. Native header Help remains unavailable (#81). |
| Partial initialization and failed popup creation leave no list-owned registrations or stale menu state | `test_adapter_failures.py` with forwarding adapters and owned-key failure tests | Integration. Shared structure monitor intentionally lives until document disposal. Key-handler removal is not directly observed by panel-disposal tests. |

Input and paint investigations, including negative controls, are in
[#23](https://github.com/viell-dev/slop-calc-sheet-manager/issues/23),
[#86](https://github.com/viell-dev/slop-calc-sheet-manager/issues/86), and
[#134](https://github.com/viell-dev/slop-calc-sheet-manager/issues/134).
Accessibility evidence and limits are in
[#83](https://github.com/viell-dev/slop-calc-sheet-manager/issues/83) and
[#133](https://github.com/viell-dev/slop-calc-sheet-manager/issues/133).

## Performance measurements

Pure planning has a five-second regression budget at 10,000 sheets for one-call and reverse-order
move plans; rename tests budget five seconds for a 1,000-sheet cycle and chain. Native timings are
measurements, not limits:

- `reorder-performance-<session>.json`: three runs each at 200 and 1,000 sheets with cross-sheet
  formulas, named ranges and charts; first, half, all-but-last and alternating selections moved
  to bottom. Timings include snapshot, planning, preflight, application and final verification.
  Undo is timed separately, with reference-integrity assertions before/after it.
- `rename-performance-headless.json`: complete batches and Undo, three runs at 200 sheets and one
  at 1,000, across the UNO bridge.
- `test_sheet_list.py:measure_large_workbook`: list opening and tab following at 1,000 sheets.
  Activation settles selection/model rebuilding before the separate tab-only measurement.
  Property-driven rebuild cost remains tracked in
  [#22](https://github.com/viell-dev/slop-calc-sheet-manager/issues/22).

All inputs are synthetic. Workbooks stay in memory unless the contributor explicitly runs the
inspection generator described in CONTRIBUTING.md.

## The visible Windows desktop

`tests/ui/run_windows_ui.py` runs the shared checks through `tests/ui/winput.py`. In addition to the
Windows paths named above, `hide_undo_after_other_document` checks Ctrl+Z/Ctrl+Y of menu Hide after
returning from another workbook by a real click. API-only activation can still lose the undo step
in headless LibreOffice (#108); the headless fixture makes a real deactivate/activate transition.

Preflight refuses session 0, an inaccessible input desktop and a non-en-US layout. Results record
session, screen, DPI, layout, corrected pointer moves and office shutdown. `test_winput.py` checks
keys, input structure layout, scaling and PNG encoding. Key presses are held for 50 ms; a 10 ms
injected Esc did not reliably cancel native dragging. The workflow's scope and deliberate
key-handler-removal experiment are recorded in
[#114](https://github.com/viell-dev/slop-calc-sheet-manager/issues/114).

## The checks themselves

`test_office_process.py`, `test_teardown.py`, `test_stalled_cleanup.py` and UI-runner unit tests
ensure that failed checks cannot pass through cleanup. Sessions fail on nonzero exits, forced
shutdowns, fatal messages, crash dumps, stalled main-thread callbacks or held terminate requests.
Windows crash dumps matter even when the office exits with status zero. Only startup is retried;
its dumps are retained separately. Debugger runs also reject signals, incomplete exits and missing
traces. The Xvfb helper disables key repeat; `single_tap_after_client_pause` verifies one cursor
step after a one-second held key. Operating-system timed repeat is outside that check.

Fixture procedures and artifact diagnosis are in
[CONTRIBUTING.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/CONTRIBUTING.md#failures-and-shutdown).
Lifecycle failure evidence is in
[#40](https://github.com/viell-dev/slop-calc-sheet-manager/issues/40),
[#48](https://github.com/viell-dev/slop-calc-sheet-manager/issues/48), and
[#50](https://github.com/viell-dev/slop-calc-sheet-manager/issues/50).
