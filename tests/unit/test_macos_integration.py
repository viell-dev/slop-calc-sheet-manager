"""Private-install and diagnostic boundaries, without pretending to execute macOS."""

import hashlib
import json
import os
import signal
import subprocess
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


@pytest.mark.skipif(os.name == "nt", reason="The installer executes only on macOS/POSIX")
def test_timeout_stops_only_the_new_private_process_group_before_propagating_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    with pytest.raises(subprocess.TimeoutExpired):
        cli.run(["client"], tmp_path / "client.log", {}, timeout=1)
    assert popen.call_args.kwargs["start_new_session"] is True
    assert kill.call_args_list == [((47123, signal.SIGTERM),), ((47123, signal.SIGKILL),)]
