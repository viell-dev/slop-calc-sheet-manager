# Contributing

Issues and pull requests from people and from agents are welcome. The project is maintained by AI
agents, as the [README](README.md#status) says, and its owner follows it through issue and pull
request descriptions rather than code, so write them for a reader who has not seen the code.
Agents maintaining the repository also follow [AGENTS.md](AGENTS.md). Everyone follows the
[code of conduct](CODE_OF_CONDUCT.md).

If an AI agent wrote or submitted your issue, pull request, or comment, say so at the start: which
agent, for whom, and whether a person reviewed it. The maintainers' own posts open with such a
note.

## Report a defect

Search the open and closed [issues](https://github.com/viell-dev/slop-calc-sheet-manager/issues)
first, then open one with the
[bug report form](https://github.com/viell-dev/slop-calc-sheet-manager/issues/new?template=bug.yml).
It asks for:

- the Sheet Manager version, from Tools ▸ Extension Manager, or the commit you built;
- LibreOffice's version information: in Help ▸ About, select **Copy Version Information**. It
  includes the operating system and the user interface (the "VCL" line, such as `win`, `gtk3`, or
  `kf6`);
- how LibreOffice was installed, such as from libreoffice.org or as a distribution package;
- the exact steps, from opening the workbook to the problem;
- what happened and what you expected;
- a workbook that shows it, made for the report: never attach a real workbook or a screenshot of
  one with private content.

Suggest an improvement to existing behaviour or a new capability with the other forms, and ask how
something works with the question form.
[#33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33) lists known defects in
LibreOffice that affect Sheet Manager. Report vulnerabilities privately, as
[SECURITY.md](SECURITY.md) describes.

Maintainers label each issue with one `Type:` label, at most one `Status:` label, and `Needs: Owner`
or `Needs: Human` when a particular person has to act. The labels and their meanings are in
[`.github/labels.json`](.github/labels.json).

## Set up

Use Python 3.12–3.14, Git, and Node.js for Pyright, at the version in `.nvmrc` that CI also
installs; `nvm use` or `fnm use` in the repository root selects it. Install Node before running
checks; the check command fails without it rather than allowing Pyright to download a runtime.
The extension has no third-party runtime dependencies. Development tools and UNO type stubs stay
in a project virtual environment; never install them into LibreOffice's Python. Docker Desktop
on Windows, or Docker Engine on Linux,
runs the official Linux LibreOffice builds in an isolated test environment.

Windows, in PowerShell 7 with a development Python installed:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
```

Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
```

LibreOffice's bundled Python is for integration tests. Some bundled builds cannot create a venv
(including Windows 26.8.1.1, which lacks `venvlauncher.exe`). On Windows with Docker Desktop and
no development Python or Node, run these commands from the repository root in PowerShell 7:

```powershell
docker build --file ci/checks.Dockerfile --tag sheet-manager-checks .
docker run --rm --network none --mount "type=bind,source=${PWD},target=/work" sheet-manager-checks
```

This uses digest-pinned Python 3.12.15 and Node images, the latter at the `.nvmrc` version, and
hash-pinned development tools. It writes caches, test output and `dist/` into the checkout; the
container is removed on exit. Rebuild the image after changing `requirements-dev.txt`. This checks
Linux semantics; CI also runs the complete check command on Windows in the Windows integration job.

## Checks

One command runs Ruff lint and format checks, Pyright, unit tests, and two builds whose bytes must
match. Pyright uses Python 3.12 semantics and strict checking, with limited exceptions at the
dynamic UNO boundary. The test stubs never ship in the extension.

Windows PowerShell 7:

```powershell
.\.venv\Scripts\python.exe tools/check.py
```

Linux:

```sh
.venv/bin/python tools/check.py
```

To build without installing development tools, run `python tools/build.py` (or
`& 'C:\Program Files\LibreOffice\program\python.exe' tools/build.py` on a Windows machine with
only LibreOffice's Python). This writes `dist/sheet-manager-0.0.9.oxt` and its `.oxt.sha256` file.
The version comes only from `extension/description.xml`. Packaging uses explicit file lists,
sorted ZIP members, fixed timestamps and permissions, LF text, and uncompressed members so that
different zlib versions cannot change the result. Add new shipped modules to the allowlist in
`tools/build.py` and to the package-content test.

## Tests

[docs/verification.md](docs/verification.md) maps each promise the extension makes to the checks
that verify it, where they run, and what they do not show. Update it in the same pull request as a
change to a promise or to its checks.

Unit tests need no LibreOffice and run as part of the checks. To run them alone:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

```sh
.venv/bin/python -m pytest
```

### Integration suites

The integration runner installs the built OXT into a fresh temporary profile and connects over a
unique local UNO pipe. It never attaches to an existing office or uses the normal LibreOffice
profile. Every workbook is synthetic and loaded visibly, even in a headless office. Logs, actual
versions, package inventories, performance measurements and results go into `test-results/` and
CI artifacts.

Feature suites are `tests/integration/test_*.py` modules with an
`exercise(context, desktop, directory, output)` entry point; the runner passes `headless=` when
accepted. They run in filename order, except suites with session-wide native state run last
(`LAST_SUITES` in `run.py`). They import the built OXT through zipimport, so a missing packaged
module fails integration. Keep suites additive and failure injection in test-only forwarding
adapters, never in the shipped extension.

The [verification map](docs/verification.md) owns current coverage and evidence limits, including
identity, recovery, performance, accessibility and real input. The
[reordering contract](docs/reordering.md) describes the panel/adapter boundary.
[RELEASING.md](RELEASING.md#verification-boundary) explains update testing and the live checks that
publication still requires.

When adding or changing fixtures:

- Close documents through `main_thread.close_document`, on LibreOffice's main thread. Release
  unrelated workbooks between cases while retaining the simultaneous windows a case needs.
- After Reload, wait for the replacement's `OnLoad`, drain queued native events and idles on the
  main thread, then reacquire the panel and establish a fresh baseline before input. Correct rows
  alone do not establish readiness; later native timers can still conservatively clear picks.
  Never weaken the identity checks to make an initialization race pass
  ([#88](https://github.com/viell-dev/slop-calc-sheet-manager/issues/88)).
- Use `Workbook.hold` for a held-press precondition: the tree's native selection precedes the
  list's mouse listener. Wait for the listener and its main-thread round trip before changing the
  workbook ([#134](https://github.com/viell-dev/slop-calc-sheet-manager/issues/134)).
- Keep profile and configuration changes isolated to the runner. Only startup is retried, up to
  three times; assertions and shutdown are never retried.

On Windows, build and test the installed LibreOffice with its bundled Python:

```powershell
$lo = 'C:\Program Files\LibreOffice\program'
& "$lo\python.exe" tools/build.py
& "$lo\python.exe" tests/integration/run.py --program $lo --oxt dist/sheet-manager-0.0.9.oxt
```

On Linux, when using an official TDF installation at `/opt/libreoffice26.8`:

```sh
python3 tools/build.py
/opt/libreoffice26.8/program/python tests/integration/run.py \
  --program /opt/libreoffice26.8/program --oxt dist/sheet-manager-0.0.9.oxt
```

Run the complete Linux matrix in Docker with these commands (PowerShell 7 and POSIX shells both
accept them; substitute the path to a working Python if `python` is unavailable):

```text
python tools/linux_integration.py minimum --sessions both
python tools/linux_integration.py current-26.2 --sessions both
python tools/linux_integration.py current-26.8 --sessions both
python tools/linux_integration.py unsupported
```

The helper builds `ci/Dockerfile`, verifies the repository-pinned TDF archive checksum, builds the
extension, and runs the container unprivileged with networking disabled. Source and the OXT are
mounted read-only; only `test-results/<lane>/` is writable on the host. On Linux, run as a non-root
user: the helper maps that user's UID/GID into the container so artifacts remain writable. The
container has a temporary home directory. It uses Xvfb and Openbox inside the container and
never mounts a host display socket. `--skip-build` reuses only an image matching the Dockerfile,
lane pin and host UID/GID; a missing or outdated image is rebuilt. `--sessions headless` (the
default), `--sessions gtk3`, and `--sessions both` select independent office sessions. Painted
gtk3 sessions save `deck.png`; `--screenshot` remains an alias for running both sessions when
`--sessions` is omitted. The `unsupported` lane asserts that
26.2.0 refuses installation for a dependency error and leaves the extension uninstalled.
Image changes retain older `sheet-manager-ci:<version>-<fingerprint>` tags locally; list them with
`docker image ls sheet-manager-ci` and remove obsolete tags explicitly with `docker image rm <tag>`
(including old unfingerprinted `sheet-manager-ci:<version>` tags, which are no longer reused).

Real mouse, wheel, and keyboard input needs a display, so the UI tests run only in Docker, with
separate gtk3 and gen sessions under Xvfb, driving XTEST:

```text
python tools/linux_integration.py minimum --ui
python tools/linux_integration.py current-26.8 --ui
```

The input helper disables keyboard repeat on its private Xvfb display. Otherwise, a client
descheduled between a flushed key press and release can turn an intended tap into several keys.
A real-input regression pauses for one second with Down pressed and still expects one cursor
step. These tests exercise explicit key events, not the operating system's timed repeat behavior.

Inside the container, `tests/ui/run_ui.py --check NAME` (repeatable) selects checks.
Results and screenshots are in `test-results/<lane>/ui-gtk3/` and `ui-gen/`.
Windows synthetic input bypasses key handlers and cannot start a native drag; use the
[visible Windows desktop](#visible-windows-desktop) workflow for those paths. Human usability
and additional platform observations follow [docs/manual-tests.md](docs/manual-tests.md).

To retain the synthetic performance workbooks for inspection, run the generator with the tested
office's bundled Python (set `$lo` to its `program` directory as above):

```powershell
& "$lo\python.exe" tests/integration/generate_workbooks.py --program $lo `
  --oxt dist/sheet-manager-0.0.9.oxt --output test-results/workbooks --sheets 200 1000
```

It uses a separate private profile and saves only the synthetic workbooks it creates.

### Failures and shutdown

Logs, actual office/Python versions, package inventory, and results are in `test-results/` and in
CI artifacts. The runner records the exit status of each office session and rejects nonzero exits,
forced shutdowns after a 30-second grace period, fatal-error messages, and LibreOffice's own crash
dumps, including during termination. It copies those dumps into the results as `crash-*.dmp`,
with the `dump.ini` that names the version and the last commands; on Windows a crashed office
exits with status 0, so the dump is the sign there
([#48](https://github.com/viell-dev/slop-calc-sheet-manager/issues/48)). Dumps from a startup
attempt that is retried are kept and listed as `office_startup_crash_dumps` without failing the
session. GitHub's Windows runners have CDB, though not on `PATH`. With `$dump` set to a dump's
path and `$cache` to a local symbol cache directory, this prints every thread's stack with TDF's
symbols:

```powershell
$cdb = 'C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe'
$symbols = "srv*$cache*https://dev-downloads.libreoffice.org/symstore/symbols;srv*$cache*https://msdl.microsoft.com/download/symbols"
& $cdb -z $dump -y $symbols -c '.ecxr; !analyze -v; ~* kp; q'
```

A document close that takes more than 60 seconds fails the session. After a stalled callback,
try no further closes or configuration restores: stop only the runner's own office. A terminate
request held for 30 seconds also fails and forces shutdown. The runner must produce failed results
instead of hanging or reporting success. The safeguards and investigations are in
[#47](https://github.com/viell-dev/slop-calc-sheet-manager/issues/47),
[#50](https://github.com/viell-dev/slop-calc-sheet-manager/issues/50), and
[#40](https://github.com/viell-dev/slop-calc-sheet-manager/issues/40).

The painted resize check repeats the initial request if a late maximize changes its geometry;
`resize-initial-*.json` retains requests and measurements
([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)). Keep the one-second delay
between opening and closing the Writer fixture to avoid its native teardown race
([#30](https://github.com/viell-dev/slop-calc-sheet-manager/issues/30)).
Windows CI and the Windows desktop workflow verify a pinned MSI before silently installing it;
this installation script is for disposable CI runners, not a contributor's existing installation.

`Linux (LibreOffice …)` jobs run the headless checks and `Linux gtk3 (LibreOffice …)` jobs the
painted checks and the real-input UI tests under Xvfb; both are required for merging. Every job
fails on any test or shutdown failure and uploads its artifacts; no error message is treated as an
allowed crash.

### Visible Windows desktop

The **Windows desktop** workflow (`.github/workflows/windows-desktop.yml`) runs real-input checks
in a visible Calc window on a GitHub-hosted `windows-2025` runner. The runner's job runs in the
active console session, where input reaches a visible LibreOffice, unlike an agent shell in
Windows session 0. The workflow installs the MSI pinned in `ci/libreoffice.json` with
`ci/install-windows.ps1`, builds the OXT with LibreOffice's Python, and runs
`tests/ui/run_windows_ui.py`: one private office with the `win` interface, a fresh profile with
Tip of the Day and the first-start dialog turned off, and the synthetic 80-sheet workbook
maximised to the desktop with the Sheet Manager deck shown. `tests/ui/winput.py` sends keys and
pointer input through Windows' `SendInput` with the same interface as the X11 helper, so the suite
runs the checks of `run_ui.py` and `rename_dialog.py` themselves rather than copies, and reads the
results back through public UNO as on Linux. Window and screen geometry are read from the live
desktop; nothing assumes the runner's present 1024×768 screen at 96 DPI.

The [verification map](docs/verification.md#the-visible-windows-desktop) identifies the shared
checks this workflow runs and the paths it does not cover. Its artifacts establish functional
behaviour on that desktop; they do not satisfy human usability testing.

It runs on pull requests that change `src/`, `extension/` (which includes release preparation,
since the version is there), `tests/ui/`, the integration helpers it shares, `tools/build.py`,
`ci/`, or the workflow itself, and by manual dispatch, whose `checks` input names checks to run,
separated by spaces. Dispatch it for a branch with
`gh workflow run windows-desktop.yml --ref <branch> -f checks="keys_stay_in_list wheel"`.

The `windows-desktop` artifact holds `ui-results.json`, with the desktop the run saw (session,
screen, DPI, keyboard layout), each check's result, and the office's exit status, forced shutdown
and crash dumps; `ui-win/checks.json`, with each check's evidence or traceback and its duration;
screenshots taken at menus, dialogs and drags; and the office log and the built OXT. A failed
check also leaves `failed-<check>.png`, and its entry in `checks.json` records the foreground
window, the pointer position and the office's visible top-level windows. The job fails on a failed
check, an extension error in the office log, a nonzero exit, a forced shutdown, a fatal message or
a crash dump, as the integration runner does; only startup is retried.

Never run the suite on your own computer: its input goes to whatever has the focus.
`winput.WinInput` refuses to start unless `SHEET_MANAGER_REAL_DESKTOP=1` is set, which only the
workflow does, and the runner refuses session 0, a desktop it cannot open for input, and a
keyboard layout other than en-US.

The workflow is not a required check yet. Its evidence is limited to Windows Server 2025, not
Windows 11; one 1024×768 desktop at 96 DPI with the en-US layout; the `win` interface; the
Windows pin of `ci/libreoffice.json`; and no screen reader or input method. Promote it, by moving
the job into `ci.yml` and adding its name to the main ruleset's required contexts, once at least
ten consecutive runs on pull requests have passed, with every failure in between classified from
its artifacts as a product defect rather than the harness or the runner, and while a run stays
within about fifteen minutes.

### Soak painted sessions

Run the **Painted gtk3 soak** workflow manually with `sessions` between 1 and 100 (default 20).
Each lane runs that many fresh gtk3 profiles with the extension and that many without it, retaining
per-session runner logs, office logs, results and debugger traces, plus a job summary. A failed
session, including unreadable or missing results, fails the job after all measurements finish.
The soak passes `--suites none` to skip feature suites and their performance workbooks within its
180-second per-session limit; ordinary integration runs keep all feature suites enabled. Feature
suites never run in the absent-extension control. The soak disables startup retries too, so
every attempted session contributes to the measurement. The absent-extension control repeats the
Calc/save/reopen-read-only/Writer lifecycle and frame requests, but cannot exercise the panel or
its disposal. It is a control, not equivalent extension coverage.

Dispatch the soak on the branch to measure:

```text
gh workflow run gtk3-soak.yml --ref <branch> -f sessions=20
```

Locally, use `python tools/linux_integration.py minimum --sessions gtk3 --soak 20 --backtrace`.
The test image includes `gdb`; `--backtrace` starts LibreOffice's own debugger wrapper and preserves
its `gdbtrace.log` under each session's output directory. The recorded process exit is the wrapper's
exit in this mode, so the runner also rejects debugger signal/nonzero-inferior-exit markers,
missing traces and incomplete exits. Debugging can change timing, and a clean soak does not rule
out an intermittent crash. No host ptrace capability or relaxed container security is required.
Before UNO is exposed, the debugger path handles one normal profile-initialization restart
(LibreOffice exit 81), as the normal launcher does, and preserves its trace separately. A signal,
fatal marker or different nonzero exit never qualifies; test assertions and shutdown are not retried.

`ci/libreoffice.json` pins the minimum 26.2.1 build, the newest tested 26.2 and 26.8 builds, the
unsupported 26.2.0 build, and Windows. When updating a lane, verify the current TDF catalogue and
published SHA-256, update the version, URL and digest together, and run that lane. Always use
`https://downloadarchive.documentfoundation.org/libreoffice/old/<full version>/` and the full
four-part version in filenames: `stable/` downloads disappear when the offered releases change.
These pins do not discover newer releases automatically. Dependabot checks development tools,
GitHub-owned actions and Docker base images weekly after a seven-day cooldown. Action references
remain full commit SHAs, with their versions in comments. The checks image's two base images are
held on purpose. Python stays on 3.12, the oldest supported version, so Dependabot proposes only
3.12 patch releases and digest refreshes for it. Node stays on its current major version, so
Dependabot proposes newer Node 24 releases and digest refreshes but not Node 26. The workflows
install Node separately from `.nvmrc`, which Dependabot cannot change: a pull request that moves
the Node image to a new version must also change `.nvmrc`, so that local and CI checks use the
same Node, and a unit test fails until they match. That test accepts setup-node steps only as
`actions/setup-node@<commit SHA>`, with the action's lowercase input names and no expressions in
keys or `uses`. Moving to a new major version of Python or Node is a deliberate change made by
hand.

## Documentation

The user guide is in `docs/` and is built with VitePress, whose exact version `package.json` pins.
It is published on [GitHub Pages](https://viell-dev.github.io/slop-calc-sheet-manager/) together
with the update feeds. To work on it, select the Node.js version in `.nvmrc` (`nvm use` or
`fnm use`), then run:

```sh
npm ci
npm run docs:dev
```

`npm run docs:build` builds it as CI does; a broken link between pages fails the build.
`python tools/check_release_page.py` also builds empty and synthetic release histories, checking
channel separation, version order, rendered OXT/checksum links, and markers beside instructions
that are not published yet. It covers preparation with old history, publication, and an older
stable release alongside a newer test build, in the required docs job.
Its disposable build output uses the operating system's temporary directory; it never publishes
a build.
Some Windows security policies block the native module that VitePress's bundler loads. Then build in a
container, from the repository root in PowerShell 7, and find the site in `test-results/docs/`:

```powershell
New-Item -ItemType Directory -Force test-results/docs | Out-Null
docker run --rm --env "SHEET_MANAGER_DOCS_COMMIT=$(git rev-parse HEAD)" `
  --mount "type=bind,source=${PWD},target=/src,readonly" `
  --mount "type=bind,source=${PWD}/test-results/docs,target=/out" node:24.21.0-bookworm-slim `
  bash -c 'cp -r /src /build && cd /build && rm -rf node_modules && npm ci && npm run docs:build && cp -r docs/.vitepress/dist/. /out/'
```

Write for users of the extension. A user-visible change updates the guide in the same pull
request. Mark new behaviour where it appears with an inline `<Unreleased />` inside its paragraph
(for example, `Move buttons: <Unreleased /> ...`). When preparing its release, set
`<Unreleased since="VERSION" />` to the first numeric version containing it; keep that marker
in the source. The site shows **Unreleased** until published history reaches that version in the
latest stable release, or the newest test build before any stable release. A source version,
tag, or draft does not establish availability. An abandoned preparation keeps its markers.
Documentation-only corrections use the same build and synthetic-history checks and deploy from
`main` without changing a software version or tag; verify the deployed notice's source commit.
Every page is listed in the sidebar in `docs/.vitepress/config.mts`, and
`tests/unit/test_consistency.py` checks the sidebar and the facts that the README, the guide,
and the extension's metadata share.

## Pull requests

Every change to `main` goes through a pull request with passing checks and is merged with a merge
commit. Contributions are made under the [Mozilla Public License 2.0](LICENSE).

- Describe the problem, the resulting behaviour, and the decisions made and why, for a reader who
  will not read the diff. Link the issue.
- Add a "Verification" section: the commands run, the inputs tried beyond the tests, the
  platforms and LibreOffice versions checked, and any behaviour you broke on purpose to show that
  a check catches it. Maintainers add how the change was reviewed, as
  [AGENTS.md](AGENTS.md#review) describes.
- Update every document, test, and setting that describes what you changed, in the same pull
  request, and add the change to the `Unreleased` section of [CHANGELOG.md](CHANGELOG.md).
- Keep changes scoped, and state remaining limits.
