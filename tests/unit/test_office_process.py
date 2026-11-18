"""A successful test body must never conceal a crashed or forcibly stopped office."""

import dataclasses
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.integration import office_process, teardown
from tests.integration.office_process import (
    Process,
    StallWatch,
    assert_clean_shutdown,
    descendants,
    end_office,
    finish_process,
    native_stacks,
    normal_startup_restart,
    office_processes,
    retain_crash_dumps,
    run_debugger,
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


@pytest.fixture
def session() -> Iterator[None]:
    teardown.start_session()
    yield
    teardown.start_session()


def offices(*targets: Process) -> Callable[[int, float], list[Process]]:
    """A process search that finds `targets`, as `office_processes` would."""

    def find(root: int, seconds: float) -> list[Process]:
        return list(targets)

    return find


def watch(process: subprocess.Popen[str], output: Path, **options: Any) -> StallWatch:
    """A watch over `process` with the runner's own progress and a short limit."""
    defaults: dict[str, Any] = {"expire": teardown.stall_if_idle, "limit": 0.2, "find": offices()}
    return StallWatch(process, output, "stall-True-0", **(defaults | options))


def wait_until(condition: Callable[[], object], seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "Timed out"
        time.sleep(0.02)


def test_a_session_without_progress_keeps_its_stacks_and_stops_its_office(
    tmp_path: Path, session: None
) -> None:
    # A UNO call that never returns would hold the client until the job's limit (#45).
    process = sleeper()
    target = Process(process.pid, os.getpid(), "soffice.bin", 1)
    seen: list[tuple[Process, bool, list[str], bool]] = []

    def native(found: Process, path: Path, *, debugger_parent: bool, seconds: float) -> str:
        # The stall is recorded and on disk before any stack is read.
        receipt = (tmp_path / "stall-True-0.json").exists()
        seen.append((found, debugger_parent, teardown.stalled_callbacks(), receipt))
        assert 0 < seconds <= 60
        path.write_text("Thread 1 (main)", encoding="utf-8")
        return "fake debugger"

    stall = watch(process, tmp_path, find=offices(target), stacks=native).start()
    wait_until(lambda: process.poll() is not None)
    evidence = stall.close()
    assert evidence is not None
    ((found, debugger_parent, stalled, receipt),) = seen
    assert found == target and debugger_parent is False and receipt
    assert len(stalled) == 1 and "No test progress" in stalled[0]
    assert evidence["office_stacks"] == {
        str(process.pid): {
            "method": "fake debugger",
            "file": f"stall-True-0-office-{process.pid}-stacks.txt",
        }
    }
    assert evidence["office_stopped"] and evidence["capture_finished"]
    assert evidence["cause"] == "no progress" and evidence["idle_seconds"] >= 0.2
    client = (tmp_path / "stall-True-0-client-stacks.txt").read_text(encoding="utf-8")
    assert "most recent call first" in client
    receipt_text = (tmp_path / "stall-True-0.json").read_text(encoding="utf-8")
    assert json.loads(receipt_text) == evidence
    with pytest.raises(AssertionError):
        assert_clean_shutdown(
            {
                "office_exit_code": 0,
                "office_forced_shutdown": False,
                "office_fatal_markers": [],
                "office_progress_stall": evidence,
            }
        )


def test_progress_keeps_the_watch_from_stopping_the_office(tmp_path: Path, session: None) -> None:
    process = sleeper()
    stall = watch(process, tmp_path).start()
    try:
        started = time.monotonic()
        while time.monotonic() - started < 1:  # Five limits, with progress every quarter.
            teardown.note_progress()
            time.sleep(0.05)
        assert stall.close() is None
        assert process.poll() is None
        assert teardown.stalled_callbacks() == []
        assert not list(tmp_path.iterdir())
        assert teardown.longest_progress_interval() < 0.2
    finally:
        stop_process(process)


@pytest.mark.parametrize("expired", [False, True])
def test_closing_and_expiry_are_one_decision(tmp_path: Path, session: None, expired: bool) -> None:
    # The reviewer's race: progress and close() arrive while the watch is deciding. Whichever
    # wins, the outcome is consistent: close() returns evidence exactly when the office stopped.
    process = sleeper()
    deciding, closed = threading.Event(), threading.Event()
    outcome: list[dict[str, Any] | None] = []

    def expire(limit: float, message: str, overdue: bool) -> float | None:
        if deciding.is_set():
            return None  # Only the first decision races.
        deciding.set()
        teardown.note_progress()  # Progress arrives during the decision...
        closer = threading.Thread(target=lambda: (outcome.append(stall.close()), closed.set()))
        closer.start()  # ...and so does the session's end.
        assert not closed.wait(0.3), "close() did not wait for the decision"
        return teardown.stall_if_idle(0, message) if expired else None

    stall = watch(process, tmp_path, expire=expire)
    stall.start()
    try:
        assert deciding.wait(10) and closed.wait(20)
        (evidence,) = outcome
        if expired:
            assert evidence is not None and evidence["office_stopped"]
            assert process.poll() is not None and teardown.stalled_callbacks()
        else:
            assert evidence is None and process.poll() is None
            assert teardown.stalled_callbacks() == []
            time.sleep(0.5)  # The watch has ended: nothing stops the office later.
            assert process.poll() is None
    finally:
        stop_process(process)


def test_no_close_or_restore_starts_while_stacks_are_taken(tmp_path: Path, session: None) -> None:
    process = sleeper()
    capturing, release = threading.Event(), threading.Event()

    def slow(target: Process, path: Path, **options: Any) -> str:
        capturing.set()
        assert release.wait(20)
        return "slow debugger"

    target = Process(process.pid, os.getpid(), "soffice.bin", 1)
    stall = watch(process, tmp_path, find=offices(target), stacks=slow).start()
    assert capturing.wait(20)
    calls: list[str] = []
    with (
        pytest.raises(TimeoutError),
        teardown.Configured(lambda: None, lambda: calls.append("restore")),
    ):
        teardown.close_leftovers(["document"], lambda _: calls.append("close"), None)
    assert calls == []
    release.set()
    evidence = stall.close()
    assert evidence is not None and evidence["office_stopped"]


def test_a_capture_that_hangs_ends_the_wait_within_its_budget(
    tmp_path: Path, session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(office_process, "STOP_SECONDS", 0.2)
    process = sleeper()
    entered, release = threading.Event(), threading.Event()

    def hung(target: Process, path: Path, **options: Any) -> str:
        entered.set()
        release.wait(30)
        return "too late"

    target = Process(process.pid, os.getpid(), "soffice.bin", 1)
    stall = watch(process, tmp_path, budget=0.3, find=offices(target), stacks=hung).start()
    try:
        assert entered.wait(20)
        started = time.monotonic()
        evidence = stall.close()
        assert time.monotonic() - started < 2
        assert evidence is not None and evidence["capture_finished"] is False
        assert teardown.stalled_callbacks()  # The session still fails and stops its office.
    finally:
        release.set()
        stop_process(process)


def test_every_failed_capture_step_is_recorded_and_the_office_still_stops(
    tmp_path: Path, session: None
) -> None:
    process = sleeper()

    def broken_find(root: int, seconds: float) -> list[Process]:
        raise OSError("process listing failed")

    stall = watch(process, tmp_path, find=broken_find).start()
    wait_until(lambda: process.poll() is not None)
    evidence = stall.close()
    assert evidence is not None and evidence["office_stopped"]
    assert "process listing failed" in evidence["diagnostic_errors"]["office_processes"]
    assert "office_search" not in evidence  # A failed search is not "no office found".
    assert teardown.stalled_callbacks()


def skipped(*args: Any, **kwargs: Any) -> str:
    return "skipped: not the gdb wrapper's inferior (tracer 0)"


def test_an_interrupt_waits_for_the_gdb_wrapper_only_when_it_was_sent(
    tmp_path: Path, session: None
) -> None:
    process = sleeper()
    target = Process(process.pid, os.getpid(), "soffice.bin", 1)
    stall = watch(
        process,
        tmp_path,
        debugger_parent=True,
        budget=30,
        find=offices(target),
        stacks=skipped,
    ).start()
    started = time.monotonic()
    wait_until(lambda: process.poll() is not None)
    assert time.monotonic() - started < 10  # Not the 30 s budget.
    evidence = stall.close()
    assert evidence is not None
    assert evidence["office_stacks"][str(process.pid)]["method"].startswith("skipped")


def test_a_debugger_that_times_out_keeps_its_output(tmp_path: Path) -> None:
    path = tmp_path / "stacks.txt"
    writes_then_hangs = (
        "import sys, time; sys.stdout.buffer.write(b'Thread 1 frames\\xff\\n'); "
        "sys.stdout.flush(); time.sleep(60)"
    )
    how = run_debugger([sys.executable, "-c", writes_then_hangs], path, seconds=2)
    assert "did not finish in 2 s" in how
    assert path.read_bytes().startswith(b"Thread 1 frames\xff")
    finished = run_debugger([sys.executable, "-c", "print('\\xff no stacks')"], path, seconds=10)
    assert "could not read the stacks" in finished


def test_only_the_sessions_own_offices_are_found() -> None:
    rows = [
        Process(10, 1, "python", 100),
        Process(11, 10, "soffice.exe", 110),
        Process(12, 11, "soffice.bin", 120),
        Process(13, 12, "/opt/lo/program/soffice.bin", 130),
        Process(20, 1, "soffice.bin", 200),  # Another session's office.
        Process(21, 20, "soffice.bin", 210),
        # An older office whose dead parent's ID the launcher now has (Windows keeps it).
        Process(30, 11, "soffice.bin", 105),
        Process(31, 30, "soffice.bin", 106),
    ]
    assert [row.pid for row in descendants(rows, 10, "soffice.bin")] == [12, 13]
    assert descendants(rows, 99, "soffice.bin") == []


@pytest.mark.skipif(sys.platform != "linux", reason="Linux identifies processes through /proc")
def test_a_real_office_tree_is_found_and_a_changed_identity_is_skipped(tmp_path: Path) -> None:
    office = tmp_path / "soffice.bin"
    shutil.copyfile(shutil.which("sleep") or "/bin/sleep", office)
    office.chmod(0o755)
    launcher = subprocess.Popen(
        ["sh", "-c", f'"{office}" 60 & "{office}" 60 & wait'], start_new_session=True
    )
    try:
        wait_until(lambda: len(office_processes(launcher.pid, 10)) == 2)
        found = office_processes(launcher.pid, 10)
        assert all(row.parent == launcher.pid and row.name == "soffice.bin" for row in found)
        assert office_processes(os.getpid(), 10) == found  # Grandchildren of this test too.
        assert office_processes(found[0].pid, 10) == []
        stale = dataclasses.replace(found[0], started=found[0].started - 1)
        assert "no longer names" in native_stacks(
            stale, tmp_path / "x.txt", debugger_parent=False, seconds=5
        )
        # An office that is not a gdb inferior never gets the wrapper's interrupt.
        how = native_stacks(found[1], tmp_path / "y.txt", debugger_parent=True, seconds=5)
        assert how.startswith("skipped: not the gdb wrapper's inferior")
    finally:
        if sys.platform != "win32":
            os.killpg(launcher.pid, signal.SIGKILL)
        launcher.wait()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows lists processes through CIM")
def test_a_real_office_tree_is_found_on_windows(tmp_path: Path) -> None:
    office = tmp_path / "soffice.bin"
    shutil.copyfile(Path(os.environ["SYSTEMROOT"], "System32", "PING.EXE"), office)
    child = subprocess.Popen([str(office), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        found = office_processes(os.getpid(), 60)
        assert [row.pid for row in found] == [child.pid]
        stale = dataclasses.replace(found[0], started=found[0].started - 10)
        assert (
            "no longer names"
            in native_stacks(stale, tmp_path / "x.txt", debugger_parent=False, seconds=5)
            or not office_process.CDB.exists()
        )
    finally:
        child.kill()
        child.wait()
