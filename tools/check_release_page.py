"""Build the release page with empty and synthetic history; verify its rendered downloads."""

import json
import os
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from build import ROOT

RELEASES = "https://github.com/viell-dev/slop-calc-sheet-manager/releases"


class Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[list[str]] = []
        self.inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.links.append([])
            self.inside = True
        elif tag == "a" and self.inside:
            href = dict(attrs).get("href")
            if href is not None:
                self.links[-1].append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self.inside = False


def links(version: str) -> list[str]:
    package = f"{RELEASES}/download/{version}/sheet-manager-{version}.oxt"
    return [f"{RELEASES}/tag/{version}", package, package + ".sha256"]


def main() -> None:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Select the Node.js version in .nvmrc before checking the docs")
    with tempfile.TemporaryDirectory(prefix="sheet-manager-release-page-") as scratch:
        directory = Path(scratch)
        history = directory / "releases.json"
        fixture = [
            {"version": number, "prerelease": candidate, "minimum": minimum, "published": date}
            for number, candidate, minimum, date in (
                ("0.0.2", True, "26.2.1", "2026-10-20T00:00:00Z"),
                ("0.1.90", False, "26.2.1", "2026-10-21T00:00:00Z"),
                ("0.1.91", True, "26.8.1", "2026-10-22T00:00:00Z"),
            )
        ]
        for name, builds in (("empty", []), ("published", fixture)):
            history.write_text(json.dumps(builds), encoding="utf-8")
            output = directory / name
            subprocess.run(
                [
                    node,
                    "node_modules/vitepress/bin/vitepress.js",
                    "build",
                    "docs",
                    "--outDir",
                    output,
                ],
                cwd=ROOT,
                env={**os.environ, "SHEET_MANAGER_RELEASES": str(history)},
                check=True,
            )
            html = (output / "guide/releases.html").read_text(encoding="utf-8")
            tables = Tables()
            tables.feed(html)
            if name == "empty":
                assert "No stable releases have been published yet." in html
                assert "No test builds have been published yet." in html
                assert not any(tables.links)
            else:
                expected = [links("0.1.90"), links("0.1.91") + links("0.0.2")]
                assert tables.links[:2] == expected, tables.links[:2]
                assert "No test builds have been published yet." not in html
        print("Release page: empty state, channel separation, version order and asset links passed")


if __name__ == "__main__":
    main()
