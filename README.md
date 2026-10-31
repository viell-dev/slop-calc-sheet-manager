# Sheet Manager

A LibreOffice Calc extension that lists a workbook's sheets in the sidebar, top to bottom, so that
you can find, select, and rearrange them quickly, however many there are.

The sheet tab bar at the bottom of Calc is small and scrolls one tab at a time. Moving a sheet
across dozens of others means a long, precise drag, and the alternative, the Move or Copy Sheet
dialog, is buried in a menu. Sheet Manager puts every sheet in one vertical list, as browsers do
with vertical tabs, where any selection of sheets moves any distance in one drag.

The [user guide](https://viell-dev.github.io/slop-calc-sheet-manager/) covers installation,
updates, removal, use, known issues, troubleshooting, and reporting a problem.

## Status

Source version: `0.0.8` beta towards the first stable release, 0.1.0. Sheet Manager is in
**beta**: the features planned for 0.1.0 are complete, and the remaining work is fixing the
logged defects and polishing. No stable release date is set. Stable publication requires the
agreed release goal ([#120](https://github.com/viell-dev/slop-calc-sheet-manager/issues/120)),
human usability testing, and resolution of release blockers.
See [Releases and test builds](https://viell-dev.github.io/slop-calc-sheet-manager/guide/releases)
for currently published downloads. Sheet Manager lists the workbook's sheets, supports selection,
drag and drop, and move actions with keyboard shortcuts,
handles keyboard navigation, and runs Calc's common sheet commands from its own menu. Each
extension move or batch rename is one undo step.
It follows this window's Calc tab selection and shows grouped-editing feedback separately from
the list's own picks. Its features include:

- every sheet in document order, kept in sync with changes from anywhere, with the active sheet,
  hidden sheets, tab colours, and protection shown;
- full-width rows: click to select, double-click or Enter to go to a sheet, and Ctrl/Shift to
  select several;
- drag and drop of one or more selected sheets, with an insertion line and scrolling near the
  edges;
- top buttons and context-menu actions to move sheets to the top, up, down, or to the bottom;
- Calc's Insert, Delete, Rename and Hide sheet commands in the list's context menu, acting on
  exactly the right-clicked row or the picked sheets without changing the list's picks; Calc's
  sheet tabs keep their full menu;
- renaming several sheets in one dialog, with find and replace and every new name checked before
  anything changes;
- complete keyboard operation;
- one undo step per change, and respect for protected and read-only documents.

Sheet Manager is written and maintained by AI agents, and no person reviews the code. A change is
accepted on its tests and on CI against real LibreOffice builds on Linux and Windows. Changes are
independently reviewed where another agent's perspective adds confidence; every release PR gets a
review of all changes since the previous release. [AGENTS.md](AGENTS.md) holds the agents' rules
for this project. Before the first stable release and after substantial interface or workflow
changes, a person also tries the product; [RELEASING.md](RELEASING.md#human-release-testing)
describes that gate and how its results are tracked.

## Requirements

- LibreOffice **26.2.1 or later**. Earlier versions are refused at installation: they cannot keep a
  selection of several sheets while it is dragged.
- LibreOffice's Python support. Builds from libreoffice.org include it. On Linux distributions it
  can be a separate package, such as `python3-uno` on Debian and Ubuntu or `libreoffice-pyuno` on
  Fedora and openSUSE.

<!-- #region environments -->

| Environment                                                                       | Status                                             |
| --------------------------------------------------------------------------------- | -------------------------------------------------- |
| Linux x86-64, libreoffice.org 26.2.1.2, 26.2.6.3, and 26.8.2.2: headless and gtk3 | Verified in CI for every change                    |
| Windows x86-64, libreoffice.org 26.8.2.2: headless                                | Verified in CI for every change                    |
| Windows x86-64, libreoffice.org 26.8.2.2: a visible window with real input        | Checked on extension changes; not a required check |
| Other 26.2 and 26.8 releases, and later versions, from libreoffice.org            | Expected to work, not verified                     |
| Distribution packages, other interfaces such as kf6 or gtk4, Wayland, macOS       | Expected to work, not verified                     |
| Flatpak, Snap, and Arm builds                                                     | Expected to work, not verified                     |
| LibreOffice 26.2.0 and earlier                                                    | Unsupported: installation is refused               |
| LibreOffice without Python support                                                | Unsupported: the extension cannot run              |

<!-- #endregion environments -->

The gtk3 checks run under X11 in a virtual display. The visible Windows checks run on GitHub's
hosted Windows Server 2025 runners, on one 1024×768 desktop at 96 DPI with the en-US keyboard
layout, the `win` interface and no screen reader; they are not yet required for merging. If
Sheet Manager does not work somewhere it is expected to, please
[report it](CONTRIBUTING.md#report-a-defect).

## Install and update

Download an available `.oxt` package from
[Releases and test builds](https://viell-dev.github.io/slop-calc-sheet-manager/guide/releases), open it in
LibreOffice, and follow Tools ▸ Extension Manager's installation prompts. Restart LibreOffice if
asked, then open a Calc workbook and select the Sheet Manager deck in the sidebar. Each release
also includes an `.oxt.sha256` file for checking the download's SHA-256 hash.

Use Tools ▸ Extension Manager ▸ Check for Updates to find newer stable builds. The extension
checks the [stable feed](https://viell-dev.github.io/slop-calc-sheet-manager/updates/stable.xml)
through LibreOffice's own update mechanism; it does not make network requests when opening a
workbook. Updates requiring a newer LibreOffice cannot be installed on an older version.

Every published build, including test builds marked **Pre-release**, has a GitHub release with
an `.oxt` manual-install package and its checksum. Find test downloads on
[Releases and test builds](https://viell-dev.github.io/slop-calc-sheet-manager/guide/releases#test-builds).
Installing one keeps stable updates enabled; later test builds are downloaded manually.

Versions are **not full SemVer** because LibreOffice itself treats `0.1.0-rc.1` as newer than
`0.1.0`: the final would not be offered as an update, and manually installing it would be shown
as a downgrade. This is independent of the extension directory. We use increasing numeric
versions instead. GitHub's explicit **Pre-release** flag identifies test builds, and the release
title names their stage: alpha, beta, or release candidate, as in `0.1.0 beta (0.0.7)`, a beta for
0.1.0 whose own version is 0.0.7. Alpha builds do not reserve a final version or imply readiness.
No patch numbers are reserved, so `0.1.90` can be an ordinary stable patch. The
[version guide](https://viell-dev.github.io/slop-calc-sheet-manager/guide/releases#version-numbers)
explains the model; [RELEASING.md](RELEASING.md) gives the maintainer rules and evidence.

## Known issues

- Changes made outside the list are observed periodically, so they can appear after a short delay.
- With LibreOffice's gtk3 interface, a save moves keyboard focus from the sidebar to the sheet.
  Test builds up to 0.0.6 leave it there after Ctrl+S from the list; the development version
  gives it back to the list (#23).
- A change that may replace a sheet clears the list's selection conservatively. Large lists are
  rebuilt after changes, which can delay the active-sheet marker (#22).
- The sidebar header's `?` opens LibreOffice's unavailable help topic for this extension. Use
  **Sheet Manager Help** in the context menu for the project guide (#81).
- In LibreOffice 26.8.0 and 26.8.1, Calc's own Duplicate Sheet and Move or Copy Sheet copy
  formulas with relative sheet references incorrectly
  ([tdf#173608](https://bugs.documentfoundation.org/show_bug.cgi?id=173608)). LibreOffice 26.8.2
  fixes this. From 0.0.5, the list's menu leaves both commands to Calc's sheet tabs; test builds up
  to 0.0.4 offer them through **Sheet actions…**.
- Defects in LibreOffice that affect Sheet Manager, and how each is handled, are listed in
  [#33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33).

## Contributing, security, and licence

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to report a defect and how changes are made, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) what is expected of everyone who takes part. Report
vulnerabilities as [SECURITY.md](SECURITY.md) describes. Sheet Manager is released under the
[Mozilla Public License 2.0](LICENSE).
