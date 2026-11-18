"""An unreadable session result must fail the soak without losing later measurements."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tests.integration import office_process, soak

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    sys.platform != "linux", reason="The soak runs only inside the Linux test image"
)
@pytest.mark.parametrize("failure", ["truncated", "unreadable", "missing"])
def test_soak_continues_after_unreadable_results(tmp_path: Path, failure: str) -> None:
    shutil.copyfile(ROOT / "tests/integration/soak.py", tmp_path / "soak.py")
    (tmp_path / "run.py").write_text(
        "import json, pathlib, sys\n"
        "assert sys.argv[sys.argv.index('--suites') + 1] == 'none'\n"
        "output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "result = output / 'results.json'\n"
        "if output.name == '001' and '--without-extension' not in sys.argv:\n"
        f"    failure = {failure!r}\n"
        "    if failure == 'truncated':\n"
        "        result.write_text('[{')\n"
        "    elif failure == 'unreadable':\n"
        "        result.mkdir()\n"
        "else:\n"
        "    result.write_text(json.dumps([{'assertions_passed': True, 'office_exit_code': 0}]))\n",
        encoding="utf-8",
    )
    output = tmp_path / "results"
    process = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "soak.py"),
            "--program",
            str(tmp_path),
            "--oxt",
            str(tmp_path / "synthetic.oxt"),
            "--output",
            str(output),
            "--soak",
            "2",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 1, process.stdout + process.stderr
    rows = json.loads((output / "soak-results.json").read_text(encoding="utf-8"))
    assert [(row["mode"], row["session"]) for row in rows] == [
        ("installed", 1),
        ("installed", 2),
        ("absent", 1),
        ("absent", 2),
    ]
    assert rows[0]["runner_exit"] == 0  # A bad result fails even if the runner exited zero.
    assert rows[0]["results"] is None
    assert rows[0]["results_error"]
    assert all(row["results_error"] is None for row in rows[1:])
    assert all(row["results"][0]["assertions_passed"] for row in rows[1:])
    summary = (output / "soak-summary.md").read_text(encoding="utf-8")
    assert rows[0]["results_error"] in summary
    assert "| absent | 2 | 0 |" in summary


@pytest.mark.skipif(
    sys.platform != "linux", reason="The soak runs only inside the Linux test image"
)
def test_a_session_past_its_limit_fails_but_keeps_its_stall_evidence(tmp_path: Path) -> None:
    # The runner's deadline is the soak's limit; it then keeps its stacks and exits (#45).
    deadline = tmp_path / "deadline.txt"
    runner = "\n".join(
        [
            "import os, pathlib, sys, time",
            "out = pathlib.Path(sys.argv[1])",
            "out.write_text(os.environ['SHEET_MANAGER_DEADLINE_MONOTONIC'])",
            "assert 'SHEET_MANAGER_DEADLINE_SECONDS' not in os.environ",
            "time.sleep(1.5)",
            "out.with_name('stall-False-0.json').write_text('{}')",
            "sys.exit(1)",
        ]
    )
    started = time.monotonic()
    with (tmp_path / "runner.log").open("w", encoding="utf-8") as log:
        status = soak.run_session(
            [sys.executable, "-c", runner, str(deadline)], log, limit=0.5, grace=10
        )
    assert status == 124  # A session still running at the limit fails, whatever follows.
    assert 0.5 <= float(deadline.read_text(encoding="utf-8")) - started < 0.6
    assert (tmp_path / "stall-False-0.json").exists()  # Its capture finished in the grace.
    assert time.monotonic() - started < 10


@pytest.mark.skipif(
    sys.platform != "linux", reason="The soak runs only inside the Linux test image"
)
def test_the_soak_and_its_runner_share_one_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The runner's start-up, before it imports office_process, must not move its deadline past
    # the soak's own limit (#45).
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    deadline = tmp_path / "deadline.txt"
    runner = "\n".join(
        [
            "import sys, time",
            "time.sleep(0.5)  # A slow start-up.",
            "from tests.integration import office_process",
            "open(sys.argv[1], 'w').write(repr(office_process.DEADLINE))",
        ]
    )
    started = time.monotonic()
    with (tmp_path / "runner.log").open("w", encoding="utf-8") as log:
        status = soak.run_session(
            [sys.executable, "-c", runner, str(deadline)], log, limit=30, grace=10
        )
    assert status == 0, (tmp_path / "runner.log").read_text(encoding="utf-8")
    assert 30 <= float(deadline.read_text(encoding="utf-8")) - started < 30.1


@pytest.mark.skipif(
    sys.platform != "linux", reason="The soak runs only inside the Linux test image"
)
def test_a_session_that_outlasts_its_grace_has_its_group_killed(tmp_path: Path) -> None:
    beats = tmp_path / "beats.txt"
    heartbeat = "\n".join(
        [
            "import sys, time",
            "while True:",
            "    open(sys.argv[1], 'a').write('.')",
            "    time.sleep(0.05)",
        ]
    )
    runner = "\n".join(
        [
            "import subprocess, sys, time",
            f"subprocess.Popen([sys.executable, '-c', {heartbeat!r}, {str(beats)!r}])",
            "time.sleep(60)",
        ]
    )
    started = time.monotonic()
    with (tmp_path / "runner.log").open("w", encoding="utf-8") as log:
        status = soak.run_session([sys.executable, "-c", runner], log, limit=0.5, grace=0.5)
    assert status == 124
    assert 1 <= time.monotonic() - started < 10
    size = beats.stat().st_size
    time.sleep(0.5)
    assert beats.stat().st_size == size  # The office's stand-in in the group is gone too.


def test_the_soak_grace_covers_the_stall_watchs_capture_and_stop() -> None:
    # The watch looks every 5 s at most; the runner then shuts down and writes its results.
    margin = 5 + 10
    limit = office_process.CAPTURE_SECONDS + office_process.STOP_SECONDS + margin
    assert limit <= soak.CAPTURE_GRACE_SECONDS


@pytest.mark.skipif(
    sys.platform != "linux", reason="The soak runs only inside the Linux test image"
)
def test_the_group_is_killed_before_its_leader_is_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Once its leader is reaped and its group empty, the group's number can pass to a new
    # process, whose group the kill would then reach. Here the runner exits during its grace.
    assert sys.platform == "linux"
    unreaped: list[bool] = []
    kill = os.killpg

    def checked(group: int, number: int) -> None:
        try:
            exited = os.waitid(os.P_PID, group, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            unreaped.append(exited is not None)
        except ChildProcessError:
            unreaped.append(False)  # Already reaped.
        kill(group, number)

    monkeypatch.setattr(soak.os, "killpg", checked)
    with (tmp_path / "runner.log").open("w", encoding="utf-8") as log:
        status = soak.run_session(
            [sys.executable, "-c", "import time; time.sleep(1)"], log, limit=0.3, grace=10
        )
    assert status == 124
    assert unreaped == [True]  # It had exited, and was reaped only after the kill.


@pytest.mark.skipif(
    sys.platform != "linux", reason="The soak runs only inside the Linux test image"
)
def test_a_limit_reached_after_the_checks_is_told_apart_in_the_summary(tmp_path: Path) -> None:
    # The watch ends with the session's checks, so a limit that falls in shutdown keeps no stacks;
    # the summary says so, from the runner's own record, instead of leaving an unexplained 124.
    source = (ROOT / "tests/integration/soak.py").read_text(encoding="utf-8")
    for before, after in (
        ("SESSION_SECONDS = 180", "SESSION_SECONDS = 1"),
        ("CAPTURE_GRACE_SECONDS = 150", "CAPTURE_GRACE_SECONDS = 10"),
    ):
        assert source.count(before) == 1
        source = source.replace(before, after)
    (tmp_path / "soak.py").write_text(source, encoding="utf-8")
    (tmp_path / "run.py").write_text(
        "import json, pathlib, sys, time\n"
        "output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "result = {'assertions_passed': True, 'office_exit_code': 0, 'run_complete': True,\n"
        "          'checks_ended_before_deadline': True}\n"
        "(output / 'results.json').write_text(json.dumps([result]))\n"
        "if '--without-extension' not in sys.argv:\n"
        "    time.sleep(1.5)  # A shutdown that outlasts the limit.\n",
        encoding="utf-8",
    )
    output = tmp_path / "results"
    process = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "soak.py"),
            "--program",
            str(tmp_path),
            "--oxt",
            str(tmp_path / "synthetic.oxt"),
            "--output",
            str(output),
            "--soak",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 1, process.stdout + process.stderr
    installed, absent = json.loads((output / "soak-results.json").read_text(encoding="utf-8"))
    assert installed["runner_exit"] == 124
    assert installed["limit"] == "after the checks: no stall recorded"
    assert absent["runner_exit"] == 0 and absent["limit"] == ""
    summary = (output / "soak-summary.md").read_text(encoding="utf-8")
    assert "| after the checks: no stall recorded |" in summary


# The real runner, in a soak session whose start-up is slow, with the reviewer's two cases: checks
# that make progress across the soak's limit, and a stall whose capture keeps no stack bytes.
SESSION = """
import sys, time
from pathlib import Path

output, case, outer = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])
time.sleep(0.8)  # A slow start-up, before the runner imports office_process.
import pytest
from tests.integration import office_process, teardown
from tests.unit import test_stall_session as stall_session

deadline = office_process.DEADLINE
with pytest.MonkeyPatch.context() as patch, stall_session.loaded_runner(patch) as runner:
    patch.setattr(office_process, "DEADLINE", deadline)  # The fixture clears it.
    patch.setattr(office_process, "STALL_SECONDS", 900.0)
    if case == "receipt only":
        def unwritable(*args, **kwargs):
            raise OSError("synthetic: the client's stacks cannot be written")
        patch.setattr(office_process.faulthandler, "dump_traceback", unwritable)
    office = stall_session.Office()

    def body(*args):
        if case == "receipt only":
            office.wait_stopped(30)  # Blocked, as in a UNO call, until the office stops.
        while time.monotonic() < outer + 0.3:  # Otherwise progress until past the soak's limit.
            teardown.note_progress()
            time.sleep(0.02)
        return {}

    stall_session.session(runner, patch, output, office, body)
"""


@pytest.mark.skipif(
    sys.platform != "linux", reason="The soak runs only inside the Linux test image"
)
@pytest.mark.parametrize("case", ["progress across the limit", "receipt only"])
def test_a_limit_in_the_checks_is_recorded_whatever_the_runners_start_up_takes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    monkeypatch.setenv("PYTHONPATH", f"{ROOT}{os.pathsep}{ROOT / 'src'}")
    limit = 4.0
    outer = time.monotonic() + limit  # The soak's limit, as run_session computes it.
    command = [sys.executable, "-c", SESSION, str(tmp_path), case, repr(outer)]
    with (tmp_path / "runner.log").open("w", encoding="utf-8") as log:
        status = soak.run_session(command, log, limit=limit, grace=15)
    output = tmp_path / "results"
    log_text = (tmp_path / "runner.log").read_text(encoding="utf-8")
    assert status == 124, log_text
    (result,) = json.loads((output / "results.json").read_text(encoding="utf-8"))
    stalls = sorted(path.name for path in output.glob("stall-*.json"))
    assert stalls == ["stall-True-0.json"], log_text
    assert result["office_progress_stall"]["cause"] == "deadline"
    assert not result["run_complete"] and "checks_ended_before_deadline" not in result
    assert soak.limit_outcome(status, [result], stalls) == "stall recorded"
    if case == "receipt only":
        # The summary claims a recorded stall, and no more: no stack bytes were kept.
        assert sum(path.stat().st_size for path in output.glob("*stacks.txt")) == 0
        assert "client_stacks" in result["office_progress_stall"]["diagnostic_errors"]


OUTCOMES: list[tuple[int, list[dict[str, Any]] | None, list[str], str]] = [
    (0, [{"assertions_passed": True}], [], ""),
    (1, [{}], ["stall-False-0.json"], ""),
    # A receipt shows the stall was recorded, even when its capture kept no stack bytes.
    (
        124,
        [{"office_progress_stall": {"office_stacks": {}}}],
        ["stall-True-0.json"],
        "stall recorded",
    ),
    (
        124,
        [{"assertions_passed": True, "checks_ended_before_deadline": True}],
        [],
        "after the checks: no stall recorded",
    ),
    # Passed checks show that they ended, not when.
    (124, [{"assertions_passed": True}], [], "no stall recorded; phase unknown"),
    (124, [{}], [], "no stall recorded; phase unknown"),
    (124, None, [], "no stall recorded; phase unknown"),
]


@pytest.mark.parametrize(("status", "results", "stalls", "outcome"), OUTCOMES)
def test_the_limit_column_names_each_outcome(
    status: int, results: list[dict[str, Any]] | None, stalls: list[str], outcome: str
) -> None:
    assert soak.limit_outcome(status, results, stalls) == outcome
