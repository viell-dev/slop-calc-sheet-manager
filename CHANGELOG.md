# Changelog

Notable changes to Sheet Manager, newest first. Version numbers are plain dotted numbers; see
[RELEASING.md](RELEASING.md#versions-and-titles) for why there are no prerelease suffixes.

## Unreleased

- Added checked release publication with versioned OXT/checksum assets, a read-only dry run, and
  stable/prerelease update feeds on GitHub Pages. Installed copies use the stable feed. No build
  has been published yet ([#6](https://github.com/viell-dev/slop-calc-sheet-manager/issues/6)).
- Added the reorder operation layer for drag/drop and Top, Up, Down, and Bottom: minimum-call
  planning, scenario blocks, permission checks, one undo step, and verified failure recovery.
  The sidebar controls will use this interface when the list panel is integrated.
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

## 0.0.1 - Development baseline (unpublished)

- Initial development package for release-process dry runs. This is not a published release;
  the first feature release is planned as 0.1.0.
