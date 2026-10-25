# Status and plans

Sheet Manager has no release yet. This page separates what the development version does today from
what the first release is planned to do.

## What exists today

- **An installable extension.** It installs on LibreOffice 26.2.1 or later, and earlier versions
  refuse it. It can be removed cleanly. It names the project's update feed, so that
  LibreOffice's Extension Manager can offer updates once builds are published.
- **A sheet list in Calc's sidebar (Unreleased).** It shows every sheet in tab order, with the
  active sheet, tab colours, hidden sheets, protection, and scenarios identified. Click to switch,
  Ctrl+click or Shift+click to select, and use the keyboard or Calc's sheet tab menu. It refreshes
  after changes and follows this window's selected tabs even when its active sheet stays the same.
  A separate status line identifies Calc's grouped tabs, which can differ from the list's picks.
- **Drag and drop (Unreleased).** It reaches a new order with the fewest moves and
  applies the whole change as one undo step. It checks permissions first, and recovers and
  verifies if a change fails part-way. It is tested against real LibreOffice on workbooks of up to
  1,000 sheets. Drag any selection to an insertion line; the list scrolls near its edges.
- **Move buttons (Unreleased).** Top, Up, Down, and Bottom act on the list's selection, in one
  undo step, with Alt+Home/Up/Down/End shortcuts. Unavailable buttons explain why in their
  tooltips, and a move keeps the sheets selected for the next press.
- **Release and update infrastructure**, with no published build yet. The update feeds are empty.

## Planned for 0.1.0

The first release is planned to offer:

- every sheet in document order, kept in sync with changes from anywhere, with the active sheet,
  hidden sheets, tab colours, and protection shown;
- click to go to a sheet, and Ctrl+click and Shift+click to select several, as on the tab bar;
- drag and drop of one or more selected sheets, with an insertion line and scrolling near the
  edges;
- buttons to move the selection to the top, up, down, or to the bottom;
- the sheet tab bar's own context menu, including your customizations of it;
- complete keyboard operation;
- one undo step per change, and respect for protected and read-only documents.

The sheet list, synchronization, keyboard handling, menu, drag and drop, and move buttons are
implemented but unreleased. The first release still needs the preparation and exact-commit
verification described in the
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
