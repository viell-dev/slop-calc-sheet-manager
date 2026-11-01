"""Verify the official macOS package in a disposable hosted runner (#145).

Keep the application in this job's temporary directory, never /Applications. Verify the DMG
before mounting it, use LibreOffice's own Python wrapper, and let the existing runner own every
profile/process and assertion. A prepared lane is not macOS coverage until its native run passes.
Each command owns a new process group; timeout cleanup stops it before removing the application.
Keep the workflow timeout above the commands' combined budgets, including cleanup and upload.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def checked_binary(app: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(app.resolve()) or not resolved.is_file():
        raise ValueError(
            f"Missing executable or bundle link leaves the private application: {path}"
        )
    if not os.access(resolved, os.X_OK):
        raise ValueError(f"The bundled executable is not executable: {path}")
    return resolved


def run(command: list[str], log: Path, environment: dict[str, str], timeout: int = 120) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Native command execution requires macOS")
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # The integration client's office processes inherit this private process group.
            # Stop that group before TemporaryDirectory can remove the live application.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            # Keep the group leader unreaped until the final signal, so its PID cannot be
            # reused for an unrelated group. Children may outlive a terminated client.
            time.sleep(0.5)
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)


def install(
    image: Path, pin: dict[str, str], temporary: Path, output: Path, environment: dict[str, str]
) -> Path:
    with image.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    size = image.stat().st_size
    (output / "download.json").write_text(
        json.dumps({**pin, "actual_sha256": actual, "bytes": size}, indent=2) + "\n",
        encoding="utf-8",
    )
    if actual != pin["sha256"]:
        raise ValueError(
            f"LibreOffice DMG checksum mismatch: expected {pin['sha256']}, got {actual} "
            f"({size} bytes); nothing will be mounted or executed"
        )
    mount = temporary / "mount"
    mount.mkdir()
    run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(image)],
        output / "mount.log",
        environment,
    )
    app = temporary / "LibreOffice.app"
    try:
        run(["ditto", str(mount / "LibreOffice.app"), str(app)], output / "copy.log", environment)
    finally:
        run(["hdiutil", "detach", str(mount)], output / "unmount.log", environment)
    return app


def collect_reports(app: Path, output: Path, preceding: set[Path]) -> list[str]:
    """Retain new reports whose content identifies this job's private application."""
    names: list[str] = []
    directory = Path.home() / "Library/Logs/DiagnosticReports"
    for path in directory.glob("*"):
        if path in preceding or not path.is_file() or path.suffix not in (".ips", ".crash"):
            continue
        if str(app.resolve()) not in path.read_text(encoding="utf-8", errors="replace"):
            continue
        shutil.copy2(path, output / path.name)
        names.append(path.name)
    return names


def main() -> None:
    output = ROOT / "test-results/macos"
    output.mkdir(parents=True, exist_ok=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTHONEXECUTABLE",
            "VIRTUAL_ENV",
            "__PYVENV_LAUNCHER__",
            "DYLD_LIBRARY_PATH",
            "DYLD_FALLBACK_LIBRARY_PATH",
            "URE_BOOTSTRAP",
            "UNO_PATH",
        }
    }
    result: dict[str, Any] = {
        "assertions_passed": False,
        "platform": platform.platform(),
        "architecture": platform.machine(),
    }
    try:
        if sys.platform != "darwin" or os.environ.get("GITHUB_ACTIONS") != "true":
            raise SystemExit("This installer is for a disposable macOS GitHub runner only")
        pin = json.loads((ROOT / "ci/libreoffice.json").read_text("utf-8"))["macos"]
        result["pin"] = pin
        if platform.machine() != pin["architecture"]:
            raise SystemExit(f"Expected {pin['architecture']}, got {platform.machine()}")
        reports = Path.home() / "Library/Logs/DiagnosticReports"
        preceding = set(reports.glob("*"))
        with tempfile.TemporaryDirectory(
            prefix="sheet-manager-macos-", dir=os.environ["RUNNER_TEMP"]
        ) as directory:
            temporary = Path(directory).resolve()
            image = temporary / "libreoffice.dmg"
            run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--retry",
                    "2",
                    "--max-time",
                    "600",
                    "--output",
                    str(image),
                    pin["url"],
                ],
                output / "download.log",
                environment,
                660,
            )
            app = install(image, pin, temporary, output, environment)
            try:
                wrapper = checked_binary(app, app / "Contents/Resources/python")
                program = app / "Contents/MacOS"
                office = checked_binary(app, program / "soffice")
                checked_binary(app, program / "unopkg")
                run(
                    [
                        str(office),
                        "-env:UserInstallation=" + (temporary / "version-profile").as_uri(),
                        "--headless",
                        "--version",
                    ],
                    output / "office-version.txt",
                    environment,
                )
                actual = (output / "office-version.txt").read_text("utf-8")
                if not re.search(r"\b" + re.escape(pin["version"]) + r"\b", actual):
                    raise ValueError(f"Unexpected installed version: {actual}")
                run(
                    [str(wrapper), "-c", "import sys,uno; print(sys.version); print(uno.__file__)"],
                    output / "python-uno.txt",
                    environment,
                )
                run([str(wrapper), str(ROOT / "tools/build.py")], output / "build.log", environment)
                packages = list((ROOT / "dist").glob("*.oxt"))
                if len(packages) != 1:
                    raise ValueError("Expected one freshly built package")
                run(
                    [
                        str(wrapper),
                        str(ROOT / "tests/integration/run.py"),
                        "--program",
                        str(program),
                        "--oxt",
                        str(packages[0]),
                        "--sessions",
                        "headless",
                        "--output",
                        str(output / "integration"),
                    ],
                    output / "integration.log",
                    environment,
                    1200,
                )
                result["assertions_passed"] = True
            finally:
                result["native_crash_reports"] = collect_reports(app, output, preceding)
                if result["native_crash_reports"]:
                    result["assertions_passed"] = False
                    raise AssertionError("This private application produced a native crash report")
    except BaseException:
        result["error"] = traceback.format_exc()
        raise
    finally:
        (output / "host-results.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
