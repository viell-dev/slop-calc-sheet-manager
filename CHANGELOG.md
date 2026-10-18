# Changelog

Notable changes to Sheet Manager, newest first. Version numbers are plain dotted numbers; see
[AGENTS.md](AGENTS.md#releases) for why there are no prerelease suffixes.

## Unreleased

- Added an empty Sheet Manager deck to Calc's sidebar as the foundation for the sheet list.
- Added Windows development checks, durable LibreOffice download pins, and integration checks that
  reject crashes or fatal-error logs during shutdown. The intermittent gtk3 abort on the minimum
  version is tracked in [#8](https://github.com/viell-dev/slop-calc-sheet-manager/issues/8).
- Kept automatic dependency updates for the checks container on Python 3.12, the oldest supported
  version, and on the Node major version that CI uses.
- Made the integration resize test use observed frame dimensions across gtk3 window layouts,
  retaining the exact 150-pixel frame and panel growth checks
  ([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)).
