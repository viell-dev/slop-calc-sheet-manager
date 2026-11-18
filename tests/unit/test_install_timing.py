"""The integration runner records how long each `unopkg add` takes, and a timeout fails (#235).

`add_package` is read from `tests/integration/run.py`, which imports UNO, and run with a Python
script standing in for unopkg: the script receives the profile argument as its own path, then
`add` and the package, as unopkg would.
"""

import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, cast

import pytest

from tests.unit.source_methods import function

RUN = "tests/integration/run.py"


def add_package(limit: float) -> Any:
    namespace: dict[str, Any] = {
        "subprocess": subprocess,
        "time": time,
        "cast": cast,
        "INSTALL_SECONDS": limit,
    }
    function(RUN, "_text", namespace)
    return function(RUN, "add_package", namespace)


def installer(directory: Path, body: str) -> str:
    script = directory / "unopkg.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(script)


def test_an_install_records_its_elapsed_time(tmp_path: Path) -> None:
    script = installer(
        tmp_path,
        """
        import sys, time
        time.sleep(0.3)
        print("added", sys.argv[1:])
        """,
    )
    record: dict[str, object] = {}
    completed = add_package(10)(sys.executable, script, tmp_path / "x.oxt", record)
    assert completed.returncode == 0 and "added ['add'," in completed.stdout
    seconds = cast(list[float], record["install_seconds"])
    assert len(seconds) == 1 and 0.3 <= seconds[0] < 10
    assert "install_timed_out" not in record


def test_a_failed_install_keeps_its_time_and_appends_to_earlier_attempts(tmp_path: Path) -> None:
    script = installer(tmp_path, "raise SystemExit(3)\n")
    record: dict[str, object] = {"install_seconds": [1.5]}
    completed = add_package(10)(sys.executable, script, tmp_path / "x.oxt", record)
    assert completed.returncode == 3
    seconds = cast(list[float], record["install_seconds"])
    assert len(seconds) == 2 and seconds[0] == 1.5 and 0 <= seconds[1] < 10


def test_a_timeout_fails_with_its_elapsed_time_and_the_output_so_far(tmp_path: Path) -> None:
    script = installer(
        tmp_path,
        """
        import time
        print("synchronizing", flush=True)
        time.sleep(30)
        """,
    )
    record: dict[str, object] = {}
    started = time.monotonic()
    with pytest.raises(AssertionError, match="did not finish within 1 seconds\nsynchronizing"):
        add_package(1)(sys.executable, script, tmp_path / "x.oxt", record)
    assert time.monotonic() - started < 15  # The installer is stopped, not waited for.
    assert record["install_timed_out"] is True
    seconds = cast(list[float], record["install_seconds"])
    assert len(seconds) == 1 and 1 <= seconds[0] < 15
