"""Fetch and verify the pinned LibreOffice packages shared by native test lanes.

Treat restored bytes as untrusted. Keep incomplete or invalid downloads outside the cache
entry, and publish the file atomically only after checking its SHA-256.
"""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from time import monotonic
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "libreoffice-packages"
LANES = ("minimum", "current-26.2", "current-26.8", "unsupported", "windows", "macos")


def read_pin(lane: str) -> dict[str, str]:
    pins = cast(
        dict[str, dict[str, str]], json.loads((ROOT / "ci/libreoffice.json").read_text("utf-8"))
    )
    return pins[lane]


def package_path(lane: str, pin: dict[str, str]) -> Path:
    digest = pin["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"Invalid SHA-256 pin for {lane}: {digest}")
    extension = {"windows": "msi", "macos": "dmg"}.get(lane, "tar.gz")
    return CACHE / digest / f"libreoffice.{extension}"


def verify_package(path: Path, expected: str) -> None:
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(
            f"LibreOffice package checksum mismatch for {path}: expected {expected}, got {actual} "
            f"({path.stat().st_size} bytes)"
        )


def download_package(url: str, output: Path, *, seconds: int, retries: int) -> None:
    # Retry short failures from the archive URL, including mirror certificate errors (#61).
    # Bound delays before they consume the integration budget (#203).
    subprocess.run(
        [
            "curl",
            "--disable",
            "--silent",
            "--show-error",
            "--fail",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--retry",
            str(retries),
            "--retry-all-errors",
            "--connect-timeout",
            "30",
            "--max-time",
            str(seconds),
            "--retry-max-time",
            "60",
            "--write-out",
            "\nLibreOffice download: code=%{http_code} bytes=%{size_download} "
            "seconds=%{time_total} speed=%{speed_download} url=%{url_effective}\n",
            "--output",
            str(output),
            "--",
            url,
        ],
        check=True,
    )


def stable_download_url(archive: str) -> str | None:
    # TDF publishes final builds under the three-part release name on its mirror network.
    match = re.fullmatch(
        r"https://downloadarchive\.documentfoundation\.org/libreoffice/old/"
        r"((\d+\.\d+\.\d+)\.\d+)/(.+)",
        archive,
    )
    if match is None:
        return None
    build, release, path = match.groups()
    return f"https://download.documentfoundation.org/libreoffice/stable/{release}/" + path.replace(
        f"LibreOffice_{build}_", f"LibreOffice_{release}_", 1
    )


def download_pinned(pin: dict[str, str], output: Path, *, desktop: bool) -> None:
    deadline = monotonic() + (600 if desktop else 240)
    archive = pin["url"]
    mirror = stable_download_url(archive)
    if mirror is not None:
        try:
            download_package(mirror, output, seconds=90, retries=0)
            verify_package(output, pin["sha256"])
        except (subprocess.CalledProcessError, ValueError) as error:
            print(
                f"Stable mirror did not supply the pinned package; trying the archive: {error}",
                flush=True,
            )
            output.unlink(missing_ok=True)
        else:
            return
    download_package(
        archive,
        output,
        seconds=max(1, math.ceil(deadline - monotonic())),
        retries=2 if desktop else 3,
    )
    verify_package(output, pin["sha256"])


def ensure_package(lane: str, pin: dict[str, str]) -> Path:
    path = package_path(lane, pin)
    if path.exists():
        verify_package(path, pin["sha256"])
        print(
            f"LibreOffice package cache hit (SHA-256 verified): {path.name} {pin['sha256']}",
            flush=True,
        )
        return path
    print(f"LibreOffice package cache miss: {path.name} {pin['sha256']}", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="download-", dir=CACHE) as directory:
        received = Path(directory) / path.name
        download_pinned(pin, received, desktop=lane in {"windows", "macos"})
        received.replace(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=LANES)
    parser.add_argument("--github-outputs", action="store_true")
    arguments = parser.parse_args()
    pin = read_pin(arguments.lane)
    if arguments.github_outputs:
        path = package_path(arguments.lane, pin).relative_to(ROOT).as_posix()
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"path={path}\nsha256={pin['sha256']}\n")
    else:
        ensure_package(arguments.lane, pin)


if __name__ == "__main__":
    main()
