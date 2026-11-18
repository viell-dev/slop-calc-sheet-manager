# Verification map

This map describes the maintained implementation on `main`: its promises, current checks and
known evidence limits. It is not a release-readiness receipt. The guide's notice identifies the
published baseline; behaviour absent from it remains marked **Unreleased**. Update this map when
a promise or its checks change. Commands and fixture safeguards belong in
[Native LibreOffice testing](./development/native-testing.md).
Record run results, deliberate-break experiments and review findings in the owning issue or PR.

## Where checks run

- **Checks:** Ruff, strict Pyright for Linux, Windows and macOS API availability, unit
  tests and byte-for-byte reproducible builds, on Python 3.12 and 3.14. Static platform targets do
  not execute native behaviour.
- **Integration:** routine CI uses the newest tested Linux build, headless. The manual full release
  sweep adds the minimum and newest tested 26.2, painted gtk3 on all three builds, the Windows pin
  headless, Intel macOS headless integration/lifecycle, and the unsupported-version refusal.
  `ci/libreoffice.json` owns the pins.
- **Linux UI:** gtk3 and gen under private Xvfb displays on current Linux in routine CI and all
  three Linux builds in the full release sweep.
  Real XTEST input exercises native dispatch and drag behaviour that synthetic UNO input cannot.
- **Documentation:** guide build, offline feed combination and rendered synthetic-history checks.

The Linux lab requires direct UID/GID mapping for its writable results mount. The helper
rejects rootless and daemon-level remapped Docker contexts before building. Verification
receipts for rootful Linux, rootless Docker and Docker Desktop are tracked in
[#191](https://github.com/viell-dev/slop-calc-sheet-manager/issues/191).

The required **Routine CI** aggregate checks every routine dependency on every PR and push to
`main`, refusing missing, failed or skipped work. **Release sweep** is manual, on demand and at most
weekly. Its aggregate and publication gate require every supported release lane for the exact
revision; routine CI and PR planning previews cannot authorize publication. Workflow/policy
consistency and negative job/run evidence are checked by `test_ci_policy.py`, `test_release_ci.py`
and `test_consistency.py`.

Routine Linux uploads headless evidence before starting input, captures both phases' console
output without hiding failures, and requires headless success before input. A hard job timeout
can still prevent the final input artifact; absent logs cannot classify the original failure
([#152](https://github.com/viell-dev/slop-calc-sheet-manager/issues/152)).

The release sweep also uploads its painted Linux evidence before input and starts input only
after painted integration and upload succeed. Both phases keep their console output in
`test-results/ci/`, and `pipefail` keeps the runner's exit status through `tee`. The early
artifact can be inspected independently of the final input artifact
([#192](https://github.com/viell-dev/slop-calc-sheet-manager/issues/192)). Its synthetic check
ran a copy of these steps with a failed first phase and a step-level timeout in the second; a
job-level timeout or cancellation during the painted phase itself is not exercised.

**Windows desktop** uses real `SendInput` on a visible
Windows Server 2025 desktop, the pinned `win` build and en-US layout. Its current evidence covers
one 1024×768 desktop at 96 DPI. Windows 11 and input methods are outside this lane. The full
release sweep requires the complete suite. See
[Hosted checks](./development/hosted-checks.md#visible-windows-desktop) for focused dispatch
and cadence.

No automated lane runs a screen reader. Native Wayland input, distribution packages,
Flatpak, Snap, Arm and other themes or scaling are not established by these checks.
[#145](https://github.com/viell-dev/slop-calc-sheet-manager/issues/145) owns macOS release verification.
Intel macOS 15 with the pinned official build has passed the full headless integration/lifecycle
suite and is required by the manual release sweep. The runner requests `svp`; Aqua rendering,
OS input, GUI installation/update, upgrades from published macOS builds, Apple Silicon and
system-wide/delayed crash reports remain unverified. Installer unit checks cover integrity,
private paths, diagnostic ownership and failure propagation for version mismatch, new crash
reports or diagnostic collection failure. Command lifecycle controls distinguish a child that
drains after TERM from a TERM-resistant group requiring KILL. After ordinary exits, the former
group is observed for a bounded time without signals; a member still live after it, or an
unverifiable group, fails the lane and retains the private app and an audit receipt. A
descendant that starts its own session or process group escapes this audit, which shows only
that the command's own group emptied. Unit checks with a simulated group cover the drain,
escalation, failed snapshots, interrupted waits and the bounded audit; native evidence for the
audit through installation and packaged integration is linked from
[#163](https://github.com/viell-dev/slop-calc-sheet-manager/issues/163). The installer unit
checks are separate from the native evidence linked in #145. A standalone focused Mac run cannot
replace the complete exact-revision sweep.
A focused [human usability pass](./manual-tests.md) remains a separate release requirement.
Failed integration input polls also retain a bounded trace of the fixtures' existing selection
reads, row coordinates and posted pointer actions, without extra UNO reads, waits or retries
([#160](https://github.com/viell-dev/slop-calc-sheet-manager/issues/160)). The accessibility and
theme fixtures can also record delivered mouse and selection events without making UNO calls
from listeners. Successful theme results keep the initial input trace too; unavailable
observers are identified explicitly. Detailed theme state is read only after a failed pick.
The theme fixture finishes edits and cleanup while its workbook is hidden, before opening
the panel. Resetting modified state after the list has loaded invalidates its structure proof;
a click before the pending refresh is correctly cleared. Native journals established that
setup race in #160. Preparing the fixture before the monitor exists preserves the identity
safeguard. The [optional paired input probe](./development/hosted-checks.md#macos-packaged-integration)
retains all eight outcomes using the normal package, with and without native delivery observers.
Completed suites and rename benchmark cases are saved incrementally so an external timeout
retains partial evidence; `run_complete` distinguishes the final result from partial checkpoints.
The macOS helper records its owned process group on timeout and runs
native TERM/KILL controls before installing the app; a zombie-only signalling refusal is accepted
only after reading member states. Unverified cleanup retains the private directory and fails
([#162](https://github.com/viell-dev/slop-calc-sheet-manager/issues/162)).
The Mac integration command has 30 minutes for the measured complete benchmark workload, with
60 minutes for its job's installation, commands and evidence collection. Functional assertion
deadlines and correctness checks remain separate; the enclosing release wait/job budgets are
documented in [RELEASING.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md).

## Installation, packaging and publication

| Promise | Current checks | Runs and limits |
| --- | --- | --- |
| Native test packages are cached by exact SHA-256 and verified before use | `test_libreoffice_package.py` covers cold downloads, stable-to-archive fallback, verified hits, corrupt restores and failed downloads. The original mirror TLS/digest control is in [#61](https://github.com/viell-dev/slop-calc-sheet-manager/issues/61). Hosted cache receipts are tracked in [#215](https://github.com/viell-dev/slop-calc-sheet-manager/issues/215). | Routine CI, release sweep, gtk3 soak and the focused Windows/macOS workflows. A miss or eviction still needs a TDF download. Exhausted downloads and digest mismatches on the final source fail setup. |
| Unsupported LibreOffice refuses installation and leaves nothing installed | `run.py:check_refusal` | Refusal lane; only the pinned unsupported build is tried. |
| Supported versions install; Calc and read-only workbooks get the deck, Writer does not | `tests/integration/run.py:exercise`, fresh-profile `unopkg add` | Integration; the installation dialog is not driven. |
| Panel size follows the sidebar and panel disposal follows document closure | `run.py` geometry and disposal assertions | Integration; compares growth, since gtk3 does not report the requested absolute height (#9). |
| Headless conversion works; removal leaves no deck, factory or installed payload | `run.py:check_lifecycle`, with presence controls before removal | Headless integration; one conversion direction, command-line removal. LibreOffice's staging copy under `user/extensions/tmp` is excluded. |
| Packages contain exactly the allowlisted files and build reproducibly | `test_build.py`, `tools/check.py` | Checks; two builds must match byte for byte. |
| Repeated compatibility, package and guide claims agree with their sources | `test_consistency.py` | Checks; prose still needs review. Historical versions and policy examples are independent of the source version. |
| Downloads and availability markers follow published history | `tools/check_release_page.py` | Documentation. Full guide builds check channel order, OXT/checksum links, baselines and selected instructions before and after publication. One focused fixture renders the marker component at each marked version, including a newer test build beside an older stable baseline ([#196](https://github.com/viell-dev/slop-calc-sheet-manager/issues/196)). Public bytes still need post-publication verification. |
| Stages are explicit; releases require complete routine and full-sweep evidence for the exact revision; tags, assets and feed history cannot regress | `test_release_data.py`, `test_github_release.py`, `test_release_ci.py`, affected-PR planning previews | Checks and Release workflow. History tests cover migration from the pinned tag-rebuild receipts, which stay a second anchor, and reject paired OXT/checksum replacement before writing feeds, during planning, in the recheck just before publication, and when an uploaded asset's GitHub digest differs from the built file ([#193](https://github.com/viell-dev/slop-calc-sheet-manager/issues/193)). The tag rebuilds themselves were a one-time check, recorded in the issue. The deployed digest protects subsequent downloads. Missing, stale, failed, skipped or duplicate required jobs are refused. PR previews cannot authorize publication, and mocks/dry runs do not create live tags or upload assets. A stage or green run does not establish feature completeness or human usability. |
| Compatible newer updates are offered and install correctly | `test_updates.py`, `tests/ui/update_dialog.py` | Provider/dependency checks in integration; real dialogs, download/install and same-profile restart in Linux UI jobs, using gen and loopback feeds. See the [release verification boundary](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md#verification-boundary) for GUI, HTTPS and post-publication limits. |

## Sheet identity and synchronization

| Promise | Current checks | Runs and limits |
| --- | --- | --- |
| Picks and retained snapshots never transfer to a replacement sheet within the notification boundary | `test_selection.py` randomized sessions and broken controls; `test_reorder_identity.py`; `test_sheet_list.py:check_identity`; `test_assistive_selection.py` kept-tree cases over the real refresh and intake; `test_accessibility.py:check_assistive_selection_in_a_kept_tree`; real-input structural-change, held-lock and stale-drop checks | Checks, integration and Linux UI. Covers same-count replacements, name reuse, recorded/unrecorded batches, locks, Undo/Redo, saves and shared-monitor lifetime. <Unreleased /> A refresh that loses the proof replaces the native model even when the rows read the same, which clears a native selection still awaiting intake when the list owns no pick (#22); the native case selects through `XAccessibleSelection`, since real pointer and key input reach the list's own handlers. Entirely silenced, save-window-only and deliberately typed-input-shaped structural edits remain outside the [contract](./reordering.md). |
| Delayed observations and refreshes cannot overwrite newer input or activate stale rows | `test_view_observation.py`, `test_pointer_observation.py`, `test_assistive_selection.py`; integration stale-click cases; real-input `newer_selection_kept`, `press_then_change`, `newer_pick_survives_voided_press` | Checks, integration and Linux UI. Ordering adapters do not establish native visibility or selection behaviour. Held-press checks wait for the list's own listener via `Workbook.hold`; changes before it runs are ordered before the press (#134). |
| This window's native tabs and grouped-editing status follow without rebuilding rows or replacing independent picks | `test_sync_sheet_list.py:check_tabs`; observation unit tests; real-input synchronization checks | Integration, Checks and Linux UI. Tabs are sampled about every 0.25 seconds between interactions, not received as timestamped events. |
| Observation pauses while hidden and stays bound to the correct view through window changes and reload | `test_sync_sheet_list.py:check_hidden`, `check_views`, `check_reload`; `reload_accepts_real_input`; visibility/timer unit tests | Integration, Checks and Linux UI; minimize requires a painted session. Visibility is checked about once a second. Input during native initialization may still clear conservatively (#88). A failed Reload pick retains the posted click, delivered press/release, native selection changes and later modify notifications from callbacks, and names any selection notice, so the failure classifies itself. |
| Rows show each sheet's own order, viewed state, visibility, protection, scenarios and colour | Unit/integration `test_sheet_list.py`, `test_refresh_rebuild.py`; `test_reorder_identity.py:check_confusable_names` | Checks and integration. <Unreleased /> Sheet switches and tab colours repaint the rows and keep the native model while the identity proof holds and the picks are unchanged; name, order, visibility, protection and scenario changes rebuild it, because the hidden-root tree reparents every row when a node's label or image changes (26.2.1.2 and 26.8.2.2, #22), and so does every other refresh. The comparison uses each node's name as well as its label, so a label kept under another name rebuilds. The rows are taken after the repaint is requested, so a failed request is repeated by the retry; that failure is injected only into the simulated peer. The 1,000-sheet benchmark waits for each tab colour's repaint; only painted sessions read the swatch back. Rapid switches can still lag. |
| Names Calc confuses still use the picked sheet's handle; a move that needs a confused name uses the planner's equally short mirror image when Calc can address all its calls, and is refused otherwise | `check_confusable_names` with `ﬁ`/`fi` and `I`/`ı`; `test_reorder.py:lookup_conflict` and `addressable_plan` against an independent replay model and the planner on reversed orders | Integration and Checks. Exercises rows, Show, Hide, moves (one made by the mirror image, with its Undo and view restoration), refusals, per-call guards and batch rename. Grouped-tab Undo forces view reactivation and checks its activation sequence by identifying cells; menu Delete refuses either side of a confusable pair without changing the view, data or undo history (#138), then deletes exactly the second sheet as one undo step after the other is renamed, with complete restoration on Undo. Only two measured pairs and English locales; scenario combinations remain unverified. Calc's formula lookup remains defective (#113), and some moves are refused (#125). |

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
| Opening/dismissing the menu preserves picks, tabs and view; chosen Calc commands act on exactly their targets | `test_sheet_commands.py`, `test_menu_targeting.py`, `test_menu_lifetime.py`; real-input `context_*` and keyboard-menu checks | Integration, Checks, Linux UI and Windows desktop. Checks again after grouping/callbacks. Refusals restore a provable prior view; except for completed Hide, after dispatch begins Calc stays on its targets, including cancelled or uncertain dialogs. Synthetic input cannot reach gtk3 native menus. |
| Hide preserves an unaffected visible view and the remaining members of its previous tab group | `check_commands`, `check_hide_views`, `check_hide_restoration_callbacks`; targeting unit tests; real-input right-click/keyboard Hide | Integration, Checks, Linux UI and Windows desktop menu checks. Synchronous Hide and hidden targets are verified before restoration; proof, names and visibility are rechecked after activation and grouping. Moved sheets use fresh indices; replaced/renamed/hidden old group members stop restoration. Hiding the viewed sheet itself keeps Calc's visible fallback; uncertain dispatch never restores. |
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
| <Unreleased since="0.0.9" /> The list follows Calc's document background; native labels, selection, dividers and unused space stay readable without rebuilding rows or changing input/document state | `test_theme.py` readability, native selection pairs and tint-preserving adaptation, bounded/cached accessibility traversal and transient retry; `test_document_theme.py` private-profile live changes; real-input `document_colors` with independent glyph/background pixel checks; `test_theme_pixels.py` antialiasing and wrong-colour controls | Checks, integration and Linux gtk3/gen UI. Five controlled palettes include unreadable ordinary text, a background matching the native highlight and a white document with a faint blue selection from a dark native field; adapted saturated selections must retain their tint, and independent pixels check the painted result; restoration checks the original background and Calc's native selection/text pair. Ordinary text and synthesised selection text meet 4.5:1; retained platform selection pairs keep the platform's own contrast. A one-off Windows 26.8.1.1 probe also reads the resolved automatic dark background. Native labels/empty space are pixel-checked on Linux; Windows and Intel macOS headless verify native properties and state. Aqua pixels, other themes and high-contrast desktop modes are not established. The document surface lookup stops at tables/trees, eight levels and 128 objects; missing/disposed surfaces retain the preceding palette and retry. Obtaining the surface activates Calc's document/shape accessibility listeners for the view, even after hiding the list; caching avoids repeated walks, not that native cost. Bounded 1,000-rectangle selection measurements and their limits are recorded in [#141](https://github.com/viell-dev/slop-calc-sheet-manager/issues/141). |
| Full-width clicks select; double-click/Enter activates and ends grouped editing | Integration selection/activation cases; real-input `click_activates`, `ctrl_shift_selection`, `plain_click_ends_group` | Integration, Linux UI and Windows desktop selection checks. Built-in commands retain Calc's grouping semantics. `plain_click_ends_group` clicks the grid once and records the cursor's response time; a failure records whether the click arrived late or not at all (#42). |
| Shift, Ctrl and Alt do not crash LibreOffice while the deck is shown | `run.py` presses real modifiers with `xdotool`; Windows desktop selection and shortcut checks use `SendInput`; both check office shutdown and dumps | Painted Linux integration and Windows desktop in the release sweep; routine real-input UI checks also press modifiers. The headless Windows sweep lane does not press them. |
| Drag/drop keeps order/view, marks the gap, scrolls, cancels and undoes once | Real-input midpoint, in-place, Esc, autoscroll, stale-drop and undo checks; reorder integration | Linux UI and integration; Windows desktop covers native OLE drag, cancel and scrolling, but not stale drops. Autoscroll follows viewport resizing after a notice expires, preserving its six-second budget and order checks (#90). |
| Move buttons, menu actions and Alt shortcuts preserve independent picks | `test_move_buttons.py`, `test_move_menu.py`, key/queued-operation unit tests; real-input `move_*` checks; `test_button_paint.py` state-before-paint failure and other-platform controls; independent disabled-button interior/glyph pixels in `move_buttons` and `rename_sheets_keyboard` | Integration, Checks and Linux UI with the built-in Light theme enabled. Linux disabled controls use the supported local VCL paint route (#166), keeping the true disabled state and native enabled faces; toolbar sizing measures both paint modes. Pixel controls reject solid grey masks and absent glyphs. Windows/macOS painting is unchanged; Windows desktop covers Alt shortcuts, not button input or menu moves. |
| <Unreleased /> Moves stay usable when LibreOffice leaves the focused window's frame inactive; input in the list activates it, and only the move itself requires it | `test_window_activation.py` claim, enablement and preflight tests; `test_move_buttons.py:check_inactive_window` through the toolkit robot; real-input `moves_after_inactive_frame` | Checks, Integration and Linux UI; the release sweep's Windows and macOS integration run the robot case. The inactive state is made with `frame.deactivate()` while the window keeps the focus; the window sequence that produced it on the reporter's Wayland desktop is not reproduced (#211). |
| List/button keys cannot edit cells; shortcuts and focus traversal remain usable | `test_keys.py`; real-input `keys_stay_in_list`, `move_focus_and_queued_navigation`, `shortcuts_reach_calc`, `other_document`, `native_cursor_positions`, `cursor_across_refresh` | Checks and Linux UI. Windows desktop covers list keys/shortcuts, not the button, other-document or cursor probes. Input methods and screen-reader experience are unverified. |
| Ctrl+S returns focus to the list without taking it from a save dialog | Save-only routing unit test; `shortcuts_reach_calc`, `save_prompts_keep_focus` | Checks and Linux UI, plus basic save shortcut on Windows desktop. Save As cancellation and read-only error are automated on Linux. Keep Current Format retains focus while open, but its completion is not automated; Windows prompt paths and Wayland are unverified. |
| Cursor/range anchor survives rebuilds; refused held clicks preserve surviving picks | Retained-anchor and coalesced-intent unit tests; `cursor_across_refresh`, `native_cursor_positions`, `selected_press_cursor` | Checks and Linux UI. The cursor checks rebuild the rows by toggling a sheet's protection; <Unreleased /> painted-only refreshes keep the tree and write no cursor (#22). A refused hold need not retain an unpicked cursor position; no cursor is promised without surviving picks. |
| Selection notice expires after ten seconds without changing focus, picks or grouped warning | `test_selection_notice.py`, real-input `selection_notice` | Checks and Linux UI. Text fit was inspected at one GTK width; no automated font/width/DPI assertion, Windows notice check or screen-reader announcement check. |
| Dividers track native bounds and avoid scrollbars | `test_row_paint.py`, `row_paint_scroll`, `row_paint_long_names` | Checks and Linux UI; focused GTK 120-DPI evidence in #86. Synthetic short/long names and pinned themes; only the last lower divider may be omitted. Horizontal endpoint gestures are inspected in screenshots, not an asserted final position. Windows painting is unverified. |
| <Unreleased since="0.0.9" /> Accessible list name identifies the viewed sheet; external accessibility picks survive a rebuilding refresh, <Unreleased /> and a refresh that keeps the tree, while the list can still prove sheet identity | `test_accessibility.py:check_viewed_sheet`, `check_assistive_selection_before_rebuild`, `check_assistive_selection_in_a_kept_tree`; pure and real-method assistive-selection tests; `viewed_sheet_name`; `newer_selection_kept` | Integration, Checks, Linux UI and Windows desktop name check. Reads public UNO metadata/events; no screen reader or cross-process selection bridge runs. A rebuild shows a selection still awaiting intake again, so the kept-tree check observes the intake through Move to Top's enablement, which only the list's own picks change. A lost proof clears such a pick, whichever sheet caused it: a replaced sheet, or another sheet's handle that could not be read. Name can lag with the arrow (#22). |
| <Unreleased since="0.0.9" /> Accessible hierarchy reaches the list and lists controls in visual order; margin drags leave the sidebar docked | `test_accessibility.py:check_hierarchy`, `run.py:drag_from_margins`, `margin_drag_keeps_sidebar_docked` | Integration, Linux UI and Windows desktop drag check. Disabled unnamed backdrop is last. gtk3 does not undock even without handling the press, so gen/win are needed to expose that regression. A one-off gtk3 AT-SPI probe found controls and focus/cursor/name events; no AT-SPI or IAccessible2 bridge probe runs in CI (#133). |
| Help hands the guide URI to the desktop; <Unreleased since="0.0.10" /> the header's `?` opens bundled quick help | `help_menu` with real SystemShellExecute and a private URI recorder; `test_help.py` installed topic, locale fallback and unknown-HID control; `header_help` real click and internal viewer | Integration verifies native help compilation/lookup; Linux gtk3/gen UI checks the actual header and unchanged document state. The fixed Linux lab measures the click from its calibrated panel origin. Browser rendering, arbitrary header themes and Windows/Aqua header input are not established. XML-help support is optional in LibreOffice builds; the online menu action remains available (#81). |
| Partial initialization and failed popup creation leave no list-owned registrations or stale menu state | `test_adapter_failures.py` with forwarding adapters and owned-key failure tests | Integration. Shared structure monitor intentionally lives until document disposal. Key-handler removal is not directly observed by panel-disposal tests. |
| <Unreleased /> A list that cannot open shows a message naming only the error type; failed refreshes stay pending and retry with a bounded backoff; panel disposal and move-button callbacks finish after failures | `test_panel_failures.py`; `test_adapter_failures.py:check_failed_panel`, `check_failed_refresh` | Checks and Integration. Failures are injected through test-only subclasses and patched constructors; how often LibreOffice itself causes them is not measured. |

Input and paint investigations, including negative controls, are in
[#23](https://github.com/viell-dev/slop-calc-sheet-manager/issues/23),
[#86](https://github.com/viell-dev/slop-calc-sheet-manager/issues/86), and
[#134](https://github.com/viell-dev/slop-calc-sheet-manager/issues/134).
Accessibility evidence and limits are in
[#83](https://github.com/viell-dev/slop-calc-sheet-manager/issues/83) and
[#133](https://github.com/viell-dev/slop-calc-sheet-manager/issues/133).

## Performance measurements

Pure planning has a regression budget of five seconds of process CPU time at 10,000 sheets for
one-call and reverse-order move plans, which take under a second even on a loaded host. It
catches a planner that grows quadratically in Python, such as the old block scan (36 to 43 seconds
for the one-call plan), but not a slowdown by a constant factor, nor a return to the earlier list
simulation, whose quadratic scans run in C (3 to 7 seconds on a loaded laptop). Inside a virtual
machine, CPU time still counts time that the host takes away
([#214](https://github.com/viell-dev/slop-calc-sheet-manager/issues/214)). Rename tests budget
five seconds of elapsed time for a 1,000-sheet cycle and chain. Native timings are measurements,
not limits:

- `reorder-performance-<session>.json`: three runs each at 200 and 1,000 sheets with cross-sheet
  formulas, named ranges and charts; first, half, all-but-last and alternating selections moved
  to bottom. Timings include snapshot, planning, preflight, application and final verification.
  Undo is timed separately, with reference-integrity assertions before/after it.
- `rename-performance-headless.json`: complete batches and Undo, three runs at 200 sheets and one
  at 1,000, across the UNO bridge.
- `test_sheet_list.py:measure_large_workbook`: list opening and tab following at 1,000 sheets.
  Activation waits until the tree's accessible name names the viewed sheet, and asserts that the
  native model was kept, before the separate tab-only measurement. Three tab colours, the last
  restoring the default, must also keep the model: each waits for the tree's next paint
  (`XPaintListener`) after a quiet second, and painted sessions also wait for the first row's
  swatch to show it. Headless (svp) reads of the window return a uniform background (26.8.2.2),
  so headless sessions show that a repaint followed, not what it drew. Four protection changes
  time the label rebuilds that still replace the model.
  Menu construction records three consecutive `SheetMenu.build` samples with unique names,
  then an unrelated pick and each member of a `ﬁ`/`fi` pair at the last two indices. Delete stays
  enabled for the unrelated sheet and refuses either collision member, without changing sheet
  order, viewed sheet, grouped tabs, undo/redo history, modified state or the identifying cell.
  These are external test-client UNO wall times, with snapshots, setup, assertions and cleanup
  excluded; they do not measure in-process popup display or input latency. There is no warm-up,
  sample selection or timing threshold. Results are retained under `large_workbook.menu_build`
  in the integration session's JSON, alongside lane artifacts identifying the office and Python
  versions and the tested environment.
  The native reparenting and an in-process profile of the rebuild are recorded in
  [#22](https://github.com/viell-dev/slop-calc-sheet-manager/issues/22).

All inputs are synthetic. Workbooks stay in memory unless the contributor explicitly runs the
[inspection workbook generator](./development/native-testing.md#inspection-workbooks).

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
ensure that failed checks cannot pass through cleanup. `test_ui_failure_records.py` fails each
real-input failure diagnostic and clean-up step in turn and checks that the failed check's record
is already on disk and keeps its own error (#190). `test_lab_calibration.py` checks that the
Xvfb lab's pointer calibration waits for the tree's own report of its move, so a busy office
cannot shift a workbook's calibrated positions and pixel coordinates by two pixels (#209).
`test_rename_dialog_calibration.py` checks that the rename dialog's calibration takes its offset
only from two reports that follow its two moves, so a late report of another point cannot move
the dialog's clicks off their controls (#232).
Sessions fail on nonzero exits, forced
shutdowns, fatal messages, crash dumps, stalled main-thread callbacks or held terminate requests.
`test_install_timing.py` checks that each package installation's elapsed time is recorded and
that one exceeding its limit still fails, with that time and unopkg's output kept (#235).
Windows crash dumps matter even when the office exits with status zero. Only startup is retried;
its dumps are retained separately. Debugger runs also reject signals, incomplete exits and missing
traces. The Xvfb helper disables key repeat; `single_tap_after_client_pause` verifies one cursor
step after a one-second held key. Operating-system timed repeat is outside that check.

Fixture procedures and artifact diagnosis are in
[Native LibreOffice testing](./development/native-testing.md#failures-and-shutdown).
Lifecycle failure evidence is in
[#40](https://github.com/viell-dev/slop-calc-sheet-manager/issues/40),
[#48](https://github.com/viell-dev/slop-calc-sheet-manager/issues/48), and
[#50](https://github.com/viell-dev/slop-calc-sheet-manager/issues/50).
