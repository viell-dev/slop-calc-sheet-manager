"""Build and run a pinned LibreOffice Docker lane on Linux or Windows."""

import argparse
import hashlib
import json
import os
import subprocess
from typing import cast

from build import ROOT, build


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=["minimum", "current-26.2", "current-26.8", "unsupported"])
    parser.add_argument("--skip-build", action="store_true", help="Reuse only a matching CI image")
    parser.add_argument("--screenshot", action="store_true")
    parser.add_argument("--sessions", choices=["headless", "gtk3", "both"])
    parser.add_argument("--backtrace", action="store_true")
    parser.add_argument(
        "--soak", type=int, metavar="N", help="Run N gtk3 sessions per extension mode"
    )
    arguments = parser.parse_args()
    if arguments.soak is not None and not 1 <= arguments.soak <= 100:
        parser.error("--soak must be between 1 and 100")
    if arguments.soak is not None and (
        arguments.lane == "unsupported"
        or arguments.sessions not in (None, "gtk3")
        or arguments.screenshot
    ):
        parser.error("--soak requires a supported lane and --sessions gtk3")
    if os.name == "posix":
        uid, gid = os.getuid(), os.getgid()
        if uid == 0:
            raise SystemExit("Run the integration helper as an unprivileged host user")
    else:
        uid, gid = 1000, 1000
    pins = cast(dict[str, dict[str, str]], json.loads((ROOT / "ci/libreoffice.json").read_text()))
    pin = pins[arguments.lane]
    fingerprint = hashlib.sha256(
        (ROOT / "ci/Dockerfile").read_bytes()
        + json.dumps(pin, sort_keys=True).encode()
        + f"{uid}:{gid}".encode()
    ).hexdigest()[:16]
    image = f"sheet-manager-ci:{pin['version']}-{fingerprint}"
    cached = (
        arguments.skip_build
        and subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
        ).returncode
        == 0
    )
    if not cached:
        if arguments.skip_build:
            print("No image matches this Dockerfile, pin, and UID/GID; rebuilding", flush=True)
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
    else:
        command.extend(
            [
                "--sessions",
                arguments.sessions
                or (
                    "gtk3"
                    if arguments.soak is not None
                    else "both"
                    if arguments.screenshot
                    else "headless"
                ),
            ]
        )
        if arguments.soak is not None:
            command.extend(["--soak", str(arguments.soak)])
        if arguments.backtrace:
            command.append("--backtrace")
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
