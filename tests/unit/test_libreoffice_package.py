"""Check the pin-to-cache boundary with synthetic archives and installers."""

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools import libreoffice_package as package

PAYLOAD = b"pinned package"
PIN = {"url": "https://example.invalid/office", "sha256": hashlib.sha256(PAYLOAD).hexdigest()}


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(package, "CACHE", tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("lane", "name"),
    [
        ("current-26.8", "libreoffice.tar.gz"),
        ("windows", "libreoffice.msi"),
        ("macos", "libreoffice.dmg"),
    ],
)
def test_miss_downloads_once_and_verified_hit_needs_no_network(
    cache: Path, monkeypatch: pytest.MonkeyPatch, lane: str, name: str
) -> None:
    def download(url: str, output: Path, *, desktop: bool) -> None:
        assert url == PIN["url"]
        assert desktop == (lane in {"windows", "macos"})
        output.write_bytes(PAYLOAD)

    fetch = Mock(side_effect=download)
    monkeypatch.setattr(package, "download_package", fetch)
    path = cache / PIN["sha256"] / name
    assert package.ensure_package(lane, PIN) == path
    assert path.read_bytes() == PAYLOAD
    assert package.ensure_package(lane, PIN) == path
    fetch.assert_called_once()


def test_corrupt_restored_package_is_refused_without_fetching(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = package.package_path("minimum", PIN)
    path.parent.mkdir()
    path.write_bytes(b"corrupt archive")
    fetch = Mock()
    monkeypatch.setattr(package, "download_package", fetch)
    with pytest.raises(ValueError, match="checksum mismatch"):
        package.ensure_package("minimum", PIN)
    fetch.assert_not_called()
    assert list(cache.iterdir()) == [path.parent]


@pytest.mark.parametrize("interrupted", [False, True])
def test_bad_download_never_publishes_a_cache_entry(
    cache: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool
) -> None:
    def broken_download(url: str, output: Path, *, desktop: bool) -> None:
        output.write_bytes(b"partial transfer")
        if interrupted:
            raise subprocess.CalledProcessError(28, "curl")

    monkeypatch.setattr(package, "download_package", broken_download)
    expected = subprocess.CalledProcessError if interrupted else ValueError
    with pytest.raises(expected):
        package.ensure_package("macos", PIN)
    assert not list(cache.rglob("*.dmg"))
    assert not list(cache.glob("download-*"))
