"""Measure independent painted sessions with and without the extension; never retry a failure."""

# A session that this process finds still running at SESSION_SECONDS fails with status 124. The
# runner gets the same moment as its deadline, as an absolute time on the monotonic clock that
# both share (`SHEET_MANAGER_DEADLINE_MONOTONIC`), so its own start-up cannot move it later. There
# its stall watch records the stall, tries to save stacks and stops the office (#45);
# CAPTURE_GRACE_SECONDS more lets it do that and exit before its process group is killed. Keep
# the grace above the watch's CAPTURE_SECONDS and STOP_SECONDS together (`office_process`; a unit
# test checks it). Kill the group before reaping the runner: until it is reaped, its process ID,
# which is the group's, cannot pass to a new process. A runner that exits after the limit while
# this process is not scheduled reports its own status (#244).
# The summary gives each session's status and what its `results.json` says, and points to the
# session's directory; it draws no conclusion of its own about stalls or when a limit fell, which
# the session's results and receipts record. Each session starts in an emptied directory, so that
# nothing the summary reads or points to comes from an earlier soak, even if the runner never
# reaches its own clean-up.

import argparse
import contextlib
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

SESSION_SECONDS = 180
CAPTURE_GRACE_SECONDS = 150


def wait_unreaped(process: subprocess.Popen[bytes], seconds: float) -> None:
    """Wait up to `seconds` for `process` to exit, leaving it unreaped."""
    if sys.platform != "linux":
        raise RuntimeError("Run the soak inside the Linux test image")
    try:
        handle = os.pidfd_open(process.pid)
    except ProcessLookupError:  # Not possible while it is unreaped; nothing to wait for.
        return
    try:
        select.select([handle], [], [], seconds)  # A pidfd turns readable when its process exits.
    finally:
        os.close(handle)


def run_session(
    command: list[str],
    log: TextIO,
    limit: float = SESSION_SECONDS,
    grace: float = CAPTURE_GRACE_SECONDS,
) -> int:
    """Run one runner in its own process group; return its status, or 124 after `limit` seconds.

    A runner still running at `limit` fails whatever happens next; it then has `grace` seconds
    to keep its stall evidence and exit, and its whole group is killed after that. The runner's
    deadline is this same moment.
    """
    deadline = time.monotonic() + limit
    environment = dict(os.environ, SHEET_MANAGER_DEADLINE_MONOTONIC=repr(deadline))
    environment.pop("SHEET_MANAGER_DEADLINE_SECONDS", None)
    process = subprocess.Popen(
        command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=environment
    )
    try:
        return process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        if sys.platform != "linux":
            raise
        wait_unreaped(process, grace)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return 124


def main():
    if sys.platform != "linux":
        raise SystemExit("Run the soak inside the Linux test image")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--oxt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--soak", type=int, required=True, choices=range(1, 101))
    parser.add_argument("--sessions", choices=["gtk3"], default="gtk3")
    parser.add_argument("--backtrace", action="store_true")
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    rows = []
    summary = [
        "# Painted gtk3 soak",
        "",
        f"{arguments.soak} fresh sessions per mode; backtrace: {arguments.backtrace}.",
        "",
        "Runner status and office/wrapper exit are separate; "
        "debugger fatal markers also fail a run.",
        "",
        "Each session's `results.json`, `runner.log` and any `stall-*.json` receipts are in the "
        "directory under Files, which the soak empties before the session starts.",
        "",
        "| Mode | Session | Runner exit | Office/wrapper exit | Fatal markers | Assertions | "
        "Results error | Files |",
        "| --- | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    try:
        for mode in ("installed", "absent"):
            for number in range(1, arguments.soak + 1):
                files = f"{mode}/{number:03d}"
                directory = output / files
                # An earlier soak's files there would pass for this session's.
                if directory.exists():
                    shutil.rmtree(directory)
                directory.mkdir(parents=True)
                command = [
                    sys.executable,
                    str(Path(__file__).with_name("run.py")),
                    "--program",
                    str(arguments.program),
                    "--oxt",
                    str(arguments.oxt),
                    "--output",
                    str(directory),
                    "--sessions",
                    "gtk3",
                    "--startup-attempts",
                    "1",
                    "--suites",
                    "none",
                ]
                if mode == "absent":
                    command.append("--without-extension")
                if arguments.backtrace:
                    command.append("--backtrace")
                with (directory / "runner.log").open("w", encoding="utf-8") as log:
                    status = run_session(command, log)
                result_path = directory / "results.json"
                results_error = None
                try:
                    results = json.loads(result_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as error:
                    results = None
                    results_error = f"{type(error).__name__}: {error}"
                row = {
                    "mode": mode,
                    "session": number,
                    "runner_exit": status,
                    "files": files,
                    "results": results,
                    "results_error": results_error,
                }
                rows.append(row)
                print(json.dumps(row), flush=True)
                office = [result.get("office_exit_code") for result in results or []]
                markers = [
                    marker
                    for result in results or []
                    for marker in result.get("office_fatal_markers", [])
                ]
                assertions = bool(results) and all(
                    result.get("assertions_passed") for result in results
                )
                summary.append(
                    f"| {mode} | {number} | {status} | {office} | {markers} | {assertions} | "
                    f"{results_error or ''} | `{files}/` |"
                )
    finally:
        output.mkdir(parents=True, exist_ok=True)
        (output / "soak-results.json").write_text(
            json.dumps(rows, indent=2) + "\n", encoding="utf-8"
        )
        (output / "soak-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    raise SystemExit(int(any(row["runner_exit"] or row["results_error"] for row in rows)))


if __name__ == "__main__":
    main()
