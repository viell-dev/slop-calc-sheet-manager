# Native LibreOffice testing

Use these procedures for the repository's current integration and real-input runners. Follow
[contributor setup][setup] before running checks. The [verification map](../verification.md)
records coverage and limits.

## Integration suites

The integration runner installs the built OXT into a fresh temporary profile and connects over a
unique local UNO pipe. It never attaches to an existing office or uses the normal LibreOffice
profile. Stop only office processes started by the runner. Every workbook is synthetic. Load
workbooks visibly for native assertions, even in a headless office. Logs, actual versions,
package inventories, performance measurements and results go into `test-results/` and CI artifacts.

Feature suites are `tests/integration/test_*.py` modules with an
`exercise(context, desktop, directory, output)` entry point; the runner passes `headless=` when
accepted. They run in filename order, except suites with session-wide native state run last
(`LAST_SUITES` in `run.py`). They import the built OXT through zipimport, so a missing packaged
module fails integration. Keep suites additive and failure injection in test-only forwarding
adapters, never in the shipped extension.

The [verification map](../verification.md) owns current coverage and evidence limits, including
identity, recovery, performance, accessibility and real input. The
[reordering contract](../reordering.md) describes the panel/adapter boundary.
[Release verification][release-verification] explains update testing and the live checks before
and after publication.

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

## Installed LibreOffice

In the commands below and in [Inspection workbooks](#inspection-workbooks), substitute the OXT
filename printed by the build for `sheet-manager-VERSION.oxt`.

On Windows, build and test the installed LibreOffice with its bundled Python:

```powershell
$lo = 'C:\Program Files\LibreOffice\program'
& "$lo\python.exe" tools/build.py
& "$lo\python.exe" tests/integration/run.py --program $lo --oxt dist/sheet-manager-VERSION.oxt
```

On Linux, when using an official TDF installation at `/opt/libreoffice26.8`:

```sh
python3 tools/build.py
/opt/libreoffice26.8/program/python tests/integration/run.py \
  --program /opt/libreoffice26.8/program --oxt dist/sheet-manager-VERSION.oxt
```

Each session first installs the OXT into its fresh profile, which normally takes a few seconds and
is recorded as `install_seconds` in `results.json`. On a computer whose processors or memory are
taken up by other work, such as several office test runs at once, the installation can exceed its
90-second limit and fail the run before any suite starts. Compare its `install_seconds` and the
computer's load with a normal installation, and run again once the computer is less busy
([#235](https://github.com/viell-dev/slop-calc-sheet-manager/issues/235)).

## Linux Docker lab

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
user against a rootful Docker daemon without `userns-remap`: the helper maps the host user's
UID/GID directly into the container so artifacts remain writable. For a rootless or remapped
daemon, select a compatible context with `docker context ls` and `docker context use`. Docker
Desktop on Windows is supported. The container has a temporary home directory. It uses Xvfb
and Openbox inside the container and never mounts a host display socket. `--skip-build` reuses
only an image matching the Dockerfile, lane pin and host UID/GID. A missing or outdated image is
rebuilt. `--sessions headless` (the
default), `--sessions gtk3`, and `--sessions both` select independent office sessions. Painted
gtk3 sessions save `deck.png`; `--screenshot` remains an alias for running both sessions when
`--sessions` is omitted. The `unsupported` lane asserts that
26.2.0 refuses installation for a dependency error and leaves the extension uninstalled.

The Linux helper needs curl 7.71 or newer and Docker with BuildKit. It keeps each verified
archive under `.cache/libreoffice-packages/<sha256>/` and supplies it to the build in a read-only
context. On a miss, curl tries TDF's stable mirror network when the archive pin names a versioned
build, then falls back to the archive if that route cannot supply the exact bytes. Both routes
require HTTPS with certificate verification and share the download budget. The archive route
allows at most three retries, including after a redirected mirror's certificate failure. An
exhausted download or checksum mismatch on the final source fails setup. Remove the affected
cache file before retrying a corrupt local entry. See [Hosted checks](./hosted-checks.md#installer-cache)
for GitHub Actions caching.

Image changes retain older `sheet-manager-ci:<version>-<fingerprint>` tags locally; list them with
`docker image ls sheet-manager-ci` and remove obsolete tags explicitly with `docker image rm <tag>`
(including old unfingerprinted `sheet-manager-ci:<version>` tags, which are no longer reused).

## Linux real input

Real mouse, wheel, and keyboard input on Linux needs a display. Run these tests in Docker, with
separate gtk3 and gen sessions under Xvfb, driving XTEST:

```text
python tools/linux_integration.py minimum --ui
python tools/linux_integration.py current-26.8 --ui
```

These private UI profiles enable LibreOffice's built-in Light theme, including the native
disabled-button rendering path behind [#166](https://github.com/viell-dev/slop-calc-sheet-manager/issues/166).

The input helper disables keyboard repeat on its private Xvfb display. Otherwise, a client
descheduled between a flushed key press and release can turn an intended tap into several keys.
A real-input regression pauses for one second with Down pressed and still expects one cursor
step. These tests exercise explicit key events, not the operating system's timed repeat behavior.

Inside the container, `tests/ui/run_ui.py --check NAME` (repeatable) selects checks.
`run_ui.py` lists the checks in order; they live in `tests/ui/*_checks.py` by subject, with the
shared workbook fixture and its rules in `workbook.py`.
Results and screenshots are in `test-results/<lane>/ui-gtk3/` and `ui-gen/`.
Windows synthetic input bypasses key handlers and cannot start a native drag; use the
[visible Windows desktop](./hosted-checks.md#visible-windows-desktop) workflow for those paths.
See [Optional desktop observations](../manual-tests.md) for human usability and additional
platform observations.

## Inspection workbooks

To retain the synthetic performance workbooks for inspection, run the generator with the tested
office's bundled Python (set `$lo` to its `program` directory as above):

```powershell
& "$lo\python.exe" tests/integration/generate_workbooks.py --program $lo `
  --oxt dist/sheet-manager-VERSION.oxt --output test-results/workbooks --sheets 200 1000
```

It uses a separate private profile and saves only the synthetic workbooks it creates.

## Failures and shutdown

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

Each installation with `unopkg add` has 90 seconds. Every results entry that installs the package
records `install_seconds`, one value per startup attempt; GitHub's runners install it in two to six
seconds on Linux, Windows and macOS. An installation that takes longer fails the session with
`install_timed_out` and the elapsed time in its entry, and with `failure_stage` set to `install`
([#235](https://github.com/viell-dev/slop-calc-sheet-manager/issues/235)).

A document close that takes more than 60 seconds fails the session. After a stalled callback,
try no further closes or configuration restores: stop only the runner's own office. Graceful
shutdown has 30 seconds in all, shared by the release wait below, the terminate request and the
office's exit: a request still held, or an office still running, when they run out fails the
session and forces shutdown. The runner must produce failed results instead of hanging or
reporting success. The safeguards and investigations are in
[#47](https://github.com/viell-dev/slop-calc-sheet-manager/issues/47),
[#50](https://github.com/viell-dev/slop-calc-sheet-manager/issues/50), and
[#40](https://github.com/viell-dev/slop-calc-sheet-manager/issues/40).

When the runner stops its office itself (`stop_process`), as in a forced shutdown, after an
unfinished release wait or after a stall, it sends the launcher it started SIGTERM, then SIGKILL
after 10 seconds; on Windows, `taskkill /T` stops the launcher's whole process tree instead. On
Linux, LibreOffice's `oosplash` launcher passes SIGTERM on to its `soffice.bin` and waits for it,
and the gdb wrapper's `soffice.bin` died with gdb even when gdb was killed. But a `soffice.bin`
kept running after an `oosplash` that was killed, and after one that was told to stop just after
it had started a `soffice.bin` and before it had taken it over, as at its first-start restart
([#266](https://github.com/viell-dev/slop-calc-sheet-manager/issues/266)). So on Linux the
runner first pauses the launcher, holds each `soffice.bin` beneath it and each of the launcher's
own child processes, then sends the launcher SIGTERM and lets it continue. Each held process
still running when the launcher's stop ends is sent SIGTERM, then SIGKILL after 5 seconds. A
forced shutdown's results, and a stall's receipt, record what the stop saw of each as
`office_stop`.

Before asking the office to terminate, the runner waits until the office has run the UNO
releases the test process sent before the wait, as `tests/integration/client_releases.py`
describes. LibreOffice runs releases in order on one bridge thread that no other call waits for,
so a check that drops many sheet handles just before the session ends can leave them running
during shutdown. An office that exits meanwhile can crash in a `cppu_threadpool` thread, in
`cppu::getCaughtException`, with or without the extension
([#242](https://github.com/viell-dev/slop-calc-sheet-manager/issues/242)). Releases sent during
the wait are not covered. A session normally ends with no documents open, but a document that a
failed check left open can still call the test process's listeners, which can send more. A wait
that does not finish in time, or whose bridge disconnected, stops the launcher the runner started
(its whole process tree on Windows) and fails the session with the unfinished step in
`office_unsettled_releases`. `office_release_wait_seconds`
and `office_shutdown_seconds` record how long the wait and the whole shutdown took. After a
stalled callback, including a stall below, neither the wait nor the terminate request is sent.

A session that reports no progress for 15 minutes from its launch, because a UNO call never
returned, fails and is never retried. Suites, checks, and the benchmarks' workbooks and repetitions
count as progress; each session records its `longest_progress_interval_seconds`. The runner first
records the stall, as a stalled callback and in a `stall-*.json` receipt, so no close through the
shared close helpers, settings restore, release wait or terminate request starts afterwards. On
Windows that includes a close the shared helper posted to the main thread before the stall: it
checks again when the main thread reaches it, and the helper then fails as after any stall
([#261](https://github.com/viell-dev/slop-calc-sheet-manager/issues/261)). The test's other
calls, and any already under way, continue until the office stops: among them a close the main
thread had already started, and an Escape tap of the update dialog's cleanup, which checks for a
stall before each tap. For up to 60 seconds the
runner then tries to save the client's Python stacks and the office's native stacks as `stall-*`
files; a step or result that arrives later is not recorded. It starts stopping the launcher it
started (`stop_process`, above) when those steps end or when the 60 seconds end, even if the
test client, a debugger or a receipt write is still blocked, and the stop itself is bounded by
its own limits, about 60 seconds more. Under
`--backtrace` the runner sends the gdb wrapper's `soffice.bin` SIGINT, after which gdb normally
prints every thread's stack into its trace; on Windows, CDB at its standard path writes them.
Without the wrapper no debugger attaches on Linux, and macOS has no debugger in this path, so only
the client's stacks are tried there
([#45](https://github.com/viell-dev/slop-calc-sheet-manager/issues/45)). Only a `soffice.bin`
still identified as the session's own is examined; on Linux that includes its launcher, so after
the gdb wrapper's startup restart has replaced it, the first launcher's tree is not read. The
session waits for the watch, bounded, before it shuts down, so shutdown is never watched; a
stalled session then skips the release wait and the terminate request as after any stalled
callback, and stops its launcher at once if it is still running, instead of giving graceful
shutdown its 30 seconds.
`SHEET_MANAGER_STALL_SECONDS` lowers the limit to try this, and `SHEET_MANAGER_DEADLINE_SECONDS`
ends a run that many seconds after its start the same way; `tools/linux_integration.py` passes
both into the container. Neither is a test timeout.

The receipt and the session's `office_progress_stall` record what the watch did and saw, not
what follows from it:

- `cause` is `no progress` or `deadline`. `limit_seconds` is the no-progress limit in force, and
  `idle_seconds` the time since the last progress when the watch recorded the stall.
  `launcher_pid` is the process ID of the launcher the watch was watching then: after the gdb
  wrapper's startup restart, the replacement's. `receipt` names the receipt file itself.
- `client_stacks` and each `office_stacks` entry's `file` name the files the watch wrote. An
  entry's `method` says what was tried for that process, such as CDB's exit status or the SIGINT
  sent to the gdb wrapper's inferior. A sent SIGINT is not saved stacks: the stacks are those in
  the session's `gdbtrace-*.log`, if gdb printed them. `wrapper_exit_status` is present only when
  the watch sent that SIGINT and then saw the gdb wrapper exit before the 60 seconds ended; a
  wrapper that exited without an interrupt being sent leaves no such field.
- `office_search` says what the process listing returned: no `soffice.bin` under the launcher, or
  that the listing was not used because the launcher's ID no longer names it, or because the watch
  took no identity for the launcher to compare. Neither shows that no office was running.
- `launcher_exit_status` is the launcher's exit status as `Popen.poll()` reported it after the
  stop, or `null` when it reported none. It is not the office's: a `soffice.bin` can outlive its
  launcher ([#266](https://github.com/viell-dev/slop-calc-sheet-manager/issues/266)).
  `stop_returned_after_seconds` is the time from detection until `stop_process` returned or
  raised.
- `office_stop`, on Linux, says what the stop saw of each process it held: that it had exited
  when the launcher's stop ended, or that it was still running then, which signals it was sent
  and when its exit was seen. It also says when nothing was held, and why, such as a listing that
  failed. It is absent when the launcher had already exited before the stop, as after the gdb
  wrapper's own exit following the interrupt.
- `diagnostic_errors` holds each step that failed, and under `capture` the step the collector was
  at when the 60 seconds ended; `collection_finished` is true only if every step returned before
  then.
- The receipt is rewritten as the evidence grows, and only the watch's last snapshot has
  `watch_finished`. A receipt without it is partial, as when the runner exited first; a write that
  failed is recorded as `receipt_error` in the session's `office_progress_stall`, which is the
  snapshot taken when the runner stopped waiting. `stall_wait_timed_out` marks a wait that ended
  before the watch finished.

An enclosing time limit can still end a stalled run before its stacks are saved and uploaded:
detection, the capture, the stop and the upload take up to about 18 minutes after the last
progress, depending on how long the capture and the upload take. The stacks of a stall that
begins later than that before a job's `timeout-minutes`, or before the macOS helper's 30-minute
integration command limit, may be lost at that limit. On recent runs this covers the second half
of every Linux real-input phase and most of the Windows integration job
([#244](https://github.com/viell-dev/slop-calc-sheet-manager/issues/244)). The soak, below,
gives each runner the soak's own limit as its deadline.

The painted resize check repeats the initial request if a late maximize changes its geometry;
`resize-initial-*.json` retains requests and measurements
([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)). Keep the one-second delay
between opening and closing the Writer fixture to avoid its native teardown race
([#30](https://github.com/viell-dev/slop-calc-sheet-manager/issues/30)).

## Soak painted sessions

Run the **Painted gtk3 soak** workflow manually with `sessions` between 1 and 100 (default 20).
Each lane runs that many fresh gtk3 profiles with the extension and that many without it, retaining
per-session runner logs, office logs, results and debugger traces, plus a job summary. A failed
session, including unreadable or missing results, fails the job after all measurements finish.
The soak passes `--suites none` to skip feature suites and their performance workbooks within its
180-second per-session limit; ordinary integration runs keep all feature suites enabled. A
session that the soak finds still running at that limit fails with status 124; one that exits
after it while the soak's own process is not scheduled reports its own status
([#244](https://github.com/viell-dev/slop-calc-sheet-manager/issues/244)). Its runner has the
same moment as its deadline, passed as an absolute time on the container's monotonic clock
(`SHEET_MANAGER_DEADLINE_MONOTONIC`), so the runner's own start-up cannot move it later. When the
limit falls during startup or the checks, the runner's stall watch records the stall, tries to
save stacks and stops the launcher it started; the soak waits 150 more seconds before it kills
the session's process group. Installation, before the office's launch, is not watched: when the
limit passes during an installation that then succeeds, the watch finds the deadline already
passed at the launch and records a startup stall, so the receipt shows when the watch found the
stall, not when the limit passed. The watch ends with the checks, so a limit reached while
shutting down records no stall; the session's `checks_ended_before_deadline` shows that its
checks ended in time. The summary gives each
session's runner status and what its `results.json` says, and names its directory, which holds
its results, runner log and any `stall-*.json` receipts. Before its first session, the soak
removes every numbered session directory (`<output>/<mode>/<NNN>`) that an earlier soak left, so
the output holds only this soak's sessions
([#268](https://github.com/viell-dev/slop-calc-sheet-manager/issues/268)). It removes nothing
else there, and unlinks a symbolic link in their place, or a mode directory that is one, without
following it. Feature suites never run in the
absent-extension control. The soak disables startup retries too, so every attempted session
contributes to the measurement. The absent-extension control repeats the
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

## Updating lab pins and tools

`ci/libreoffice.json` pins the minimum 26.2.1 build, the newest tested 26.2 and 26.8 builds, the
unsupported 26.2.0 build, Windows and Intel macOS. When updating a lane, verify the current TDF
catalogue and published SHA-256, update the version, URL and digest together, and run that lane.
Always use `https://downloadarchive.documentfoundation.org/libreoffice/old/<full version>/`
and the full four-part version in filenames: `stable/` downloads disappear when the offered
releases change.
The lab download allows 30 seconds to connect and four minutes per transfer, with retry starts
confined to the first minute. This bounds download setup to about five minutes so a slow mirror
cannot consume the routine job's 45-minute native testing budget. Its effective mirror and
transfer measurements are logged; TLS and the pinned SHA-256 remain required.
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

[setup]: https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/CONTRIBUTING.md#set-up
[release-verification]: https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md#verification-boundary
