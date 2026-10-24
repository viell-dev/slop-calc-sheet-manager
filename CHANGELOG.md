# Changelog

Notable changes to Sheet Manager, newest first. Version numbers are plain dotted numbers; see
[RELEASING.md](RELEASING.md#versions-and-titles) for why there are no prerelease suffixes.

## Unreleased

- Cursor restoration now follows the native tree's focused row rather than predicting its position
  from key callbacks, including navigation outside the selection and across a list rebuild
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
