"""Private-install and diagnostic boundaries, without pretending to execute macOS."""

import hashlib
import json
import math
import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from tests.integration import office_process
from tools import macos_integration as cli

GROUP = 47123
REPOSITORY = Path(__file__).resolve().parents[2]
INSTALL = cli.install


@pytest.fixture(autouse=True)
def native_cli_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["macos_integration.py"])


class Interrupted(BaseException):
    """An interruption that, unlike KeyboardInterrupt, cannot also stop the pytest session."""


@dataclass
class Member:
    """A simulated group member: it exits at `exits_at`, or a delay after a signal it honours."""

    honours: dict[int, float] = field(default_factory=dict[int, float])
    exits_at: float = math.inf


class FakeGroup:
    """Simulate one private group's members, signals and clock; no real process is involved."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *members: Member) -> None:
        self.now = 0.0
        self.members = list(members)
        self.signals: list[int] = []
        self.signal_times: list[float] = []
        self.snapshots = 0
        self.failures: dict[int, BaseException] = {}
        self.reaped: list[bool] = []
        monkeypatch.setattr(cli.sys, "platform", "darwin")
        monkeypatch.setattr(cli.os, "killpg", self.killpg, raising=False)
        monkeypatch.setattr(cli, "group_members", self.snapshot)
        monkeypatch.setattr(cli.time, "monotonic", lambda: self.now)
        monkeypatch.setattr(cli.time, "sleep", self.sleep)

    def killpg(self, group: int, sig: int) -> None:
        assert group == GROUP, "A signal reached another process group"
        self.signals.append(sig)
        self.signal_times.append(self.now)
        for member in self.members:
            if sig in member.honours:
                member.exits_at = min(member.exits_at, self.now + member.honours[sig])

    def snapshot(self, group: int) -> list[dict[str, Any]]:
        assert group == GROUP
        index = self.snapshots
        self.snapshots += 1
        if index in self.failures:
            raise self.failures[index]
        return [
            {
                "pid": GROUP + offset,
                "pgid": GROUP,
                "state": "Z" if self.now >= member.exits_at else "S",
                "uid": 501,
                "command": "python",
            }
            for offset, member in enumerate(self.members)
        ]

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def stopped(self) -> bool:
        return all(self.now >= member.exits_at for member in self.members)

    def reap(self, timeout: float | None = None) -> None:
        self.reaped.append(self.stopped())

    def leader(self) -> Mock:
        """An unreaped leader that records whether its group had stopped when it was reaped."""
        return Mock(pid=GROUP, wait=Mock(side_effect=self.reap))


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


@pytest.mark.parametrize("mounted", [False, True])
def test_failed_attach_is_detached_when_it_left_the_image_mounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mounted: bool
) -> None:
    image = tmp_path / "office.dmg"
    image.write_bytes(b"known fixture")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    calls: list[list[str]] = []

    def run(command: list[str], log: Path, environment: dict[str, str], timeout: int = 120) -> None:
        calls.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            raise cli.GroupCleanupError("the attach command's group audit failed")

    def is_mount(path: Path) -> bool:
        return mounted and path == tmp_path / "mount"

    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(cli.Path, "is_mount", is_mount)
    with pytest.raises(cli.GroupCleanupError, match="group audit failed"):
        cli.install(image, {"sha256": digest}, tmp_path, tmp_path, {})
    assert (["hdiutil", "detach", str(tmp_path / "mount")] in calls) is mounted
    assert not any(command[0] == "ditto" for command in calls)


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
    monkeypatch.setattr(cli, "ensure_package", Mock(return_value=tmp_path / "libreoffice.dmg"))
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


@pytest.mark.parametrize("probe", [False, True])
def test_only_the_integration_runner_gets_its_own_deadline(
    native_commands_stubbed: tuple[Path, Mock], monkeypatch: pytest.MonkeyPatch, probe: bool
) -> None:
    _, runner = native_commands_stubbed
    if probe:
        monkeypatch.setattr(sys, "argv", ["macos_integration.py", "--theme-pick-probe"])
    # An inherited absolute deadline would take precedence over the runner's own (#244).
    monkeypatch.setenv("SHEET_MANAGER_DEADLINE_MONOTONIC", "1.0")
    monkeypatch.setenv("SHEET_MANAGER_DEADLINE_SECONDS", "7")
    cli.main()
    integration = [call for call in runner.call_args_list if call.args[1].name == "integration.log"]
    assert len(integration) == 1
    command, _, environment, timeout = integration[0].args
    assert command[1].endswith("theme_pick_probe.py" if probe else "run.py")
    assert environment["SHEET_MANAGER_DEADLINE_SECONDS"] == str(cli.RUNNER_DEADLINE)
    assert "SHEET_MANAGER_DEADLINE_MONOTONIC" not in environment
    assert timeout == cli.INTEGRATION_TIMEOUT
    assert os.environ["SHEET_MANAGER_DEADLINE_MONOTONIC"] == "1.0", "The host's own was changed"


def test_the_runner_deadline_leaves_the_stall_capture_inside_the_command_limit() -> None:
    # At the deadline the watch looks at once, then has its capture and stop budgets (#45); a
    # minute more covers the runner's start before its deadline counts and its exit afterwards.
    needed = office_process.CAPTURE_SECONDS + office_process.STOP_SECONDS + 60
    gap = cli.INTEGRATION_TIMEOUT - cli.RUNNER_DEADLINE
    assert gap >= needed, "The command's limit would cut the stall capture short"
    assert cli.RUNNER_DEADLINE >= 30 * 60, "#162 measured 30 minutes for the complete workload"


@pytest.mark.parametrize("filename", ["macos.yml", "release-sweep.yml"])
def test_the_job_outlasts_every_command_budget_and_its_upload(
    native_commands_stubbed: tuple[Path, Mock], monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    output, runner = native_commands_stubbed
    root = output.parents[1]
    # The real installation, so that its attach, copy and detach commands count too.
    image = root / "libreoffice.dmg"
    image.write_bytes(b"synthetic image")
    pins = root / "ci/libreoffice.json"
    pin = json.loads(pins.read_text("utf-8"))
    pin["macos"]["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
    pins.write_text(json.dumps(pin), "utf-8")
    monkeypatch.setattr(cli, "install", INSTALL)
    cli.main()
    logs = {call.args[1].name for call in runner.call_args_list}
    assert {"mount.log", "copy.log", "unmount.log", "integration.log"} <= logs
    # Each command's limit, or `run`'s default, then the audit of its former group.
    commands = sum(
        (call.args[3] if len(call.args) > 3 else 120) + cli.EXIT_GRACE
        for call in runner.call_args_list
    )
    # The two native timeout controls, each with its TERM and KILL graces.
    controls = 2 * (5 + cli.TERM_GRACE + cli.KILL_GRACE)
    # The package action's download: a 600-second deadline and curl's 60-second retry window.
    download = 660
    text = (REPOSITORY / ".github/workflows" / filename).read_text("utf-8")
    limit = int(yaml.load(text, yaml.BaseLoader)["jobs"]["macos"]["timeout-minutes"]) * 60
    # A minute more for checkout, Python setup, the crash-report search and the upload.
    assert limit >= download + commands + controls + 60


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
    monkeypatch.setattr(
        cli, "group_members", Mock(side_effect=[[{"state": "S"}], [{"state": "Z"}]])
    )
    with pytest.raises(subprocess.TimeoutExpired):
        cli.run(["client"], tmp_path / "client.log", {}, timeout=1)
    assert popen.call_args.kwargs["start_new_session"] is True
    kill.assert_called_once_with(47123, signal.SIGTERM)


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
        cli.os, "killpg", Mock(side_effect=PermissionError("refused")), raising=False
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
            "before": [{"state": "S"}, {"state": "S"}],
            "after_signals": [{"state": "S" if fault == "live" else "Z"}],
            "kill_escalated": False,
        }
        if fault == "missing_after":
            del receipt["after_signals"]
        if fault == "missing_before":
            del receipt["before"]
        log.write_text(
            "" if fault == "setup" else "term-parent-ready\nterm-child-ready\nterm-child-drained\n",
            encoding="utf-8",
        )
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


@pytest.mark.parametrize("returncode", [0, 17])
@pytest.mark.parametrize(
    "audit_result", ["clear", "late", "live", "unavailable", "lost", "interrupted"]
)
def test_post_reap_audit_never_signals_and_retains_uncertain_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int, audit_result: str
) -> None:
    # The leader is reaped before the audit, so only its former group's other members remain.
    remaining: list[Member] = (
        []
        if audit_result == "clear"
        else [Member(exits_at=0.4 if audit_result == "late" else math.inf)]
    )
    group = FakeGroup(monkeypatch, *remaining)
    # Snapshot 0 is the audit's first; a failure at 1 interrupts its bounded observation.
    failures: dict[str, dict[int, BaseException]] = {
        "unavailable": {0: OSError("process snapshot failed")},
        "lost": {1: OSError("process snapshot failed")},
        "interrupted": {1: Interrupted()},
    }
    group.failures = failures.get(audit_result, {})
    process = Mock(pid=GROUP)
    process.wait.return_value = returncode
    monkeypatch.setattr(cli.subprocess, "Popen", Mock(return_value=process))

    def reaped_first(group_id: int) -> list[dict[str, Any]]:
        process.wait.assert_called_once_with(timeout=120)
        return group.snapshot(group_id)

    monkeypatch.setattr(cli, "group_members", reaped_first)
    log = tmp_path / "client.log"
    if audit_result in ("clear", "late"):
        if returncode:
            with pytest.raises(subprocess.CalledProcessError) as error:
                cli.run(["client"], log, {})
            assert error.value.returncode == returncode
        else:
            cli.run(["client"], log, {})
        if audit_result == "clear":
            assert not log.with_suffix(".group.json").exists()
        else:
            receipt = json.loads(log.with_suffix(".group.json").read_text("utf-8"))
            assert receipt["proved_stopped"] is True
            assert cli.live_members(receipt["members"])
            assert not cli.live_members(receipt["after_grace"])
            assert 0.4 <= group.now < cli.EXIT_GRACE, "The audit waited past the member's exit"
    else:
        with (
            pytest.raises(
                cli.GroupCleanupError,
                match=f"could not be proved stopped after the client exited with status "
                f"{returncode}: ",
            ),
            cli.private_directory(str(tmp_path)) as private,
        ):
            cli.run(["client"], log, {})
        assert private.exists()
        receipt = json.loads(log.with_suffix(".group.json").read_text("utf-8"))
        assert receipt["group"] == GROUP
        assert receipt["client_returncode"] == returncode
        assert receipt["proved_stopped"] is False
        assert ("members" in receipt) is (audit_result != "unavailable")
        if audit_result == "live":
            assert cli.live_members(receipt["after_grace"])
            assert cli.EXIT_GRACE <= group.now < cli.EXIT_GRACE + 0.1, "The audit is unbounded"
        else:
            assert type(group.failures[min(group.failures)]).__name__ in receipt["audit_error"]
    assert group.signals == [], "A reaped client's former group must never be signalled"


def test_cooperative_group_drains_after_term_without_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform == "win32":
        pytest.skip("The installer executes only on macOS/POSIX")
    # Like the native control, the child's TERM handler needs a second before it exits.
    honours: dict[int, float] = {signal.SIGTERM: 1.0, signal.SIGKILL: 0.0}
    group = FakeGroup(monkeypatch, Member(dict(honours)), Member(dict(honours)))
    receipt: dict[str, Any] = {}
    cli.stop_group(group.leader(), receipt)
    assert group.signals == [signal.SIGTERM], "TERM was not given its bounded grace"
    assert receipt["kill_escalated"] is False
    assert not cli.live_members(receipt["after_term"])
    assert receipt["cleanup_succeeded"] is True
    assert group.reaped == [True]


def test_term_resistant_group_is_killed_before_the_leader_is_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform == "win32":
        pytest.skip("The installer executes only on macOS/POSIX")
    honours: dict[int, float] = {signal.SIGKILL: 0.0}
    group = FakeGroup(monkeypatch, Member(dict(honours)), Member(dict(honours)))
    receipt: dict[str, Any] = {}
    cli.stop_group(group.leader(), receipt)
    assert group.signals == [signal.SIGTERM, signal.SIGKILL]
    assert group.signal_times[1] >= cli.TERM_GRACE, "KILL preceded the TERM grace"
    assert receipt["kill_escalated"] is True
    assert cli.live_members(receipt["after_term"])
    assert not cli.live_members(receipt["after_signals"])
    assert group.reaped == [True], "The leader was reaped before its group stopped"


@pytest.mark.parametrize("failing", [(1,), (1, 2)])
def test_failed_term_snapshot_is_not_proof_that_the_group_stopped(
    monkeypatch: pytest.MonkeyPatch, failing: tuple[int, ...]
) -> None:
    if sys.platform == "win32":
        pytest.skip("The installer executes only on macOS/POSIX")
    # Snapshot 0 precedes TERM, 1 is the first after TERM and 2 the first after KILL. The member
    # does stop on TERM: only the missing proof forces the escalation.
    group = FakeGroup(monkeypatch, Member({signal.SIGTERM: 0.0, signal.SIGKILL: 0.0}))
    group.failures = {index: OSError("process snapshot failed") for index in failing}
    receipt: dict[str, Any] = {}
    if 2 in failing:
        with pytest.raises(OSError, match="snapshot failed"):
            cli.stop_group(group.leader(), receipt)
        assert group.reaped == [], "The leader was reaped without proof that its group stopped"
        assert "cleanup_succeeded" not in receipt
    else:
        cli.stop_group(group.leader(), receipt)
        assert group.reaped == [True]
    assert "OSError" in receipt["term_grace_error"]
    assert receipt["kill_escalated"] is True
    assert group.signals == [signal.SIGTERM, signal.SIGKILL]


def test_interrupted_wait_retains_the_application_and_the_unreaped_leader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    interruption = Interrupted()
    process = Mock(pid=GROUP)
    process.wait.side_effect = interruption
    monkeypatch.setattr(cli.subprocess, "Popen", Mock(return_value=process))
    kill = Mock()
    monkeypatch.setattr(cli.os, "killpg", kill, raising=False)
    audit = Mock()
    monkeypatch.setattr(cli, "audit_exited_group", audit)
    with (
        pytest.raises(cli.GroupCleanupError, match="wait was interrupted") as raised,
        cli.private_directory(str(tmp_path)) as private,
    ):
        cli.run(["client"], tmp_path / "client.log", {})
    assert raised.value.__cause__ is interruption
    assert private.exists()
    assert process.wait.call_count == 1
    kill.assert_not_called()
    audit.assert_not_called()
