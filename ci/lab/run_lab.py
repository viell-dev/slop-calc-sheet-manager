"""Investigation of #8 only: run crash_lab.py arms in a pinned painted gtk3 image.

Builds the normal CI image for the lane, derives an image whose gdb script also records the
fault address, registers and library load addresses, builds the extension, and runs every arm
from ci/lab/arms.txt (or --arm) round-robin in fresh profiles. Not part of the normal checks.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from build import build  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=["minimum", "current-26.2", "current-26.8"])
    parser.add_argument("--rounds", type=int, required=True)
    parser.add_argument("--arm", action="append")
    parser.add_argument("--arms-file", type=Path, default=ROOT / "ci/lab/arms.txt")
    parser.add_argument("--no-backtrace", action="store_true")
    parser.add_argument(
        "--instrumented", action="store_true", help="Log view/shell lifetimes at breakpoints"
    )
    arguments = parser.parse_args()
    arms = arguments.arm or [
        line.strip()
        for line in arguments.arms_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    uid, gid = (os.getuid(), os.getgid()) if os.name == "posix" else (1000, 1000)
    pin = json.loads((ROOT / "ci/libreoffice.json").read_text())[arguments.lane]
    base = f"sheet-manager-ci:{pin['version']}-lab-base"
    image = f"sheet-manager-ci:{pin['version']}-lab"
    command = ["docker", "build", "--file", str(ROOT / "ci/Dockerfile"), "--tag", base]
    for key in ("version", "series", "url", "sha256"):
        command.extend(["--build-arg", f"LO_{key.upper()}={pin[key]}"])
    command.extend(["--build-arg", f"TEST_UID={uid}", "--build-arg", f"TEST_GID={gid}"])
    subprocess.run([*command, str(ROOT / "ci")], check=True)
    subprocess.run(
        [
            "docker",
            "build",
            "--file",
            str(ROOT / "ci/lab/Dockerfile"),
            "--build-arg",
            f"BASE={base}",
            "--build-arg",
            "GDBTRACE=" + ("gdbtrace-instr" if arguments.instrumented else "gdbtrace"),
            "--tag",
            image,
            str(ROOT / "ci/lab"),
        ],
        check=True,
    )
    package = build(ROOT / "dist")
    output = ROOT / "test-results" / arguments.lane
    output.mkdir(parents=True, exist_ok=True)
    command = ["docker", "run", "--rm", "--init", "--network", "none", "--shm-size", "512m"]
    if os.name == "posix":
        command.extend(["--user", f"{uid}:{gid}"])
    command.extend(["--env", "HOME=/tmp/sheet-manager-home"])
    for source, destination, readonly in (
        (ROOT, "/work", True),
        (ROOT / "ci/lab", "/lab", True),
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
    command.extend(["--entrypoint", "/bin/bash", image, "/lab/entry.sh"])
    command.extend(["--rounds", str(arguments.rounds)])
    for arm in arms:
        command.extend(["--arm", arm])
    if not arguments.no_backtrace:
        command.append("--backtrace")
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
