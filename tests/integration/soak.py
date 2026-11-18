"""Measure independent painted sessions with and without the extension; never retry a failure."""

# A session that has not finished within SESSION_SECONDS fails with status 124. The runner gets
# the same moment as its deadline, as an absolute time on the monotonic clock that both share
# (`SHEET_MANAGER_DEADLINE_MONOTONIC`), so its own start-up cannot move it later. There its stall
# watch records the stall, keeps what stacks it can and stops the office (#45);
# CAPTURE_GRACE_SECONDS more lets it do that and exit before its process group is killed. Keep
# the grace above the watch's CAPTURE_SECONDS and STOP_SECONDS together (`office_process`; a unit
# test checks it). The watch runs from the office's launch until the session's checks end, so a
# limit reached while installing or shutting down, which have limits of their own, records no
# stall. The summary's Limit column claims only what the session's files show: a stall receipt,
# or the runner's record that its checks ended before the deadline; otherwise the phase is
# unknown. Kill the group before reaping the runner: until it is reaped, its process ID, which is
# the group's, cannot pass to a new process.

import argparse
import contextlib
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TextIO

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


def limit_outcome(status: int, results: list[dict[str, Any]] | None, stalls: list[str]) -> str:
    """For the summary: what a session's files show about when it reached its limit.

    A receipt shows that the stall was recorded; which stacks its capture kept is in the receipt.
    The runner records that its checks ended before the deadline only when its watch closed
    before it. Without either, when the limit fell is not known.
    """
    if status != 124:
        return ""
    if stalls:
        return "stall recorded"
    if results and all(result.get("checks_ended_before_deadline") for result in results):
        return "after the checks: no stall recorded"
    return "no stall recorded; phase unknown"


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
        "| Mode | Session | Runner exit | Office/wrapper exit | Fatal markers | Assertions | "
        "Stall | Limit | Results error |",
        "| --- | ---: | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    try:
        for mode in ("installed", "absent"):
            for number in range(1, arguments.soak + 1):
                directory = output / mode / f"{number:03d}"
                directory.mkdir(parents=True, exist_ok=True)
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
                stalls = sorted(path.name for path in directory.glob("stall-*.json"))
                limit = limit_outcome(status, results, stalls)
                row = {
                    "mode": mode,
                    "session": number,
                    "runner_exit": status,
                    "limit": limit,
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
                    f"{', '.join(stalls)} | {limit} | {results_error or ''} |"
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
