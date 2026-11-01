"""Verify the official macOS package in a disposable hosted runner (#145).

Keep the application in this job's temporary directory, never /Applications. Verify the DMG
before mounting it, use LibreOffice's own Python wrapper, and let the existing runner own every
profile/process and assertion. A prepared lane is not macOS coverage until its native run passes.
Each command owns a new process group; timeout cleanup stops it before removing the application.
Darwin can refuse signals to zombie-only groups; verify member states before accepting that
case. Never reap the leader before signalling/draining its group, or signal it after reaping.
An unverified cleanup retains the private directory. Native controls exercise both TERM and KILL.
Keep the workflow timeout above the commands' combined budgets, including cleanup and upload.
Every failure, including diagnostic collection, leaves the host result marked unsuccessful.
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
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Complete native benchmark work exceeded 20 minutes in retained phase receipts (#162).
INTEGRATION_TIMEOUT = 30 * 60


class GroupCleanupError(RuntimeError):
    """A private command group could not be proved stopped; retain its application."""


def group_members(group: int) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid=,stat=,uid=,comm="],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    members: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 4)
        if len(fields) < 2:
            raise ValueError(f"Unexpected process-state row: {line!r}")
        pid, pgid = fields[:2]
        if int(pgid) != group:
            continue
        if len(fields) < 4:
            raise ValueError(f"Incomplete owned process-state row: {line!r}")
        state, uid = fields[2:4]
        members.append(
            {
                "pid": int(pid),
                "pgid": int(pgid),
                "state": state,
                "uid": int(uid),
                "command": fields[4] if len(fields) == 5 else "",
            }
        )
    return members


def live_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [member for member in members if not str(member["state"]).startswith("Z")]


def signal_group(group: int, sig: int, receipt: dict[str, Any]) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Private process-group signals require macOS")
    try:
        os.killpg(group, sig)
    except ProcessLookupError:
        receipt.setdefault("absent_at_signal", []).append(sig)
    except PermissionError:
        members = group_members(group)
        receipt.setdefault("permission_at_signal", []).append({"signal": sig, "members": members})
        if live_members(members):
            raise


def stop_group(process: subprocess.Popen[Any], receipt: dict[str, Any]) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Private process-group cleanup requires macOS")
    try:
        receipt["before"] = group_members(process.pid)
    except Exception as error:
        receipt["before_error"] = repr(error)  # A diagnostic failure cannot prevent the stop.
    signal_group(process.pid, signal.SIGTERM, receipt)
    time.sleep(0.5)
    signal_group(process.pid, signal.SIGKILL, receipt)
    deadline = time.monotonic() + 5
    while True:
        members = group_members(process.pid)
        receipt["after_signals"] = members
        if not live_members(members):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Private process-group members remain alive after SIGKILL")
        time.sleep(0.05)
    process.wait(timeout=5)  # Reap only after the group is stopped. Never signal this ID again.
    receipt["cleanup_succeeded"] = True


@contextmanager
def private_directory(parent: str) -> Generator[Path, None, None]:
    manager = tempfile.TemporaryDirectory(prefix="sheet-manager-macos-", dir=parent, delete=False)
    try:
        yield Path(manager.name).resolve()
    except BaseException as failure:
        pending = [failure]
        seen: set[int] = set()
        unsafe = False
        while pending:
            cause = pending.pop()
            if id(cause) in seen:
                continue
            seen.add(id(cause))
            unsafe = unsafe or isinstance(cause, GroupCleanupError)
            pending.extend(
                error for error in (cause.__context__, cause.__cause__) if error is not None
            )
        if unsafe:
            failure.add_note(
                f"Unverified process cleanup: retained private directory {manager.name}"
            )
        else:
            manager.cleanup()
        raise
    else:
        manager.cleanup()


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
        except subprocess.TimeoutExpired as failure:
            receipt: dict[str, Any] = {
                "command": command,
                "group": process.pid,
                "timeout_seconds": timeout,
                "cleanup_succeeded": False,
            }
            cleanup_error = None
            try:
                stop_group(process, receipt)
            except BaseException as error:
                cleanup_error = error
                receipt["cleanup_error"] = repr(error)
            try:
                log.with_suffix(".timeout.json").write_text(
                    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
                )
            except Exception as error:
                failure.add_note(f"Retaining timeout diagnostics also failed: {error!r}")
            if cleanup_error is not None:
                raise GroupCleanupError(
                    f"Private group {process.pid} cleanup failed: {cleanup_error}"
                ) from failure
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)


def timeout_controls(output: Path, environment: dict[str, str]) -> None:
    """Prove native stopped-group handling before running an installed application."""
    controls = {}
    for name, source in (
        ("term", "import time; print('term-ready', flush=True); time.sleep(60)"),
        (
            "kill",
            "import signal,subprocess,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "subprocess.Popen([sys.executable, '-c', "
            "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            'print("kill-child-ready", flush=True); time.sleep(60)\']); '
            "print('kill-parent-ready', flush=True); "
            "time.sleep(60)",
        ),
    ):
        log = output / f"timeout-control-{name}.log"
        try:
            run([sys.executable, "-c", source], log, environment, timeout=5)
        except subprocess.TimeoutExpired as failure:
            receipt = json.loads(log.with_suffix(".timeout.json").read_text("utf-8"))
            after = receipt.get("after_signals")
            if receipt.get("cleanup_succeeded") is not True or after is None or live_members(after):
                raise AssertionError(
                    f"The {name} timeout control left an unverified group"
                ) from failure
            expected = (
                ["term-ready"] if name == "term" else ["kill-parent-ready", "kill-child-ready"]
            )
            text = log.read_text("utf-8")
            if not all(marker in text for marker in expected) or len(
                live_members(receipt.get("before", []))
            ) < len(expected):
                raise AssertionError(
                    f"The {name} timeout control did not finish setup"
                ) from failure
            controls[name] = receipt
        else:
            raise AssertionError(f"The {name} timeout control did not fail at its deadline")
    (output / "timeout-controls.json").write_text(
        json.dumps(controls, indent=2) + "\n", encoding="utf-8"
    )


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
        timeout_controls(output, environment)
        reports = Path.home() / "Library/Logs/DiagnosticReports"
        preceding = set(reports.glob("*"))
        with private_directory(os.environ["RUNNER_TEMP"]) as temporary:
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
                    INTEGRATION_TIMEOUT,
                )
                result["assertions_passed"] = True
            finally:
                result["native_crash_reports"] = collect_reports(app, output, preceding)
                if result["native_crash_reports"]:
                    result["assertions_passed"] = False
                    raise AssertionError("This private application produced a native crash report")
    except BaseException:
        result["assertions_passed"] = False
        result["error"] = traceback.format_exc()
        raise
    finally:
        (output / "host-results.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
