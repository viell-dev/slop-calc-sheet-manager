"""Build and run a pinned LibreOffice Docker lane on Linux or Windows."""

import argparse
import json
import os
import subprocess
from typing import cast

from build import ROOT, build


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=["minimum", "current-26.2", "current-26.8", "unsupported"])
    parser.add_argument("--skip-build", action="store_true", help="Use an already built CI image")
    parser.add_argument("--screenshot", action="store_true")
    parser.add_argument(
        "--ui", action="store_true", help="Run the real-input UI tests with gtk3 and gen instead"
    )
    arguments = parser.parse_args()
    if arguments.ui and (arguments.lane == "unsupported" or arguments.screenshot):
        parser.error("--ui needs a supported lane and cannot be combined with --screenshot")
    if os.name == "posix":
        uid, gid = os.getuid(), os.getgid()
        if uid == 0:
            raise SystemExit("Run the integration helper as an unprivileged host user")
    else:
        uid, gid = 1000, 1000
    pins = cast(dict[str, dict[str, str]], json.loads((ROOT / "ci/libreoffice.json").read_text()))
    pin = pins[arguments.lane]
    image = "sheet-manager-ci:" + pin["version"]
    if not arguments.skip_build:
        command = ["docker", "build", "--file", str(ROOT / "ci/Dockerfile"), "--tag", image]
        for key in ("version", "series", "url", "sha256"):
            command.extend(["--build-arg", f"LO_{key.upper()}={pin[key]}"])
        command.extend(["--build-arg", f"TEST_UID={uid}", "--build-arg", f"TEST_GID={gid}"])
        subprocess.run([*command, str(ROOT / "ci")], check=True)
    package = build(ROOT / "dist")
    output = ROOT / "test-results" / arguments.lane
    output.mkdir(parents=True, exist_ok=True)
    # Docker Desktop and Linux both accept these argument-array mounts; no shell quoting.
    # xvfb-run waits for a readiness signal; keep its shell away from PID 1's signal semantics.
    command = ["docker", "run", "--rm", "--init", "--network", "none", "--shm-size", "512m"]
    if os.name == "posix":
        command.extend(["--user", f"{uid}:{gid}"])
    command.extend(["--env", "HOME=/tmp/sheet-manager-home"])
    for source, destination, readonly in (
        (ROOT, "/work", True),
        (package, "/packages/extension.oxt", True),
        (output, "/results", False),
    ):
        command.extend(
            [
                "--mount",
                f"type=bind,source={source},target={destination}"
                + (",readonly" if readonly else ""),
            ]
        )
    command.append(image)
    if arguments.lane == "unsupported":
        command.append("--expect-refusal")
    elif arguments.ui:
        command.append("--ui")
    elif arguments.screenshot:
        command.append("--screenshot")
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
