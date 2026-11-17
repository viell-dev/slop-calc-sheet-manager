"""Check Docker mode before building or starting the Linux verification lane."""

import json
import os
import subprocess
import sys
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
