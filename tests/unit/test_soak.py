"""An unreadable session result must fail the soak without losing later measurements."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.integration import office_process, soak

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != "posix", reason="The soak runs only inside the Linux test image")
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


@pytest.mark.skipif(os.name != "posix", reason="The soak runs only inside the Linux test image")
def test_a_session_past_its_limit_fails_but_keeps_its_stall_evidence(tmp_path: Path) -> None:
    # The runner's deadline is the soak's limit; it then keeps its stacks and exits (#45).
    deadline = tmp_path / "deadline.txt"
    runner = "\n".join(
        [
            "import os, pathlib, sys, time",
            "out = pathlib.Path(sys.argv[1])",
            "out.write_text(os.environ['SHEET_MANAGER_DEADLINE_SECONDS'])",
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
    assert deadline.read_text(encoding="utf-8") == "0.5"
    assert (tmp_path / "stall-False-0.json").exists()  # Its capture finished in the grace.
    assert time.monotonic() - started < 10


@pytest.mark.skipif(os.name != "posix", reason="The soak runs only inside the Linux test image")
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
