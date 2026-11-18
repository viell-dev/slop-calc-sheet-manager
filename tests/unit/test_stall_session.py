"""A session that stops making progress fails, with its stacks, through the real runner (#45).

`tests/integration/run.py` is loaded as it is, with fake UNO modules, and its own `main()` and
`office_session` run against a child Python process that stands in for the office: stopping
it is what makes a blocked call fail. Only the office's connection and documents are fake; the
stall watch, progress, shutdown checks and `results.json` are the runner's own. Timing is
asserted, so a watch that is disconnected or fires late fails here, not only in a native run.
"""

import functools
import importlib.util
import json
import subprocess
import sys
import threading
import time
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.integration import input_trace, office_process, teardown

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 2.0  # The patched stall limit; the watch looks every quarter of it.
OFFICE = "import sys; sys.stdin.read()"  # Ends when the runner asks the office to terminate.


class FakeModule(types.ModuleType):
    """A UNO module whose every name is a distinct class, enough to import the runner."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        value = type(name, (), {})
        setattr(self, name, value)
        return value


class Office:
    """The child process standing in for soffice, and the fake UNO objects connected to it."""

    def __init__(self, resolve: Callable[["Office"], None] | None = None) -> None:
        self.launches: list[subprocess.Popen[str]] = []
        self.resolve_hook = resolve

    def popen(self, command: list[str], **options: Any) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-c", OFFICE],
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
        stdin = self.process.stdin
        assert stdin is not None
        stdin.close()

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
            return desktop if name == "com.sun.star.frame.Desktop" else resolver

        return types.SimpleNamespace(
            ServiceManager=types.SimpleNamespace(createInstanceWithContext=create)
        )

    def wait_stopped(self, seconds: float = 20) -> float:
        """Wait, as a blocked UNO call does, until the office stops; return when it did."""
        deadline = time.monotonic() + seconds
        while self.process.poll() is None:
            assert time.monotonic() < deadline, "The stall watch never stopped the office"
            time.sleep(0.02)
        return time.monotonic()


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The real runner module, importable without LibreOffice."""
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
    monkeypatch.setattr(office_process, "STALL_SECONDS", LIMIT)
    monkeypatch.setattr(office_process, "DEADLINE", None)
    monkeypatch.setattr(sys, "path", list(sys.path))  # main() adds the package's pythonpath.
    spec = importlib.util.spec_from_file_location(
        "run_under_test", ROOT / "tests" / "integration" / "run.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    teardown.start_session()


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
        watch or functools.partial(office_process.StallWatch, find=lambda root, seconds: []),
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
    assert stall["office_stopped"] and stall["capture_finished"]
    assert "diagnostic_errors" not in stall
    assert "No test progress" in result["office_stalled_callbacks"][0]
    assert result["office_exit_code"] != 0
    assert json.loads((output / stall["receipt"]).read_text(encoding="utf-8"))["office_stopped"]
    client = (output / stall["client_stacks"]).read_text(encoding="utf-8")
    assert "blocked_uno_call" in client  # The client's stack shows where it waited.


def test_a_failed_diagnostic_never_turns_a_stall_into_a_pass(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The reviewer's shape: a debugger that breaks, and a body that finishes once the stall is
    # detected, as a slow call that returns late would.
    office = Office()
    target = office_process.Process(1, 0, "soffice.bin", 0)

    def broken(*args: Any, **kwargs: Any) -> str:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    def finishes_late(context: Any, desktop: Any, directory: Path) -> dict[str, object]:
        teardown.note_progress()
        deadline = time.monotonic() + 20
        while not teardown.stalled_callbacks():
            assert time.monotonic() < deadline, "No stall was recorded"
            time.sleep(0.02)
        return {"synthetic_body_completed": True}

    watch = functools.partial(
        office_process.StallWatch, find=lambda root, seconds: [target], stacks=broken
    )
    raised, result, _ = session(runner, monkeypatch, tmp_path, office, finishes_late, watch=watch)
    assert isinstance(raised, AssertionError), raised
    assert not result["run_complete"]
    stall = result["office_progress_stall"]
    assert "UnicodeDecodeError" in stall["diagnostic_errors"]["office_1"]
    assert stall["office_stacks"]["1"] == {"method": None, "file": None}
    assert stall["office_stopped"]
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
    assert stall["cause"] == "no progress" and stall["office_stopped"]
    assert result["office_stalled_callbacks"]
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
