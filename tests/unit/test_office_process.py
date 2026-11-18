"""A successful test body must never conceal a crashed or forcibly stopped office."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.integration.office_process import (
    StallWatch,
    assert_clean_shutdown,
    descendants,
    end_office,
    finish_process,
    normal_startup_restart,
    retain_crash_dumps,
    stop_process,
)


@pytest.mark.parametrize(
    ("code", "exit_code", "fatal"),
    [
        ("print('normal shutdown')", 0, []),
        ("raise SystemExit(7)", 7, []),
        ("print('Unspecified Application Error')", 0, ["Unspecified Application Error"]),
        ("print('Fatal exception: signal 6')", 0, ["Fatal exception"]),
    ],
)
def test_exit_and_fatal_log_validation(
    tmp_path: Path, code: str, exit_code: int, fatal: list[str]
) -> None:
    log_path = tmp_path / "soffice.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", code], stdout=log, stderr=subprocess.STDOUT, text=True
        )
        result = finish_process(process, log_path)
    assert result["office_exit_code"] == exit_code
    assert result["office_fatal_markers"] == fatal
    assert result["office_forced_shutdown"] is False
    if exit_code or fatal:
        with pytest.raises(AssertionError):
            assert_clean_shutdown(result)
    else:
        assert_clean_shutdown(result)


def test_hung_process_is_stopped_and_rejected(tmp_path: Path) -> None:
    log_path = tmp_path / "soffice.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=log, text=True
        )
        result = finish_process(process, log_path, timeout=0.1)
    assert process.poll() is not None
    assert result["office_forced_shutdown"] is True
    with pytest.raises(AssertionError):
        assert_clean_shutdown(result)


@pytest.mark.parametrize(
    ("trace", "clean"),
    [
        ("[Inferior 1 (process 123) exited normally]", True),
        ("Thread 1 received signal SIGABRT, Aborted.", False),
        ("[Inferior 1 (process 123) exited with code 0206]", False),
        ("Starting program: soffice.bin", False),
        (None, False),
    ],
)
def test_debugger_cannot_hide_inferior_failure(
    tmp_path: Path, trace: str | None, clean: bool
) -> None:
    log_path, trace_path = tmp_path / "soffice.log", tmp_path / "gdbtrace.log"
    if trace is not None:
        trace_path.write_text(trace, encoding="utf-8")
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-c", "pass"], stdout=log, text=True)
        result = finish_process(process, log_path, backtrace_path=trace_path)
    assert result["office_exit_code"] == 0
    if clean:
        assert_clean_shutdown(result)
    else:
        with pytest.raises(AssertionError):
            assert_clean_shutdown(result)


@pytest.mark.parametrize(
    ("trace", "restart"),
    [
        ("[Inferior 1 (process 123) exited with code 0121]", True),
        ("[Inferior 1 (process 123) exited with code 0117]", False),
        ("[Inferior 1 (process 123) exited normally]", False),
        ("received signal SIGABRT\nexited with code 0121", False),
        ("Unspecified Application Error\nexited with code 0121", False),
        ("exited with code 0121\nexited with code 0121", False),
    ],
)
def test_only_normal_bootstrap_restart_is_recognized(trace: str, restart: bool) -> None:
    assert normal_startup_restart(trace) is restart


def test_crash_dump_is_retained_and_rejected(tmp_path: Path) -> None:
    # On Windows a crashed office exits with status 0; its own dump must still fail the run.
    crash, output = tmp_path / "profile" / "crash", tmp_path / "output"
    crash.mkdir(parents=True)
    output.mkdir()
    (crash / "dump.ini").write_text("ProductName=LibreOffice\n", encoding="utf-8")
    assert retain_crash_dumps(crash, output, "crash-True-0") == []
    assert not list(output.iterdir()), "A profile without a dump retains nothing"
    (crash / "0f1e.dmp").write_bytes(b"MDMP")
    names = retain_crash_dumps(crash, output, "crash-True-0")
    assert names == ["crash-True-0-0f1e.dmp"]
    assert (output / "crash-True-0-0f1e.dmp").read_bytes() == b"MDMP"
    assert (output / "crash-True-0-dump.ini").exists()
    log_path = tmp_path / "soffice.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-c", "pass"], stdout=log, text=True)
        result = finish_process(process, log_path)
    assert_clean_shutdown({**result, "office_crash_dumps": []})
    with pytest.raises(AssertionError):
        assert_clean_shutdown({**result, "office_crash_dumps": names})
    assert retain_crash_dumps(tmp_path / "missing", output, "crash-True-1") == []


class Desktop:
    def __init__(self) -> None:
        self.terminate_requests = 0

    def terminate(self) -> None:
        self.terminate_requests += 1


def test_a_stalled_session_stops_its_office_without_asking_it(tmp_path: Path) -> None:
    # After a stalled main-thread callback a UNO terminate request could block for good (#50).
    log_path, desktop = tmp_path / "soffice.log", Desktop()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=log, text=True
        )
        started = time.monotonic()
        result = end_office(desktop, process, log_path, stalled=["a close timed out"])
    assert desktop.terminate_requests == 0
    assert process.poll() is not None and time.monotonic() - started < 30
    assert result["office_forced_shutdown"] is True
    assert result["office_stalled_callbacks"] == ["a close timed out"]
    with pytest.raises(AssertionError):
        assert_clean_shutdown(result)


def test_a_session_without_stalls_asks_its_office_to_terminate(tmp_path: Path) -> None:
    log_path, desktop = tmp_path / "soffice.log", Desktop()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-c", "pass"], stdout=log, text=True)
        result = end_office(desktop, process, log_path, stalled=[])
    assert desktop.terminate_requests == 1
    assert result["office_stalled_callbacks"] == []
    assert result["office_terminate_returned"] is True
    assert_clean_shutdown(result)


@pytest.mark.skipif(os.name != "nt", reason="soffice.exe runs soffice.bin as a child on Windows")
def test_stopping_the_launcher_stops_its_children_on_windows() -> None:
    code = (
        "import subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print(child.pid, flush=True); time.sleep(60)"
    )
    process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert process.stdout is not None
    child = process.stdout.readline().strip()
    stop_process(process)
    deadline = time.monotonic() + 10
    listing = ""
    while time.monotonic() < deadline:
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {child}", "/NH"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if child not in listing.split():
            break
        time.sleep(0.2)
    assert child not in listing.split(), listing


class BlockedDesktop:
    """A terminate request held by a dialog that nobody answers (#40)."""

    def __init__(self) -> None:
        self.terminate_requests = 0

    def terminate(self) -> None:
        self.terminate_requests += 1
        time.sleep(60)


def test_a_terminate_request_held_by_a_dialog_stops_the_office(tmp_path: Path) -> None:
    log_path, desktop = tmp_path / "soffice.log", BlockedDesktop()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=log, text=True
        )
        started = time.monotonic()
        result = end_office(desktop, process, log_path, stalled=[], grace=0.5)
    assert desktop.terminate_requests == 1
    assert process.poll() is not None and time.monotonic() - started < 30
    assert result["office_terminate_returned"] is False
    assert result["office_forced_shutdown"] is True
    with pytest.raises(AssertionError):
        assert_clean_shutdown(result)


def sleeper() -> subprocess.Popen[str]:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], text=True)


def test_a_session_without_progress_keeps_its_stacks_and_stops_its_office(
    tmp_path: Path,
) -> None:
    # A UNO call that never returns would hold the client until the job's limit (#45).
    process = sleeper()
    stalls: list[str] = []
    stacks: list[tuple[int, bool]] = []

    def native(pid: int, path: Path, *, debugger_parent: bool) -> str:
        stacks.append((pid, debugger_parent))
        path.write_text("Thread 1 (main)", encoding="utf-8")
        return "fake debugger"

    watch = StallWatch(
        process,
        tmp_path,
        "stall-True-0",
        idle=lambda: 1.0,
        stalled=stalls.append,
        limit=0.2,
        find=lambda office: [office.pid],
        stacks=native,
    ).start()
    deadline = time.monotonic() + 20
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    watch.close()
    assert process.poll() is not None
    assert stacks == [(process.pid, False)]
    assert len(stalls) == 1 and "No test progress" in stalls[0]
    assert watch.evidence is not None
    office = f"stall-True-0-office-{process.pid}-stacks.txt"
    assert watch.evidence["office_stacks"] == {
        str(process.pid): {"method": "fake debugger", "file": office}
    }
    client = (tmp_path / "stall-True-0-client-stacks.txt").read_text(encoding="utf-8")
    assert "most recent call first" in client


def test_progress_keeps_the_watch_from_stopping_the_office(tmp_path: Path) -> None:
    process = sleeper()
    stalls: list[str] = []
    watch = StallWatch(
        process,
        tmp_path,
        "stall-True-0",
        idle=lambda: 0.0,
        stalled=stalls.append,
        limit=0.2,
        find=lambda office: [office.pid],
        stacks=lambda *args, **kwargs: "unused",
    ).start()
    time.sleep(1)
    watch.close()
    try:
        assert process.poll() is None
        assert stalls == [] and watch.evidence is None
        assert not list(tmp_path.iterdir())
    finally:
        stop_process(process)


def test_only_the_sessions_own_offices_are_found() -> None:
    rows = [
        (10, 1, "python"),
        (11, 10, "soffice.exe"),
        (12, 11, "soffice.bin"),
        (13, 12, "/opt/lo/program/soffice.bin"),
        (20, 1, "soffice.bin"),  # Another session's office.
        (21, 20, "soffice.bin"),
    ]
    assert descendants(rows, 10, "soffice.bin") == [12, 13]
    assert descendants(rows, 99, "soffice.bin") == []
