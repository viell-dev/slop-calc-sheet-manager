# Status and plans

Sheet Manager has no release yet. This page separates what the development version does today from
what the first release is planned to do.

## What exists today

- **An installable extension.** It installs on LibreOffice 26.2.1 or later, and earlier versions
  refuse it. It can be removed cleanly. It names the project's update feed, so that
  LibreOffice's Extension Manager can offer updates once builds are published.
- **An empty Sheet Manager deck in Calc's sidebar.** The deck is there, in read-only workbooks
  too, and fills the sidebar as you resize it. It shows nothing yet, and it neither reads nor
  changes the content of your documents.
- **The operation that will move sheets.** It reaches a new order with the fewest moves and
  applies the whole change as one undo step. It checks permissions first, and recovers and
  verifies if a change fails part-way. It is tested against real LibreOffice on workbooks of up to
  1,000 sheets. No control reaches it yet.
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

None of these is available in the development version. Their progress is tracked on GitHub:

- the sheet list, its keys, and the menu:
  [#2](https://github.com/viell-dev/slop-calc-sheet-manager/issues/2) and pull request
  [#21](https://github.com/viell-dev/slop-calc-sheet-manager/pull/21);
- keeping the list in sync:
  [#5](https://github.com/viell-dev/slop-calc-sheet-manager/issues/5);
- the move buttons: [#35](https://github.com/viell-dev/slop-calc-sheet-manager/issues/35).

## How releases will work

- **Downloads.** Each release is an `.oxt` file with a checksum, published on
  [GitHub Releases](https://github.com/viell-dev/slop-calc-sheet-manager/releases).
- **Version numbers.** Releases have plain numbers such as `0.1.0`.
- **Test builds.** Release candidates have their own lower numbers: `0.0.90` tests `0.1.0`.
  They are marked **Pre-release** and are never offered as updates to people who installed a
  stable release.

See [Install, update, and remove](./install.md).
