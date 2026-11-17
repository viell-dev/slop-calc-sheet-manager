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
    def download(url: str, output: Path, *, seconds: int, retries: int) -> None:
        assert url == PIN["url"]
        assert seconds == (240 if lane == "current-26.8" else 600)
        assert retries == (3 if lane == "current-26.8" else 2)
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
    def broken_download(url: str, output: Path, *, seconds: int, retries: int) -> None:
        output.write_bytes(b"partial transfer")
        if interrupted:
            raise subprocess.CalledProcessError(28, "curl")

    monkeypatch.setattr(package, "download_package", broken_download)
    expected = subprocess.CalledProcessError if interrupted else ValueError
    with pytest.raises(expected):
        package.ensure_package("macos", PIN)
    assert not list(cache.rglob("*.dmg"))
    assert not list(cache.glob("download-*"))


@pytest.mark.parametrize("mirror_result", ["verified", "wrong digest", "missing"])
def test_stable_tdf_route_uses_the_same_pin_and_cold_transfer_budget(
    cache: Path, monkeypatch: pytest.MonkeyPatch, mirror_result: str
) -> None:
    archive = (
        "https://downloadarchive.documentfoundation.org/libreoffice/old/"
        "26.8.2.2/deb/x86_64/LibreOffice_26.8.2.2_Linux_x86-64_deb.tar.gz"
    )
    mirror = (
        "https://download.documentfoundation.org/libreoffice/stable/"
        "26.8.2/deb/x86_64/LibreOffice_26.8.2_Linux_x86-64_deb.tar.gz"
    )

    def download(url: str, output: Path, *, seconds: int, retries: int) -> None:
        calls.append((url, seconds, retries))
        if url == mirror:
            if mirror_result == "missing":
                raise subprocess.CalledProcessError(22, "curl")
            output.write_bytes(PAYLOAD if mirror_result == "verified" else b"another build")
        else:
            assert not output.exists()
            output.write_bytes(PAYLOAD)

    calls: list[tuple[str, int, int]] = []
    monkeypatch.setattr(package, "download_package", download)
    monkeypatch.setattr(package, "monotonic", Mock(side_effect=[0, 90]))
    path = package.ensure_package("current-26.8", {**PIN, "url": archive})
    assert path.read_bytes() == PAYLOAD
    expected = [(mirror, 90, 0)]
    if mirror_result != "verified":
        expected.append((archive, 150, 3))
    assert calls == expected
