"""Collect and validate private office process shutdown without a UNO dependency.

A UNO call that never returns blocks the test client until its job's time limit, which then
leaves no evidence. Integration and UI stalls of this kind were seen without native stacks
(#45). `StallWatch` therefore ends a session that makes no progress for `STALL_SECONDS`
(default 15 minutes, overridden by `SHEET_MANAGER_STALL_SECONDS`): it saves the client's Python
stacks and the office's native stacks, records the stall, and stops the office, so that the
blocked call fails and the session fails with that evidence. The limit is not a test timeout:
the slowest measured suite took about 7 minutes (macOS `test_reorder`), and nothing waits for
it. Never shorten it to speed up a run, and never let it turn a failure into a pass.
"""

import faulthandler
import os
import re
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

FATAL_MARKERS = ("Unspecified Application Error", "Fatal exception")
STALL_SECONDS = float(os.environ.get("SHEET_MANAGER_STALL_SECONDS", "900"))
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


def descendants(rows: list[tuple[int, int, str]], root: int, name: str) -> list[int]:
    """Process IDs named `name` among `root`'s descendants, from (pid, parent, name) rows."""
    children: dict[int, list[int]] = {}
    names: dict[int, str] = {}
    for pid, parent, process_name in rows:
        children.setdefault(parent, []).append(pid)
        names[pid] = Path(process_name).name
    found: list[int] = []
    pending, seen = [root], {root}
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in seen:
                seen.add(child)
                pending.append(child)
                if names[child] == name:
                    found.append(child)
    return sorted(found)


def office_processes(process: subprocess.Popen[str]) -> list[int]:
    """Every soffice.bin that this session's process started, directly or through others."""
    if os.name == "nt":
        command = [
            "pwsh",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | ForEach-Object "
            "{ '{0}|{1}|{2}' -f $_.ProcessId, $_.ParentProcessId, $_.Name }",
        ]
    else:
        command = ["ps", "-A", "-o", "pid=,ppid=,comm="]
    try:
        listing = subprocess.run(
            command, capture_output=True, text=True, timeout=60, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: list[tuple[int, int, str]] = []
    for line in listing.splitlines():
        parts = line.split("|", 2) if os.name == "nt" else line.split(None, 2)
        if len(parts) == 3 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2].strip()))
    return descendants(rows, process.pid, "soffice.bin")


def native_stacks(pid: int, path: Path, *, debugger_parent: bool) -> str:
    """Write every thread's native stack of office `pid` to `path`; return how, or why not."""
    if debugger_parent:
        # LibreOffice's gdb wrapper already traces the office: an interrupt makes it print every
        # thread's stack into its own trace, which the session keeps, and end the office.
        os.kill(pid, signal.SIGINT)
        return "SIGINT to the gdb wrapper's inferior; the stacks are in its gdbtrace log"
    if os.name == "nt":
        if not CDB.exists():
            return f"no CDB at {CDB}"
        command = [str(CDB), "-pv", "-p", str(pid), "-c", "~*kc 60; q"]
    else:
        gdb = shutil.which("gdb")
        if gdb is None:
            return "no gdb on PATH"
        command = [gdb, "-nx", "-batch", "-p", str(pid), "-ex", "thread apply all bt"]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=300, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"{Path(command[0]).name} failed: {error!r}"
    text = completed.stdout + completed.stderr
    path.write_text(text, encoding="utf-8")
    if not re.search(r"^Thread \d|Id: [0-9a-f]+\.[0-9a-f]+", text, re.M):
        # Containers' default security profile refuses ptrace without the gdb wrapper.
        first = next((line for line in text.splitlines() if line.strip()), "no output")
        return f"{Path(command[0]).name} could not read the stacks: {first}"
    return f"{Path(command[0]).name} exited {completed.returncode}"


class StallWatch:
    """End a session that makes no progress for `limit` seconds, keeping its stacks first."""

    def __init__(
        self,
        process: subprocess.Popen[str],
        output: Path,
        prefix: str,
        *,
        idle: Callable[[], float],
        stalled: Callable[[str], None],
        debugger_parent: bool = False,
        limit: float = STALL_SECONDS,
        find: Callable[[subprocess.Popen[str]], list[int]] = office_processes,
        stacks: Callable[..., str] = native_stacks,
        stop: Callable[[subprocess.Popen[str]], None] = stop_process,
    ) -> None:
        self.process, self.output, self.prefix = process, output, prefix
        self.idle, self.stalled, self.limit = idle, stalled, limit
        self.debugger_parent = debugger_parent
        self.find, self.stacks, self.stop = find, stacks, stop
        self.evidence: dict[str, object] | None = None
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="stall-watch", daemon=True)

    def start(self) -> "StallWatch":
        self._thread.start()
        return self

    def close(self) -> None:
        """Stop watching; a capture already under way finishes first."""
        self._done.set()
        self._thread.join(timeout=900)

    def _watch(self) -> None:
        while not self._done.wait(min(5.0, self.limit / 4)):
            idle = self.idle()
            if idle >= self.limit and self.process.poll() is None:
                self._capture(idle)
                return

    def _capture(self, idle: float) -> None:
        evidence: dict[str, object] = {"limit_seconds": self.limit, "idle_seconds": round(idle, 1)}
        client = self.output / f"{self.prefix}-client-stacks.txt"
        with client.open("w", encoding="utf-8") as file:
            faulthandler.dump_traceback(file, all_threads=True)
        evidence["client_stacks"] = client.name
        office: dict[str, object] = {}
        for pid in self.find(self.process):
            path = self.output / f"{self.prefix}-office-{pid}-stacks.txt"
            how = self.stacks(pid, path, debugger_parent=self.debugger_parent)
            office[str(pid)] = {"method": how, "file": path.name if path.exists() else None}
        evidence["office_stacks"] = office
        if self.debugger_parent:
            with suppress(subprocess.TimeoutExpired):
                self.process.wait(timeout=60)  # The wrapper prints the stacks, then exits.
        self.stalled(
            f"No test progress for {self.limit:.0f} s; the client's and the office's stacks "
            "were saved and the office was stopped"
        )
        self.evidence = evidence
        self.stop(self.process)
