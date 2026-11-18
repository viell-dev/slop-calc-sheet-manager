"""A session that stops making progress fails, with its stacks, through the real runner (#45).

`tests/integration/run.py` is loaded as it is, with fake UNO modules, and its own `main()` and
`office_session` run against a child Python process that stands in for the office: stopping
it is what makes a blocked call fail. Only the office's connection and documents are fake; the
stall watch, progress, shutdown checks and `results.json` are the runner's own. Timing is
asserted, so a watch that is disconnected or fires late fails here, not only in a native run.
"""

import contextlib
import functools
import importlib.util
import json
import subprocess
import sys
import threading
import time
import types
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.integration import input_trace, office_process, teardown

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 2.0  # The patched stall limit; the watch looks every quarter of it.
OFFICE = "import sys; sys.stdin.read()"  # Ends when the runner asks the office to terminate.
MARKER_SERVICE = "com.sun.star.awt.UnoControlFixedTextModel"  # `client_releases`' marker.


class FakeModule(types.ModuleType):
    """A UNO module whose every name is a distinct class, enough to import the runner."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        value = type(name, (), {})
        setattr(self, name, value)
        return value


class ReleaseMarker:
    """The office's control model behind the runner's release marker (`client_releases`).

    Like the office's model, it holds its listeners until the office runs its release.
    """

    def __init__(self) -> None:
        self.listeners: list[object] = []

    def addEventListener(self, listener: object) -> None:
        self.listeners.append(listener)


class Office:
    """The child process standing in for soffice, and the fake UNO objects connected to it."""

    def __init__(
        self,
        resolve: Callable[["Office"], None] | None = None,
        first: Callable[[Path], str] | None = None,
        release_after: float | None = 0.0,
    ) -> None:
        self.launches: list[subprocess.Popen[str]] = []
        self.resolve_hook = resolve
        self.first = first  # The first launch's program, given the office's working directory.
        # When the office runs a release marker's release, after its creation; None for never.
        self.release_after = release_after
        self.markers: list[float] = []  # When each release marker was created.
        self.terminate_requests: list[float] = []
        self._held: list[ReleaseMarker] = []

    def popen(self, command: list[str], **options: Any) -> subprocess.Popen[str]:
        first = self.first is not None and not self.launches
        program = self.first(Path(options["cwd"])) if self.first is not None and first else OFFICE
        process = subprocess.Popen(
            [sys.executable, "-c", program],
            stdin=subprocess.PIPE,
            stdout=options["stdout"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.launches.append(process)
        return process

    @property
    def process(self) -> subprocess.Popen[str]:
        return self.launches[-1]

    def terminate(self) -> None:
        self.terminate_requests.append(time.monotonic())
        stdin = self.process.stdin
        assert stdin is not None
        stdin.close()

    def marker(self) -> ReleaseMarker:
        """A release marker; the runner's wait sees its release once nothing holds the model."""
        self.markers.append(time.monotonic())
        model = ReleaseMarker()
        if self.release_after is None:
            self._held.append(model)  # The office never runs its release.
        elif self.release_after > 0:
            held = [model]
            timer = threading.Timer(self.release_after, held.clear)
            timer.daemon = True
            timer.start()
        return model

    def service_manager(self) -> object:
        """A synchronous call over the bridge, which fails once the office has stopped."""
        if self.process.poll() is not None:
            raise RuntimeError("Binary URP bridge already disposed")
        return self.context.ServiceManager

    def resolve(self, url: str) -> Any:
        if self.resolve_hook is not None:
            self.resolve_hook(self)
        return self.context

    @functools.cached_property
    def context(self) -> Any:
        desktop = types.SimpleNamespace(
            terminate=self.terminate,
            getComponents=lambda: types.SimpleNamespace(hasElements=lambda: False),
        )
        resolver = types.SimpleNamespace(resolve=self.resolve)

        def create(name: str, context: Any) -> Any:
            if name == MARKER_SERVICE:
                return self.marker()
            return desktop if name == "com.sun.star.frame.Desktop" else resolver

        return types.SimpleNamespace(
            ServiceManager=types.SimpleNamespace(createInstanceWithContext=create),
            getServiceManager=self.service_manager,
        )

    def wait_stopped(self, seconds: float = 20) -> float:
        """Wait, as a blocked UNO call does, until the office stops; return when it did."""
        deadline = time.monotonic() + seconds
        while self.process.poll() is None:
            assert time.monotonic() < deadline, "The stall watch never stopped the office"
            time.sleep(0.02)
        return time.monotonic()


def integration_module(name: str) -> Any:
    """A runner helper loaded from its source, as the runner imports it."""
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tests" / "integration" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def loaded_runner(monkeypatch: pytest.MonkeyPatch) -> Generator[Any]:
    """The real runner module, importable without LibreOffice; the soak's tests use it too."""
    for name in (
        "uno",
        "unohelper",
        "com",
        "com.sun",
        "com.sun.star",
        "com.sun.star.awt",
        "com.sun.star.beans",
        "com.sun.star.lang",
        "com.sun.star.view",
        "main_thread",
        "sheet_list_view",
    ):
        monkeypatch.setitem(sys.modules, name, FakeModule(name))
    vars(sys.modules["unohelper"])["Base"] = type("Base", (), {})
    # The runner's own helpers, shared with these tests so that they can be inspected.
    monkeypatch.setitem(sys.modules, "office_process", office_process)
    monkeypatch.setitem(sys.modules, "teardown", teardown)
    monkeypatch.setitem(sys.modules, "input_trace", input_trace)
    # The runner's wait for its UNO releases (#242) imports UNO, so it is loaded against the fakes.
    releases = integration_module("client_releases")
    assert releases.MARKER_SERVICE == MARKER_SERVICE
    monkeypatch.setitem(sys.modules, "client_releases", releases)
    monkeypatch.setattr(office_process, "STALL_SECONDS", LIMIT)
    monkeypatch.setattr(office_process, "DEADLINE", None)
    monkeypatch.setattr(sys, "path", list(sys.path))  # main() adds the package's pythonpath.
    spec = importlib.util.spec_from_file_location(
        "run_under_test", ROOT / "tests" / "integration" / "run.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        teardown.start_session()


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    with loaded_runner(monkeypatch) as module:
        yield module


def session(
    runner: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    office: Office,
    body: Callable[..., dict[str, object]],
    *arguments: str,
    watch: Callable[..., office_process.StallWatch] | None = None,
) -> tuple[BaseException | None, dict[str, Any], Path]:
    """Run the runner's `main()` once; return what it raised, its result and its output."""

    def create(name: str, context: Any) -> Any:
        return types.SimpleNamespace(resolve=office.resolve)

    local = types.SimpleNamespace(
        ServiceManager=types.SimpleNamespace(createInstanceWithContext=create)
    )
    monkeypatch.setattr(runner, "uno", types.SimpleNamespace(getComponentContext=lambda: local))
    monkeypatch.setattr(
        runner,
        "subprocess",
        types.SimpleNamespace(
            Popen=office.popen, DEVNULL=subprocess.DEVNULL, STDOUT=subprocess.STDOUT
        ),
    )
    monkeypatch.setattr(runner, "exercise_without_extension", body)
    # Native stacks are another test's subject; here the office is a Python child process.
    monkeypatch.setattr(
        runner,
        "StallWatch",
        watch or functools.partial(office_process.StallWatch, find=lambda root, end: []),
    )
    output = tmp_path / "results"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--program",
            str(tmp_path),
            "--oxt",
            str(tmp_path / "synthetic.oxt"),
            "--output",
            str(output),
            "--without-extension",
            *arguments,
        ],
    )
    raised: BaseException | None = None
    try:
        runner.main()
    except BaseException as error:  # The runner's own failure is the subject.
        raised = error
    finally:
        for process in office.launches:
            if process.poll() is None:
                process.kill()
            process.wait()
    (result,) = json.loads((output / "results.json").read_text(encoding="utf-8"))
    return raised, result, output


def test_a_session_that_keeps_making_progress_is_never_stopped(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    office = Office()

    def body(context: Any, desktop: Any, directory: Path) -> dict[str, object]:
        started = time.monotonic()
        while time.monotonic() - started < 3 * LIMIT:
            teardown.note_progress()
            time.sleep(LIMIT / 5)
            assert office.process.poll() is None, "The watch stopped an office making progress"
        return {"long_session": round(time.monotonic() - started, 1)}

    raised, result, output = session(runner, monkeypatch, tmp_path, office, body)
    assert raised is None, raised
    assert result["run_complete"] and result["assertions_passed"]
    assert result["long_session"] >= 3 * LIMIT
    assert "office_progress_stall" not in result and result["office_stalled_callbacks"] == []
    assert result["office_exit_code"] == 0 and not result["office_forced_shutdown"]
    assert result["longest_progress_interval_seconds"] < LIMIT
    assert not list(output.glob("stall-*"))
    assert "checks_ended_before_deadline" not in result  # There was no deadline.


def test_checks_that_end_before_the_deadline_are_recorded_as_such(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A session found past the soak's limit shows by this that its checks had ended in time.
    monkeypatch.setattr(office_process, "DEADLINE", time.monotonic() + 60)

    def body(*args: Any) -> dict[str, object]:
        return {}

    raised, result, _ = session(runner, monkeypatch, tmp_path, Office(), body)
    assert raised is None and result["run_complete"]
    assert result["checks_ended_before_deadline"] is True


def test_a_wait_that_ends_before_the_capture_is_recorded_apart_from_its_evidence(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The watch's stop hangs, so the session stops waiting for the capture. The evidence says
    # nothing it does not know; the timed-out wait is the runner's own record.
    monkeypatch.setattr(office_process, "STOP_SECONDS", 0.2)
    release = threading.Event()

    def hung_stop(process: subprocess.Popen[str]) -> None:
        release.wait(30)

    def fails_once_stalled(*args: Any) -> dict[str, object]:
        teardown.note_progress()
        deadline = time.monotonic() + 20
        while not teardown.stalled_callbacks():
            assert time.monotonic() < deadline, "No stall was recorded"
            time.sleep(0.02)
        raise RuntimeError("Binary URP bridge disposed during call")

    watch = functools.partial(
        office_process.StallWatch, budget=0.2, find=lambda root, end: [], stop=hung_stop
    )
    try:
        raised, result, _ = session(
            runner, monkeypatch, tmp_path, Office(), fails_once_stalled, watch=watch
        )
    finally:
        release.set()
    assert isinstance(raised, AssertionError | RuntimeError), raised
    assert result["stall_wait_timed_out"] is True
    assert "watch_finished" not in result["office_progress_stall"]
    assert not result["run_complete"] and result["office_exit_code"] != 0


def test_a_release_wait_longer_than_the_stall_limit_is_not_a_stall(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The watch closes before shutdown, so a healthy session's wait for its UNO releases (#242),
    # here longer than the stall limit, is neither watched nor stopped, and the office is asked to
    # terminate only once the office has run the marker's release.
    office = Office(release_after=1.5 * LIMIT)
    ended: list[float] = []

    def body(*args: Any) -> dict[str, object]:
        teardown.note_progress()
        ended.append(time.monotonic())
        return {}

    raised, result, output = session(runner, monkeypatch, tmp_path, office, body)
    assert raised is None, raised
    assert result["run_complete"] and result["assertions_passed"]
    ((marker,), (terminate,)) = office.markers, office.terminate_requests
    assert ended[0] < marker and terminate - marker >= 1.5 * LIMIT
    assert result["office_unsettled_releases"] is None
    wait, shutdown = result["office_release_wait_seconds"], result["office_shutdown_seconds"]
    assert 1.5 * LIMIT <= wait <= shutdown < 30
    assert "office_progress_stall" not in result and result["office_stalled_callbacks"] == []
    assert result["office_terminate_returned"] is True and not result["office_forced_shutdown"]
    assert result["office_exit_code"] == 0
    assert result["longest_progress_interval_seconds"] < LIMIT  # Shutdown is not a check.
    assert not list(output.glob("stall-*"))


@pytest.mark.parametrize("office_at_shutdown", ["stopped by the watch", "still running"])
def test_a_stalled_session_neither_waits_for_its_releases_nor_spends_the_grace(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, office_at_shutdown: str
) -> None:
    # A stall is a stalled callback, so shutdown sends neither the release wait (#242) nor the
    # terminate request (#50). This office never runs a marker's release, so a wait would last
    # graceful shutdown's 30 s. With the watch's own stop hung, the office still runs when
    # shutdown starts, and shutdown stops it at once.
    monkeypatch.setattr(office_process, "STOP_SECONDS", 0.2)
    office = Office(release_after=None)
    release = threading.Event()

    def hung_stop(process: subprocess.Popen[str]) -> None:
        release.wait(30)

    def fails_once_stalled(*args: Any) -> dict[str, object]:
        teardown.note_progress()
        deadline = time.monotonic() + 20
        while not teardown.stalled_callbacks():
            assert time.monotonic() < deadline, "No stall was recorded"
            time.sleep(0.02)
        if office_at_shutdown == "stopped by the watch":
            office.wait_stopped()
        raise RuntimeError("Binary URP bridge disposed during call")

    def no_offices(root: int, end: float) -> list[office_process.Process]:
        return []

    running = office_at_shutdown == "still running"
    options: dict[str, Any] = {"budget": 0.2, "find": no_offices}
    if running:
        options["stop"] = hung_stop
    watch = functools.partial(office_process.StallWatch, **options)
    try:
        raised, result, _ = session(
            runner, monkeypatch, tmp_path, office, fails_once_stalled, watch=watch
        )
    finally:
        release.set()
    assert isinstance(raised, AssertionError | RuntimeError), raised
    assert office.markers == [] and office.terminate_requests == []
    assert result["office_unsettled_releases"] is None
    assert result["office_release_wait_seconds"] < 1 and result["office_shutdown_seconds"] < 15
    assert result["office_terminate_returned"] is False
    assert result["office_forced_shutdown"] is running
    assert result.get("stall_wait_timed_out", False) is running
    assert result["office_progress_stall"]["cause"] == "no progress"
    assert not result["run_complete"] and result["office_exit_code"] != 0


def test_a_session_without_progress_fails_with_its_stacks_in_time(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    office = Office()
    times: dict[str, float] = {}

    def blocked_uno_call(context: Any, desktop: Any, directory: Path) -> dict[str, object]:
        teardown.note_progress()
        times["progress"] = time.monotonic()
        times["stopped"] = office.wait_stopped()
        raise RuntimeError("Binary URP bridge disposed during call")

    raised, result, output = session(runner, monkeypatch, tmp_path, office, blocked_uno_call)
    assert isinstance(raised, AssertionError | RuntimeError), raised
    # Detected no earlier than the limit, and within one look of it plus the capture.
    assert LIMIT <= times["stopped"] - times["progress"] < 2 * LIMIT
    assert not result["run_complete"] and "assertions_passed" not in result
    stall = result["office_progress_stall"]
    assert stall["cause"] == "no progress" and stall["limit_seconds"] == LIMIT
    assert LIMIT <= stall["idle_seconds"] < 2 * LIMIT
    assert stall["launcher_exit_status"] is not None and stall["watch_finished"]
    assert "diagnostic_errors" not in stall and "stall_wait_timed_out" not in result
    assert "No test progress" in result["office_stalled_callbacks"][0]
    assert result["office_exit_code"] != 0
    assert (
        json.loads((output / stall["receipt"]).read_text(encoding="utf-8"))["launcher_exit_status"]
        is not None
    )
    client = (output / stall["client_stacks"]).read_text(encoding="utf-8")
    assert "blocked_uno_call" in client  # The client's stack shows where it waited.


def test_a_failed_diagnostic_never_turns_a_stall_into_a_pass(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The reviewer's shape: a debugger that breaks, and a body that finishes once the stall is
    # detected, as a slow call that returns late would.
    office = Office()
    target = office_process.Process(1, 0, "soffice.bin", 0)

    def broken(*args: Any, **kwargs: Any) -> office_process.StackAttempt:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    def finishes_late(context: Any, desktop: Any, directory: Path) -> dict[str, object]:
        teardown.note_progress()
        deadline = time.monotonic() + 20
        while not teardown.stalled_callbacks():
            assert time.monotonic() < deadline, "No stall was recorded"
            time.sleep(0.02)
        return {"synthetic_body_completed": True}

    watch = functools.partial(
        office_process.StallWatch, find=lambda root, end: [target], stacks=broken
    )
    raised, result, _ = session(runner, monkeypatch, tmp_path, office, finishes_late, watch=watch)
    assert isinstance(raised, AssertionError), raised
    assert not result["run_complete"]
    stall = result["office_progress_stall"]
    assert "UnicodeDecodeError" in stall["diagnostic_errors"]["office_1"]
    assert stall["office_stacks"]["1"] == {"method": None, "file": None}
    assert stall["launcher_exit_status"] is not None
    assert result["office_stalled_callbacks"]


def test_a_stall_during_startup_ends_the_session_without_a_retry(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def connection_never_completes(office: Office) -> None:
        office.wait_stopped()
        raise RuntimeError("Connector: couldn't connect to pipe")

    office = Office(resolve=connection_never_completes)

    def body(*args: Any) -> dict[str, object]:
        raise AssertionError("A session without a connection ran its body")

    raised, result, output = session(
        runner, monkeypatch, tmp_path, office, body, "--startup-attempts", "3"
    )
    assert isinstance(raised, RuntimeError), raised
    assert len(office.launches) == 1  # Never retried.
    assert result["failure_stage"] == "startup" and not result["run_complete"]
    stall = result["office_progress_stall"]
    assert stall["cause"] == "no progress" and stall["launcher_exit_status"] is not None
    assert result["office_stalled_callbacks"]
    assert result["longest_progress_interval_seconds"] >= LIMIT
    startup = json.loads((output / "startup-True-0.json").read_text(encoding="utf-8"))
    assert startup["office_progress_stall"]["receipt"] == "stall-True-0.json"


def test_an_enclosing_deadline_ends_a_session_that_makes_progress(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The soak's per-session limit: the session fails there, whether or not it progresses.
    monkeypatch.setattr(office_process, "STALL_SECONDS", 900.0)
    deadline = time.monotonic() + 3.0  # After the runner's startup, within the body.
    monkeypatch.setattr(office_process, "DEADLINE", deadline)
    office = Office()
    times: dict[str, float] = {}

    def busy(context: Any, desktop: Any, directory: Path) -> dict[str, object]:
        stop = threading.Event()

        def progress() -> None:
            while not stop.wait(0.1):
                teardown.note_progress()

        threading.Thread(target=progress, daemon=True).start()
        try:
            times["stopped"] = office.wait_stopped()
        finally:
            stop.set()
        raise RuntimeError("Binary URP bridge disposed during call")

    raised, result, _ = session(runner, monkeypatch, tmp_path, office, busy)
    assert isinstance(raised, AssertionError | RuntimeError), raised
    assert deadline <= times["stopped"] < deadline + LIMIT
    stall = result["office_progress_stall"]
    assert stall["cause"] == "deadline" and stall["idle_seconds"] < 1
    assert "deadline" in result["office_stalled_callbacks"][0]
    assert "checks_ended_before_deadline" not in result


def test_a_rerun_leaves_no_stall_evidence_of_an_earlier_run(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "results"
    output.mkdir()
    for name in ("stall-True-0.json", "stall-True-0-client-stacks.txt"):
        (output / name).write_text("an earlier run's stall", encoding="utf-8")

    def body(*args: Any) -> dict[str, object]:
        return {}

    raised, result, _ = session(runner, monkeypatch, tmp_path, Office(), body)
    assert raised is None and result["run_complete"]
    assert not list(output.glob("stall-*"))


@pytest.mark.skipif(sys.platform == "win32", reason="The gdb wrapper runs only on Linux")
def test_the_gdb_wrappers_startup_restart_hands_the_new_office_to_the_watch(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Under --backtrace the first soffice.bin exits 81 to initialize its profile, and the runner
    # starts another; a stall later must stop that one, not the first.
    def bootstrap(directory: Path) -> str:
        trace = directory / "gdbtrace.log"
        trace.write_text("[Inferior 1 (process 7) exited with code 0121]", encoding="utf-8")
        return "raise SystemExit(81)"

    def connects_after_restart(office: Office) -> None:
        if len(office.launches) == 1:
            office.wait_stopped()
            raise RuntimeError("Connector: couldn't connect to pipe")

    office = Office(resolve=connects_after_restart, first=bootstrap)

    times: dict[str, float] = {}

    def blocked_uno_call(context: Any, desktop: Any, directory: Path) -> dict[str, object]:
        teardown.note_progress()
        times["progress"] = time.monotonic()
        times["stopped"] = office.wait_stopped()
        raise RuntimeError("Binary URP bridge disposed during call")

    raised, result, _ = session(
        runner, monkeypatch, tmp_path, office, blocked_uno_call, "--backtrace"
    )
    assert isinstance(raised, AssertionError | RuntimeError), raised
    assert len(office.launches) == 2 and result["office_startup_restart"] == 81
    stall = result["office_progress_stall"]
    assert (
        stall["launcher_pid"] == office.launches[1].pid
        and stall["launcher_exit_status"] is not None
    )
    assert LIMIT <= times["stopped"] - times["progress"] < 2 * LIMIT


@pytest.mark.skipif(sys.platform == "win32", reason="The gdb wrapper runs only on Linux")
def test_a_stall_during_the_restart_launches_no_unwatched_office(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The stall comes while the runner handles the first office's exit 81. The watch captures
    # and stops that office; the replacement would then run with nothing watching it, so the
    # watch refuses it and the runner stops it, and startup fails before another UNO call.
    def bootstrap(directory: Path) -> str:
        trace = directory / "gdbtrace.log"
        trace.write_text("[Inferior 1 (process 7) exited with code 0121]", encoding="utf-8")
        return "raise SystemExit(81)"

    unwatched: list[int] = []

    def connects(office: Office) -> None:
        if len(office.launches) == 1:
            office.wait_stopped()
            raise RuntimeError("Connector: could not connect to pipe")
        unwatched.append(office.process.pid)  # A UNO call to an office nothing watches.

    office = Office(resolve=connects, first=bootstrap)
    receipt = tmp_path / "results" / "stall-True-0.json"
    recognize = runner.normal_startup_restart

    def after_the_capture(trace: str) -> bool:
        deadline = time.monotonic() + 20
        while not (
            receipt.exists() and "launcher_exit_status" in receipt.read_text(encoding="utf-8")
        ):
            assert time.monotonic() < deadline, "The watch never stopped the first office"
            time.sleep(0.02)
        return recognize(trace)

    monkeypatch.setattr(runner, "normal_startup_restart", after_the_capture)
    stopped: list[int] = []

    def recorded_stop(process: subprocess.Popen[str]) -> None:
        stopped.append(process.pid)
        office_process.stop_process(process)

    monkeypatch.setattr(runner, "stop_process", recorded_stop, raising=False)

    def body(*args: Any) -> dict[str, object]:
        raise AssertionError("A session whose startup stalled ran its body")

    raised, result, _ = session(runner, monkeypatch, tmp_path, office, body, "--backtrace")
    assert len(office.launches) == 2 and unwatched == []
    assert stopped == [office.launches[1].pid]  # Stopped by the runner, before any UNO call.
    assert result["office_exit_code"] not in (0, None) and not result["office_forced_shutdown"]
    assert isinstance(raised, TimeoutError), raised
    assert result["failure_stage"] == "startup" and not result["run_complete"]
    stall = result["office_progress_stall"]
    assert (
        stall["launcher_pid"] == office.launches[0].pid
        and stall["launcher_exit_status"] is not None
    )


def test_a_hung_collector_cannot_keep_a_blocked_session_running(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The body is blocked in a UNO call, so it never reaches the watch's close(), and a
    # collector hangs too. The office still stops when the capture's budget ends.
    budget = 0.5
    entered, release = threading.Event(), threading.Event()
    target = office_process.Process(1, 0, "soffice.bin", 0)

    def hung(*args: Any, **kwargs: Any) -> office_process.StackAttempt:
        entered.set()
        release.wait(30)
        return office_process.StackAttempt("too late")

    office = Office()
    times: dict[str, float] = {}

    def blocked_uno_call(context: Any, desktop: Any, directory: Path) -> dict[str, object]:
        teardown.note_progress()
        try:
            assert entered.wait(4 * LIMIT), "No capture started"
            times["capturing"] = time.monotonic()
            times["stopped"] = office.wait_stopped(seconds=budget + 3)
        finally:
            release.set()
        raise RuntimeError("Binary URP bridge disposed during call")

    watch = functools.partial(
        office_process.StallWatch, budget=budget, find=lambda root, end: [target], stacks=hung
    )
    raised, result, _ = session(
        runner, monkeypatch, tmp_path, office, blocked_uno_call, watch=watch
    )
    assert isinstance(raised, AssertionError | RuntimeError), raised
    assert times["stopped"] - times["capturing"] < budget + 1
    stall = result["office_progress_stall"]
    assert stall["launcher_exit_status"] is not None and stall["collection_finished"] is False
    assert "the collector was at " in stall["diagnostic_errors"]["capture"]
    assert not result["run_complete"]


def test_no_document_close_starts_during_the_capture(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The absent-extension exercise closed its document while the stacks were being taken. Its
    # real body runs here, with the real shared close helper.
    spec = importlib.util.spec_from_file_location(
        "main_thread_under_test", ROOT / "tests" / "integration" / "main_thread.py"
    )
    assert spec is not None and spec.loader is not None
    main_thread = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main_thread)  # Its UNO base classes come from the runner fixture.
    monkeypatch.setattr(runner, "close_document", main_thread.close_document)
    exercise = runner.exercise_without_extension
    capturing, release = threading.Event(), threading.Event()
    closes: list[list[str]] = []

    def returns(value: Any) -> Callable[..., Any]:
        def call(*args: Any) -> Any:
            return value

        return call

    class Document:
        def __getattr__(self, name: str) -> Any:
            return returns(self)  # Controllers, sidebars, frames and windows alike.

        def hasByName(self, name: str) -> bool:
            return False

        def storeAsURL(self, url: str, arguments: Any) -> None:
            assert capturing.wait(4 * LIMIT), "No capture started"

        def close(self, deliver: bool) -> None:
            closes.append(teardown.stalled_callbacks())

    def stacks(*args: Any, **kwargs: Any) -> office_process.StackAttempt:
        capturing.set()
        release.wait(10)
        return office_process.StackAttempt("synthetic stacks")

    def body(context: Any, desktop: Any, directory: Path) -> dict[str, object]:
        teardown.note_progress()
        factory = types.SimpleNamespace(createInstanceWithContext=returns(None))
        documents = types.SimpleNamespace(loadComponentFromURL=returns(Document()))
        try:
            return exercise(types.SimpleNamespace(ServiceManager=factory), documents, directory)
        finally:
            release.set()

    target = office_process.Process(1, 0, "soffice.bin", 0)
    watch = functools.partial(
        office_process.StallWatch, find=lambda root, end: [target], stacks=stacks
    )
    raised, result, _ = session(runner, monkeypatch, tmp_path, Office(), body, watch=watch)
    assert closes == [], "A document close started after the stall was recorded"
    assert isinstance(raised, TimeoutError | AssertionError), raised
    assert (
        not result["run_complete"]
        and result["office_progress_stall"]["launcher_exit_status"] is not None
    )


def test_no_writer_close_starts_after_a_stall(runner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "WRITER_SETTLE_SECONDS", 0)
    closes: list[bool] = []
    writer = types.SimpleNamespace(close=closes.append)
    teardown.start_session()
    runner.close_writer(writer)
    assert closes == [True]
    assert teardown.stall_if_idle(0, "a synthetic stall") is not None
    with pytest.raises(TimeoutError, match="a synthetic stall"):
        runner.close_writer(writer)
    assert closes == [True]


def test_a_failed_startup_records_its_longest_interval_without_progress(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def exits(office: Office) -> None:
        office.wait_stopped()
        raise RuntimeError("Connector: could not connect to pipe")

    office = Office(resolve=exits, first=lambda directory: "raise SystemExit(3)")

    def body(*args: Any) -> dict[str, object]:
        raise AssertionError("A session without a connection ran its body")

    raised, result, output = session(
        runner, monkeypatch, tmp_path, office, body, "--startup-attempts", "1"
    )
    assert isinstance(raised, RuntimeError), raised
    assert result["failure_stage"] == "startup" and "office_progress_stall" not in result
    assert 0 <= result["longest_progress_interval_seconds"] < LIMIT
    startup = json.loads((output / "startup-True-0.json").read_text(encoding="utf-8"))
    interval = result["longest_progress_interval_seconds"]
    assert startup["longest_progress_interval_seconds"] == interval
