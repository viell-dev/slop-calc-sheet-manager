"""Collect and validate private office process shutdown without a UNO dependency.

A UNO call that never returns blocks the test client until an enclosing time limit ends the run,
which then leaves no evidence. Integration and UI stalls of this kind were seen without native
stacks (#45). `StallWatch` therefore fails a session that reports no progress (`teardown`) for
`STALL_SECONDS` (15 minutes; `SHEET_MANAGER_STALL_SECONDS` overrides it), or that is still
running at the deadline an enclosing runner gives this process (`DEADLINE`), and then stops the
launcher it started through `stop_process`, on Windows with its whole process tree and on Linux
with each process held beneath it that outlives it, so that the blocked call fails: on Linux it
then failed with a disposed bridge under both launchers measured, the plain one and the gdb
wrapper. Rules for changing it:

- Closing the watch, progress, expiry and accepting the gdb wrapper's replacement office are one
  decision, under the watch's lock and `teardown`'s progress lock; nothing external, such as a
  launch or a file write, runs under the lock. A close after the deadline records the stall
  instead, so a watch that closed shows that the checks ended before it. When expiry wins, the
  stall is recorded as a stalled callback first, so no close or settings restore starts during
  the capture, and `assert_clean_shutdown` fails it whatever the capture does. A replacement
  refused after a stall is stopped before any UNO call to it.
- The session closes the watch before `end_office`, so shutdown is never watched. Because a
  stall is a stalled callback, `end_office` then sends neither `settle` nor the terminate
  request and stops the launcher at once if it still runs: the stall already fails the session,
  and an office whose calls stopped returning could hold either for graceful shutdown's whole
  grace (#50, #242).
- The watch runs from the office's launch. Installation, before it, is not watched: a deadline
  that passes then is found at the launch, which records a startup stall, so a receipt shows
  when the watch found a stall, not when the limit passed.
- One budget, `CAPTURE_SECONDS` from detection, ends at one absolute time. A collector thread
  waits for the first `stall-*.json` receipt, then tries to save the client's Python stacks and
  the office's native stacks, with debugger output streamed into its file; a step or result that
  arrives after the budget's end is never recorded. Each collector subprocess (CDB, the Windows
  process listing) is sent a kill at that time, or at once if starting it took longer. The
  watch's own thread starts the stop when the collector finishes or the budget ends, whatever the
  collector, the client or a receipt write is doing; a receipt thread is the receipt's only
  writer, so an older snapshot never replaces a newer one, and receipt I/O never delays the stop.
  A failed step, including a failed listing, is recorded beside the others, never read as an
  empty process tree. The session waits for the watch, bounded; a wait that ended first is
  recorded apart from the evidence (`wait_timed_out`).
- The evidence records what the watch did and saw in this session, never a conclusion drawn from
  it: the files it wrote, an interrupt it sent, a debugger's or the gdb wrapper's exit status,
  what a listing returned, whether the launcher had exited after the stop, and on Linux what the
  stop saw of each process it held (`office_stop`). An interrupt sent to
  the gdb wrapper's inferior is not saved stacks, since gdb may not print; a listing that finds no
  `soffice.bin` under the launcher does not show that none runs; the launcher's exit is not the
  office's. Only the watch's last snapshot has `watch_finished`; an earlier one is partial. The
  watch acts on what a step returns, never on the text it records: it waits for the gdb wrapper
  only when `native_stacks` reports that it sent the interrupt (`StackAttempt.interrupted`), so
  rewording a receipt's text changes no behaviour (#267).
- Native stacks are read only from a process still identified as this session's office: a
  `soffice.bin` descendant of the session's launcher that started no earlier than its parent
  (Windows keeps a dead parent's ID, which a newer process can reuse) and still has the start
  time it was listed with, checked while a Linux pidfd or Windows process handle holds it. On
  Linux the launcher's own start time is bound when the watch takes it, and a listing, empty or
  not, is used only if the launcher's ID still names that launcher after it: once the runner has
  reaped an exited launcher, such as the gdb wrapper's first one at its exit-81 restart, its
  number can pass to another process's tree. On Windows the session's `Popen` holds the
  launcher's handle, so its ID cannot be reused. On Linux only a `soffice.bin` traced by the gdb
  wrapper (`--backtrace`) is interrupted, through its pidfd. Without the wrapper no debugger
  attaches there: `gdb -p` takes a number, which a new process could have reused by the time it
  attaches, and containers refuse `ptrace` anyway. An uncertain target is skipped, with the
  reason recorded.
- On Linux `stop_process` pauses the launcher with SIGSTOP, holds a pidfd for each `soffice.bin`
  beneath it and for each of its own children, sends it SIGTERM, then SIGCONT, and stops each
  held process still running when the launcher's stop ends. Natively (26.8.2.2) `oosplash`
  passed SIGTERM on, and the gdb wrapper's inferior died with gdb even when gdb was killed, but a
  `soffice.bin` outlived an `oosplash` killed after 10 s, and one forked at the exit-81 restart
  outlived an `oosplash` stopped before it had recorded that fork (#266). `oosplash` forks from a
  helper thread (`osl_executeProcess`) while its main thread waits, and a fork under way when
  SIGSTOP arrives finishes before its own thread stops, so the listing waits until every thread
  of the launcher is seen stopped. Signal a process only through a pidfd taken while its identity
  is checked, never by its number alone: for the launcher, `waitid` confirms that the pidfd names
  this process's own unreaped child. `Popen.terminate` and `kill` on this process's own children,
  which signal by number once `poll()` finds the child unreaped, are the exception.
- The limit is not a test timeout, and never shorten it to speed up a run. The slowest measured
  suite took 649 s (Intel macOS `test_reorder`, #162), so the benchmarks also report progress at
  each workbook and repetition; each session records its `longest_progress_interval_seconds`.
- An enclosing limit that ends the run first still wins; `docs/development/native-testing.md`
  says where (#244).
"""

import faulthandler
import json
import math
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

FATAL_MARKERS = ("Unspecified Application Error", "Fatal exception")
STALL_SECONDS = float(os.environ.get("SHEET_MANAGER_STALL_SECONDS", "900"))


def enclosing_deadline(environment: Mapping[str, str]) -> float | None:
    """When an enclosing runner ends this process, on `time.monotonic()`'s clock, or None.

    The soak passes an absolute time (`SHEET_MANAGER_DEADLINE_MONOTONIC`), so that its own limit
    and this process's deadline are one moment whatever this process's start-up takes: on Linux,
    where the soak runs, `time.monotonic()` is CLOCK_MONOTONIC, one clock for every process on
    the machine. `SHEET_MANAGER_DEADLINE_SECONDS`, for trying the deadline by hand, counts from
    this module's import.
    """
    if absolute := environment.get("SHEET_MANAGER_DEADLINE_MONOTONIC"):
        return float(absolute)
    if relative := environment.get("SHEET_MANAGER_DEADLINE_SECONDS"):
        return time.monotonic() + float(relative)
    return None


DEADLINE = enclosing_deadline(os.environ)
# One budget, from a stall's detection, for listing the office's processes, reading their native
# stacks and letting the gdb wrapper print its own. The stop starts at its end at the latest and
# takes up to STOP_SECONDS (`stop_process`: taskkill's 30 s, then waits of 10 s and 10 s; on
# Linux PAUSE_SECONDS, the launcher's 10 s and 10 s, then OFFICE_STOP_SECONDS twice).
CAPTURE_SECONDS = 60.0
STOP_SECONDS = 60.0
# How long `stop_process` waits on Linux to see every thread of the launcher paused before it
# lists the processes.
PAUSE_SECONDS = 1.0
# The states of a thread that has exited, or that /proc no longer shows (None).
EXITED: set[str | None] = {"Z", "X", None}
# How long a process still running after its launcher's stop has to exit after SIGTERM, and then
# after SIGKILL. A stalled soffice.bin exited within 2 ms of SIGTERM (26.8.2.2, #266).
OFFICE_STOP_SECONDS = 5.0
CDB = Path(r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe")
# Each Windows process's ID, its parent's ID, its creation time as a FILETIME, and its name.
WINDOWS_LISTING = [
    "pwsh",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    "Get-CimInstance Win32_Process | Where-Object CreationDate | ForEach-Object { '{0}|{1}|"
    "{2}|{3}' -f $_.ProcessId, $_.ParentProcessId, $_.CreationDate.ToFileTimeUtc(), $_.Name }",
]


def retain_crash_dumps(crash_directory: Path, output: Path, prefix: str) -> list[str]:
    """Copy LibreOffice's own crash dumps out of a temporary profile; return the copies' names.

    LibreOffice's crash handler writes a minidump into the profile's `crash` directory. On
    Windows it then ends soffice.bin with exception code 0, so the office exits with status 0
    after a crash (#48); the dump is the reliable sign there. `dump.ini` names the version and
    the last UNO commands.
    """
    names = []
    for dump in sorted(crash_directory.glob("*.dmp")):
        target = output / f"{prefix}-{dump.name}"
        shutil.copy2(dump, target)
        names.append(target.name)
    if names and (crash_directory / "dump.ini").exists():
        shutil.copy2(crash_directory / "dump.ini", output / f"{prefix}-dump.ini")
    return names


def normal_startup_restart(trace: str) -> bool:
    """soffice.bin requests one profile-initialization restart before exposing UNO.

    LibreOffice's normal launcher handles EXITHELPER_NORMAL_RESTART (81); its gdb
    wrapper does not. Gdb prints inferior exit statuses in octal (0121).
    """
    return (
        re.findall(r"exited with code ([0-7]+)", trace) == ["0121"]
        and "received signal" not in trace
        and not any(marker in trace for marker in FATAL_MARKERS)
    )


def stop_process(process: subprocess.Popen[str]) -> list[str]:
    """Stop the office this session started; on Linux, return what was seen of what it held.

    On Windows the `soffice.exe` launcher runs `soffice.bin` as a child process, which stopping
    the launcher alone would leave running, so the launcher's whole process tree is stopped there.
    Elsewhere the launcher is sent SIGTERM, then SIGKILL after 10 s. On Linux `oosplash` passes
    SIGTERM on to the `soffice.bin` it has recorded and waits for it, and the gdb wrapper's
    inferior died with gdb even when gdb was killed. A `soffice.bin` outlived an `oosplash` that
    was killed instead, and one that `oosplash` had forked but not yet recorded when SIGTERM
    arrived, at the exit-81 restart (#266). So on Linux every process that is or may become the
    office is held first (`hold_offices`), and each one still running when the launcher's stop
    ends is stopped (`stop_offices`). The result is empty on other platforms, and when the
    launcher had already been reaped, since its ID may then name another process's tree. If the
    stop raises, what it saw goes with the error as notes (`office_stop: …`), which a traceback,
    such as a stall receipt's `diagnostic_errors.stop`, prints.
    """
    if process.poll() is not None:
        return []
    held = Held()
    try:
        try:
            hold_offices(process, held)
        except Exception as error:  # The launcher is stopped all the same.
            held.seen.append(f"holding stopped early: {error!r}")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=30,
            )
        else:
            process.terminate()
            resume(held)  # Only after SIGTERM, so that it acts on it before forking again.
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    except BaseException as error:
        for line in end_hold(held):
            error.add_note(f"office_stop: {line}")
        raise
    return end_hold(held)


@dataclass
class Held:
    """What `stop_process` holds on Linux while it stops a launcher."""

    launcher: int | None = None  # A pidfd to the launcher, which was sent SIGSTOP through it.
    processes: dict[int, tuple[int, str]] = field(default_factory=dict)  # ID: pidfd, name.
    seen: list[str] = field(default_factory=list)


def hold_offices(process: subprocess.Popen[str], held: Held) -> None:
    """On Linux, pause the launcher and hold, in `held`, each process that is or may be its office.

    Held are each `soffice.bin` descended from the launcher and each of the launcher's own
    children: `oosplash` forks `soffice.bin` before it records it as the child to pass SIGTERM
    on to, and the fork has the launcher's name until it execs. The launcher is paused before
    the listing (`pause`), so it starts nothing between the listing and its SIGTERM;
    `stop_process` resumes it after that SIGTERM. `poll()` found the launcher unreaped, so its ID
    names it during the listing; one that another thread reaped meanwhile has a `returncode`
    afterwards, and the listing is then not used. Each process's listed start time is checked
    while its pidfd holds it, so a signal sent through the pidfd can only reach that process; its
    name is not compared, since an exec, such as the fork's into `soffice.bin`, changes it.
    """
    if sys.platform != "linux" or not pause(process, held):
        return
    try:
        rows = listed_processes(time.monotonic() + OFFICE_STOP_SECONDS)
    except Exception as error:  # The launcher is stopped all the same.
        held.seen.append(f"nothing was held: the listing failed: {error!r}")
        return
    if process.returncode is not None:
        held.seen.append(f"nothing was held: the launcher {process.pid} was reaped meanwhile")
        return
    launcher = next((row for row in rows if row.pid == process.pid), None)
    if launcher is None:
        held.seen.append(f"nothing was held: the listing had no row for the launcher {process.pid}")
        return
    found = {row.pid: row for row in descendants(rows, process.pid, "soffice.bin")}
    found.update(
        (row.pid, row)
        for row in rows
        if row.parent == launcher.pid
        and row.pid != launcher.pid
        and row.started >= launcher.started
    )
    if not found:
        held.seen.append(
            f"the listing had no soffice.bin or other child under the launcher {process.pid}"
        )
    for row in sorted(found.values(), key=lambda row: row.pid):
        try:
            handle = os.pidfd_open(row.pid)
        except OSError as error:
            held.seen.append(f"{row.name} {row.pid} was not held: {error!r}")
            continue
        current = linux_process(row.pid)
        if current is None or current.started != row.started:
            os.close(handle)
            held.seen.append(f"{row.name} {row.pid} was not held: its start time had changed")
            continue
        held.processes[row.pid] = (handle, row.name)


def pause(process: subprocess.Popen[str], held: Held) -> bool:
    """On Linux, pause the launcher through a pidfd kept in `held`; see each of its threads stop.

    Return whether to list the processes beneath it: not when its ID no longer names this
    process's own unreaped child, nor when it had exited, since its children then have another
    parent. A launcher that could not be paused, or was not seen paused, is still listed under,
    and what was seen is recorded.

    `poll()` found the launcher unreaped, but another thread may have reaped it since, and its ID
    would then name whatever process has it now; `waitid` accepts only this process's own
    unreaped child, so nothing else is sent SIGSTOP or SIGCONT. Every thread is waited for, not
    only the first, which /proc/<pid>/stat describes: a thread that is forking when SIGSTOP
    arrives finishes the fork before it stops, so once each thread is stopped, every child the
    launcher started is in the listing.
    """
    if sys.platform != "linux":
        return False
    try:
        handle = os.pidfd_open(process.pid)
    except OSError as error:
        held.seen.append(f"the launcher {process.pid} was not paused: {error!r}")
        return True
    try:
        exited = os.waitid(os.P_PIDFD, handle, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except OSError as error:
        os.close(handle)
        if isinstance(error, ChildProcessError):
            held.seen.append(
                f"nothing was held: the launcher's ID {process.pid} no longer names an unreaped "
                "child of this process"
            )
            return False
        held.seen.append(f"the launcher {process.pid} was not paused: {error!r}")
        return True
    if exited is not None:
        os.close(handle)
        held.seen.append(f"nothing was held: the launcher {process.pid} had already exited")
        return False
    held.launcher = handle  # From here on, `resume` continues it and `stop_offices` closes it.
    try:
        signal.pidfd_send_signal(handle, signal.SIGSTOP)
    except OSError as error:
        held.seen.append(f"the launcher {process.pid} was not paused: {error!r}")
        return True
    end = time.monotonic() + PAUSE_SECONDS
    while True:
        states = set(linux_thread_states(process.pid))
        if states <= EXITED:
            held.seen.append(
                f"nothing was held: the launcher {process.pid} had exited before it was seen paused"
            )
            return False
        if states <= {"T", *EXITED}:
            return True
        if time.monotonic() >= end:
            listed = ", ".join(sorted(str(state) for state in states))
            held.seen.append(
                f"the launcher {process.pid} was not seen paused within {PAUSE_SECONDS:g} s "
                f"(its threads' states: {listed}), so it may have started a process after the "
                "listing"
            )
            return True
        time.sleep(0.001)


def resume(held: Held) -> None:
    """Let a launcher that `hold_offices` paused run again, so that it acts on its SIGTERM."""
    if sys.platform == "linux" and held.launcher is not None:
        with suppress(ProcessLookupError):
            signal.pidfd_send_signal(held.launcher, signal.SIGCONT)


def end_hold(held: Held) -> list[str]:
    """Resume the launcher, then stop what it held (`stop_offices`); return what was seen."""
    try:
        resume(held)
    finally:
        seen = stop_offices(held)
    return seen


def stop_offices(held: Held) -> list[str]:
    """Stop each held process still running after its launcher's stop; close every pidfd.

    Return what was seen of each held process. Its exit is seen as its pidfd becoming readable,
    so this returns only once each one has exited or its last wait has ended. Each running one
    is checked in turn against one deadline, so the time recorded is when its exit was seen, an
    upper bound on when it exited.
    """
    seen = list(held.seen)
    if sys.platform != "linux":
        return seen
    try:
        running: dict[int, str] = {}  # The ID and how to name it.
        for pid, (handle, listed) in held.processes.items():
            if pidfd_exited(handle, 0):
                seen.append(f"{listed} {pid} had exited when its launcher's stop ended")
                continue
            current = linux_process(pid)  # It runs, so its ID still names it.
            name = current.name if current is not None else listed
            running[pid] = f"{name} {pid}" + (f" (listed as {listed})" if name != listed else "")
        started = time.monotonic()
        sent: dict[int, list[str]] = {pid: [] for pid in running}  # The signals delivered.
        gone: dict[int, str] = {}  # The signal that found it already reaped, so reached nothing.
        exited_within: dict[int, float] = {}

        def signal_and_wait(pids: list[int], number: signal.Signals, label: str) -> None:
            for pid in pids:
                try:
                    signal.pidfd_send_signal(held.processes[pid][0], number)
                except ProcessLookupError:
                    gone[pid] = number.name
                else:
                    sent[pid].append(label)
            end = time.monotonic() + OFFICE_STOP_SECONDS
            for pid in pids:
                if pidfd_exited(held.processes[pid][0], max(0.0, end - time.monotonic())):
                    exited_within[pid] = time.monotonic() - started

        signal_and_wait(list(running), signal.SIGTERM, "SIGTERM")
        signal_and_wait(
            [pid for pid in running if pid not in exited_within],
            signal.SIGKILL,
            f"SIGKILL after {OFFICE_STOP_SECONDS:g} s",
        )
        for pid, name in running.items():
            told = [f"was sent {', then '.join(sent[pid])}"] if sent[pid] else []
            if pid in gone:
                told.append(f"had gone before {gone[pid]}")
            within = exited_within.get(pid)
            outcome = (
                f"was seen exited within {tenths_up(within):.1f} s"
                if within is not None
                else f"was not seen exited within {2 * OFFICE_STOP_SECONDS:g} s"
            )
            seen.append(
                f"{name} was running when its launcher's stop ended; it {', then '.join(told)} "
                f"and {outcome}"
            )
    finally:
        for handle, _ in held.processes.values():
            os.close(handle)
        if held.launcher is not None:
            os.close(held.launcher)
    return seen


def tenths_up(seconds: float) -> float:
    """`seconds` rounded up to a tenth, so that a time said to be "within" it stays true."""
    return math.ceil(seconds * 10) / 10


def pidfd_exited(handle: int, timeout: float) -> bool:
    """Whether the process behind the pidfd `handle` exits within `timeout` seconds.

    `poll`, unlike `select`, takes a descriptor numbered 1024 or more.
    """
    if sys.platform != "linux":
        raise OSError("pidfd_exited is for Linux pidfds")
    poller = select.poll()
    poller.register(handle, select.POLLIN)
    return bool(poller.poll(timeout * 1000))


def linux_state(pid: int) -> str | None:
    """`pid`'s state as /proc lists it now, such as T for stopped, or None once it has gone.

    This is the state of its first thread only.
    """
    return stat_state(Path(f"/proc/{pid}/stat"))


def linux_thread_states(pid: int) -> list[str | None]:
    """The state of each of `pid`'s threads as /proc lists them now; empty once it has gone."""
    try:
        threads = [entry.name for entry in Path(f"/proc/{pid}/task").iterdir()]
    except OSError:
        return []
    return [stat_state(Path(f"/proc/{pid}/task/{thread}/stat")) for thread in threads]


def stat_state(path: Path) -> str | None:
    """The state field of the /proc stat file `path`, or None once it has gone."""
    with suppress(OSError):
        text = path.read_text(encoding="utf-8", errors="replace")
        return text.rpartition(")")[2].split()[0]
    return None


def finish_process(
    process: subprocess.Popen[str],
    log_path: Path,
    *,
    timeout: float = 30,
    backtrace_path: Path | None = None,
) -> dict[str, object]:
    forced = False
    stopped: list[str] = []
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        forced = True
        stopped = stop_process(process)
    log = log_path.read_text(encoding="utf-8", errors="replace")
    markers = [marker for marker in FATAL_MARKERS if marker in log]
    if backtrace_path is not None and backtrace_path.exists():
        trace = backtrace_path.read_text(encoding="utf-8", errors="replace")
        # LibreOffice's gdb wrapper can exit zero after the inferior crashes.
        markers.extend(
            marker for marker in ("received signal", "exited with code") if marker in trace
        )
        markers.extend(
            marker for marker in FATAL_MARKERS if marker in trace and marker not in markers
        )
        if "exited normally" not in trace and not markers:
            markers.append("Debugger did not record normal office exit")
    elif backtrace_path is not None:
        markers.append("Debugger backtrace missing")
    result: dict[str, object] = {
        "office_exit_code": process.returncode,
        "office_forced_shutdown": forced,
        "office_fatal_markers": markers,
        "office_log": log_path.name,
        "office_backtrace": backtrace_path.name if backtrace_path is not None else None,
    }
    if stopped:  # On Linux, what the forced stop saw of each process it held (#266).
        result["office_stop"] = stopped
    return result


def request_termination(desktop: Any, timeout: float) -> bool:
    """Ask the office to terminate over UNO; return whether the request returned in time.

    `terminate()` does not return while the office shows a dialog, such as "Save Document?" for
    a document that a failed check left modified in a painted session (#40). The request
    therefore runs on its own thread, which is left behind if it does not return; stopping the
    office ends it.
    """
    returned = threading.Event()

    def request() -> None:
        with suppress(Exception):  # The bridge is normally disposed during successful termination.
            desktop.terminate()
        returned.set()

    threading.Thread(target=request, name="terminate-office", daemon=True).start()
    return returned.wait(timeout)


def end_office(
    desktop: Any,
    process: subprocess.Popen[str],
    log_path: Path,
    *,
    stalled: list[str],
    settle: Callable[[float], str | None],
    backtrace_path: Path | None = None,
    grace: float = 30,
) -> dict[str, object]:
    """End this session's office and record how it ended.

    Graceful shutdown has `grace` seconds in all, counted from one monotonic deadline: each step
    gets only the time the steps before it left. First `settle` waits until the office has run
    the UNO releases this process sent: an office that exits while it still runs them can crash
    (#242, `client_releases`). It returns None, or why it stopped waiting; then the office is
    stopped instead of asked, and the session fails with that reason in its results. Every
    session passes it, so it is required. Next the office is asked to terminate over UNO, and
    finally it has the rest of the time to exit, after which it is stopped. A request that does
    not return, such as one held by a dialog (#40), leaves the office running, so it is stopped
    too: the session fails with a forced shutdown instead of hanging until the job's time limit.
    The release wait's duration and the whole shutdown's are recorded.

    After a stalled main-thread callback (`teardown`), the request could wait for the stuck
    thread without bound (#50), so neither it nor `settle` is sent and the office is stopped at
    once; the session then fails, with the stall and the forced shutdown in its results. A stall
    that a `StallWatch` recorded is such a callback, and the watch is closed before this runs.
    """
    started = time.monotonic()
    deadline = started + grace

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    unsettled = None if stalled else settle(remaining())
    waited = round(time.monotonic() - started, 3)
    returned = not stalled and unsettled is None and request_termination(desktop, remaining())
    ended = finish_process(
        process, log_path, timeout=remaining() if returned else 0, backtrace_path=backtrace_path
    )
    ended["office_stalled_callbacks"] = list(stalled)
    ended["office_unsettled_releases"] = unsettled
    ended["office_release_wait_seconds"] = waited
    ended["office_terminate_returned"] = returned
    ended["office_shutdown_seconds"] = round(time.monotonic() - started, 3)
    return ended


def assert_clean_shutdown(result: dict[str, object]) -> None:
    assert result["office_exit_code"] == 0, result
    assert not result["office_forced_shutdown"], result
    assert not result["office_fatal_markers"], result
    assert not result.get("office_crash_dumps"), result
    assert not result.get("office_stalled_callbacks"), result
    assert not result.get("office_unsettled_releases"), result
    assert not result.get("office_progress_stall"), result


@dataclass(frozen=True)
class Process:
    """A listed process: its ID, its parent's ID, its name, and when it started.

    `started` orders processes on one machine: clock ticks since boot on Linux, and a FILETIME
    (100 ns since 1601) on Windows, where Win32_Process gives it to the microsecond.
    """

    pid: int
    parent: int
    name: str
    started: int


def descendants(rows: list[Process], root: int, name: str) -> list[Process]:
    """The processes named `name` among `root`'s descendants, in `rows`.

    A process that started before its recorded parent is not that parent's child: Windows keeps a
    dead parent's ID (`Win32_Process.ParentProcessId`), which a newer process can then reuse.
    """
    by_pid = {row.pid: row for row in rows}
    children: dict[int, list[Process]] = {}
    for row in rows:
        parent = by_pid.get(row.parent)
        if parent is not None and parent.pid != row.pid and row.started >= parent.started:
            children.setdefault(parent.pid, []).append(row)
    found: list[Process] = []
    pending, seen = [root], {root}
    while pending:
        for child in children.get(pending.pop(), []):
            if child.pid not in seen:
                seen.add(child.pid)
                pending.append(child.pid)
                if Path(child.name).name == name:
                    found.append(child)
    return sorted(found, key=lambda row: row.pid)


def linux_process(pid: int) -> Process | None:
    """`pid` as /proc lists it now, or None once it has gone."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    head, _, tail = text.rpartition(")")  # The name can hold spaces and parentheses.
    fields = tail.split()
    # stat(5): after the name come state, ppid, ..., and starttime as the 20th field.
    if len(fields) < 20:
        return None
    return Process(pid, int(fields[1]), head.partition("(")[2], int(fields[19]))


def listed_processes(end: float) -> list[Process]:
    """Every process this one can see, by `end`, or none where native stacks are not read.

    A listing that fails raises OSError, so that it is never taken for an empty process tree.
    """
    if sys.platform == "linux":
        pids = (int(entry.name) for entry in Path("/proc").iterdir() if entry.name.isdigit())
        rows = [row for row in map(linux_process, pids) if row is not None]
    elif sys.platform == "win32":
        rows = windows_processes(end)
    else:
        return []
    if not rows:  # This process at least is always there.
        raise OSError("The process listing found no processes")
    return rows


def windows_processes(end: float, command: list[str] | None = None) -> list[Process]:
    """Every process `command` lists in `WINDOWS_LISTING`'s format; raise OSError if it fails."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        status = run_collector(command or WINDOWS_LISTING, out, end, stderr=err)
        out.seek(0)
        err.seek(0)
        listing = out.read().decode("utf-8", "replace")
        problem = err.read().decode("utf-8", "replace").strip() or "no error output"
    if status is None:
        raise TimeoutError(f"The process listing did not finish by its deadline: {problem}")
    if status:
        raise OSError(f"The process listing exited {status}: {problem}")
    rows: list[Process] = []
    for line in listing.splitlines():
        parts = line.strip().split("|", 3)
        if len(parts) == 4 and all(part.isdigit() for part in parts[:3]):
            rows.append(Process(int(parts[0]), int(parts[1]), parts[3], int(parts[2])))
    return rows


def office_processes(root: int, end: float) -> list[Process]:
    """Every soffice.bin that the session's launcher `root` started, directly or through others."""
    return descendants(listed_processes(end), root, "soffice.bin")


def run_collector(
    command: list[str],
    stdout: IO[bytes],
    end: float,
    *,
    stderr: IO[bytes] | int = subprocess.STDOUT,
) -> int | None:
    """Run a diagnostic command until `end`, on `time.monotonic()`'s clock.

    Return its exit status, or None if it was sent a kill at `end`, or not started after it. The
    time left is taken after the command starts, so a slow start does not extend its life; one
    that starts after `end` is sent a kill at once. After a kill its exit is waited for up to 5 s
    and not checked. Its output goes to files, which keep what it wrote before then. A pipe could
    stay open in a child of the command and hold this thread after the kill.
    """
    if time.monotonic() >= end:
        return None
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
    try:
        return process.wait(timeout=max(0.0, end - time.monotonic()))
    except subprocess.TimeoutExpired:
        process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        return None


def run_debugger(command: list[str], path: Path, end: float) -> str:
    """Run a debugger with its output streamed into `path`: a timeout keeps what it wrote."""
    name = Path(command[0]).name
    try:
        with path.open("wb") as file:
            status = run_collector(command, file, end)
    except OSError as error:
        return f"{name} failed: {error!r}"
    if status is None:
        return (
            f"{name} had not exited by the capture's end and was sent a kill; "
            f"{path.name} has what it wrote"
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"Id: [0-9a-f]+\.[0-9a-f]+", text):
        # CDB prints why instead, such as access being denied.
        first = next((line for line in text.splitlines() if line.strip()), "no output")
        return f"{name} exited {status}; its output has no thread line: {first}"
    return f"{name} exited {status}; its output has thread lines"


@dataclass(frozen=True)
class StackAttempt:
    """What `native_stacks` did for one office process.

    `method` is the receipt's text for it. `interrupted` says whether SIGINT was sent to the gdb
    wrapper's inferior, after which the watch waits for the wrapper to exit. The watch acts on
    `interrupted` and only records `method`, so rewording the text changes no behaviour (#267).
    """

    method: str
    interrupted: bool = False


def native_stacks(
    target: Process, path: Path, *, debugger_parent: bool, end: float
) -> StackAttempt:
    """Try to have every native stack of the office `target` written by `end`; say what was done.

    Only a process that is still `target` is touched: its identity is checked while a handle to
    it is held, and the handle is held until the action ends. On Linux, only the gdb wrapper's
    inferior is touched, through its pidfd: it is sent SIGINT, after which gdb normally prints
    every thread's stack into its own trace. That the signal was sent is all this observes; a
    gdb that is itself blocked prints nothing. The result says what was done, or why nothing was,
    and whether that signal was sent.
    """
    if sys.platform == "linux":
        if not debugger_parent:
            # `gdb -p` attaches by number, which a new process can have reused by then.
            return StackAttempt("not read: Linux native stacks need the gdb wrapper (--backtrace)")
        try:
            handle = os.pidfd_open(target.pid)
        except ProcessLookupError:
            return StackAttempt(f"skipped: no process {target.pid} when its pidfd was opened")
        try:
            current = linux_process(target.pid)
            if current is None or (current.name, current.started) != (target.name, target.started):
                return StackAttempt(
                    f"skipped: process {target.pid} no longer has its listed name and start time"
                )
            parent = linux_process(current.parent)
            tracer = tracer_of(target.pid)
            if parent is None or parent.name != "gdb" or tracer != parent.pid:
                return StackAttempt(f"skipped: not the gdb wrapper's inferior (tracer {tracer})")
            signal.pidfd_send_signal(handle, signal.SIGINT)
            return StackAttempt(
                f"SIGINT sent through its pidfd to {target.pid}, traced by gdb {parent.pid}; "
                "whatever gdb printed is in the session's gdbtrace log",
                interrupted=True,
            )
        finally:
            os.close(handle)
    if sys.platform == "win32":
        if not CDB.exists():
            return StackAttempt(f"no CDB at {CDB}")
        import _winapi

        try:
            # Query and wait access; an open handle keeps the process ID from being reused.
            handle = _winapi.OpenProcess(0x1000 | 0x100000, False, target.pid)
        except OSError as error:
            return StackAttempt(f"skipped: OpenProcess({target.pid}) failed: {error!r}")
        try:
            if creation_time(handle) // 10 != target.started // 10:
                return StackAttempt(
                    f"skipped: process {target.pid} no longer has its listed start time"
                )
            return StackAttempt(
                run_debugger(
                    [str(CDB), "-pv", "-p", str(target.pid), "-c", "~*kc 60; q"], path, end
                )
            )
        finally:
            _winapi.CloseHandle(handle)
    return StackAttempt(f"native stacks are not read on {sys.platform}")


def tracer_of(pid: int) -> int | None:
    """The process tracing `pid` (0 for none), or None if it cannot be read."""
    with suppress(OSError):
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("TracerPid:"):
                return int(line.split()[1])
    return None


def creation_time(handle: int) -> int:
    """When the Windows process behind `handle` started, as a FILETIME."""
    if sys.platform != "win32":
        raise OSError("creation_time is for Windows process handles")
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel32.GetProcessTimes(wintypes.HANDLE(handle), *map(ctypes.byref, times)):
        raise ctypes.WinError(ctypes.get_last_error())
    return times[0].dwHighDateTime << 32 | times[0].dwLowDateTime


def launcher_identity(process: subprocess.Popen[str]) -> Process | None:
    """On Linux, the launcher `process` as /proc lists it now; None elsewhere or once it has gone.

    Take it right after the launch: until the runner reaps the launcher, its ID names only it.
    """
    return linux_process(process.pid) if sys.platform == "linux" else None


class StallWatch:
    """Fail and stop a session that makes no progress for `limit` seconds, trying to save stacks.

    `expire(limit, message, overdue)` records `message` as a stall and returns the seconds since
    progress when the session has made none for `limit` seconds or is `overdue` (`DEADLINE`),
    atomically with progress (`teardown.stall_if_idle`); otherwise it returns None. `follow`
    accepts a replacement office only while nothing has stalled. `close` ends the watch before the
    deadline; once expiry has won, or when the deadline has passed, it waits for the capture and
    returns its evidence.
    """

    def __init__(
        self,
        process: subprocess.Popen[str],
        output: Path,
        prefix: str,
        *,
        expire: Callable[[float, str, bool], float | None],
        debugger_parent: bool = False,
        limit: float | None = None,
        deadline: float | None = None,
        budget: float | None = None,
        find: Callable[[int, float], list[Process]] = office_processes,
        stacks: Callable[..., StackAttempt] = native_stacks,
        stop: Callable[[subprocess.Popen[str]], object] = stop_process,
    ) -> None:
        self.process, self.output, self.prefix = process, output, prefix
        self.expire, self.debugger_parent = expire, debugger_parent
        self.limit = STALL_SECONDS if limit is None else limit
        self.deadline = DEADLINE if deadline is None else deadline
        self.budget = CAPTURE_SECONDS if budget is None else budget
        self.find, self.stacks, self.stop = find, stacks, stop
        # close() stopped waiting before the capture finished. It describes the caller's wait,
        # not the capture, so it is never part of the evidence.
        self.wait_timed_out = False
        self._lock = threading.Lock()
        self._state = "watching"  # Then "closed", or "stalled" when expiry wins.
        self._launcher = launcher_identity(process)
        self._evidence: dict[str, Any] = {}
        self._detected = self._end = 0.0  # When the stall was recorded, and when its budget ends.
        self._collected = False  # The collector finished all its steps before the budget's end.
        self._final = False  # The office's stop has ended: the evidence is complete.
        self._step_name = ""  # The collector's current step, for a capture that overruns.
        self._changed = threading.Event()  # The evidence changed since the receipt was written.
        self._written = threading.Event()  # The first receipt was written, or could not be.
        self._captured = threading.Event()  # The final receipt was written, or could not be.
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="stall-watch", daemon=True)

    def start(self) -> "StallWatch":
        self._thread.start()
        return self

    def follow(self, process: subprocess.Popen[str]) -> bool:
        """Watch `process`, which replaces the watched office, unless the session has stalled.

        Return whether it is now watched, as for the gdb wrapper's startup restart (`run.py`).
        Accepting it and expiry are one decision under the watch's lock, and nothing external
        runs under that lock; the caller stops a refused replacement before any UNO call to it.
        """
        launcher = launcher_identity(process)  # Read before the lock: it reads /proc.
        with self._lock:
            if self._state != "watching":
                return False
            self.process, self._launcher = process, launcher
            return True

    @property
    def stalled(self) -> bool:
        with self._lock:
            return self._state == "stalled"

    def close(self) -> dict[str, Any] | None:
        """End the watch before the deadline; otherwise wait for the capture, return its evidence.

        A close at or after the deadline records the stall, as the watch's next look would have,
        so a watch that closed shows that the session's checks ended before the deadline. The
        wait is bounded by the capture's budget, the office's stop and a little time for the
        receipt. It never writes the receipt and never changes the evidence: `watch_finished`
        is the watch's own, and `wait_timed_out` says whether this wait ended first.
        """
        with self._lock:
            if self._state == "watching" and not (self._overdue() and self._decide()):
                self._state = "closed"
            stalled, end = self._state == "stalled", self._end
        self._wake.set()
        if not stalled:
            self._thread.join(timeout=10)  # It returns at its next look at the state.
            return None
        finished = self._captured.wait(max(0.0, end - time.monotonic()) + STOP_SECONDS + 2)
        self.wait_timed_out = not finished
        with self._lock:
            return json.loads(json.dumps(self._evidence, default=repr))

    def _overdue(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline

    def _watch(self) -> None:
        while True:
            pause = min(5.0, self.limit / 4)
            if self.deadline is not None:
                pause = max(0.0, min(pause, self.deadline - time.monotonic()))
            self._wake.wait(pause)
            with self._lock:
                if self._state == "closed":
                    return
                if self._state == "watching" and not self._decide():
                    continue
                process, launcher, end = self.process, self._launcher, self._end
            self._supervise(process, launcher, end)
            return

    def _decide(self) -> bool:
        """Record a stall if expiry wins now, and return whether it did; hold the lock."""
        overdue = self._overdue()
        cause = (
            "The deadline its enclosing runner set had passed"
            if overdue
            else f"No test progress for {self.limit:g} s"
        )
        idle = self.expire(
            self.limit, f"{cause}; recorded as a stall ({self.prefix}.json)", overdue
        )
        if idle is None:
            return False
        self._state = "stalled"
        self._detected = time.monotonic()
        self._end = self._detected + self.budget
        self._step_name = "first_receipt"
        self._evidence = {
            "cause": "deadline" if overdue else "no progress",
            "limit_seconds": self.limit,
            "idle_seconds": round(idle, 1),
            "receipt": f"{self.prefix}.json",
            "launcher_pid": self.process.pid,
            "office_stacks": {},
        }
        self._changed.set()  # The receipt thread writes this before the collector's first step.
        return True

    def _supervise(
        self, process: subprocess.Popen[str], launcher: Process | None, end: float
    ) -> None:
        """Let the collector work until `end`, then stop the launcher, on the watch's own thread.

        Nothing delays the start of the stop past `end`: this thread writes no files, and a
        collector still working then is left behind, its later steps and results refused.
        """
        try:
            threading.Thread(target=self._write_receipts, name="stall-receipt", daemon=True).start()
            collector = threading.Thread(
                target=self._collect,
                args=(process, launcher, end),
                name="stall-capture",
                daemon=True,
            )
            collector.start()
            collector.join(max(0.0, end - time.monotonic()))
            with self._lock:
                self._evidence["collection_finished"] = self._collected
                if not self._collected:
                    self._evidence.setdefault("diagnostic_errors", {})["capture"] = (
                        f"the collector was at {self._step_name} when the {self.budget:g} s "
                        "budget ended"
                    )
        finally:
            stopped = self._step("stop", lambda: self.stop(process), collector=False)
            # The launcher's status, not the office's: a soffice.bin can outlive its launcher.
            status = process.poll()
            with self._lock:
                if stopped:  # On Linux, what the stop saw of each process it held (#266).
                    self._evidence["office_stop"] = stopped
                self._evidence.update(
                    launcher_exit_status=status,
                    stop_returned_after_seconds=round(time.monotonic() - self._detected, 1),
                    watch_finished=True,
                )
                self._final = True
            self._changed.set()

    def _collect(
        self, process: subprocess.Popen[str], launcher: Process | None, end: float
    ) -> None:
        """Save the client's and the office's stacks before `end`, on the collector's thread."""
        # The stall is on disk before any step can fail or an outer limit hits.
        self._written.wait(max(0.0, end - time.monotonic()))
        self._step("client_stacks", self._client_stacks)
        targets = self._step("office_processes", lambda: self.find(process.pid, end))
        if targets is not None and sys.platform == "linux":
            # The listing is rooted at the launcher's ID, so it says nothing about this session,
            # found or empty, unless that ID still names the launcher. Checked after the listing:
            # if the ID names the launcher now, it named it throughout the listing.
            current = linux_process(process.pid)
            if launcher is None:
                seen = f"the watch took no identity for the launcher {process.pid}"
            elif current is None:
                seen = f"/proc shows no process for the launcher's ID {process.pid}"
            elif current.started != launcher.started:
                seen = f"/proc shows another start time for the launcher's ID {process.pid}"
            else:
                seen = None
            if seen is not None:
                reason = f"listing not used: {seen}, so its descendants may not be this session's"
                self._record(lambda evidence: evidence.update(office_search=reason))
                targets = None
        if targets == []:
            searched = sys.platform in ("linux", "win32")
            search = (
                f"the listing has no soffice.bin descended from the launcher {process.pid}"
                if searched
                else f"native stacks are not read on {sys.platform}"
            )
            self._record(lambda evidence: evidence.update(office_search=search))
        interrupted = False
        for target in targets or []:
            path = self.output / f"{self.prefix}-office-{target.pid}-stacks.txt"
            attempt: StackAttempt | None = self._step(  # None when the step failed.
                f"office_{target.pid}",
                lambda target=target, path=path: self.stacks(
                    target, path, debugger_parent=self.debugger_parent, end=end
                ),
            )
            interrupted = interrupted or (attempt is not None and attempt.interrupted)
            self._record_stacks(target, attempt, path)
        if interrupted:  # The gdb wrapper normally prints the stacks, then ends the office.
            status = self._step(
                "wrapper_exit", lambda: process.wait(timeout=max(0.0, end - time.monotonic()))
            )
            if status is not None:
                self._record(lambda evidence: evidence.update(wrapper_exit_status=status))
        with self._lock:
            self._collected = time.monotonic() < end

    def _record_stacks(self, target: Process, attempt: StackAttempt | None, path: Path) -> None:
        method = attempt.method if attempt is not None else None
        entry = {"method": method, "file": path.name if path.exists() else None}

        def add(evidence: dict[str, Any]) -> None:
            evidence["office_stacks"][str(target.pid)] = entry

        self._record(add)

    def _client_stacks(self) -> str:
        path = self.output / f"{self.prefix}-client-stacks.txt"
        with path.open("w", encoding="utf-8") as file:
            faulthandler.dump_traceback(file, all_threads=True)
        self._record(lambda evidence: evidence.update(client_stacks=path.name))
        return path.name

    def _step(self, name: str, step: Callable[[], Any], *, collector: bool = True) -> Any:
        """Run one capture step; record its error and let the later steps run.

        The collector starts no step after the budget's end.
        """
        if collector:
            with self._lock:
                if time.monotonic() >= self._end:
                    return None
                self._step_name = name
        try:
            return step()
        except Exception:
            error = traceback.format_exc()

            def add(evidence: dict[str, Any]) -> None:
                evidence.setdefault("diagnostic_errors", {})[name] = error

            self._record(add, collector=collector)
            return None

    def _record(
        self, update: Callable[[dict[str, Any]], object], *, collector: bool = True
    ) -> None:
        """Apply `update` to the evidence; the collector's only before the budget's end."""
        with self._lock:
            if collector and time.monotonic() >= self._end:
                return
            update(self._evidence)
        self._changed.set()

    def _write_receipts(self) -> None:
        """Write the receipt whenever the evidence changes, until the final one; its only writer."""
        path = self.output / f"{self.prefix}.json"
        try:
            while True:
                self._changed.wait()
                with self._lock:
                    self._changed.clear()
                    text = json.dumps(self._evidence, indent=2, default=repr) + "\n"
                    final = self._final
                try:
                    temporary = path.with_name(path.name + ".tmp")
                    temporary.write_text(text, encoding="utf-8")
                    os.replace(temporary, path)
                except OSError as error:  # The session's result still carries the evidence.
                    with self._lock:
                        self._evidence["receipt_error"] = repr(error)
                self._written.set()
                if final:
                    self._captured.set()
                    return
        finally:
            self._written.set()  # The collector never waits for a writer that has died.
