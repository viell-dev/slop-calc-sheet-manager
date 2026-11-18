"""Collect and validate private office process shutdown without a UNO dependency.

A UNO call that never returns blocks the test client until an enclosing time limit ends the run,
which then leaves no evidence. Integration and UI stalls of this kind were seen without native
stacks (#45). `StallWatch` therefore fails a session that reports no progress (`teardown`) for
`STALL_SECONDS` (15 minutes; `SHEET_MANAGER_STALL_SECONDS` overrides it), or that reaches the
deadline an enclosing runner gives this process (`SHEET_MANAGER_DEADLINE_SECONDS`, counted from
its start), and stops its office so that the blocked call fails. Rules for changing it:

- Closing the watch, progress and expiry are one decision, under the watch's lock and
  `teardown`'s progress lock. When expiry wins, the stall is recorded as a stalled callback and
  in the `stall-*.json` receipt before anything else, so no close or settings restore starts
  during the capture, and `assert_clean_shutdown` fails it whatever the capture does.
- The capture saves the client's Python stacks, then the office's native stacks, with debugger
  output streamed into its file, within one budget (`CAPTURE_SECONDS`). A failed step is
  recorded beside the others, and the office is stopped in a `finally`. The session waits for
  that, bounded, and records whether it finished.
- Native stacks are read only from a process still identified as this session's office: a
  `soffice.bin` descendant of the session's launcher that started no earlier than its parent
  (Windows keeps a dead parent's ID, which a newer process can reuse) and still has the start
  time it was listed with, checked while a Linux pidfd or Windows process handle holds it. Under
  the gdb wrapper only a `soffice.bin` traced by its `gdb` parent is interrupted. An uncertain
  target is skipped, with the reason recorded.
- The limit is not a test timeout, and never shorten it to speed up a run. The slowest measured
  suite took 649 s (Intel macOS `test_reorder`, #162), so the benchmarks also report progress at
  each workbook and repetition; each session records its `longest_progress_interval_seconds`.
- An enclosing limit that ends the run first still wins; CONTRIBUTING.md says where.
"""

import faulthandler
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FATAL_MARKERS = ("Unspecified Application Error", "Fatal exception")
STALL_SECONDS = float(os.environ.get("SHEET_MANAGER_STALL_SECONDS", "900"))
_DEADLINE = os.environ.get("SHEET_MANAGER_DEADLINE_SECONDS")
# When an enclosing runner ends this process, such as the soak's 180 s per session, on
# `time.monotonic()`'s clock; None without a deadline.
DEADLINE = time.monotonic() + float(_DEADLINE) if _DEADLINE else None
# One budget, from a stall's detection, for listing the office's processes, reading their native
# stacks and letting the gdb wrapper print its own. Stopping the office follows, within
# STOP_SECONDS (`stop_process`: taskkill's 30 s, then waits of 10 s and 10 s).
CAPTURE_SECONDS = 60.0
STOP_SECONDS = 60.0
CDB = Path(r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe")


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
    """Every process this one can see, or none where native stacks are not read."""
    if sys.platform == "linux":
        pids = (int(entry.name) for entry in Path("/proc").iterdir() if entry.name.isdigit())
        return [row for row in map(linux_process, pids) if row is not None]
    if sys.platform != "win32":
        return []
    listing = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_Process | Where-Object CreationDate | ForEach-Object { '{0}|{1}|"
            "{2}|{3}' -f $_.ProcessId, $_.ParentProcessId, $_.CreationDate.ToFileTimeUtc(), "
            "$_.Name }",
        ],
        capture_output=True,
        text=True,
        timeout=max(1.0, seconds),
        check=False,
    ).stdout
    rows: list[Process] = []
    for line in listing.splitlines():
        parts = line.strip().split("|", 3)
        if len(parts) == 4 and all(part.isdigit() for part in parts[:3]):
            rows.append(Process(int(parts[0]), int(parts[1]), parts[3], int(parts[2])))
    return rows


def office_processes(root: int, seconds: float) -> list[Process]:
    """Every soffice.bin that the session's launcher `root` started, directly or through others."""
    return descendants(listed_processes(seconds), root, "soffice.bin")


def run_debugger(command: list[str], path: Path, seconds: float) -> str:
    """Run a debugger with its output streamed into `path`: a timeout keeps what it wrote."""
    name = Path(command[0]).name
    with path.open("wb") as file:
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=file,
                stderr=subprocess.STDOUT,
                timeout=max(1.0, seconds),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"{name} did not finish in {seconds:.0f} s; its output so far is kept"
        except OSError as error:
            return f"{name} failed: {error!r}"
    text = path.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"^Thread \d|Id: [0-9a-f]+\.[0-9a-f]+", text, re.M):
        # Containers' default security profile refuses ptrace without the gdb wrapper.
        first = next((line for line in text.splitlines() if line.strip()), "no output")
        return f"{name} could not read the stacks: {first}"
    return f"{name} exited {completed.returncode}"


def native_stacks(target: Process, path: Path, *, debugger_parent: bool, seconds: float) -> str:
    """Write every thread's native stack of the office `target` to `path`; return how, or why not.

    Only a process that is still `target` is touched: its identity is checked while a handle to
    it is held, and the handle is held until the action ends.
    """
    if sys.platform == "linux":
        try:
            handle = os.pidfd_open(target.pid)
        except ProcessLookupError:
            return "skipped: the process had exited"
        try:
            current = linux_process(target.pid)
            if current is None or (current.name, current.started) != (target.name, target.started):
                return "skipped: its process ID no longer names the listed office"
            if debugger_parent:
                # LibreOffice's gdb wrapper already traces the office: an interrupt makes it print
                # every thread's stack into its own trace, which the session keeps, and end it.
                parent = linux_process(current.parent)
                tracer = tracer_of(target.pid)
                if parent is None or parent.name != "gdb" or tracer != parent.pid:
                    return f"skipped: not the gdb wrapper's inferior (tracer {tracer})"
                signal.pidfd_send_signal(handle, signal.SIGINT)
                return "SIGINT to the gdb wrapper's inferior; the stacks are in its gdbtrace log"
            gdb = shutil.which("gdb")
            if gdb is None:
                return "no gdb on PATH"
            how = run_debugger(
                [gdb, "-nx", "-batch", "-p", str(target.pid), "-ex", "thread apply all bt"],
                path,
                seconds,
            )
            if select.select([handle], [], [], 0)[0]:  # A pidfd turns readable when it exits.
                how += "; the office exited during the capture, so the stacks may not be its own"
            return how
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
    atomically with progress (`teardown.stall_if_idle`); otherwise it returns None. `close` ends
    the watch, unless expiry has won, in which case it waits for the capture and returns its
    evidence.
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
        self._wake = threading.Event()
        self._captured = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="stall-watch", daemon=True)

    def start(self) -> "StallWatch":
        self._thread.start()
        return self

    def follow(self, process: subprocess.Popen[str]) -> None:
        """Watch `process` from now on, as when the gdb wrapper's startup restart replaces one."""
        with self._lock:
            self.process = process

    @property
    def stalled(self) -> bool:
        with self._lock:
            return self._state == "stalled"

    def close(self) -> dict[str, Any] | None:
        """End the watch; after a stall, wait for its capture and return its evidence.

        The wait is bounded by the capture's budget and the office's stop; the evidence says
        whether they finished.
        """
        with self._lock:
            if self._state == "watching":
                self._state = "closed"
            stalled = self._state == "stalled"
        self._wake.set()
        if not stalled:
            self._thread.join(timeout=10)  # It returns at its next look at the state.
            return None
        finished = self._captured.wait(self.budget + STOP_SECONDS)
        self._update(capture_finished=finished)
        self._save()
        with self._lock:
            return json.loads(json.dumps(self._evidence))

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
                self._evidence = {
                    "cause": "deadline" if overdue else "no progress",
                    "limit_seconds": self.limit,
                    "idle_seconds": round(idle, 1),
                    "receipt": f"{self.prefix}.json",
                    "office_stacks": {},
                }
                process = self.process
            self._capture(process)

    def _capture(self, process: subprocess.Popen[str]) -> None:
        started = time.monotonic()
        end = started + self.budget
        try:
            self._save()  # The stall is on disk before any step can fail or an outer limit hits.
            self._step("client_stacks", self._client_stacks)
            targets = self._step(
                "office_processes", lambda: self.find(process.pid, end - time.monotonic())
            )
            if targets == []:
                self._update(office_search="no soffice.bin among the session's processes")
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
                with self._lock:
                    self._evidence["office_stacks"][str(target.pid)] = {
                        "method": how,
                        "file": path.name if path.exists() else None,
                    }
                self._save()
            if interrupted:  # The gdb wrapper prints the stacks, then ends the office.
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=max(0.0, end - time.monotonic()))
        finally:
            self._step("stop", lambda: self.stop(process))
            self._update(
                office_stopped=process.poll() is not None,
                capture_seconds=round(time.monotonic() - started, 1),
            )
            self._save()
            self._captured.set()

    def _client_stacks(self) -> str:
        path = self.output / f"{self.prefix}-client-stacks.txt"
        with path.open("w", encoding="utf-8") as file:
            faulthandler.dump_traceback(file, all_threads=True)
        self._update(client_stacks=path.name)
        return path.name

    def _step(self, name: str, step: Callable[[], Any]) -> Any:
        """Run one capture step; record its error and let the later steps run."""
        try:
            return step()
        except Exception:
            with self._lock:
                self._evidence.setdefault("diagnostic_errors", {})[name] = traceback.format_exc()
            self._save()
            return None

    def _update(self, **values: object) -> None:
        with self._lock:
            self._evidence.update(values)

    def _save(self) -> None:
        with self._lock:
            text = json.dumps(self._evidence, indent=2) + "\n"
        path = self.output / f"{self.prefix}.json"
        try:
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)
        except OSError as error:  # The session's result still carries the evidence.
            with self._lock:
                self._evidence["receipt_error"] = repr(error)
