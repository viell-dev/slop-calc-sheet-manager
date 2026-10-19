"""Pure release policy, changelog extraction, and LibreOffice update-feed rendering."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from itertools import zip_longest

DESCRIPTION = "http://openoffice.org/extensions/description/2006"
UPDATE = "http://openoffice.org/extensions/update/2006"
LO = "http://libreoffice.org/extensions/description/2011"
XLINK = "http://www.w3.org/1999/xlink"
ATOM = "http://www.w3.org/2005/Atom"
IDENTIFIER = "dev.viell.sheetmanager"
REPOSITORY = "viell-dev/slop-calc-sheet-manager"
SITE = f"https://viell-dev.github.io/{REPOSITORY.split('/')[1]}"
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"


def compare_versions(first: str, second: str) -> int:
    """Match dp_version.cxx: strip zeroes, then compare token length and text.

    This deliberately accepts nonnumeric examples to test why SemVer suffixes fail.
    Published versions are separately restricted to canonical three-part numbers.
    """
    for left, right in zip_longest(first.split("."), second.split("."), fillvalue=""):
        left, right = left.lstrip("0"), right.lstrip("0")
        a, b = (len(left), left), (len(right), right)
        if a != b:
            return 1 if a > b else -1
    return 0


def version_parts(version: str) -> tuple[int, int, int]:
    if re.fullmatch(VERSION, version) is None:
        raise ValueError("Version must be three plain dotted numbers without leading zeroes")
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def release_title(version: str, prerelease: bool, target: str = "") -> str:
    major, minor, patch = version_parts(version)
    if prerelease:
        if patch < 90:
            raise ValueError("Release candidates use patch numbers starting at 90")
        target = target or f"{major}.{minor + 1}.0"
        if version_parts(target) not in {(major, minor + 1, 0), (major + 1, 0, 0)}:
            raise ValueError("Candidate target must be the next minor or next major .0 release")
        return f"{target} release candidate {patch - 89} ({version})"
    if patch >= 90 or target:
        raise ValueError("Stable patch releases stay below .90 and have no candidate target")
    return version


def changelog_section(text: str, version: str) -> str:
    version_parts(version)
    # A heading inside a fenced example belongs to the notes, not to a new section.
    headings: list[tuple[int, int, str]] = []
    fence = ""
    offset = 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if (
                marker is not None
                and marker.group(1)[0] == fence[0]
                and len(marker.group(1)) >= len(fence)
                and not marker.group(2).strip()
            ):
                fence = ""
        elif marker is not None:
            fence = marker.group(1)
        else:
            heading = re.match(r" {0,3}## +(.+?)\s*#*\s*$", line)
            if heading is not None:
                headings.append((offset, offset + len(line), heading.group(1)))
        offset += len(line)
    sections: list[str] = []
    for index, (_, start, heading) in enumerate(headings):
        if re.match(rf"(?:\[{re.escape(version)}\]|{re.escape(version)})(?:\s|$)", heading):
            end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
            sections.append(text[start:end].strip())
    if len(sections) != 1 or not sections[0]:
        raise ValueError(f"CHANGELOG.md needs exactly one nonempty section for {version}")
    return sections[0] + "\n"


def package_metadata(description: bytes) -> tuple[str, str]:
    root = ET.fromstring(description)
    identifier = root.find(f"{{{DESCRIPTION}}}identifier")
    version = root.find(f"{{{DESCRIPTION}}}version")
    minimum = root.find(f"{{{DESCRIPTION}}}dependencies/{{{LO}}}LibreOffice-minimal-version")
    if identifier is None or identifier.get("value") != IDENTIFIER:
        raise ValueError("Unexpected extension identifier")
    if version is None or minimum is None:
        raise ValueError("Package needs a version and LibreOffice minimum version")
    number, floor = version.attrib["value"], minimum.attrib["value"]
    version_parts(number)
    version_parts(floor)
    return number, floor


@dataclass(frozen=True)
class PublishedBuild:
    version: str
    prerelease: bool
    minimum: str
    published: str

    @property
    def download(self) -> str:
        return (
            f"https://github.com/{REPOSITORY}/releases/download/{self.version}/"
            f"sheet-manager-{self.version}.oxt"
        )

    @property
    def notes(self) -> str:
        return f"https://github.com/{REPOSITORY}/releases/tag/{self.version}"


def validate_history(builds: list[PublishedBuild], previous: list[PublishedBuild]) -> None:
    """Refuse rewritten history, removed builds, or non-increasing publication order."""
    by_version: dict[str, PublishedBuild] = {}
    for build in builds:
        release_title(build.version, build.prerelease)
        version_parts(build.minimum)
        if build.version in by_version:
            raise ValueError(f"Duplicate published version: {build.version}")
        by_version[build.version] = build
    for old in previous:
        if by_version.get(old.version) != old:
            raise ValueError(f"Published build removed or changed: {old.version}")
    ordered = sorted(builds, key=lambda item: (item.published, version_parts(item.version)))
    for older, newer in zip(ordered, ordered[1:], strict=False):
        if compare_versions(newer.version, older.version) <= 0:
            raise ValueError(
                f"Publication would move backwards: {older.version} -> {newer.version}"
            )


def check_new_version(version: str, builds: list[PublishedBuild], tags: list[str]) -> None:
    version_parts(version)
    for existing in [item.version for item in builds] + tags:
        if re.fullmatch(VERSION, existing) and compare_versions(version, existing) <= 0:
            raise ValueError(f"Version {version} must exceed existing version/tag {existing}")


def feed(builds: list[PublishedBuild], *, stable: bool) -> bytes:
    """Atom allows an empty initial feed and a complete, newest-first release history."""
    ET.register_namespace("", ATOM)
    ET.register_namespace("update", UPDATE)
    ET.register_namespace("lo", LO)
    ET.register_namespace("xlink", XLINK)
    channel = "stable" if stable else "prerelease"
    root = ET.Element(f"{{{ATOM}}}feed")
    ET.SubElement(root, f"{{{ATOM}}}id").text = f"{SITE}/updates/{channel}.xml"
    ET.SubElement(root, f"{{{ATOM}}}title").text = f"Sheet Manager {channel} updates"
    author = ET.SubElement(root, f"{{{ATOM}}}author")
    ET.SubElement(author, f"{{{ATOM}}}name").text = "viell"
    selected = sorted(
        (item for item in builds if not stable or not item.prerelease),
        key=lambda item: version_parts(item.version),
        reverse=True,
    )
    ET.SubElement(root, f"{{{ATOM}}}updated").text = (
        selected[0].published if selected else "2000-01-01T00:00:00Z"
    )
    for item in selected:
        entry = ET.SubElement(root, f"{{{ATOM}}}entry")
        ET.SubElement(entry, f"{{{ATOM}}}id").text = item.notes
        ET.SubElement(entry, f"{{{ATOM}}}title").text = f"Sheet Manager {item.version}"
        ET.SubElement(entry, f"{{{ATOM}}}updated").text = item.published
        ET.SubElement(entry, f"{{{ATOM}}}category", term=IDENTIFIER)
        content = ET.SubElement(entry, f"{{{ATOM}}}content", type="application/xml")
        description = ET.SubElement(content, f"{{{UPDATE}}}description")
        ET.SubElement(description, f"{{{UPDATE}}}identifier", value=IDENTIFIER)
        ET.SubElement(description, f"{{{UPDATE}}}version", value=item.version)
        dependencies = ET.SubElement(description, f"{{{UPDATE}}}dependencies")
        ET.SubElement(dependencies, f"{{{LO}}}LibreOffice-minimal-version", value=item.minimum)
        for name, url in (("update-download", item.download), ("release-notes", item.notes)):
            links = ET.SubElement(description, f"{{{UPDATE}}}{name}")
            ET.SubElement(links, f"{{{UPDATE}}}src", {f"{{{XLINK}}}href": url})
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
