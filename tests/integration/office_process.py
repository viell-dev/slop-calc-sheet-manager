"""Collect and validate private office process shutdown without a UNO dependency.

A UNO call that never returns blocks the test client until an enclosing time limit ends the run,
which then leaves no evidence. Integration and UI stalls of this kind were seen without native
stacks (#45). `StallWatch` therefore fails a session that reports no progress (`teardown`) for
`STALL_SECONDS` (15 minutes; `SHEET_MANAGER_STALL_SECONDS` overrides it), or that reaches the
deadline an enclosing runner gives this process (`SHEET_MANAGER_DEADLINE_SECONDS`, counted from
its start), and stops its office so that the blocked call fails. Rules for changing it:

- Closing the watch, progress, expiry and accepting the gdb wrapper's replacement office are one
  decision, under the watch's lock and `teardown`'s progress lock; nothing external, such as a
  launch, runs under the lock. When expiry wins, the stall is recorded as a stalled callback and
  in the `stall-*.json` receipt before anything else, so no close or settings restore starts
  during the capture, and `assert_clean_shutdown` fails it whatever the capture does. A
  replacement refused after a stall is stopped before any UNO call to it.
- The watch's own thread decides, stops the office and is the receipt's only writer, so an older
  snapshot never replaces a newer one. A collector thread saves the client's Python stacks, then
  the office's native stacks, with debugger output streamed into its file. The watch waits for it
  until `CAPTURE_SECONDS` after detection, then stops the office whatever the collector or the
  client is doing, and ignores the collector's later results; each collector subprocess (CDB,
  the Windows process listing) is killed at that deadline. A failed step, including a failed
  listing, is recorded beside the others, never read as an empty process tree. The session waits
  for the watch, bounded, and records whether it finished.
- Native stacks are read only from a process still identified as this session's office: a
  `soffice.bin` descendant of the session's launcher that started no earlier than its parent
  (Windows keeps a dead parent's ID, which a newer process can reuse) and still has the start
  time it was listed with, checked while a Linux pidfd or Windows process handle holds it. On
  Linux only a `soffice.bin` traced by the gdb wrapper (`--backtrace`) is interrupted, through
  its pidfd. Without the wrapper no debugger attaches there: `gdb -p` takes a number, which a new
  process could have reused by the time it attaches, and containers refuse `ptrace` anyway. An
  uncertain target is skipped, with the reason recorded.
- The limit is not a test timeout, and never shorten it to speed up a run. The slowest measured
  suite took 649 s (Intel macOS `test_reorder`, #162), so the benchmarks also report progress at
  each workbook and repetition; each session records its `longest_progress_interval_seconds`.
- An enclosing limit that ends the run first still wins; `docs/development/native-testing.md`
  says where (#244).
"""

import faulthandler
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

FATAL_MARKERS = ("Unspecified Application Error", "Fatal exception")
STALL_SECONDS = float(os.environ.get("SHEET_MANAGER_STALL_SECONDS", "900"))
_DEADLINE = os.environ.get("SHEET_MANAGER_DEADLINE_SECONDS")
# When an enclosing runner ends this process, such as the soak's 180 s per session, on
# `time.monotonic()`'s clock; None without a deadline.
DEADLINE = time.monotonic() + float(_DEADLINE) if _DEADLINE else None
# One budget, from a stall's detection, for listing the office's processes, reading their native
# stacks and letting the gdb wrapper print its own. Stopping the office follows at its end at the
# latest, within STOP_SECONDS (`stop_process`: taskkill's 30 s, then waits of 10 s and 10 s).
CAPTURE_SECONDS = 60.0
STOP_SECONDS = 60.0
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


def stop_process(process: subprocess.Popen[str]) -> None:
    """Stop the office this session started.

    On Windows the `soffice.exe` launcher runs `soffice.bin` as a child process, which stopping
    the launcher alone would leave running, so the launcher's whole process tree is stopped there.
    """
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=30,
            )
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def finish_process(
    process: subprocess.Popen[str],
    log_path: Path,
    *,
    timeout: float = 30,
    backtrace_path: Path | None = None,
) -> dict[str, object]:
    forced = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        forced = True
        stop_process(process)
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
    return {
        "office_exit_code": process.returncode,
        "office_forced_shutdown": forced,
        "office_fatal_markers": markers,
        "office_log": log_path.name,
        "office_backtrace": backtrace_path.name if backtrace_path is not None else None,
    }


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
    backtrace_path: Path | None = None,
    grace: float = 30,
) -> dict[str, object]:
    """End this session's office and record how it ended.

    Normally the office is asked to terminate over UNO and given `grace` seconds to return from
    that request and then to exit, after which it is stopped. A request that does not return,
    such as one held by a dialog (#40), leaves the office running, so it is stopped too: the
    session fails with a forced shutdown instead of hanging until the job's time limit.

    After a stalled main-thread callback (`teardown`), the request could wait for the stuck
    thread without bound (#50), so it is not sent and the office is stopped at once; the session
    then fails, with the stall and the forced shutdown in its results.
    """
    returned = not stalled and request_termination(desktop, grace)
    ended = finish_process(
        process, log_path, timeout=grace if returned else 0, backtrace_path=backtrace_path
    )
    ended["office_stalled_callbacks"] = list(stalled)
    ended["office_terminate_returned"] = returned
    return ended


def assert_clean_shutdown(result: dict[str, object]) -> None:
    assert result["office_exit_code"] == 0, result
    assert not result["office_forced_shutdown"], result
    assert not result["office_fatal_markers"], result
    assert not result.get("office_crash_dumps"), result
    assert not result.get("office_stalled_callbacks"), result
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


def listed_processes(seconds: float) -> list[Process]:
    """Every process this one can see, or none where native stacks are not read.

    A listing that fails raises OSError, so that it is never taken for an empty process tree.
    """
    if sys.platform == "linux":
        pids = (int(entry.name) for entry in Path("/proc").iterdir() if entry.name.isdigit())
        rows = [row for row in map(linux_process, pids) if row is not None]
    elif sys.platform == "win32":
        rows = windows_processes(seconds)
    else:
        return []
    if not rows:  # This process at least is always there.
        raise OSError("The process listing found no processes")
    return rows


def windows_processes(seconds: float, command: list[str] | None = None) -> list[Process]:
    """Every process `command` lists in `WINDOWS_LISTING`'s format; raise OSError if it fails."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        status = run_collector(command or WINDOWS_LISTING, out, seconds, stderr=err)
        out.seek(0)
        err.seek(0)
        listing = out.read().decode("utf-8", "replace")
        problem = err.read().decode("utf-8", "replace").strip() or "no error output"
    if status is None:
        raise TimeoutError(f"The process listing did not finish in {seconds:.0f} s: {problem}")
    if status:
        raise OSError(f"The process listing exited {status}: {problem}")
    rows: list[Process] = []
    for line in listing.splitlines():
        parts = line.strip().split("|", 3)
        if len(parts) == 4 and all(part.isdigit() for part in parts[:3]):
            rows.append(Process(int(parts[0]), int(parts[1]), parts[3], int(parts[2])))
    return rows


def office_processes(root: int, seconds: float) -> list[Process]:
    """Every soffice.bin that the session's launcher `root` started, directly or through others."""
    return descendants(listed_processes(seconds), root, "soffice.bin")


def run_collector(
    command: list[str],
    stdout: IO[bytes],
    seconds: float,
    *,
    stderr: IO[bytes] | int = subprocess.STDOUT,
) -> int | None:
    """Run a diagnostic command; return its exit status, or None if it was killed at `seconds`.

    Its output goes to files, which keep what it wrote before it was killed. A pipe could stay
    open in a child of the command and hold this thread after the kill.
    """
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
    try:
        return process.wait(timeout=max(0.1, seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        return None


def run_debugger(command: list[str], path: Path, seconds: float) -> str:
    """Run a debugger with its output streamed into `path`: a timeout keeps what it wrote."""
    name = Path(command[0]).name
    try:
        with path.open("wb") as file:
            status = run_collector(command, file, seconds)
    except OSError as error:
        return f"{name} failed: {error!r}"
    if status is None:
        return f"{name} did not finish in {seconds:.0f} s and was stopped; its output is kept"
    text = path.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"Id: [0-9a-f]+\.[0-9a-f]+", text):
        # CDB prints why instead, such as access being denied.
        first = next((line for line in text.splitlines() if line.strip()), "no output")
        return f"{name} could not read the stacks: {first}"
    return f"{name} exited {status}"


def native_stacks(target: Process, path: Path, *, debugger_parent: bool, seconds: float) -> str:
    """Write every thread's native stack of the office `target` to `path`; return how, or why not.

    Only a process that is still `target` is touched: its identity is checked while a handle to
    it is held, and the handle is held until the action ends. On Linux, only the gdb wrapper's
    inferior is touched, through its pidfd; the wrapper writes the stacks into its own trace.
    """
    if sys.platform == "linux":
        if not debugger_parent:
            # `gdb -p` attaches by number, which a new process can have reused by then.
            return "not read: Linux native stacks need the gdb wrapper (--backtrace)"
        try:
            handle = os.pidfd_open(target.pid)
        except ProcessLookupError:
            return "skipped: the process had exited"
        try:
            current = linux_process(target.pid)
            if current is None or (current.name, current.started) != (target.name, target.started):
                return "skipped: its process ID no longer names the listed office"
            # LibreOffice's gdb wrapper already traces the office: an interrupt makes it print
            # every thread's stack into its own trace, which the session keeps, and end it.
            parent = linux_process(current.parent)
            tracer = tracer_of(target.pid)
            if parent is None or parent.name != "gdb" or tracer != parent.pid:
                return f"skipped: not the gdb wrapper's inferior (tracer {tracer})"
            signal.pidfd_send_signal(handle, signal.SIGINT)
            return "SIGINT to the gdb wrapper's inferior; the stacks are in its gdbtrace log"
        finally:
            os.close(handle)
    if sys.platform == "win32":
        if not CDB.exists():
            return f"no CDB at {CDB}"
        import _winapi

        try:
            # Query and wait access; an open handle keeps the process ID from being reused.
            handle = _winapi.OpenProcess(0x1000 | 0x100000, False, target.pid)
        except OSError:
            return "skipped: the process had exited"
        try:
            if creation_time(handle) // 10 != target.started // 10:
                return "skipped: its process ID no longer names the listed office"
            return run_debugger(
                [str(CDB), "-pv", "-p", str(target.pid), "-c", "~*kc 60; q"], path, seconds
            )
        finally:
            _winapi.CloseHandle(handle)
    return f"native stacks are not read on {sys.platform}"


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


class StallWatch:
    """Fail and stop a session that makes no progress for `limit` seconds, keeping its stacks.

    `expire(limit, message, overdue)` records `message` as a stall and returns the seconds since
    progress when the session has made none for `limit` seconds or is `overdue` (`DEADLINE`),
    atomically with progress (`teardown.stall_if_idle`); otherwise it returns None. `follow`
    accepts a replacement office only while nothing has stalled. `close` ends the watch, unless
    expiry has won, in which case it waits for the capture and returns its evidence.
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
        stacks: Callable[..., str] = native_stacks,
        stop: Callable[[subprocess.Popen[str]], None] = stop_process,
    ) -> None:
        self.process, self.output, self.prefix = process, output, prefix
        self.expire, self.debugger_parent = expire, debugger_parent
        self.limit = STALL_SECONDS if limit is None else limit
        self.deadline = DEADLINE if deadline is None else deadline
        self.budget = CAPTURE_SECONDS if budget is None else budget
        self.find, self.stacks, self.stop = find, stacks, stop
        self._lock = threading.Lock()
        self._state = "watching"  # Then "closed", or "stalled" when expiry wins.
        self._evidence: dict[str, Any] = {}
        self._collecting = False  # The collector's results count only while this holds.
        self._step_name = ""  # The collector's current step, for a capture that overruns.
        self._changed = threading.Event()  # The evidence changed since the receipt was written.
        self._wake = threading.Event()
        self._captured = threading.Event()
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
        with self._lock:
            if self._state != "watching":
                return False
            self.process = process
            return True

    @property
    def stalled(self) -> bool:
        with self._lock:
            return self._state == "stalled"

    def close(self) -> dict[str, Any] | None:
        """End the watch; after a stall, wait for its capture and return its evidence.

        The wait is bounded by the capture's budget and the office's stop, with a little time for
        the receipt. It never writes the receipt, whose only writer is the watch's thread.
        `capture_finished` says whether the watch had finished when the wait ended.
        """
        with self._lock:
            if self._state == "watching":
                self._state = "closed"
            stalled = self._state == "stalled"
        self._wake.set()
        if not stalled:
            self._thread.join(timeout=10)  # It returns at its next look at the state.
            return None
        finished = self._captured.wait(self.budget + STOP_SECONDS + 2)
        with self._lock:
            evidence = json.loads(json.dumps(self._evidence))
        evidence["capture_finished"] = finished
        return evidence

    def _watch(self) -> None:
        while True:
            pause = min(5.0, self.limit / 4)
            if self.deadline is not None:
                pause = max(0.0, min(pause, self.deadline - time.monotonic()))
            self._wake.wait(pause)
            with self._lock:
                if self._state != "watching":
                    return
                overdue = self.deadline is not None and time.monotonic() >= self.deadline
                cause = (
                    "The run reached the deadline its enclosing runner set"
                    if overdue
                    else f"No test progress for {self.limit:.0f} s"
                )
                idle = self.expire(
                    self.limit,
                    f"{cause}: the runner keeps the client's and the office's stacks and stops the "
                    f"office ({self.prefix}.json)",
                    overdue,
                )
                if idle is None:
                    continue
                self._state = "stalled"
                process = self.process
                self._evidence = {
                    "cause": "deadline" if overdue else "no progress",
                    "limit_seconds": self.limit,
                    "idle_seconds": round(idle, 1),
                    "receipt": f"{self.prefix}.json",
                    "launcher_pid": process.pid,
                    "office_stacks": {},
                }
            self._supervise(process)

    def _supervise(self, process: subprocess.Popen[str]) -> None:
        """Let the collector work until the budget ends, then stop the office, on this thread.

        Neither the collector nor the client can delay the stop past the budget: a collector that
        has not finished is left behind, and its later results are not recorded.
        """
        started = time.monotonic()
        end = started + self.budget
        try:
            self._publish()  # The stall is on disk before any step can fail or an outer limit hits.
            with self._lock:
                self._collecting = True
            collector = threading.Thread(
                target=self._collect, args=(process, end), name="stall-capture", daemon=True
            )
            collector.start()
            while True:
                collector.join(max(0.0, min(0.2, end - time.monotonic())))
                if self._changed.is_set():
                    self._publish()
                if not collector.is_alive() or time.monotonic() >= end:
                    break
            with self._lock:
                self._collecting = False
                finished = not collector.is_alive()
                self._evidence["collection_finished"] = finished
                if not finished:
                    self._evidence.setdefault("diagnostic_errors", {})["capture"] = (
                        f"{self._step_name} did not finish within the {self.budget:.0f} s budget"
                    )
        finally:
            self._step("stop", lambda: self.stop(process), collector=False)
            with self._lock:
                self._evidence.update(
                    office_stopped=process.poll() is not None,
                    capture_seconds=round(time.monotonic() - started, 1),
                    capture_finished=True,
                )
            self._publish()
            self._captured.set()

    def _collect(self, process: subprocess.Popen[str], end: float) -> None:
        """Save the client's and the office's stacks before `end`, on the collector's thread."""
        self._step("client_stacks", self._client_stacks)
        targets = self._step(
            "office_processes", lambda: self.find(process.pid, end - time.monotonic())
        )
        if targets == []:
            searched = sys.platform in ("linux", "win32")
            search = (
                "no soffice.bin among the session's processes"
                if searched
                else f"native stacks are not read on {sys.platform}"
            )
            self._record(lambda evidence: evidence.update(office_search=search))
        interrupted = False
        for target in targets or []:
            path = self.output / f"{self.prefix}-office-{target.pid}-stacks.txt"
            remaining = end - time.monotonic()
            how = (
                self._step(
                    f"office_{target.pid}",
                    lambda target=target, path=path, remaining=remaining: self.stacks(
                        target, path, debugger_parent=self.debugger_parent, seconds=remaining
                    ),
                )
                if remaining > 0
                else "skipped: the capture's budget was spent"
            )
            interrupted = interrupted or str(how).startswith("SIGINT")
            self._record_stacks(target, how, path)
        if interrupted:  # The gdb wrapper prints the stacks, then ends the office.
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=max(0.0, end - time.monotonic()))

    def _record_stacks(self, target: Process, how: object, path: Path) -> None:
        entry = {"method": how, "file": path.name if path.exists() else None}

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

        A collector whose budget has ended starts no further step.
        """
        if collector:
            with self._lock:
                if not self._collecting:
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
        """Apply `update` to the evidence; the collector's only while its budget lasts."""
        with self._lock:
            if collector and not self._collecting:
                return
            update(self._evidence)
            self._changed.set()

    def _publish(self) -> None:
        """Write the receipt. Only the watch's own thread calls this."""
        with self._lock:
            self._changed.clear()
            text = json.dumps(self._evidence, indent=2) + "\n"
        path = self.output / f"{self.prefix}.json"
        try:
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)
        except OSError as error:  # The session's result still carries the evidence.
            with self._lock:
                self._evidence["receipt_error"] = repr(error)
