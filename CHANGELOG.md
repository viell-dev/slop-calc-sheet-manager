# Changelog

Notable changes to Sheet Manager, newest first. Version numbers are plain dotted numbers; see
[AGENTS.md](AGENTS.md#releases) for why there are no prerelease suffixes.

## Unreleased

- Added the reorder operation layer for drag/drop and Top, Up, Down, and Bottom: minimum-call
  planning, scenario blocks, permission checks, one undo step, and verified failure recovery.
  The sidebar controls will use this interface when the list panel is integrated.
- Added an empty Sheet Manager deck to Calc's sidebar as the foundation for the sheet list.
- Added Windows development checks, durable LibreOffice download pins, and integration checks that
  reject crashes or fatal-error logs during shutdown. The intermittent gtk3 abort on the minimum
  version is tracked in [#8](https://github.com/viell-dev/slop-calc-sheet-manager/issues/8).
- Made the integration resize test use observed frame dimensions across gtk3 window layouts,
  retaining the exact 150-pixel frame and panel growth checks
  ([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)).
