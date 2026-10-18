# Changelog

Notable changes to Sheet Manager, newest first. Version numbers are plain dotted numbers; see
[AGENTS.md](AGENTS.md#releases) for why there are no prerelease suffixes.

## Unreleased

- Added an empty Sheet Manager deck to Calc's sidebar as the foundation for the sheet list.
- Added Windows development checks, durable LibreOffice download pins, and integration checks that
  reject crashes or fatal-error logs during shutdown. The intermittent gtk3 shutdown abort,
  observed on both 26.2.1.2 and 26.8.1.1, is tracked in
  [#8](https://github.com/viell-dev/slop-calc-sheet-manager/issues/8).
- Kept automatic dependency updates for the checks container on Python 3.12, the oldest supported
  version, and on the Node major version that CI uses.
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
