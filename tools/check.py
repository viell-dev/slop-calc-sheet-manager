"""Run static checks for each supported host, pure tests, and the reproducible build.

Pyright's platform targets check API availability; they do not execute native host behaviour.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from build import ROOT, build


def main() -> None:
    if shutil.which("node") is None:
        raise SystemExit("Node.js is required for Pyright; install it before running checks")
    for command in (
        ["ruff", "check", "."],
        ["ruff", "format", "--check", "."],
        ["pyright", "--pythonpath", sys.executable, "--pythonplatform", "Linux"],
        ["pyright", "--pythonpath", sys.executable, "--pythonplatform", "Windows"],
        ["pyright", "--pythonpath", sys.executable, "--pythonplatform", "Darwin"],
        ["pytest"],
    ):
        subprocess.run([sys.executable, "-m", *command], cwd=ROOT, check=True)
    package = build(ROOT / "dist")
    with tempfile.TemporaryDirectory(prefix="sheet-manager-build-") as directory:
        other = build(Path(directory))
        if package.read_bytes() != other.read_bytes():
            raise RuntimeError("Two builds produced different bytes")
    print(f"Checks passed; reproducible package: {package.name}")


if __name__ == "__main__":
    main()
