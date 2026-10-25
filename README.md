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

Under development; there is no release yet. **Unreleased:** the development version lists the
workbook's sheets, supports selection, drag and drop, and four move buttons with keyboard shortcuts,
handles keyboard navigation, and opens Calc's sheet tab menu. Each extension move is one undo step.
The remaining synchronization work is tracked in #5. The first release, 0.1.0, is planned to offer:

- every sheet in document order, kept in sync with changes from anywhere, with the active sheet,
  hidden sheets, tab colours, and protection shown;
- click to go to a sheet, and Ctrl+click and Shift+click to select several, as on the tab bar;
- drag and drop of one or more selected sheets, with an insertion line and scrolling near the
  edges;
- buttons to move the selection to the top, up, down, or to the bottom;
- the sheet tab bar's own context menu, including your customizations of it;
- complete keyboard operation;
- one undo step per change, and respect for protected and read-only documents.

Sheet Manager is written and maintained by AI agents, and no person reviews the code. A change is
accepted on its tests and on CI against real LibreOffice builds on Linux and Windows. Changes are
independently reviewed where another agent's perspective adds confidence; every release PR gets a
review of all changes since the previous release. [AGENTS.md](AGENTS.md) holds the agents' rules
for this project.

## Requirements

- LibreOffice **26.2.1 or later**. Earlier versions are refused at installation: they cannot keep a
  selection of several sheets while it is dragged.
- LibreOffice's Python support. Builds from libreoffice.org include it. On Linux distributions it
  can be a separate package, such as `python3-uno` on Debian and Ubuntu or `libreoffice-pyuno` on
  Fedora and openSUSE.

<!-- #region environments -->

| Environment                                                                       | Status                                 |
| --------------------------------------------------------------------------------- | -------------------------------------- |
| Linux x86-64, libreoffice.org 26.2.1.2, 26.2.6.3, and 26.8.1.1: headless and gtk3 | Verified in CI for every change        |
| Windows x86-64, libreoffice.org 26.8.1.1: headless                                | Verified in CI for every change        |
| Other 26.2 and 26.8 releases, and later versions, from libreoffice.org            | Expected to work, not verified         |
| Distribution packages, other interfaces such as kf6 or gtk4, Wayland, macOS       | Expected to work, not verified         |
| Flatpak, Snap, Arm builds, and the Windows interface in a visible window          | Expected to work, not verified         |
| LibreOffice 26.2.0 and earlier                                                    | Unsupported: installation is refused   |
| LibreOffice without Python support                                                | Unsupported: the extension cannot run  |

<!-- #endregion environments -->

The gtk3 checks run under X11 in a virtual display. If Sheet Manager does not work somewhere it is
expected to, please [report it](CONTRIBUTING.md#report-a-defect).

## Install and update

No download is published yet. When releases are available, download the `.oxt` from
[GitHub Releases](https://github.com/viell-dev/slop-calc-sheet-manager/releases), open it in
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
versions below the final instead, such as `0.0.2`, `0.0.3`, then `0.1.0`. GitHub's explicit
**Pre-release** flag identifies test builds; no patch numbers are reserved, so `0.1.90` can be
an ordinary stable patch. The
[version guide](https://viell-dev.github.io/slop-calc-sheet-manager/guide/releases#version-numbers)
explains the model; [RELEASING.md](RELEASING.md) gives the maintainer rules and evidence.

## Known issues

- Tab-only selection changes reach the list at the next sheet switch; the list refreshes after
  other sheet changes.
- After Ctrl+S from the list, keyboard focus moves to the sheet (#23).
- A change that may replace a sheet clears the list's selection conservatively. Large lists are
  rebuilt after changes, which can delay the active-sheet marker (#22).
- The sheet tab menu runs LibreOffice's own Duplicate Sheet and Move or Copy
  Sheet. In LibreOffice 26.8.0 and 26.8.1 these commands copy formulas with relative sheet
  references incorrectly ([tdf#173608](https://bugs.documentfoundation.org/show_bug.cgi?id=173608)),
  whether they are started from the tab bar or from the menu. LibreOffice's fix is due in 26.8.2.
- Defects in LibreOffice that affect Sheet Manager, and how each is handled, are listed in
  [#33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33).

## Contributing, security, and licence

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to report a defect and how changes are made, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) what is expected of everyone who takes part. Report
vulnerabilities as [SECURITY.md](SECURITY.md) describes. Sheet Manager is released under the
[Mozilla Public License 2.0](LICENSE).
