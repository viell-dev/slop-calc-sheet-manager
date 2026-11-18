"""Check Docker mode before building or starting the Linux verification lane."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from tools import linux_integration as cli


@pytest.mark.parametrize("security_option", ["name=rootless", "name=userns"])
def test_incompatible_docker_mode_stops_before_build(
    monkeypatch: pytest.MonkeyPatch, security_option: str
) -> None:
    monkeypatch.setattr(sys, "argv", ["linux_integration.py", "current-26.8"])
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: 1000, raising=False)
    response = json.dumps(["name=seccomp,profile=builtin", security_option, "name=cgroupns"])
    docker = Mock(return_value=subprocess.CompletedProcess([], 0, response, ""))
    monkeypatch.setattr(cli.subprocess, "run", docker)

    with pytest.raises(SystemExit, match=rf"{security_option}.*docker context ls"):
        cli.main()
    docker.assert_called_once_with(
        ["docker", "info", "--format", "{{json .SecurityOptions}}"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )


@pytest.mark.parametrize("response", ["null", '["name=seccomp,profile=builtin","name=cgroupns"]'])
def test_unmapped_docker_mode_passes_preflight(
    monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    docker = Mock(return_value=subprocess.CompletedProcess([], 0, response, ""))
    monkeypatch.setattr(cli.subprocess, "run", docker)
    cli.require_supported_docker()
    docker.assert_called_once()


def test_lowered_stall_limits_reach_the_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A local deliberate stall needs the override inside the container (#45).
    monkeypatch.setattr(sys, "argv", ["linux_integration.py", "current-26.8", "--skip-build"])
    monkeypatch.setenv("SHEET_MANAGER_STALL_SECONDS", "30")
    monkeypatch.delenv("SHEET_MANAGER_DEADLINE_SECONDS", raising=False)
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: 1000, raising=False)
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "Dockerfile").write_text("FROM scratch", encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", tmp_path)

    def pin(lane: str) -> dict[str, str]:
        return {"version": "26.8.2.2"}

    def build(directory: Path) -> Path:
        return tmp_path / "synthetic.oxt"

    monkeypatch.setattr(cli, "read_pin", pin)
    monkeypatch.setattr(cli, "build", build)
    commands: list[list[str]] = []

    def docker(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "null", "")

    monkeypatch.setattr(cli.subprocess, "run", docker)
    cli.main()
    run = commands[-1]
    assert run[:2] == ["docker", "run"]
    assert "SHEET_MANAGER_STALL_SECONDS=30" in run
    assert run[run.index("SHEET_MANAGER_STALL_SECONDS=30") - 1] == "--env"
    assert not any(item.startswith("SHEET_MANAGER_DEADLINE_SECONDS") for item in run)
