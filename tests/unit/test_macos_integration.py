"""Private-install and diagnostic boundaries, without pretending to execute macOS."""

import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools import macos_integration as cli


def test_checksum_failure_prevents_mounting_or_running_a_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "office.dmg"
    image.write_bytes(b"unexpected package")
    run = Mock()
    monkeypatch.setattr(cli, "run", run)
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match=f"checksum mismatch:.*{digest}.*{image.stat().st_size}"):
        cli.install(image, {"sha256": "0" * 64}, tmp_path, tmp_path, {})
    run.assert_not_called()
    receipt = json.loads((tmp_path / "download.json").read_text("utf-8"))
    assert receipt == {
        "sha256": "0" * 64,
        "actual_sha256": digest,
        "bytes": image.stat().st_size,
    }


def test_verified_image_is_mounted_read_only_and_always_detached_on_copy_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "office.dmg"
    image.write_bytes(b"known fixture")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    calls: list[list[str]] = []

    def run(command: list[str], log: Path, environment: dict[str, str], timeout: int = 120) -> None:
        calls.append(command)
        if command[0] == "ditto":
            raise RuntimeError("copy failed")

    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(RuntimeError, match="copy failed"):
        cli.install(image, {"sha256": digest}, tmp_path, tmp_path, {})
    assert "-readonly" in calls[0] and "-nobrowse" in calls[0]
    assert calls[-1] == ["hdiutil", "detach", str(tmp_path / "mount")]
    assert not any("/Applications" in part for command in calls for part in command)


def test_executable_must_resolve_inside_the_private_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = tmp_path / "LibreOffice.app"
    app.mkdir()
    binary = app / "python"
    binary.write_bytes(b"fixture")
    outside = tmp_path / "external-python"
    outside.write_bytes(b"fixture")
    monkeypatch.setattr(os, "access", Mock(return_value=True))
    assert cli.checked_binary(app, binary) == binary.resolve()
    with pytest.raises(ValueError, match="leaves the private application"):
        cli.checked_binary(app, outside)
    with pytest.raises(ValueError, match="Missing executable"):
        cli.checked_binary(app, app / "missing")


def test_only_new_reports_identifying_this_application_are_retained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    reports = tmp_path / "Library/Logs/DiagnosticReports"
    reports.mkdir(parents=True)
    output = tmp_path / "results"
    output.mkdir()
    app = tmp_path / "private/LibreOffice.app"
    previous = reports / "previous.crash"
    previous.write_text(str(app.resolve()), encoding="utf-8")
    owned = reports / "soffice.ips"
    owned.write_text(str(app.resolve()), encoding="utf-8")
    (reports / "unrelated.ips").write_text("/Applications/Another.app", encoding="utf-8")
    assert cli.collect_reports(app, output, {previous}) == [owned.name]
    assert [path.name for path in output.iterdir()] == [owned.name]


def test_installer_refuses_other_hosts_before_any_external_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    run = Mock()
    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(SystemExit, match="disposable macOS"):
        cli.main()
    run.assert_not_called()
    result = json.loads((tmp_path / "test-results/macos/host-results.json").read_text("utf-8"))
    assert result["assertions_passed"] is False
    assert "disposable macOS" in result["error"]


def test_wrong_architecture_is_recorded_before_any_external_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.platform, "machine", lambda: "arm64")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci/libreoffice.json").write_text(
        json.dumps({"macos": {"architecture": "x86_64"}}), encoding="utf-8"
    )
    run = Mock()
    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(SystemExit, match="Expected x86_64, got arm64"):
        cli.main()
    run.assert_not_called()
    result = json.loads((tmp_path / "test-results/macos/host-results.json").read_text("utf-8"))
    assert result["assertions_passed"] is False
    assert result["architecture"] == "arm64"
    assert "Expected x86_64, got arm64" in result["error"]


@pytest.fixture
def native_commands_stubbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Mock]:
    """Exercise failure propagation only; no native command or application is executed."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.platform, "machine", lambda: "x86_64")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci/libreoffice.json").write_text(
        json.dumps(
            {
                "macos": {
                    "architecture": "x86_64",
                    "version": "26.8.2.2",
                    "url": "https://example.invalid/pinned.dmg",
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/fixture.oxt").write_bytes(b"test-only package placeholder")
    monkeypatch.setattr(cli, "install", Mock(return_value=tmp_path / "LibreOffice.app"))

    def binary(app: Path, path: Path) -> Path:
        return path

    monkeypatch.setattr(cli, "checked_binary", binary)
    monkeypatch.setattr(cli, "collect_reports", Mock(return_value=[]))
    monkeypatch.setattr(cli, "timeout_controls", Mock())

    def run(command: list[str], log: Path, environment: dict[str, str], timeout: int = 120) -> None:
        log.write_text("LibreOffice 26.8.2.2" if log.name == "office-version.txt" else "", "utf-8")

    runner = Mock(side_effect=run)
    monkeypatch.setattr(cli, "run", runner)
    return tmp_path / "test-results/macos", runner


def test_version_mismatch_fails_before_integration_and_retains_the_reason(
    native_commands_stubbed: tuple[Path, Mock],
) -> None:
    output, runner = native_commands_stubbed

    def wrong_version(
        command: list[str], log: Path, environment: dict[str, str], timeout: int = 120
    ) -> None:
        log.write_text("LibreOffice 26.2.1.2", "utf-8")

    runner.side_effect = wrong_version
    with pytest.raises(ValueError, match="Unexpected installed version"):
        cli.main()
    assert all(call.args[1].name != "integration.log" for call in runner.call_args_list)
    result = json.loads((output / "host-results.json").read_text("utf-8"))
    assert result["assertions_passed"] is False
    assert "26.2.1.2" in result["error"]


def test_new_owned_crash_report_overrides_otherwise_successful_commands(
    native_commands_stubbed: tuple[Path, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    output, runner = native_commands_stubbed
    monkeypatch.setattr(cli, "collect_reports", Mock(return_value=["soffice.ips"]))
    with pytest.raises(AssertionError, match="native crash report"):
        cli.main()
    assert any(call.args[1].name == "integration.log" for call in runner.call_args_list)
    result = json.loads((output / "host-results.json").read_text("utf-8"))
    assert result["assertions_passed"] is False
    assert result["native_crash_reports"] == ["soffice.ips"]


def test_diagnostic_collection_error_cannot_leave_a_successful_host_record(
    native_commands_stubbed: tuple[Path, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    output, _ = native_commands_stubbed
    monkeypatch.setattr(
        cli, "collect_reports", Mock(side_effect=OSError("diagnostics unavailable"))
    )
    with pytest.raises(OSError, match="diagnostics unavailable"):
        cli.main()
    result = json.loads((output / "host-results.json").read_text("utf-8"))
    assert result["assertions_passed"] is False
    assert "diagnostics unavailable" in result["error"]


def test_timeout_stops_only_the_new_private_process_group_before_propagating_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep unavailable POSIX APIs outside Windows static analysis as well as execution.
    if sys.platform == "win32":
        pytest.skip("The installer executes only on macOS/POSIX")
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    process = Mock(pid=47123)
    process.wait.side_effect = [
        subprocess.TimeoutExpired(["client"], 1),
        None,
    ]
    popen = Mock(return_value=process)
    kill = Mock()
    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    monkeypatch.setattr(cli.os, "killpg", kill)
    monkeypatch.setattr(cli.time, "sleep", Mock())
    monkeypatch.setattr(cli, "group_members", Mock(return_value=[{"state": "Z"}]))
    with pytest.raises(subprocess.TimeoutExpired):
        cli.run(["client"], tmp_path / "client.log", {}, timeout=1)
    assert popen.call_args.kwargs["start_new_session"] is True
    assert kill.call_args_list == [((47123, signal.SIGTERM),), ((47123, signal.SIGKILL),)]


@pytest.mark.parametrize("state", ["Z", "S"])
def test_permission_error_is_accepted_only_for_a_proved_stopped_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    if sys.platform == "win32":
        pytest.skip("The installer executes only on macOS/POSIX")
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    timeout = subprocess.TimeoutExpired(["client"], 1)
    process = Mock(pid=47123)
    process.wait.side_effect = [timeout, None]
    monkeypatch.setattr(cli.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(
        cli.os, "killpg", Mock(side_effect=[None, PermissionError("refused")]), raising=False
    )
    monkeypatch.setattr(cli.time, "sleep", Mock())
    monkeypatch.setattr(cli, "group_members", Mock(return_value=[{"state": state}]))
    expected = subprocess.TimeoutExpired if state == "Z" else cli.GroupCleanupError
    with pytest.raises(expected) as raised:
        cli.run(["client"], tmp_path / "client.log", {}, timeout=1)
    receipt = json.loads((tmp_path / "client.timeout.json").read_text("utf-8"))
    assert receipt["cleanup_succeeded"] is (state == "Z")
    if state == "Z":
        assert raised.value is timeout
    else:
        assert raised.value.__cause__ is timeout
        assert process.wait.call_count == 1, "A live group leader must stay unreaped"


def test_process_snapshot_keeps_only_members_of_the_owned_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = Mock(
        return_value=subprocess.CompletedProcess(
            [],
            0,
            "42 42 S 501 /private/python\n43 42 Z 501\n99 99 S 501\n",
        )
    )
    monkeypatch.setattr(cli.subprocess, "run", command)
    members = cli.group_members(42)
    assert [member["pid"] for member in members] == [42, 43]
    assert [member["pid"] for member in cli.live_members(members)] == [42]
    assert members[1]["command"] == ""


@pytest.mark.parametrize("unsafe", [False, True])
def test_private_application_is_retained_only_when_process_cleanup_is_unverified(
    tmp_path: Path, unsafe: bool
) -> None:
    with pytest.raises(RuntimeError), cli.private_directory(str(tmp_path)) as directory:
        (directory / "owned-app").write_text("fixture", encoding="utf-8")
        if unsafe:
            raise cli.GroupCleanupError("live child remains")
        raise RuntimeError("ordinary command failure")
    assert directory.exists() is unsafe


def test_native_control_cannot_accept_a_command_that_did_not_time_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "run", Mock())
    with pytest.raises(AssertionError, match="did not fail at its deadline"):
        cli.timeout_controls(tmp_path, {})


@pytest.mark.parametrize("mode", ["context", "cause"])
def test_wrapped_cleanup_failure_still_retains_the_application(tmp_path: Path, mode: str) -> None:
    with pytest.raises(AssertionError), cli.private_directory(str(tmp_path)) as directory:
        if mode == "context":
            try:
                raise cli.GroupCleanupError("live child")
            except cli.GroupCleanupError:
                raise AssertionError("later diagnostic failure") from None
        raise AssertionError("later diagnostic failure") from cli.GroupCleanupError("live child")
    assert directory.exists()


def test_interrupted_cleanup_is_recorded_as_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    timeout = subprocess.TimeoutExpired(["client"], 1)
    process = Mock(pid=47123)
    process.wait.side_effect = timeout
    monkeypatch.setattr(cli.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(cli, "stop_group", Mock(side_effect=KeyboardInterrupt()))
    with pytest.raises(cli.GroupCleanupError) as raised:
        cli.run(["client"], tmp_path / "client.log", {}, timeout=1)
    assert raised.value.__cause__ is timeout
    receipt = json.loads((tmp_path / "client.timeout.json").read_text("utf-8"))
    assert receipt["cleanup_succeeded"] is False
    assert "KeyboardInterrupt" in receipt["cleanup_error"]


@pytest.mark.parametrize(
    "fault", ["unverified", "live", "missing_after", "missing_before", "setup"]
)
def test_native_control_rejects_incomplete_or_unsuccessful_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    def run(command: list[str], log: Path, environment: dict[str, str], timeout: int = 120) -> None:
        receipt = {
            "cleanup_succeeded": fault != "unverified",
            "before": [{"state": "S"}],
            "after_signals": [{"state": "S" if fault == "live" else "Z"}],
        }
        if fault == "missing_after":
            del receipt["after_signals"]
        if fault == "missing_before":
            del receipt["before"]
        log.write_text("" if fault == "setup" else "term-ready\n", encoding="utf-8")
        log.with_suffix(".timeout.json").write_text(json.dumps(receipt), encoding="utf-8")
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(cli, "run", run)
    reason = "did not finish setup" if fault in ("missing_before", "setup") else "unverified group"
    with pytest.raises(AssertionError, match=reason):
        cli.timeout_controls(tmp_path, {})


def test_drain_deadline_fails_without_reaping_a_live_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform == "win32":
        pytest.skip("The installer executes only on macOS/POSIX")
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.os, "killpg", Mock())
    monkeypatch.setattr(cli, "group_members", Mock(return_value=[{"state": "S"}]))
    monkeypatch.setattr(cli.time, "sleep", Mock())
    monkeypatch.setattr(cli.time, "monotonic", Mock(side_effect=range(20)))
    process = Mock(pid=47123)
    with pytest.raises(TimeoutError, match="remain alive after SIGKILL"):
        cli.stop_group(process, {})
    process.wait.assert_not_called()
