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


ARCHIVE = (
    "https://downloadarchive.documentfoundation.org/libreoffice/old/"
    "26.8.2.2/deb/x86_64/LibreOffice_26.8.2.2_Linux_x86-64_deb.tar.gz"
)
STABLE = [
    f"{route}/26.8.2/deb/x86_64/LibreOffice_26.8.2_Linux_x86-64_deb.tar.gz"
    for route in package.STABLE_ROUTES
]


@pytest.mark.parametrize("failure", ["wrong digest", "untrusted certificate"])
@pytest.mark.parametrize("supplier", [0, 1, 2, 3])
def test_stable_routes_use_the_same_pin_and_leave_time_for_the_archive(
    cache: Path, monkeypatch: pytest.MonkeyPatch, supplier: int, failure: str
) -> None:
    """The first route that supplies the pinned bytes is used; the archive comes last."""
    routes = [*STABLE, ARCHIVE]

    def download(url: str, output: Path, *, seconds: int, retries: int) -> None:
        assert not output.exists(), "an earlier route's bytes must not remain"
        calls.append((url, seconds, retries))
        if url == routes[supplier]:
            output.write_bytes(PAYLOAD)
        elif failure == "wrong digest":
            output.write_bytes(b"another build")
        else:
            raise subprocess.CalledProcessError(60, "curl")

    calls: list[tuple[str, int, int]] = []
    monkeypatch.setattr(package, "download_package", download)
    monkeypatch.setattr(package, "monotonic", Mock(side_effect=[0, 0, 1, 2, 3]))
    path = package.ensure_package("current-26.8", {**PIN, "url": ARCHIVE})
    assert path.read_bytes() == PAYLOAD
    stable = [(url, 90, 0) for url in STABLE]
    assert calls == [*stable, (ARCHIVE, 237, 3)][: supplier + 1]


def test_slow_stable_routes_leave_the_archive_its_time(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 0

    def download(url: str, output: Path, *, seconds: int, retries: int) -> None:
        nonlocal now
        calls.append((url, seconds))
        now += seconds
        if url != ARCHIVE:
            raise subprocess.CalledProcessError(28, "curl")
        output.write_bytes(PAYLOAD)

    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(package, "download_package", download)
    monkeypatch.setattr(package, "monotonic", lambda: now)
    package.ensure_package("current-26.8", {**PIN, "url": ARCHIVE})
    assert calls == [(STABLE[0], 90), (STABLE[1], 90), (ARCHIVE, 60)]
    assert now == 240, "the whole transfer stays within the budget"


def test_every_route_is_https_and_a_total_failure_is_reported(
    cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert all(route.startswith("https://") for route in package.STABLE_ROUTES)
    fetch = Mock(side_effect=subprocess.CalledProcessError(60, "curl"))
    monkeypatch.setattr(package, "download_package", fetch)
    with pytest.raises(subprocess.CalledProcessError):
        package.ensure_package("current-26.8", {**PIN, "url": ARCHIVE})
    assert fetch.call_count == len(STABLE) + 1 and not list(cache.rglob("*.tar.gz"))
