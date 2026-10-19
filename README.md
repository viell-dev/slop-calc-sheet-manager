# Sheet Manager

A LibreOffice Calc extension that lists a workbook's sheets in the sidebar, top to bottom, so that
you can find, select, and rearrange them quickly, however many there are.

The sheet tab bar at the bottom of Calc is small and scrolls one tab at a time. Moving a sheet
across dozens of others means a long, precise drag, and the alternative, the Move or Copy Sheet
dialog, is buried in a menu. Sheet Manager puts every sheet in one vertical list, as browsers do
with vertical tabs, where any selection of sheets moves any distance in one drag or one click.

## Status

Under development; there is no release yet. The first release, 0.1.0, is planned to offer:

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
accepted on its tests, on CI on Linux and Windows, on an independent review by an agent from a
different model provider than the one that wrote it, and, before a release, on checks on real
desktops. [AGENTS.md](AGENTS.md) holds the agents' rules that are specific to this project.

## Requirements

- LibreOffice **26.2.1 or later**. Earlier versions are refused at installation: they cannot keep a
  selection of several sheets while it is dragged.
- LibreOffice's Python support. Builds from libreoffice.org include it. On Linux distributions it
  can be a separate package, such as `python3-uno` on Debian and Ubuntu or `libreoffice-pyuno` on
  Fedora and openSUSE.
- Windows and Linux are tested. macOS, Qt/KDE desktops, Flatpak, and Snap are expected to work but
  have not been verified yet.

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

Testers can download releases marked **Pre-release** directly. Their plain numeric version is
lower than the final release they test: for example, `0.0.90` tests `0.1.0`. Installing one keeps
stable updates enabled; it does not subscribe to later candidates. Find those on GitHub Releases
or in the [prerelease feed](https://viell-dev.github.io/slop-calc-sheet-manager/updates/prerelease.xml),
which lists every published build, including stable releases. See [RELEASING.md](RELEASING.md)
for the release procedure and version rules.

## Known issues

- In LibreOffice 26.8.0 and 26.8.1, Duplicate Sheet and Move or Copy Sheet copy formulas with
  relative sheet references incorrectly
  ([tdf#173608](https://bugs.documentfoundation.org/show_bug.cgi?id=173608)); 26.8.2 fixes it.
  These commands are LibreOffice's own and behave the same whether started from the tab bar or from
  Sheet Manager.

## Contributing, security, and licence

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to report a defect and how changes are made, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) what is expected of everyone who takes part. Report
vulnerabilities as [SECURITY.md](SECURITY.md) describes. Sheet Manager is released under the
[Mozilla Public License 2.0](LICENSE).
