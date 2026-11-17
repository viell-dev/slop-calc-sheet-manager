# Sheet Manager

A LibreOffice Calc extension that lists a workbook's sheets in the sidebar, top to bottom, so that
you can find, select, and rearrange them quickly, however many there are.

## Requirements

- LibreOffice **26.2.1 or later**. Earlier versions are refused at installation: they cannot keep a
  selection of several sheets while it is dragged.
- LibreOffice's Python support. Builds from libreoffice.org include it. On Linux distributions it
  can be a separate package, such as `python3-uno` on Debian and Ubuntu or `libreoffice-pyuno` on
  Fedora and openSUSE.

## Install and update

Download an available `.oxt` package from
[Releases and test builds](https://viell-dev.github.io/slop-calc-sheet-manager/guide/releases), open it in
LibreOffice, and follow Tools ▸ Extension Manager's installation prompts. Restart LibreOffice if
asked, then open a Calc workbook and select the Sheet Manager deck in the sidebar. Each release
also includes an `.oxt.sha256` file for checking the download's SHA-256 hash.

Sheet Manager is in beta towards its first stable release. GitHub marks test builds
**Pre-release**. Download later test builds manually. LibreOffice's Extension Manager checks
the [stable feed](https://viell-dev.github.io/slop-calc-sheet-manager/updates/stable.xml) through
its own update mechanism. See [Install, update, and remove][install] for update and removal steps.

## Try it

In a workbook with sheets ordered **Summary**, **Jan**, **Feb**, **Notes**:

1. In the Sheet Manager sidebar, click **Jan**, then Ctrl-click **Feb** to pick both.
2. Right-click either picked row and choose **Move to bottom**.
3. The order becomes **Summary**, **Notes**, **Jan**, **Feb**. One Undo restores the original order.

A click picks a sheet in the sidebar. Double-click or press Enter to view it in Calc. Sidebar
picks can differ from Calc's grouped tabs. See the [user guide][guide] for details.

## Features

Sheet Manager follows this window's Calc tab selection and shows grouped-editing feedback
separately from the list's own picks. It includes:

- every sheet in document order, kept in sync with changes from anywhere, with the active sheet,
  hidden sheets, tab colours, and protection shown;
- full-width rows: click to pick, double-click or Enter to view a sheet, and Ctrl/Shift to
  pick several;
- drag and drop of one or more selected sheets, with an insertion line and scrolling near the
  edges;
- top buttons and context-menu actions to move sheets to the top, up, down, or to the bottom;
- Calc's Insert, Delete, Rename and Hide sheet commands in the list's context menu, acting on
  exactly the right-clicked row or the picked sheets without changing the list's picks; Calc's
  sheet tabs keep their full menu;
- renaming several sheets in one dialog, with find and replace and every new name checked before
  anything changes;
- complete keyboard operation;
- one undo step for each extension-managed move, show or batch rename, and respect for
  protected and read-only documents.

## Compatibility

<!-- #region environments -->

| Environment                                                                       | Status                                             |
| --------------------------------------------------------------------------------- | -------------------------------------------------- |
| Linux x86-64, libreoffice.org 26.8.3.1: headless integration; gtk3/gen real input | Verified in routine CI for every change |
| Linux x86-64, libreoffice.org 26.2.1.2, 26.2.7.3, and 26.8.3.1: headless/gtk3 integration; gtk3/gen real input | Verified in manual CI; required by the manual release sweep |
| Windows x86-64, libreoffice.org 26.8.3.1: headless | Verified in manual CI; required by the manual release sweep |
| Windows x86-64, libreoffice.org 26.8.3.1: a visible window with real input | Verified in manual CI; required by the manual release sweep |
| macOS Intel, macOS 15, libreoffice.org 26.8.3.1: headless integration | Verified in manual CI; required by the manual release sweep |
| Other 26.2 and 26.8 releases, and later versions, from libreoffice.org            | Expected to work, not verified                     |
| Distribution packages, other interfaces such as kf6 or gtk4, Wayland, macOS GUI input | Expected to work, not verified                     |
| Flatpak, Snap, and Arm builds                                                     | Expected to work, not verified                     |
| LibreOffice 26.2.0 and earlier                                                    | Unsupported: installation is refused               |
| LibreOffice without Python support                                                | Unsupported: the extension cannot run              |

<!-- #endregion environments -->

The gtk3 checks run under X11 in a virtual display. The visible Windows checks run on GitHub's
hosted Windows Server 2025 runners, on one 1024×768 desktop at 96 DPI with the en-US keyboard
layout, the `win` interface and no screen reader. They are required in the release sweep, with
focused manual checks available for investigation. The Intel macOS checks cover headless packaged
integration and removal, without Aqua rendering or real OS input. Apple Silicon remains
unverified. The [known issues guide](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues)
describes separate screen-reader probes and their limits. If Sheet Manager does not work somewhere it
is expected to, please
[report it](CONTRIBUTING.md#report-a-defect).

## Known issues

Read [Compatibility and known issues](https://viell-dev.github.io/slop-calc-sheet-manager/guide/known-issues)
before choosing a build. It covers selection clearing, refresh delays, accessibility, and
LibreOffice defects with their workarounds and upgrade advice.
[#33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33) tracks dependency defects
and local handling.

## Status

See [Releases and test builds](https://viell-dev.github.io/slop-calc-sheet-manager/guide/releases)
for published downloads and their release stage, and the
[release tracker](https://github.com/viell-dev/slop-calc-sheet-manager/issues/93) for work towards
0.1.0. The [release procedure](RELEASING.md) defines readiness, including the agreed scope,
human usability testing, and resolution of release blockers.

Sheet Manager is written and maintained by AI agents, and no person reviews the code. A change is
accepted on its tests and current Linux CI. Broader Linux, Windows and macOS checks run in a manual
release sweep before publication. Changes are independently reviewed where another agent's
perspective adds confidence; every release PR gets a
review of all changes since the previous release. [AGENTS.md](AGENTS.md) holds the agents' rules
for this project. Before the first stable release and after substantial interface or workflow
changes, a person also tries the product; [RELEASING.md](RELEASING.md#human-release-testing)
describes that gate and how its results are tracked.

## Contributing, security, and licence

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to report a defect and how changes are made, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) what is expected of everyone who takes part. Report
vulnerabilities as [SECURITY.md](SECURITY.md) describes. Sheet Manager is released under the
[Mozilla Public License 2.0](LICENSE).

[guide]: https://viell-dev.github.io/slop-calc-sheet-manager/guide/use
[install]: https://viell-dev.github.io/slop-calc-sheet-manager/guide/install
