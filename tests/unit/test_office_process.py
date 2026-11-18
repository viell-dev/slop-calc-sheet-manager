"""A successful test body must never conceal a crashed or forcibly stopped office."""

import dataclasses
import json
import os
import select
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
    StackAttempt,
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


def no_releases(limit: float) -> None:
    """The release wait of a session whose office has nothing left to run."""
    return None


def test_a_stalled_session_stops_its_office_without_asking_it(tmp_path: Path) -> None:
    # After a stalled main-thread callback a UNO terminate request could block for good (#50).
    log_path, desktop = tmp_path / "soffice.log", Desktop()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=log, text=True
        )
        started = time.monotonic()
        result = end_office(
            desktop, process, log_path, stalled=["a close timed out"], settle=no_releases
        )
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
        result = end_office(desktop, process, log_path, stalled=[], settle=no_releases)
    assert desktop.terminate_requests == 1
    assert result["office_stalled_callbacks"] == []
    assert result["office_terminate_returned"] is True
    assert isinstance(result["office_shutdown_seconds"], float)
    assert_clean_shutdown(result)


def test_queued_releases_settle_before_the_office_is_asked(tmp_path: Path) -> None:
    # An office that exits while it still runs this process's UNO releases can crash (#242).
    log_path, desktop = tmp_path / "soffice.log", Desktop()
    calls: list[tuple[float, int]] = []

    def settle(limit: float) -> None:
        calls.append((limit, desktop.terminate_requests))
        time.sleep(0.2)

    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-c", "pass"], stdout=log, text=True)
        result = end_office(desktop, process, log_path, stalled=[], grace=7, settle=settle)
    assert len(calls) == 1, "Settle once"
    limit, requests = calls[0]
    assert 6.5 < limit <= 7 and requests == 0, "Settle within the grace period, before asking"
    assert desktop.terminate_requests == 1
    assert result["office_unsettled_releases"] is None
    assert isinstance(result["office_release_wait_seconds"], float)
    assert result["office_release_wait_seconds"] >= 0.2
    assert_clean_shutdown(result)


def test_unsettled_releases_stop_the_office_without_asking(tmp_path: Path) -> None:
    log_path, desktop = tmp_path / "soffice.log", Desktop()
    reason = "LibreOffice did not run this process's UNO releases within 0.5 s"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=log, text=True
        )
        started = time.monotonic()
        result = end_office(
            desktop, process, log_path, stalled=[], grace=0.5, settle=lambda limit: reason
        )
    assert desktop.terminate_requests == 0
    assert process.poll() is not None and time.monotonic() - started < 30
    assert result["office_unsettled_releases"] == reason
    assert result["office_forced_shutdown"] is True
    with pytest.raises(AssertionError):
        assert_clean_shutdown(result)
    # The reason alone fails a session, even one whose office happened to exit cleanly.
    exited = {**result, "office_exit_code": 0, "office_forced_shutdown": False}
    assert_clean_shutdown({**exited, "office_unsettled_releases": None})
    with pytest.raises(AssertionError):
        assert_clean_shutdown(exited)


def test_a_stalled_session_does_not_wait_for_releases(tmp_path: Path) -> None:
    # A release that needs the stuck main thread's lock would never run (#50).
    log_path, desktop = tmp_path / "soffice.log", Desktop()
    calls: list[float] = []
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=log, text=True
        )
        result = end_office(
            desktop, process, log_path, stalled=["a close timed out"], settle=calls.append
        )
    assert calls == [] and desktop.terminate_requests == 0
    assert result["office_forced_shutdown"] is True
    assert result["office_unsettled_releases"] is None


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
        result = end_office(desktop, process, log_path, stalled=[], grace=0.5, settle=no_releases)
    assert desktop.terminate_requests == 1
    assert process.poll() is not None and time.monotonic() - started < 30
    assert result["office_terminate_returned"] is False
    assert result["office_forced_shutdown"] is True
    with pytest.raises(AssertionError):
        assert_clean_shutdown(result)


def test_a_long_release_wait_leaves_the_terminate_request_only_the_remainder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Graceful shutdown has one deadline: a wait that uses most of it leaves a held terminate
    # request only what is left, rather than a fresh grace period of its own.
    log_path, desktop = tmp_path / "soffice.log", BlockedDesktop()
    limits: list[float] = []
    request = office_process.request_termination

    def recorded(desktop: object, timeout: float) -> bool:
        limits.append(timeout)
        return request(desktop, timeout)

    def settle(limit: float) -> None:
        time.sleep(1.6)

    monkeypatch.setattr(office_process, "request_termination", recorded)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=log, text=True
        )
        started = time.monotonic()
        result = end_office(desktop, process, log_path, stalled=[], grace=2, settle=settle)
        elapsed = time.monotonic() - started
    assert len(limits) == 1 and limits[0] <= 0.45, limits
    assert elapsed < 3, "Graceful shutdown must end within its one grace period"
    assert desktop.terminate_requests == 1
    assert result["office_unsettled_releases"] is None, "The wait itself finished in time"
    assert result["office_terminate_returned"] is False
    assert result["office_forced_shutdown"] is True
    with pytest.raises(AssertionError):
        assert_clean_shutdown(result)


def test_a_long_release_wait_leaves_the_exit_only_the_remainder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path, desktop = tmp_path / "soffice.log", Desktop()
    timeouts: list[float] = []
    finish = office_process.finish_process

    def recorded(
        process: subprocess.Popen[str],
        log_path: Path,
        *,
        timeout: float = 30,
        backtrace_path: Path | None = None,
    ) -> dict[str, object]:
        timeouts.append(timeout)
        return finish(process, log_path, timeout=timeout, backtrace_path=backtrace_path)

    def settle(limit: float) -> None:
        time.sleep(1.6)

    monkeypatch.setattr(office_process, "finish_process", recorded)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdout=log, text=True
        )
        result = end_office(desktop, process, log_path, stalled=[], grace=2, settle=settle)
    assert len(timeouts) == 1 and timeouts[0] <= 0.45, timeouts
    assert result["office_terminate_returned"] is True
    assert result["office_forced_shutdown"] is True


def sleeper() -> subprocess.Popen[str]:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], text=True)


@pytest.fixture
def session() -> Iterator[None]:
    teardown.start_session()
    yield
    teardown.start_session()


def offices(*targets: Process) -> Callable[[int, float], list[Process]]:
    """A process search that finds `targets`, as `office_processes` would."""

    def find(root: int, end: float) -> list[Process]:
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


def test_a_session_without_progress_tries_its_stacks_and_stops_its_launcher(
    tmp_path: Path, session: None
) -> None:
    # A UNO call that never returns would hold the client until the job's limit (#45).
    process = sleeper()
    target = Process(process.pid, os.getpid(), "soffice.bin", 1)
    seen: list[tuple[Process, bool, list[str], bool]] = []

    def native(found: Process, path: Path, *, debugger_parent: bool, end: float) -> StackAttempt:
        # The stall is recorded and on disk before any stack is read.
        receipt = (tmp_path / "stall-True-0.json").exists()
        seen.append((found, debugger_parent, teardown.stalled_callbacks(), receipt))
        assert 0 < end - time.monotonic() <= 60
        path.write_text("Thread 1 (main)", encoding="utf-8")
        return StackAttempt("fake debugger")

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
    assert evidence["launcher_exit_status"] is not None and evidence["watch_finished"]
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


def test_progress_keeps_the_watch_from_stopping_the_launcher(tmp_path: Path, session: None) -> None:
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
            assert evidence is not None and evidence["launcher_exit_status"] is not None
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

    def slow(target: Process, path: Path, **options: Any) -> StackAttempt:
        capturing.set()
        assert release.wait(20)
        return StackAttempt("slow debugger")

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
    assert evidence is not None and evidence["launcher_exit_status"] is not None


def test_a_hung_collector_cannot_delay_the_stop(tmp_path: Path, session: None) -> None:
    # The client is blocked in UNO, so nothing calls close(), and a collector hangs as well. The
    # office still stops when the capture's budget ends, and the receipt says why.
    process = sleeper()
    entered, release = threading.Event(), threading.Event()

    def hung(target: Process, path: Path, **options: Any) -> StackAttempt:
        entered.set()
        release.wait(30)
        return StackAttempt("too late")

    target = Process(process.pid, os.getpid(), "soffice.bin", 1)
    stall = watch(process, tmp_path, budget=0.5, find=offices(target), stacks=hung).start()
    try:
        assert entered.wait(20)
        started = time.monotonic()
        wait_until(lambda: process.poll() is not None, seconds=5)
        assert time.monotonic() - started < 2
        receipt = tmp_path / "stall-True-0.json"
        wait_until(lambda: "watch_finished" in json.loads(receipt.read_text(encoding="utf-8")))
        evidence = json.loads(receipt.read_text(encoding="utf-8"))
        assert (
            evidence["launcher_exit_status"] is not None
            and evidence["collection_finished"] is False
        )
        assert evidence["diagnostic_errors"]["capture"].startswith(
            f"the collector was at office_{process.pid} when"
        )
        release.set()  # The collector returns late; what it brings is no longer recorded.
        time.sleep(0.3)
        closed = stall.close()
        assert closed is not None and closed["office_stacks"] == {}
        assert json.loads(receipt.read_text(encoding="utf-8")) == closed
    finally:
        release.set()
        stop_process(process)


def test_a_collector_past_its_budget_starts_no_further_step(
    tmp_path: Path, session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = sleeper()
    entered, release = threading.Event(), threading.Event()
    searches: list[float] = []

    def hung_dump(file: Any, all_threads: bool) -> None:
        entered.set()
        release.wait(30)

    def find(root: int, end: float) -> list[Process]:
        searches.append(end)
        return []

    monkeypatch.setattr(office_process.faulthandler, "dump_traceback", hung_dump)
    stall = watch(process, tmp_path, budget=0.3, find=find).start()
    try:
        assert entered.wait(20)
        wait_until(lambda: process.poll() is not None, seconds=5)
        release.set()
        time.sleep(0.3)
        assert searches == [], "The process listing ran after the capture's budget"
        evidence = stall.close()
        assert evidence is not None and evidence["collection_finished"] is False
        assert evidence["diagnostic_errors"]["capture"].startswith(
            "the collector was at client_stacks when"
        )
    finally:
        release.set()
        stop_process(process)


def test_close_bounds_its_wait_when_the_stop_itself_hangs(
    tmp_path: Path, session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(office_process, "STOP_SECONDS", 0.2)
    process = sleeper()
    release = threading.Event()

    def hung_stop(process: subprocess.Popen[str]) -> None:
        release.wait(30)

    stall = watch(process, tmp_path, budget=0.2, stop=hung_stop).start()
    try:
        wait_until(teardown.stalled_callbacks)
        started = time.monotonic()
        evidence = stall.close()
        assert time.monotonic() - started < 0.2 + 0.2 + 2 + 1
        # The wait ended first; that is the caller's fact, not the capture's.
        assert stall.wait_timed_out
        assert evidence is not None and "watch_finished" not in evidence
        assert teardown.stalled_callbacks()  # The session still fails, and the runner stops it.
    finally:
        release.set()
        stop_process(process)


def test_the_receipt_is_never_replaced_by_an_older_snapshot(
    tmp_path: Path, session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A close() that stopped waiting wrote a snapshot taken then; descheduled before writing it,
    # it replaced the watch's final receipt. The receipt must end as the evidence close() returns.
    monkeypatch.setattr(office_process, "STOP_SECONDS", 0.1)
    process = sleeper()
    receipt = tmp_path / "stall-True-0.json"
    capturing, release = threading.Event(), threading.Event()

    def slow(target: Process, path: Path, **options: Any) -> StackAttempt:
        capturing.set()
        assert release.wait(20)
        return StackAttempt("collected")

    write, main = Path.write_text, threading.main_thread()

    def descheduled(path: Path, text: str, *args: Any, **kwargs: Any) -> int:
        if path.name.startswith(receipt.name) and threading.current_thread() is main:
            release.set()  # Let the watch finish, as if this thread were descheduled meanwhile.
            wait_until(lambda: "launcher_exit_status" in receipt.read_text(encoding="utf-8"))
        return write(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", descheduled)
    target = Process(process.pid, os.getpid(), "soffice.bin", 1)
    stall = watch(process, tmp_path, budget=0.1, find=offices(target), stacks=slow).start()
    try:
        assert capturing.wait(20)
        evidence = stall.close()
        assert evidence is not None and evidence["launcher_exit_status"] is not None
        assert json.loads(receipt.read_text(encoding="utf-8")) == evidence
    finally:
        release.set()
        stop_process(process)


@pytest.mark.parametrize("passed", [False, True])
def test_a_close_ends_the_watch_only_before_the_deadline(
    tmp_path: Path, session: None, passed: bool
) -> None:
    # The checks end after the deadline but before the watch's next look, which is 5 s away
    # here. A close then records the stall: a watch that closed must mean that the checks ended
    # before the deadline, which the soak's summary relies on (#45).
    process = sleeper()
    stall = watch(process, tmp_path, limit=100.0).start()
    try:
        time.sleep(0.1)  # The watch is waiting for its next look.
        stall.deadline = time.monotonic() + (-0.01 if passed else 30)
        evidence = stall.close()
        if passed:
            assert evidence is not None and evidence["cause"] == "deadline"
            assert evidence["launcher_exit_status"] is not None and evidence["watch_finished"]
            assert "deadline" in teardown.stalled_callbacks()[0]
        else:
            assert evidence is None and process.poll() is None
            assert teardown.stalled_callbacks() == []
    finally:
        stop_process(process)


@pytest.mark.parametrize("held", ["first", "intermediate"])
def test_a_held_receipt_write_neither_delays_the_stop_nor_admits_a_late_result(
    tmp_path: Path, session: None, monkeypatch: pytest.MonkeyPatch, held: str
) -> None:
    # A receipt write is held, the first or the one after the client's stacks, while the
    # collector returns its result just after the budget's end. The stop still starts at that
    # end, and the late result is never recorded as part of a finished capture.
    budget = 0.4
    process = sleeper()
    holding, release = threading.Event(), threading.Event()
    times: dict[str, float] = {}
    replace = os.replace

    def held_replace(source: Any, target: Any) -> None:
        written = Path(source).read_text(encoding="utf-8")
        due = held == "first" or "client_stacks" in written
        if Path(target).name == "stall-True-0.json" and due and not holding.is_set():
            times["held"] = time.monotonic()
            holding.set()
            release.wait(10)
        replace(source, target)

    def late(target: Process, path: Path, *, end: float, **options: Any) -> StackAttempt:
        times["end"] = end
        time.sleep(max(0.0, end + 0.05 - time.monotonic()))
        times["returned"] = time.monotonic()
        return StackAttempt("a result after the budget's end")

    def timed_stop(office: subprocess.Popen[str]) -> None:
        times["stop"] = time.monotonic()
        stop_process(office)

    monkeypatch.setattr(office_process.os, "replace", held_replace)
    target = Process(process.pid, os.getpid(), "soffice.bin", 1)
    stall = watch(
        process, tmp_path, budget=budget, find=offices(target), stacks=late, stop=timed_stop
    ).start()
    try:
        assert holding.wait(20)
        wait_until(lambda: process.poll() is not None, seconds=5)
        assert not release.is_set()  # Stopped while the write was still held.
        if held == "first":
            assert times["stop"] - times["held"] < budget + 0.5
            assert "end" not in times  # No step ran before the stall was on disk.
        else:
            assert -0.05 < times["stop"] - times["end"] < 0.5
            wait_until(lambda: "returned" in times)  # The late result arrives during the hold.
            time.sleep(0.2)
        release.set()
        evidence = stall.close()
        assert evidence is not None and evidence["launcher_exit_status"] is not None
        assert evidence["office_stacks"] == {} and evidence["collection_finished"] is False
        assert "the collector was at " in evidence["diagnostic_errors"]["capture"]
        receipt = json.loads((tmp_path / "stall-True-0.json").read_text(encoding="utf-8"))
        assert receipt == evidence
    finally:
        release.set()
        stop_process(process)


def test_a_slow_start_does_not_extend_a_collectors_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Starting a process can be slow, such as under on-access scanning on Windows. The command
    # still ends at the capture's end, not that long after it started.
    started: list[subprocess.Popen[Any]] = []
    returned: list[float] = []
    popen = subprocess.Popen

    def slow_start(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        process: subprocess.Popen[Any] = popen(*args, **kwargs)
        started.append(process)
        time.sleep(1.0)
        returned.append(time.monotonic())
        return process

    monkeypatch.setattr(office_process.subprocess, "Popen", slow_start)
    command = [sys.executable, "-c", "import time; time.sleep(5)"]
    with (tmp_path / "out").open("wb") as out:
        assert office_process.run_collector(command, out, time.monotonic() + 0.5) is None
        # Killed and reaped as soon as its start returned, not 0.5 s later.
        assert time.monotonic() - returned[0] < 0.3
        assert started[0].returncode is not None
        # A command due when it would start is never started.
        assert office_process.run_collector(command, out, time.monotonic() - 0.01) is None
    assert len(started) == 1


def test_a_bounded_close_never_contradicts_the_published_receipt(
    tmp_path: Path, session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The final receipt is on disk, but its writer is held before it can report it; close()
    # stops waiting first. What close() returns must agree with that receipt, and the timed-out
    # wait is recorded apart from the evidence.
    monkeypatch.setattr(office_process, "STOP_SECONDS", 0.05)
    process = sleeper()
    held, release = threading.Event(), threading.Event()
    replace = os.replace

    def held_after_final(source: Any, target: Any) -> None:
        replace(source, target)
        receipt = Path(target)
        if receipt.name == "stall-True-0.json" and "watch_finished" in receipt.read_text("utf-8"):
            held.set()
            release.wait(10)

    monkeypatch.setattr(office_process.os, "replace", held_after_final)
    stall = watch(process, tmp_path, budget=0.1).start()
    try:
        assert held.wait(20)
        evidence = stall.close()
        assert stall.wait_timed_out
        receipt = json.loads((tmp_path / "stall-True-0.json").read_text(encoding="utf-8"))
        assert evidence is not None and evidence == receipt and evidence["watch_finished"]
    finally:
        release.set()
        stop_process(process)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux roots the office's tree at an ID")
@pytest.mark.parametrize("launcher", ["reaped", "reused"])
def test_no_native_stacks_unless_the_launchers_id_still_names_it(
    tmp_path: Path, session: None, monkeypatch: pytest.MonkeyPatch, launcher: str
) -> None:
    # The listing finds the office under the launcher's process ID. Once the runner has reaped
    # an exited launcher, as at the gdb wrapper's exit-81 restart, that ID can pass to another
    # process, whose tree is not this session's (#45).
    process, office = sleeper(), sleeper()
    target = Process(office.pid, process.pid, "soffice.bin", 1)
    touched: list[Process] = []

    def stacks(found: Process, path: Path, **options: Any) -> StackAttempt:
        touched.append(found)
        return StackAttempt("read")

    stall = watch(process, tmp_path, limit=0.5, find=offices(target), stacks=stacks)
    if launcher == "reaped":
        process.kill()
        process.wait()
    else:
        listed = office_process.linux_process

        def reused(pid: int) -> Process | None:
            row = listed(pid)
            if row is None or pid != process.pid:
                return row
            return dataclasses.replace(row, started=row.started + 1)

        monkeypatch.setattr(office_process, "linux_process", reused)
    stall.start()
    try:
        wait_until(teardown.stalled_callbacks)
        evidence = stall.close()
        assert touched == [], "Native stacks were read from a tree found under a reused ID"
        assert evidence is not None and evidence["office_stacks"] == {}
        assert evidence["office_search"].startswith("listing not used: /proc shows")
    finally:
        stop_process(process)
        stop_process(office)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux roots the office's tree at an ID")
def test_a_launcher_whose_identity_was_never_taken_is_not_trusted(
    tmp_path: Path, session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The watch is built on a launcher that was already reaped, so it never took its identity.
    # When the launcher's ID then names a live process, as after reuse, there is nothing to
    # compare it with, so the tree listed under that ID is not used (#45).
    process, office, other = sleeper(), sleeper(), sleeper()
    process.kill()
    process.wait()
    assert office_process.linux_process(process.pid) is None
    target = Process(office.pid, process.pid, "soffice.bin", 1)
    touched: list[Process] = []

    def stacks(found: Process, path: Path, **options: Any) -> StackAttempt:
        touched.append(found)
        return StackAttempt("read")

    stall = watch(process, tmp_path, limit=0.5, find=offices(target), stacks=stacks)
    listed = office_process.linux_process

    def reused(pid: int) -> Process | None:
        return listed(other.pid if pid == process.pid else pid)

    monkeypatch.setattr(office_process, "linux_process", reused)
    stall.start()
    try:
        wait_until(teardown.stalled_callbacks)
        evidence = stall.close()
        assert touched == [], "Native stacks were read from a tree under an unidentified launcher"
        assert evidence is not None and evidence["office_stacks"] == {}
        assert evidence["office_search"] == (
            f"listing not used: the watch took no identity for the launcher {process.pid}, so "
            "its descendants may not be this session's"
        )
    finally:
        stop_process(office)
        stop_process(other)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux roots the office's tree at an ID")
@pytest.mark.parametrize("launcher", ["running", "reaped"])
def test_an_empty_listing_claims_only_what_it_shows(
    tmp_path: Path, session: None, launcher: str
) -> None:
    # The real listing, under a launcher with no soffice.bin child, or under one the runner has
    # reaped while its soffice.bin lives on. Neither shows that no office runs, and the
    # launcher's exit is not the office's (#45).
    assert sys.platform == "linux"
    office = tmp_path / "soffice.bin"
    shutil.copyfile(shutil.which("sleep") or "/bin/sleep", office)
    office.chmod(0o755)
    starts = "import subprocess, sys; print(subprocess.Popen([sys.argv[1], '60']).pid, flush=True)"
    if launcher == "running":
        process, child = sleeper(), None
    else:
        process = subprocess.Popen(
            [sys.executable, "-c", starts + "; sys.stdin.read()", str(office)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert process.stdout is not None
        child = int(process.stdout.readline())
    handle = None if child is None else os.pidfd_open(child)
    try:
        stall = StallWatch(
            process,
            tmp_path,
            "stall-True-0",
            expire=teardown.stall_if_idle,
            limit=90,
            deadline=time.monotonic(),
        )  # It takes the launcher's identity now, before the runner reaps it.
        if launcher == "reaped":
            assert process.stdin is not None
            process.stdin.close()
            process.wait(10)
            assert office_process.linux_process(process.pid) is None
        evidence = stall.start().close()
        assert evidence is not None and evidence["office_stacks"] == {}
        if launcher == "running":
            search = f"the listing has no soffice.bin descended from the launcher {process.pid}"
            assert evidence["office_search"] == search
        else:
            assert evidence["office_search"].startswith("listing not used: /proc shows")
            assert handle is not None and not select.select([handle], [], [], 0)[0]
        assert evidence["launcher_exit_status"] is not None and "office_stopped" not in evidence
    finally:
        stop_process(process)
        if handle is not None:
            signal.pidfd_send_signal(handle, signal.SIGKILL)
            os.close(handle)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux interrupts the gdb wrapper's inferior")
def test_an_interrupt_to_the_gdb_wrapper_is_recorded_as_sent_not_as_saved_stacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A gdb that is itself blocked prints nothing after the interrupt (#45). This process stands
    # in for gdb: the identity checks see it as the inferior's tracing parent.
    target_process = sleeper()
    listed = office_process.linux_process

    def as_gdb(pid: int) -> Process | None:
        row = listed(pid)
        return dataclasses.replace(row, name="gdb") if row and pid == os.getpid() else row

    def traced_by_this_process(pid: int) -> int:
        return os.getpid()

    monkeypatch.setattr(office_process, "linux_process", as_gdb)
    monkeypatch.setattr(office_process, "tracer_of", traced_by_this_process)
    try:
        target = office_process.linux_process(target_process.pid)
        assert target is not None
        how = native_stacks(
            target, tmp_path / "x.txt", debugger_parent=True, end=time.monotonic() + 5
        )
        assert how == StackAttempt(
            f"SIGINT sent through its pidfd to {target.pid}, traced by gdb {os.getpid()}; "
            "whatever gdb printed is in the session's gdbtrace log",
            interrupted=True,
        )
        assert target_process.wait(10) != 0  # The interrupt reached it.
    finally:
        stop_process(target_process)


def interrupted(*args: Any, **kwargs: Any) -> StackAttempt:
    return StackAttempt(
        "SIGINT sent through its pidfd to 1, traced by gdb 2; whatever gdb printed is there",
        interrupted=True,
    )


@pytest.mark.parametrize("wrapper", ["exits", "held"])
def test_the_gdb_wrappers_exit_is_recorded_only_when_it_was_seen(
    tmp_path: Path, session: None, wrapper: str
) -> None:
    # After the interrupt, gdb normally prints the stacks and exits. Its status is recorded only
    # when the watch saw it exit within the budget; a held gdb leaves the collector at that step.
    exits = "import sys, time; time.sleep(0.2); sys.exit(3)"
    program = exits if wrapper == "exits" else "import time; time.sleep(60)"
    process = subprocess.Popen([sys.executable, "-c", program], text=True)
    target = Process(process.pid, os.getpid(), "soffice.bin", 1)
    stall = watch(
        process,
        tmp_path,
        budget=1.5,
        debugger_parent=True,
        find=offices(target),
        stacks=interrupted,
    ).start()
    try:
        wait_until(teardown.stalled_callbacks)
        evidence = stall.close()
        assert evidence is not None
        if wrapper == "exits":
            assert evidence["wrapper_exit_status"] == 3 and evidence["collection_finished"]
            assert evidence["launcher_exit_status"] == 3
        else:
            assert "wrapper_exit_status" not in evidence and not evidence["collection_finished"]
            assert evidence["diagnostic_errors"]["capture"] == (
                "the collector was at wrapper_exit when the 1.5 s budget ended"
            )
            assert evidence["launcher_exit_status"] is not None  # Stopped after the budget.
    finally:
        stop_process(process)


@pytest.mark.parametrize(
    "attempt",
    [
        StackAttempt("synthetic: the inferior was interrupted", interrupted=True),
        StackAttempt("SIGINT synthetic: nothing was sent"),
    ],
    ids=["reworded interrupt", "interrupt-like text"],
)
def test_the_wrapper_wait_follows_the_attempt_not_its_text(
    tmp_path: Path, session: None, attempt: StackAttempt
) -> None:
    # The watch read whether gdb was interrupted from the start of its own message, so rewording
    # it would have dropped the wait and `wrapper_exit_status` with it (#267).
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys, time; time.sleep(1); sys.exit(3)"], text=True
    )
    target = Process(process.pid, os.getpid(), "soffice.bin", 1)

    def stacks(*args: Any, **kwargs: Any) -> StackAttempt:
        return attempt

    stall = watch(
        process, tmp_path, budget=10, debugger_parent=True, find=offices(target), stacks=stacks
    ).start()
    try:
        wait_until(teardown.stalled_callbacks)
        evidence = stall.close()
        assert evidence is not None and evidence["collection_finished"]
        assert evidence["office_stacks"][str(process.pid)]["method"] == attempt.method
        if attempt.interrupted:
            assert evidence["wrapper_exit_status"] == 3
        else:
            assert "wrapper_exit_status" not in evidence
    finally:
        stop_process(process)


def test_a_failed_windows_listing_is_an_error_not_an_empty_tree() -> None:
    fails = "import sys; sys.stderr.write('synthetic CIM failure'); sys.exit(1)"
    failing = [sys.executable, "-c", fails]
    with pytest.raises(OSError, match="exited 1: synthetic CIM failure"):
        office_process.windows_processes(time.monotonic() + 10, failing)
    started = time.monotonic()
    hangs = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(TimeoutError):
        office_process.windows_processes(started + 0.5, hangs)
    assert time.monotonic() - started < 10  # The listing was killed at its deadline.
    listing = [sys.executable, "-c", "print('12|11|120|soffice.bin'); print('not a row')"]
    rows = office_process.windows_processes(time.monotonic() + 10, listing)
    assert rows == [Process(12, 11, "soffice.bin", 120)]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux reads stacks through the gdb wrapper")
def test_without_the_gdb_wrapper_no_debugger_attaches_by_process_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `gdb -p` takes a number, which a new process could have reused by the time it attaches.
    attached = tmp_path / "attached"
    gdb = tmp_path / "gdb"
    gdb.write_text(f"#!/bin/sh\necho \"$@\" > '{attached}'\necho 'Thread 1 (fake)'\n")
    gdb.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    process = sleeper()
    try:
        target = office_process.linux_process(process.pid)
        assert target is not None
        how = native_stacks(
            target, tmp_path / "stacks.txt", debugger_parent=False, end=time.monotonic() + 5
        )
        assert not attached.exists(), "A debugger attached by process ID"
        assert "gdb wrapper" in how.method and not how.interrupted
    finally:
        stop_process(process)


def test_every_failed_capture_step_is_recorded_and_the_launcher_still_stopped(
    tmp_path: Path, session: None
) -> None:
    process = sleeper()

    def broken_find(root: int, seconds: float) -> list[Process]:
        raise OSError("process listing failed")

    stall = watch(process, tmp_path, find=broken_find).start()
    wait_until(lambda: process.poll() is not None)
    evidence = stall.close()
    assert evidence is not None and evidence["launcher_exit_status"] is not None
    assert "process listing failed" in evidence["diagnostic_errors"]["office_processes"]
    assert "office_search" not in evidence  # A failed search is not "no office found".
    assert teardown.stalled_callbacks()


def skipped(*args: Any, **kwargs: Any) -> StackAttempt:
    return StackAttempt("skipped: not the gdb wrapper's inferior (tracer 0)")


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
    how = run_debugger([sys.executable, "-c", writes_then_hangs], path, time.monotonic() + 2)
    assert "had not exited by the capture's end" in how
    assert path.read_bytes().startswith(b"Thread 1 frames\xff")
    no_stacks = [sys.executable, "-c", "print('\\xff no stacks')"]
    finished = run_debugger(no_stacks, path, time.monotonic() + 10)
    assert "no thread line" in finished


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
        end = time.monotonic() + 30
        wait_until(lambda: len(office_processes(launcher.pid, end)) == 2)
        found = office_processes(launcher.pid, end)
        assert all(row.parent == launcher.pid and row.name == "soffice.bin" for row in found)
        assert office_processes(os.getpid(), end) == found  # Grandchildren of this test too.
        assert office_processes(found[0].pid, end) == []
        stale = dataclasses.replace(found[0], started=found[0].started - 1)
        assert (
            "no longer has its listed"
            in native_stacks(stale, tmp_path / "x.txt", debugger_parent=True, end=end).method
        )
        # An office that is not a gdb inferior never gets the wrapper's interrupt.
        how = native_stacks(found[1], tmp_path / "y.txt", debugger_parent=True, end=end)
        assert how.method.startswith("skipped: not the gdb wrapper's inferior")
        assert not how.interrupted
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
        found = office_processes(os.getpid(), time.monotonic() + 60)
        assert [row.pid for row in found] == [child.pid]
        stale = dataclasses.replace(found[0], started=found[0].started - 10)
        end = time.monotonic() + 5
        assert (
            "no longer has its listed"
            in native_stacks(stale, tmp_path / "x.txt", debugger_parent=False, end=end).method
            or not office_process.CDB.exists()
        )
    finally:
        child.kill()
        child.wait()
