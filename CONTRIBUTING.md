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
only LibreOffice's Python). This writes `dist/sheet-manager-0.0.1.oxt` and its `.oxt.sha256` file.
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

Release tests cover version ordering, candidate policy, changelog extraction, and update feeds.
The integration runner also sends generated loopback HTTP feeds through LibreOffice's update
parser and checks candidate compatibility through its deployment API. The update dialog itself
has no public headless offered-update API; see [RELEASING.md](RELEASING.md#verification-boundary)
for the tested boundary and the remaining gap. Release dry runs and publication follow
[RELEASING.md](RELEASING.md).

The reorder suite exhausts all permutations through seven sheets and all scenario partitions and
block orders through seven. It checks the minimum call count against an independent
longest-common-subsequence oracle. The panel-facing contract is in
[docs/reordering.md](docs/reordering.md).

The runner also discovers `tests/integration/test_*.py` modules with an
`exercise(context, desktop, directory, output)` entry point. These suites import the built OXT's
modules through zipimport, so allowlist omissions fail integration. Keep feature suites additive
and keep failure injection in test-only forwarding adapters. Reorder checks cover active-sheet
and native selection preservation, one undo and redo, permission refusals, stale handles, hidden
sheets, scenario ownership, failures after each real mutation, and a silently ineffective undo.
The failure suite also runs with two configured undo steps, forcing nested groups, and checks zero
and one-step settings. Full-stack tests put both native and extension moves above 99 inputs and
fail before mutation, checking that recovery never undoes either preceding move. View-restoration
failures preserve verified move/rollback outcomes and report a separate warning. All configuration
changes belong to the runner's private profile. Pure planning has a five-second regression budget
at 10,000 sheets for both one-call and reverse-order plans.

The reorder suite generates 200- and 1,000-sheet workbooks with a cross-sheet formula and named
range per sheet plus charts referencing distant sheets. It measures first-sheet, half-selection,
all-but-last, and alternating-selection moves to the bottom, three times each, and verifies direct
references before and after undo. `reorder-performance-<session>.json` records median milliseconds. Move
timing includes snapshot, planning, preflight, application, and final verification; undo timing
covers Calc's undo call, followed by separate integrity assertions. Workbooks use only synthetic
data and stay in memory; the benchmark does not save workbook files.

To retain copies for inspection, run the generator with the tested office's bundled Python:

```powershell
& "$lo\python.exe" tests/integration/generate_workbooks.py --program $lo `
  --oxt dist/sheet-manager-0.0.1.oxt --output test-results/workbooks --sheets 200 1000
```

The generator uses a separate private profile and saves only its newly created synthetic workbooks.

The integration runner installs the built OXT into a fresh temporary profile, connects over a
unique local UNO pipe, and checks the factory, tab-control peer, exact panel resizing and disposal,
read-only Calc documents, Writer exclusion, and SVG decoding. Painted gtk3 sessions also press
real Shift, Ctrl, and Alt keys with `xdotool` while the panel is shown. Every workbook is synthetic
and loaded visibly, even when the office process itself is headless. It retries only startup, up to
three times, to tolerate a Windows crash just after connecting. It never attaches to an existing
office or uses the normal LibreOffice profile.

Once per run that includes a headless session, with the extension installed and all suites
enabled, the runner also checks the extension's lifecycle in a profile of its own:

1. It installs the OXT with `unopkg`.
2. It converts a synthetic CSV file with `soffice --headless --convert-to ods`, with the extension
   installed.
3. It confirms the deck and the panel factory in a new office.
4. It removes the extension.
5. It confirms that a new office has neither. It also confirms that no installed copy is left
   outside LibreOffice's own staging area, `user/extensions/tmp`. A copy is found by its
   description naming the extension's identifier, whatever its file name, and the same search must
   find the copy before removal.

Its logs are in `lifecycle/` in the runner's output directory, `test-results/<lane>/` for the
Linux lanes.

On Windows, build and test the installed LibreOffice with its bundled Python:

```powershell
$lo = 'C:\Program Files\LibreOffice\program'
& "$lo\python.exe" tools/build.py
& "$lo\python.exe" tests/integration/run.py --program $lo --oxt dist/sheet-manager-0.0.1.oxt
```

On Linux, when using an official TDF installation at `/opt/libreoffice26.8`:

```sh
python3 tools/build.py
/opt/libreoffice26.8/program/python tests/integration/run.py \
  --program /opt/libreoffice26.8/program --oxt dist/sheet-manager-0.0.1.oxt
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

Logs, actual office/Python versions, package inventory, and results are in `test-results/` and in
CI artifacts. The runner records the exit status of each office session and rejects nonzero exits,
forced shutdowns after a 30-second grace period, fatal-error messages, and LibreOffice's own crash
dumps, including during termination. It copies those dumps into the results as `crash-*.dmp`,
with the `dump.ini` that names the version and the last commands; on Windows a crashed office
exits with status 0, so the dump is the sign there
([#48](https://github.com/viell-dev/slop-calc-sheet-manager/issues/48)). Dumps from a startup
attempt that is retried are kept and listed as `office_startup_crash_dumps` without failing the
session. On Windows the tests close Calc documents on LibreOffice's main thread, as its user
interface does: closing one from the test's own thread crashed LibreOffice when a toolbar update
was pending
([#47](https://github.com/viell-dev/slop-calc-sheet-manager/issues/47)). If such a close does not
finish within 60 seconds, the session fails, no further close is tried, and the runner stops its
own office instead of asking it to terminate
([#50](https://github.com/viell-dev/slop-calc-sheet-manager/issues/50)). A terminate request that
does not return within 30 seconds, for example because a painted office asks whether to save a
workbook that a failed check left open, also ends in a forced shutdown and a failed session,
rather than a run that hangs until the job's time limit
([#40](https://github.com/viell-dev/slop-calc-sheet-manager/issues/40)). The painted resize check
repeats its initial geometry request when the new window is maximized after it, and records every
request and measurement in `resize-initial-*.json`
([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)). The intermittent gtk3
abort of [issue #8](https://github.com/viell-dev/slop-calc-sheet-manager/issues/8) was a
LibreOffice crash when a test closed Writer within milliseconds of opening it
([#30](https://github.com/viell-dev/slop-calc-sheet-manager/issues/30)); the runner now waits a
second before closing Writer.
Windows CI verifies a pinned MSI before silently installing it; this installation script is for
disposable CI runners, not a contributor's existing installation.

`Linux (LibreOffice …)` jobs run the headless checks and `Linux gtk3 (LibreOffice …)` jobs the
painted checks under Xvfb; both are required for merging. Every job fails on any test or shutdown
failure and uploads its artifacts; no error message is treated as an allowed crash.

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

Once `gtk3-soak.yml` exists on the default branch, dispatch it on the branch to measure:

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
