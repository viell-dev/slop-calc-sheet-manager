"""Build with synthetic history; verify downloads and publication-aware instruction markers."""

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


class Paragraphs(HTMLParser):
    """Keep instruction text and its inline availability markers together."""

    def __init__(self) -> None:
        super().__init__()
        self.paragraphs: list[tuple[str, list[str]]] = []
        self.content: list[str] = []
        self.text: list[str] | None = None
        self.markers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "p":
            self.text, self.markers = [], []
        if self.text is not None and (since := dict(attrs).get("data-since")) is not None:
            self.markers.append(since)

    def handle_data(self, data: str) -> None:
        self.content.append(data)
        if self.text is not None:
            self.text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self.text is not None:
            self.paragraphs.append((" ".join("".join(self.text).split()), self.markers))
            self.text = None


def check_instructions(html: str, *, marked: bool, alpha_marked: bool) -> str:
    paragraphs = Paragraphs()
    paragraphs.feed(html)
    for instruction in (
        "buttons above the list",
        "Opening this menu leaves",
        "When visible and hidden sheets",
        "Move shortcuts also apply",
        "Tab and Shift+Tab traverse",
    ):
        matches = [
            (text, markers) for text, markers in paragraphs.paragraphs if instruction in text
        ]
        assert len(matches) == 1, (instruction, matches)
        text, markers = matches[0]
        assert ("0.0.4" in markers) == marked and ("Unreleased" in text) == marked, (
            f"Publication marker disagrees with history: {instruction}",
            markers,
        )
    for instruction in (
        "This explanation appears within the panel",
        "The menu offers four of Calc's sheet commands",
    ):
        matches = [
            (text, markers) for text, markers in paragraphs.paragraphs if instruction in text
        ]
        assert len(matches) == 1, (instruction, matches)
        text, markers = matches[0]
        assert (
            markers == (["0.0.5"] if alpha_marked else [])
            and ("Unreleased" in text) == alpha_marked
        ), ("0.0.5 publication marker disagrees with history", instruction, markers)
    for instruction in ("Right-click a row", "The four move shortcuts"):
        published = [
            (text, markers) for text, markers in paragraphs.paragraphs if instruction in text
        ]
        assert len(published) == 1 and not published[0][1], (
            "Already-published 0.0.3 behavior must not be labelled unreleased",
            instruction,
            published,
        )
    assert "These instructions describe the" not in html, "Guide version must come from history"
    return " ".join("".join(paragraphs.content).split())


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
        candidate = {
            "version": "0.0.3",
            "prerelease": True,
            "minimum": "26.2.1",
            "published": "2026-10-25T00:00:00Z",
        }
        next_build = {**candidate, "version": "0.0.4", "published": "2026-10-26T00:00:00Z"}
        alpha = {**candidate, "version": "0.0.5", "published": "2026-10-28T00:00:00Z"}
        first_stable = {**next_build, "version": "0.1.0", "prerelease": False}
        for name, builds, marked, alpha_marked, notice in (
            ("empty", [], True, True, "Sheet Manager has no release yet."),
            # Merged preparation, a failed publication and an abandoned draft all have the same
            # published history. The newer source must not silently become released instructions.
            ("preparing", [candidate], True, True, "0.0.3, the newest test build"),
            (
                "candidate-published",
                [candidate, next_build],
                False,
                True,
                "0.0.4, the newest test build",
            ),
            (
                "alpha-published",
                [candidate, next_build, alpha],
                False,
                False,
                "0.0.5, the newest test build",
            ),
            (
                "stable-with-candidate",
                [{**candidate, "prerelease": False}, next_build],
                True,
                True,
                "Sheet Manager 0.0.3, the latest release",
            ),
            (
                "stable-published",
                [candidate, {**next_build, "prerelease": False}],
                False,
                True,
                "Sheet Manager 0.0.4, the latest release",
            ),
            (
                "first-stable-candidate",
                [{**next_build, "prerelease": False}, {**first_stable, "prerelease": True}],
                False,
                True,
                "Sheet Manager 0.0.4, the latest release",
            ),
            (
                "first-stable-published",
                [candidate, next_build, first_stable],
                False,
                False,
                "Sheet Manager 0.1.0, the latest release",
            ),
            ("published", fixture, False, False, "Sheet Manager 0.1.90, the latest release"),
        ):
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
            instructions = (output / "guide/use.html").read_text(encoding="utf-8")
            plain = check_instructions(instructions, marked=marked, alpha_marked=alpha_marked)
            assert notice in plain, (name, notice)
            tables = Tables()
            tables.feed(html)
            if name == "empty":
                assert "No stable releases have been published yet." in html
                assert "No test builds have been published yet." in html
                assert not any(tables.links)
            elif name == "published":
                expected = [links("0.1.90"), links("0.1.91") + links("0.0.2")]
                assert tables.links[:2] == expected, tables.links[:2]
                assert "No test builds have been published yet." not in html
            elif name == "alpha-published":
                assert "No stable releases have been published yet." in html
                assert links("0.0.5") + links("0.0.4") + links("0.0.3") in tables.links
            elif name == "first-stable-published":
                assert tables.links[:2] == [links("0.1.0"), links("0.0.4") + links("0.0.3")]
        print("Release pages: downloads, preparation, publication and no-history markers passed")


if __name__ == "__main__":
    main()
