"""Measure independent painted sessions with and without the extension; never retry a failure."""

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path


def main():
    if os.name != "posix":
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
        "| Mode | Session | Runner exit | Office/wrapper exit | Fatal markers | Assertions |",
        "| --- | ---: | ---: | --- | --- | --- |",
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
                ]
                if mode == "absent":
                    command.append("--without-extension")
                if arguments.backtrace:
                    command.append("--backtrace")
                with (directory / "runner.log").open("w", encoding="utf-8") as log:
                    process = subprocess.Popen(
                        command,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    try:
                        status = process.wait(timeout=180)
                    except subprocess.TimeoutExpired:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                        status = 124
                result_path = directory / "results.json"
                results = json.loads(result_path.read_text()) if result_path.exists() else []
                row = {"mode": mode, "session": number, "runner_exit": status, "results": results}
                rows.append(row)
                print(json.dumps(row), flush=True)
                office = [result.get("office_exit_code") for result in results]
                markers = [
                    marker
                    for result in results
                    for marker in result.get("office_fatal_markers", [])
                ]
                assertions = bool(results) and all(
                    result.get("assertions_passed") for result in results
                )
                summary.append(
                    f"| {mode} | {number} | {status} | {office} | {markers} | {assertions} |"
                )
    finally:
        output.mkdir(parents=True, exist_ok=True)
        (output / "soak-results.json").write_text(
            json.dumps(rows, indent=2) + "\n", encoding="utf-8"
        )
        (output / "soak-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    raise SystemExit(int(any(row["runner_exit"] for row in rows)))


if __name__ == "__main__":
    main()
