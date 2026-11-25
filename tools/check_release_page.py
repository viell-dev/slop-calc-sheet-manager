"""Verify rendered downloads, release baselines and markers against synthetic history.

Use representative histories for the whole guide and one small VitePress build for all marker
thresholds. Keep prose contracts for instructions whose marker placement must also be checked.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from html.parser import HTMLParser
from pathlib import Path

from build import ROOT
from release_data import VERSION, package_metadata, version_parts

RELEASES = "https://github.com/viell-dev/slop-calc-sheet-manager/releases"
SOURCE = package_metadata((ROOT / "extension" / "description.xml").read_bytes())[0]


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


# Guide instructions for behaviour first published in each version. A rendered marker must show
# exactly when the published baseline (`baseline`) is older than that version. A paragraph may
# also carry a marker for another addition. Each visible marker must be pending or newer than
# the baseline, and "Unreleased" must appear exactly when some marker is shown.
FIRST_PUBLISHED = {
    "0.0.4": (
        "buttons above the list",
        "Opening this menu leaves",
        "When visible and hidden sheets",
        "Move shortcuts also apply",
        "Tab and Shift+Tab traverse",
    ),
    "0.0.5": (
        "This explanation appears within the panel",
        "The menu offers four of Calc's sheet commands",
    ),
    "0.0.6": ("When the menu targets two or more sheets",),
    "0.0.8": ("Undo and Redo of a move the list made",),
    "0.0.9": ("The list itself is named after the sheet Calc shows",),
    "0.0.10": (
        "This adjustment keeps the native selection's tint",
        "Their labels stay visible on Linux",
        "Hide Sheet returns to the sheet you were viewing",
        "opens this guide in your browser",
        "opens a short bundled English help page",
    ),
    "0.0.11": (
        "reports the selected proposal's refusal",
        "reports when Find is empty",
        "a range made with Shift or Ctrl+Shift, by key or by click, starts at the cursor",
        "keys keep moving from that row until the list shows the new name",
        "Hold or repeat Alt+Up or Alt+Down to move the selection one place at a time",
        "LibreOffice shows a click or key in the list before the list itself handles it",
        "or clears it with the notice when it cannot tell which sheets it means",
    ),
    "0.0.12": (
        "it stays on that row, under the new name",
        "After a picked sheet is renamed",
        "a move shortcut does nothing",
    ),
}


def baseline(builds: Sequence[Mapping[str, object]]) -> str | None:
    """The version the guide describes: the latest stable build, else the newest test build."""
    stable = [str(build["version"]) for build in builds if not build["prerelease"]]
    pool = stable or [str(build["version"]) for build in builds]
    return max(pool, key=version_parts) if pool else None


def unavailable(version: str, described: str | None) -> bool:
    return described is None or version_parts(version) > version_parts(described)


def check_instructions(html: str, *, described: str | None) -> str:
    paragraphs = Paragraphs()
    paragraphs.feed(html)
    for version, instructions in FIRST_PUBLISHED.items():
        marked = unavailable(version, described)
        for instruction in instructions:
            matches = [
                (text, markers) for text, markers in paragraphs.paragraphs if instruction in text
            ]
            assert len(matches) == 1, (instruction, matches)
            text, markers = matches[0]
            others = [marker for marker in markers if marker != version]
            assert (
                (version in markers) == marked
                and ("Unreleased" in text) == bool(markers)
                and all(
                    other == "pending"
                    or (
                        unavailable(other, described)
                        and version_parts(other) <= version_parts(SOURCE)
                    )
                    for other in others
                )
            ), (
                f"Publication marker disagrees with history: {instruction}",
                version,
                described,
                markers,
            )
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


def build_site(node: str, source: Path, output: Path, env: Mapping[str, str]) -> None:
    subprocess.run(
        [node, "node_modules/vitepress/bin/vitepress.js", "build", source, "--outDir", output],
        cwd=ROOT,
        env={**os.environ, **env},
        check=True,
    )


def check_marker_boundaries(node: str, output: Path) -> None:
    """Render the real component across all version thresholds in one small VitePress build."""
    versions = {SOURCE}
    for path in (ROOT / "docs").rglob("*.md"):
        versions.update(
            re.findall(rf'<Unreleased\s+since="({VERSION})"\s*/>', path.read_text("utf-8"))
        )
    ordered = sorted(versions, key=version_parts)
    newest = ordered[-1]
    histories: list[tuple[str | None, str | None]] = [(None, None), (None, "0.0.0")]
    histories.extend((None, version) for version in ordered)
    histories.extend((version, newest) for version in ordered)
    examples = "<Unreleased /> Pending.\n\n" + "\n\n".join(
        f'<Unreleased since="{version}" /> First available in {version}.' for version in ordered
    )

    # Keep the fixture under ROOT so VitePress resolves the same installed dependencies.
    with tempfile.TemporaryDirectory(prefix=".release-markers-", dir=ROOT) as directory:
        source = Path(directory)
        theme = source / ".vitepress/theme"
        theme.mkdir(parents=True)
        shutil.copyfile(ROOT / "docs/.vitepress/theme/Unreleased.vue", theme / "Unreleased.vue")
        (theme / "index.ts").write_text(
            'import Layout from "./Layout.vue";\n'
            'import Unreleased from "./Unreleased.vue";\n'
            "export default { Layout, enhanceApp({ app }) {\n"
            '  app.component("Unreleased", Unreleased);\n'
            "} };\n",
            encoding="utf-8",
        )
        (theme / "Layout.vue").write_text(
            """<script setup>
import { computed, provide } from "vue";
import { Content, dataSymbol, useData } from "vitepress";

const data = useData();
const theme = computed(() => {
  const { stable, prerelease } = data.frontmatter.value;
  return { release: {
    stable: stable && { version: stable },
    prerelease: prerelease && { version: prerelease },
  } };
});
provide(dataSymbol, { ...data, theme });
</script>

<template><Content /></template>
""",
            encoding="utf-8",
        )
        for index, (stable, prerelease) in enumerate(histories):
            frontmatter = json.dumps({"stable": stable, "prerelease": prerelease})
            (source / f"case-{index}.md").write_text(
                f"---\n{frontmatter}\n---\n\n{examples}\n", encoding="utf-8"
            )
        build_site(node, source, output, {})

    for index, (stable, prerelease) in enumerate(histories):
        described = stable or prerelease
        expected = ["pending", *(version for version in ordered if unavailable(version, described))]
        html = (output / f"case-{index}.html").read_text("utf-8")
        observed = re.findall(r'data-since="([^"]+)"', html)
        assert observed == expected, (
            "Component markers disagree with published history",
            {"stable": stable, "prerelease": prerelease},
            {"expected": expected, "observed": observed},
        )


def main() -> None:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Select the Node.js version in .nvmrc before checking the docs")
    with tempfile.TemporaryDirectory(prefix="sheet-manager-release-page-") as scratch:
        directory = Path(scratch)
        check_marker_boundaries(node, directory / "markers")
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
        current = {**candidate, "version": SOURCE, "published": "2026-11-03T00:00:00Z"}
        older_stable = {**candidate, "prerelease": False}
        current_stable = {**current, "prerelease": False}
        for name, builds, notice in (
            ("empty", [], "Sheet Manager has no release yet."),
            # Merged preparation, a failed publication and an abandoned draft all have the same
            # published history. The newer source must not silently become released instructions.
            ("preparing", [candidate], "0.0.3, the newest test build"),
            (
                "current-test-build",
                [candidate, current],
                f"{SOURCE}, the newest test build",
            ),
            (
                "stable-with-candidate",
                [older_stable, current],
                "Sheet Manager 0.0.3, the latest release",
            ),
            (
                "current-stable",
                [candidate, current_stable],
                f"Sheet Manager {SOURCE}, the latest release",
            ),
            ("published", fixture, "Sheet Manager 0.1.90, the latest release"),
        ):
            history.write_text(json.dumps(builds), encoding="utf-8")
            output = directory / name
            build_site(node, ROOT / "docs", output, {"SHEET_MANAGER_RELEASES": str(history)})
            html = (output / "guide/releases.html").read_text(encoding="utf-8")
            instructions = (output / "guide/use.html").read_text(encoding="utf-8")
            plain = check_instructions(instructions, described=baseline(builds))
            assert notice in plain, (name, notice)
            tables = Tables()
            tables.feed(html)
            expected: list[list[str]] = []
            for prerelease, label in ((False, "stable releases"), (True, "test builds")):
                versions = sorted(
                    (str(item["version"]) for item in builds if item["prerelease"] is prerelease),
                    key=version_parts,
                    reverse=True,
                )
                assert (f"No {label} have been published yet." in html) == (not versions), name
                if versions:
                    expected.append([link for version in versions for link in links(version)])
            # The version-number table contains no links.
            linked_tables = [table for table in tables.links if table]
            assert linked_tables == expected, (name, linked_tables, expected)
        print("Release pages: downloads, baselines, prose contracts and marker boundaries passed")


if __name__ == "__main__":
    main()
