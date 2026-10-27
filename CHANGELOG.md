# Changelog

Notable changes to Sheet Manager, newest first. Version numbers are plain dotted numbers; see
[RELEASING.md](RELEASING.md#versions-and-titles) for why there are no prerelease suffixes.

## Unreleased

- Fix **Sheet actions…** ▸ Rename Sheet renaming the previously viewed sheet instead of the
  right-clicked or picked one. Its dialog applies to the sheet viewed when confirmed, and Sheet
  Manager restored the earlier view while the dialog was open
  ([#100](https://github.com/viell-dev/slop-calc-sheet-manager/issues/100)). Once a command is
  chosen from Calc's menu, Calc now stays on its targets; closing the menu without a command still
  restores the previous view.

- Describe current development as alpha iteration, with no settled feature scope or scheduled
  stable release. Untargeted prereleases are titled with their own version and **alpha**.

## 0.1.0 - Unpublished preparation

This preparation was not published. Development continues in alpha; the earlier stable-release
plan is superseded. Requires LibreOffice 26.2.1 or later with Python support.

- Find and select sheets in a vertical sidebar list, with full-width rows, keyboard navigation,
  and an indicator for the viewed sheet. List picks remain independent of Calc's grouped tabs.
- Drag one or more selected sheets any distance, or use Top, Up, Down and Bottom buttons,
  context actions or Alt shortcuts. Each extension move is one undo step, with permission and
  sheet-identity checks before acting and verified recovery if a move fails.
- Open Calc's customized sheet-tab menu through **Sheet actions…**. Wrong-target rename after
  the native dialog is under investigation in
  [#100](https://github.com/viell-dev/slop-calc-sheet-manager/issues/100).

Changes since the 0.0.4 test build:

- Keep new guide instructions marked **Unreleased** through release preparation and failed or
  abandoned publication. Published history controls their availability markers; documentation
  corrections still deploy independently of software versions and tags.
- Release the native sheet-menu dispatch guard even if its panel is disposed while the menu is
  open, so the surviving Calc window can still run ordinary commands after dismissal.
- Replace the persistent selection-cleared infobar with a ten-second panel notice. Expiration
  keeps keyboard focus, current picks, and Calc's separate grouped-editing warning unchanged.
  Undo/Redo still clears picks conservatively; preserving verified move selections is tracked
  in [#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91).

Install alpha OXTs manually. LibreOffice's Extension Manager offers only published stable updates;
there is no stable release yet, and the unpublished 0.1.0 preparation will not be published as stable.
Restart LibreOffice when asked. Each release includes an OXT and SHA-256 checksum; test builds remain
manual downloads. See the [guide](https://viell-dev.github.io/slop-calc-sheet-manager/) for use,
compatibility, and known limits, including conservative selection clearing on Undo/Redo.
LibreOffice 26.8.0 and 26.8.1 still have a known formula-reference defect in their own Duplicate
Sheet and Move or Copy Sheet commands; see the guide before using those native copy commands.

## 0.0.4 - 2026-10-26

Third test build for 0.1.0, addressing feedback on 0.0.3.
Requires LibreOffice 26.2.1 or later with Python support.

- Opening the movement context menu keeps the viewed sheet and Calc tab selection unchanged.
  **Sheet actions…** opens Calc's customized menu when every target is visible; only that step
  temporarily targets its native tabs, with safe restoration after dismissal. Mixed visible
  and hidden targets instead offer safe Show/move actions without native grouping.
  Refused rapid repeats also leave the current view and list picks unchanged.
- Restore Top, Up, Down, and Bottom buttons above the list. They share the menu's permission,
  identity and undo checks, show refusal reasons, and support keyboard focus and activation.
  The grouped-editing warning remains a conditional footer.
- Keep row dividers aligned after scrolling and font/DPI changes by following actual native
  row geometry. Decorations stop at the content viewport instead of covering scrollbars, and
  fixed border pixels no longer get copied into rows by native scrolling. Horizontal scrolling
  of long names keeps decorations aligned across the whole viewport.

Install the OXT manually over 0.0.3, restart LibreOffice, and check its SHA-256 asset. Test builds
keep the stable update feed; later test builds remain manual downloads. Existing compatibility
and selection limits remain in the [known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues).

## 0.0.3 - 2026-10-25

Second test build for 0.1.0, focused on the sidebar's interaction and appearance.
Requires LibreOffice 26.2.1 or later with Python support.

- Click anywhere across a row to select it without switching sheets. Double-click or press
  Enter to activate it. Ctrl/Shift selection and keyboard navigation keep an independent range
  anchor through ordinary refreshes.
- Rows have full-width highlights, dividers, and more vertical space. The current-sheet arrow
  and tab-colour square sit separately to the left of the name. Dragging shows a stronger
  three-pixel insertion line with end markers.
- Move sheets from the context menu or with Alt+Home/Up/Down/End. The toolbar is removed, and the
  grouped-editing warning appears in a footer only while multiple Calc tabs are grouped.
- Right-click targets a row without selecting it. It uses the existing picked set when that row
  is already picked. Calc's customized menu is under **Sheet actions**; temporary native tab
  grouping is restored after dismissal where the original sheets can still be proved safe.
- **Sheet Manager Help** opens the project guide. The header's native `?` still opens
  LibreOffice's unavailable local help topic; this host limitation is documented in #81.

Install the OXT manually over 0.0.2 and check its SHA-256 asset. Test builds remain manual
downloads and keep stable updates enabled. Existing compatibility and conservative
selection-clearing limits still apply; see the [known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues).

## 0.0.2 - 2026-10-25

First test build for 0.1.0. This build is intended for testing with synthetic or backed-up
workbooks. It requires LibreOffice 26.2.1 or later with Python support.

- Find every sheet in a vertical sidebar list, with tab colours and active, hidden, protected,
  and scenario states identified.
- Click to activate a sheet, use Ctrl/Shift selection independently of Calc's grouped tabs, and
  navigate or search by typing with the keyboard.
- Move selected sheets by drag and drop or Top, Up, Down, and Bottom buttons, with Alt shortcuts,
  insertion feedback, and edge scrolling. Each extension move is one undo step.
- Follow changes from Calc tabs, menus, macros, other windows, undo and redo. A separate status
  identifies the Calc tabs affected by grouped cell editing.
- Use Calc's own sheet-tab menu for the picked sheets. Hidden-sheet Show and reorder operations
  check permissions, reject stale targets, and verify recovery after a failed operation.
- Install manually from the OXT asset and check its SHA-256 file. Test builds are marked
  **Pre-release**; installed copies keep stable updates enabled and later test builds are manual
  downloads.

Known limits include conservative selection clearing after uncertain structural changes,
full-tree property refresh costs on large workbooks, Ctrl+S moving focus to the sheet, and
native range/cursor limits after a rebuild or a refused held gesture. See
[Compatibility and known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues)
and the [user guide](https://viell-dev.github.io/slop-calc-sheet-manager/) before use.

## Development history before 0.0.2

These notes record implementation and verification work before the first test build; they are
historical development notes, not earlier published releases.

- The list follows this window's selected Calc tabs even when the active sheet does not change.
  A status line identifies grouped Calc tabs separately from independent list picks. Observation
  pauses while the panel is hidden and resumes on reopening, preserving newer list input and
  stale-sheet safeguards ([#5](https://github.com/viell-dev/slop-calc-sheet-manager/issues/5)).
- Added a human release/download page with OXT and checksum links for stable and test builds,
  explained why LibreOffice's version ordering prevents direct SemVer prerelease suffixes, and
  removed the arbitrary `.90` patch reservation in favour of an explicit release flag. Corrected
  outdated feature status in the guide
  ([#73](https://github.com/viell-dev/slop-calc-sheet-manager/issues/73)).
- The release dry run waits for the native CI matrix's full time budget before refusing a build
  whose exact-commit checks have not finished
  ([#72](https://github.com/viell-dev/slop-calc-sheet-manager/issues/72)).
- Cursor restoration now follows the native tree's focused row rather than predicting its position
  from key callbacks. Ordinary rebuilds preserve navigation outside the selection; a refused held
  click restores its picks and, when any survive, returns the cursor to one of them
  ([#69](https://github.com/viell-dev/slop-calc-sheet-manager/issues/69)).
- Move-button enablement no longer consumes a pending ordinary edit notification, which could
  clear the list's picks at the next refresh
  ([#66](https://github.com/viell-dev/slop-calc-sheet-manager/issues/66)).
- Added Top, Up, Down, and Bottom buttons above the list, with Alt+Home/Up/Down/End
  shortcuts, disabled reasons in tooltips, and selection preserved for repeated moves. Each press
  uses the guarded reorder adapter and is one undo step
  ([#35](https://github.com/viell-dev/slop-calc-sheet-manager/issues/35)).
- The reorder adapter now refuses snapshots held across a sheet replacement, even when sheet names
  and retained handle names still match. Snapshots and list views share a document-owned structural
  monitor, and Undo or Redo requires a fresh snapshot
  ([#19](https://github.com/viell-dev/slop-calc-sheet-manager/issues/19)).
- Clean up partial list initialization and failed menu setup, consume owned keys after a handler
  error, and refuse Show Sheet while changes are being recorded. Type-ahead now cycles through
  sheets when their first letter is repeated. The guide and verification map cover the list,
  and optional desktop observations no longer act as a routine release gate.
- Added the sheet list to the panel: every sheet in document order with its tab colour and its
  active, hidden, protected, and scenario state. A click goes to a sheet; Ctrl+click and
  Shift+click select several without changing the active sheet. Selected sheets can be dragged,
  with an insertion line and auto-scroll, to a new place through the reorder layer, in one undo
  step; Esc cancels. Keys typed in the list stay out of the sheet while Calc's shortcuts keep
  working, and the sheet tab menu opens by right click, Menu key, or Shift+F10 for exactly the
  selected sheets ([#2](https://github.com/viell-dev/slop-calc-sheet-manager/issues/2)). A
  renamed sheet leaves the selection, and when sheets may have been added or removed, also by a
  macro that turns off undo or batches its changes, the list clears its selection and says so,
  rather than act on a sheet that was not selected
  ([#28](https://github.com/viell-dev/slop-calc-sheet-manager/issues/28)); a click ends any
  grouping of Calc's tabs ([#25](https://github.com/viell-dev/slop-calc-sheet-manager/issues/25));
  Calc no longer hangs when the list schedules a refresh during a change
  ([#55](https://github.com/viell-dev/slop-calc-sheet-manager/issues/55));
  showing hidden sheets needs undo and is undone on failure
  ([#27](https://github.com/viell-dev/slop-calc-sheet-manager/issues/27)); refreshing keeps the
  keyboard position ([#29](https://github.com/viell-dev/slop-calc-sheet-manager/issues/29)).
- Added real-input UI tests with gtk3 and gen, headless sheet list checks, and a manual checklist
  with a synthetic workbook for what automation cannot reach.
- Added checked release publication with versioned OXT/checksum assets, a read-only dry run, and
  stable/prerelease update feeds on GitHub Pages. Installed copies use the stable feed. No build
  has been published yet ([#6](https://github.com/viell-dev/slop-calc-sheet-manager/issues/6)).
- Added the reorder operation layer for drag/drop and Top, Up, Down, and Bottom: minimum-call
  planning, scenario blocks, permission checks, one undo step, and verified failure recovery.
  The sheet list's drag and drop uses it.
  Planning stays responsive in large workbooks; recovery preserves the user's previous action at a full
  undo stack, and view-restoration failures warn without undoing a verified move. Both success and
  rollback restore the view before unlocking controllers to avoid an intermediate repaint. Balanced groups
  work around Calc's undo-capacity defect
  ([#16](https://github.com/viell-dev/slop-calc-sheet-manager/issues/16)); embedded chart names
  retain Calc's native rename-on-move limitation
  ([#17](https://github.com/viell-dev/slop-calc-sheet-manager/issues/17)).
- Added an empty Sheet Manager deck to Calc's sidebar as the foundation for the sheet list.
- Fixed a crash when Shift, Ctrl, or Alt was pressed in Calc while the Sheet Manager deck was
  shown ([#18](https://github.com/viell-dev/slop-calc-sheet-manager/issues/18)).
- Added Windows development checks, durable LibreOffice download pins, and integration checks that
  reject crashes or fatal-error logs during shutdown.
- Avoided an intermittent LibreOffice crash in painted integration sessions by waiting a second
  before the tests close Writer ([#8](https://github.com/viell-dev/slop-calc-sheet-manager/issues/8),
  [#30](https://github.com/viell-dev/slop-calc-sheet-manager/issues/30)).
- Kept automatic dependency updates for the checks container on Python 3.12, the oldest supported
  version, and on the Node major version that CI uses.
- Added `.nvmrc`, so that nvm and fnm select the Node version CI uses for Pyright. The workflows
  install Node from it, and a unit test keeps it equal to the checks image's Node.
- Made the integration resize test use observed frame dimensions across gtk3 window layouts,
  retaining the exact 150-pixel frame and panel growth checks
  ([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)).
- Split required Linux headless checks from non-required painted gtk3 jobs, added a manual soak
  with extension-free controls and crash backtraces, and extended the shutdown grace period to
  30 seconds. Image reuse now rebuilds for changed Dockerfiles or pins, and the checks image
  excludes unrelated build context ([#10](https://github.com/viell-dev/slop-calc-sheet-manager/issues/10)).
- Wait for two stable frame/panel measurements before the resize baseline, retaining exact
  150-pixel growth checks ([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)).
- Keep diagnostic files separate for each integration session, clear stale runner artifacts, and
  continue soak measurements after missing or unreadable session results. Manual soaks use their
  own workflow, avoiding skipped checks with required job names.
- Asked contributors to say when an AI agent wrote or submitted an issue, pull request, or comment,
  and whether a person reviewed it.
- Required the painted gtk3 checks for merging again, after 180 painted sessions on `main` ran
  without a failure ([#32](https://github.com/viell-dev/slop-calc-sheet-manager/issues/32)).
- Added issue forms for bug reports, improvements, feature requests, and questions. The bug form
  asks for LibreOffice's copied version information, how LibreOffice was installed, and a workbook
  made for the report. The README now says which LibreOffice versions and environments are
  verified, expected to work, or unsupported
  ([#56](https://github.com/viell-dev/slop-calc-sheet-manager/issues/56)).
- Made the integration checks fail visibly instead of passing or hanging:
  - They keep LibreOffice's crash dumps, and fail a session whose office crashed even though it
    exited with status 0 on Windows
    ([#48](https://github.com/viell-dev/slop-calc-sheet-manager/issues/48)).
  - On Windows they close test workbooks on LibreOffice's main thread
    ([#47](https://github.com/viell-dev/slop-calc-sheet-manager/issues/47)).
  - They stop an office whose callback or terminate request stalls
    ([#50](https://github.com/viell-dev/slop-calc-sheet-manager/issues/50),
    [#40](https://github.com/viell-dev/slop-calc-sheet-manager/issues/40)).
  - They repeat the painted resize check's setup when the new window is maximized late
    ([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)).
- Added a user guide at <https://viell-dev.github.io/slop-calc-sheet-manager/>, published with the
  update feeds. It covers installation, updates, removal, use, compatibility, troubleshooting, and
  reporting a problem, and says which version it describes. The page listing the feeds moved to
  `updates/`; the feed addresses are unchanged
  ([#56](https://github.com/viell-dev/slop-calc-sheet-manager/issues/56)).
- Checked that LibreOffice still converts files headlessly with the extension installed, and that
  removing the extension leaves no deck, panel, or installed copy behind. `docs/verification.md`
  maps each promise to the checks that verify it.

## 0.0.1 - Development baseline (unpublished)

- Initial development package for release-process dry runs. This is not a published release;
  the first feature release is planned as 0.1.0.
