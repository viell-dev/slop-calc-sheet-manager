"""Collect and validate private office process shutdown without a UNO dependency."""

import os
import re
import shutil
import subprocess
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

FATAL_MARKERS = ("Unspecified Application Error", "Fatal exception")


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
