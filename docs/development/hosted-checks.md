# Hosted checks

These workflows run the repository's current checks on GitHub Actions. Use
[Native LibreOffice testing](./native-testing.md) for local commands and shared fixture and
shutdown rules. See the [verification map](../verification.md) for coverage and evidence limits.

## Routine CI

Every PR and push to `main` runs the two Python check versions, Documentation, and **Linux current**:
headless integration on the newest tested Linux build followed by GTK3/gen real-input tests under
Xvfb. The required **Routine CI** aggregate runs even after a dependency fails and refuses missing,
failed, cancelled or skipped work. Every checkout uses the exact event revision.

The Linux job captures each phase's combined console output in `test-results/ci/`, preserving
the runner's failure status through `tee`. It uploads `linux-current-headless` before input
starts, even when headless checks fail; input requires successful headless checks. The final
`linux-current` artifact also includes input output when available. The job retains its
45-minute limit. A hard timeout can prevent the final upload, so inspect the earlier artifact
as well as the job log and check annotations; missing evidence is not a pass.

## Release sweep

**Release sweep** (`.github/workflows/release-sweep.yml`) is manual release-preparation evidence.
It retains all three pinned Linux builds, headless and painted integration, GTK3/gen input, the
unsupported-version refusal, Windows headless integration, the complete Windows desktop suite,
and Intel macOS headless packaged integration and lifecycle.
Its **Full release sweep** aggregate requires every lane. Any test or shutdown failure fails the
job; artifacts are required, and no error message is an allowed crash.

Follow [Prepare and dry-run][prepare] for the weekly platform cadence, exact revision, required
release evidence, and the role of PR planning previews. Use the focused Windows and macOS
workflows below for investigation.

## Visible Windows desktop

The **Windows desktop** workflow (`.github/workflows/windows-desktop.yml`) runs real-input checks
in a visible Calc window on a GitHub-hosted `windows-2025` runner. The runner's job runs in the
active console session, where input reaches a visible LibreOffice, unlike an agent shell in
Windows session 0. The workflow installs the MSI pinned in `ci/libreoffice.json` with
`ci/install-windows.ps1`, builds the OXT with LibreOffice's Python, and runs
`tests/ui/run_windows_ui.py`: one private office with the `win` interface, a fresh profile with
Tip of the Day and the first-start dialog turned off, and the synthetic 80-sheet workbook
maximised to the desktop with the Sheet Manager deck shown. `tests/ui/winput.py` sends keys and
pointer input through Windows' `SendInput` with the same interface as the X11 helper, so the suite
runs the shared checks of `tests/ui/*_checks.py` and `rename_dialog.py` themselves rather than
copies, with `workbook.py`'s fixture and `check_loop.py`'s loop, and reads the results back
through public UNO as on Linux. Window and screen geometry are read from the live desktop;
nothing assumes the runner's present 1024×768 screen at 96 DPI.

The [verification map](../verification.md#the-visible-windows-desktop) identifies the shared
checks this workflow runs and the paths it does not cover. Its artifacts establish functional
behaviour on that desktop.

It runs by manual dispatch for focused investigation; the full release sweep runs all its checks
for release evidence. The manual `checks` input names checks to run, separated by spaces. Dispatch
it for a branch with
`gh workflow run windows-desktop.yml --ref <branch> -f checks="keys_stay_in_list wheel"`.

The `windows-desktop` artifact holds `ui-results.json`, with the desktop the run saw (session,
screen, DPI, keyboard layout), each check's result, and the office's exit status, forced shutdown
and crash dumps; `ui-win/checks.json`, with each check's evidence or traceback and its duration;
screenshots taken at menus, dialogs and drags; and the office log and the built OXT. A failed
check also leaves `failed-<check>.png`, and its entry in `checks.json` records the foreground
window, the pointer position and the office's visible top-level windows. On both platforms that
entry is written before the screenshot and desktop evidence are taken and held input is
released; a step that fails adds its traceback under `diagnostic_errors`, keeping the check's
own error and the remaining steps
([#190](https://github.com/viell-dev/slop-calc-sheet-manager/issues/190)). The job fails on a
failed check, an extension error in the office log, a nonzero exit, a forced shutdown, a fatal
message or a crash dump, as the integration runner does; only startup is retried.

Never run the suite on your own computer: its input goes to whatever has the focus.
`winput.WinInput` refuses to start unless `SHEET_MANAGER_REAL_DESKTOP=1` is set, which only the
workflow does, and the runner refuses session 0, a desktop it cannot open for input, and a
keyboard layout other than en-US.

See the [verification map](../verification.md#where-checks-run) for this desktop's evidence limits
and [Human release testing][human-testing] for the separate usability gate.

The release sweep's Windows jobs and the Windows desktop workflow verify a pinned MSI before
silently installing it; this installation script is for disposable CI runners, not a contributor's
existing installation.

## macOS packaged integration

The full release sweep requires **macOS Intel packaged integration**, using `macos-15-intel`
and the macOS pin. The manual **macOS integration** workflow (`.github/workflows/macos.yml`)
runs the same helper for focused investigation. Its first native result and limits are recorded
in [#145](https://github.com/viell-dev/slop-calc-sheet-manager/issues/145).

The helper requires a disposable GitHub macOS runner. It verifies the pinned official DMG,
mounts it read-only, copies the app into the job's temporary directory, and uses its own
`Contents/Resources/python` wrapper for PyUNO. It never installs in `/Applications` or changes
a contributor's existing installation. The existing integration runner supplies private profiles,
synthetic fixtures, lifecycle checks and shutdown assertions. The artifact includes interpreter,
version, installer and integration logs, plus new user diagnostic reports identifying that
private app. System-wide or delayed crash reports are not established by this collection.

Dispatch focused checks with `gh workflow run macos.yml --ref <branch>`, respecting the platform
[cadence above](#release-sweep). See the [verification map](../verification.md#where-checks-run)
for coverage and evidence limits.

Pass `-f theme_pick_probe=true` to investigate the initial theme pick from
[#160](https://github.com/viell-dev/slop-calc-sheet-manager/issues/160). This runs eight fixed
cases in fresh office profiles: original, observed, observed, original, repeated once.
Each repeats the normal panel/accessibility/adapter prefix. Every outcome is retained; an
initial-pick failure allows the remaining measurements but fails the command after all eight.
Unexpected failures and unclean shutdowns stop it. This investigation is marked explicitly in
the host/probe receipts and cannot replace integration, lifecycle or a full release sweep.

## Installer cache

GitHub Actions restores the exact digest for the Linux archive, Windows MSI or macOS DMG and
checks its SHA-256 before use. Only runs on `main` populate the shared cache, and the cache
contains only public installer files. A changed pin or an evicted entry takes the same bounded
download path.

[prepare]: https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md#prepare-and-dry-run
[human-testing]: https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md#human-release-testing
