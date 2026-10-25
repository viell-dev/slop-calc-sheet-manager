# Status and plans

The `0.0.3` test build targets the first feature release, `0.1.0`. The
[release page](./releases.md) lists currently published downloads; the notice above identifies
the build this guide describes.

## What the test build includes

- **An installable extension.** It installs on LibreOffice 26.2.1 or later, and earlier versions
  refuse it. It can be removed cleanly. It names the project's update feed, so that
  LibreOffice's Extension Manager can offer updates once builds are published.
- **A sheet list in Calc's sidebar.** It shows every sheet in tab order, with the
  viewed sheet, tab colours, hidden sheets, protection, and scenarios identified. Click a full-width
  row to select, double-click or Enter to switch, and Ctrl/Shift to select several. It refreshes
  after changes and follows this window's selected tabs even when its active sheet stays the same.
  A footer identifies grouped Calc tabs only while several are grouped; these can differ from picks.
- **Drag and drop.** It reaches a new order with the fewest moves and
  applies the whole change as one undo step. It checks permissions first, and recovers and
  verifies if a change fails part-way. It is tested against real LibreOffice on workbooks of up to
  1,000 sheets. Drag any selection to an insertion line; the list scrolls near its edges.
- **Context actions.** Move to top, up, down, or bottom in one undo step, with
  Alt+Home/Up/Down/End shortcuts and disabled reasons. Right-click targets the pointed row or
  existing picked set without changing picks. Calc's customized menu is under **Sheet actions**;
  temporary native grouping is restored on dismissal where safe. The menu also links to Help.
- **Manual-install downloads and update feeds.** Each published build includes an OXT and checksum.
  Installed copies use the stable feed; later test builds are downloaded manually.

## Toward 0.1.0

The core feature set above is implemented. Test builds exercise it before the first stable
feature release. Readiness rests on native checks and release review, with the limits in
[Compatibility and known issues](./known-issues.md) kept explicit. Each publication follows the
[release procedure](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md).

## How releases will work

- **Downloads.** Each release is an `.oxt` file with a checksum, published on
  [GitHub Releases](https://github.com/viell-dev/slop-calc-sheet-manager/releases).
- **Version numbers.** Releases have plain numbers such as `0.1.0`.
- **Test builds.** Every test build has a GitHub release marked **Pre-release**, with an OXT and
  checksum for manual installation. They are never offered automatically. Their numeric
  versions work around LibreOffice's incompatible prerelease ordering; see
  [Releases and test builds](./releases.md#version-numbers).

See [Install, update, and remove](./install.md).
