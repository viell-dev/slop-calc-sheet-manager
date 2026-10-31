"""Release policy examples plus feed contracts consumed by LibreOffice."""

import itertools
import xml.etree.ElementTree as ET

import pytest

from tools.build import ROOT
from tools.release_data import (
    ATOM,
    IDENTIFIER,
    LO,
    SITE,
    UPDATE,
    XLINK,
    PublishedBuild,
    changelog_section,
    check_new_version,
    compare_versions,
    feed,
    is_prerelease,
    package_metadata,
    release_title,
    validate_history,
    version_parts,
)


def published(version: str, day: int, *, prerelease: bool = False) -> PublishedBuild:
    return PublishedBuild(version, prerelease, "26.2.1", f"2026-10-{day:02}T00:00:00Z")


def test_numeric_comparison_matches_integer_tuple_order() -> None:
    versions = ["0.0.1", "0.0.89", "0.0.90", "0.0.91", "0.0.100", "0.1.0", "0.1.1", "1.0.0"]
    for first, second in itertools.product(versions, repeat=2):
        a, b = version_parts(first), version_parts(second)
        assert compare_versions(first, second) == (a > b) - (a < b)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("0.1.0-rc.1", "0.1.0", 1),
        ("0.01.000", "0.1", 0),
        ("0.1.0", "0.1", 0),
        ("0.1.10", "0.1.9", 1),
        ("0.1.0", "0.1.0.1", -1),
    ],
)
def test_libreoffice_token_rules(first: str, second: str, expected: int) -> None:
    assert compare_versions(first, second) == expected


@pytest.mark.parametrize("version", ["v0.1.0", "0.1.0-rc.1", "0.01.0", "0.1", "0.1.0.0", "０.1.0"])
def test_noncanonical_versions_are_refused(version: str) -> None:
    with pytest.raises(ValueError):
        version_parts(version)


@pytest.mark.parametrize(
    ("version", "stage", "target", "title"),
    [
        ("0.0.2", "alpha", "", "0.0.2 alpha"),
        ("0.0.91", "alpha", "", "0.0.91 alpha"),
        ("0.1.1", "alpha", "", "0.1.1 alpha"),
        ("0.0.4", "alpha", "0.1.0", "0.1.0 alpha (0.0.4)"),
        ("0.0.7", "beta", "0.1.0", "0.1.0 beta (0.0.7)"),
        ("0.0.9", "rc", "0.1.0", "0.1.0 rc (0.0.9)"),
        ("0.8.90", "beta", "1.0.0", "1.0.0 beta (0.8.90)"),
        ("0.8.91", "rc", "1.0.0", "1.0.0 rc (0.8.91)"),
        ("0.1.89", "stable", "", "0.1.89"),
        ("0.1.0", "stable", "", "0.1.0"),
    ],
)
def test_stage_titles(version: str, stage: str, target: str, title: str) -> None:
    assert release_title(version, stage, target) == title
    assert is_prerelease(stage) is (stage != "stable")


@pytest.mark.parametrize(
    ("version", "stage", "target", "message"),
    [
        ("0.0.7", "beta", "", "needs its agreed"),
        ("0.0.9", "rc", "", "needs its agreed"),
        ("0.1.0", "stable", "0.2.0", "no candidate target"),
        ("0.0.90", "alpha", "0.1.1", "next minor or next major"),
        ("0.0.90", "beta", "0.1.1", "next minor or next major"),
        ("0.0.90", "rc", "2.0.0", "next minor or next major"),
        ("0.0.7", "beta", "0.0.8", "next minor or next major"),
        ("0.0.7", "beta", "v0.1.0", "three plain dotted numbers"),
        ("0.0.7", "rc", "0.1.0-rc.1", "three plain dotted numbers"),
        ("0.1.0-rc.1", "rc", "0.2.0", "three plain dotted numbers"),
        ("0.0.7", "", "", "stage must be one of"),
        ("0.0.7", "Beta", "0.1.0", "stage must be one of"),
        ("0.0.7", "test build", "0.1.0", "stage must be one of"),
    ],
)
def test_invalid_stage_and_target_combinations(
    version: str, stage: str, target: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        release_title(version, stage, target)


def test_patch_ninety_and_above_do_not_imply_a_test_build() -> None:
    assert release_title("0.1.90", "stable") == "0.1.90"
    assert release_title("0.1.100", "stable") == "0.1.100"
    assert release_title("0.1.4", "alpha") == "0.1.4 alpha"
    stable = published("0.1.90", 18)
    test = published("0.1.91", 19, prerelease=True)
    validate_history([stable, test], [])
    assert feed([stable, test], stable=True) == feed([stable], stable=True)
    assert b'value="0.1.90"' in feed([stable, test], stable=True)
    assert b'value="0.1.91"' not in feed([stable, test], stable=True)


def test_every_stage_joins_history_and_feeds_after_earlier_title_schemes() -> None:
    # 0.0.2-0.0.4 were published as "0.1.0 test build (...)" and 0.0.5-0.0.6 as "... alpha".
    # History carries only the channel, so later beta, rc and stable builds append to it.
    earlier = [published(f"0.0.{patch}", patch, prerelease=True) for patch in range(2, 7)]
    stages = (("0.0.7", "beta", 7), ("0.0.9", "rc", 9), ("0.1.0", "stable", 10))
    later = [
        published(version, day, prerelease=is_prerelease(stage)) for version, stage, day in stages
    ]
    validate_history(earlier + later, earlier)
    for builds in (earlier + later[:1], earlier + later[:2], earlier + later):
        check_new_version("0.1.1", builds, [])
    stable = ET.fromstring(feed(earlier + later, stable=True))
    everything = ET.fromstring(feed(earlier + later, stable=False))
    path = f"{{{ATOM}}}entry/{{{ATOM}}}content/{{{UPDATE}}}description/{{{UPDATE}}}version"
    assert [item.attrib["value"] for item in stable.findall(path)] == ["0.1.0"]
    assert [item.attrib["value"] for item in everything.findall(path)] == [
        "0.1.0",
        "0.0.9",
        "0.0.7",
        "0.0.6",
        "0.0.5",
        "0.0.4",
        "0.0.3",
        "0.0.2",
    ]
    assert feed(earlier + later[:2], stable=True) == feed([], stable=True)


def test_new_build_must_exceed_every_channel_and_orphan_tag() -> None:
    builds = [published("0.0.91", 19, prerelease=True)]
    check_new_version("0.1.0", builds, ["0.0.90", "0.0.91"])
    for number in ("0.0.89", "0.0.90", "0.0.91"):
        with pytest.raises(ValueError, match="must exceed"):
            check_new_version(number, builds, [])
    with pytest.raises(ValueError, match="must exceed"):
        check_new_version("0.1.0", builds, ["0.2.0"])


def test_history_refuses_removal_reclassification_and_duplicate_versions() -> None:
    old = published("0.0.90", 18, prerelease=True)
    new = published("0.1.0", 19)
    validate_history([new, old], [old])
    for builds in (
        [new],
        [published("0.0.90", 18), new],
        [old, old],
        [PublishedBuild("0.0.90", True, "26.8.1", old.published), new],
    ):
        with pytest.raises(ValueError):
            validate_history(builds, [old])


@pytest.mark.parametrize("prerelease", [False, True])
def test_finishing_an_older_draft_retains_the_newest_feed_version(prerelease: bool) -> None:
    newest = published("0.1.0", 18)
    recovered = published("0.0.90" if prerelease else "0.0.89", 19, prerelease=prerelease)
    validate_history([recovered, newest], [newest])
    for stable in (False, True):
        root = ET.fromstring(feed([recovered, newest], stable=stable))
        versions = [
            element.attrib["value"]
            for element in root.findall(
                f"{{{ATOM}}}entry/{{{ATOM}}}content/{{{UPDATE}}}description/{{{UPDATE}}}version"
            )
        ]
        assert versions == (
            [newest.version] if stable and prerelease else [newest.version, recovered.version]
        )
        if stable and prerelease:
            assert feed([recovered, newest], stable=True) == feed([newest], stable=True)


def test_feed_has_all_builds_newest_first_and_stable_ignores_candidates() -> None:
    stable = published("0.1.0", 18)
    candidate = published("0.1.90", 19, prerelease=True)
    builds = [stable, candidate]
    assert feed(builds, stable=True) == feed([stable], stable=True)
    root = ET.fromstring(feed(builds, stable=False))
    entries = root.findall(f"{{{ATOM}}}entry")
    assert root.findtext(f"{{{ATOM}}}id") == f"{SITE}/updates/prerelease.xml"
    assert len(entries) == 2
    for entry, item in zip(entries, [candidate, stable], strict=True):
        category = entry.find(f"{{{ATOM}}}category")
        assert category is not None and category.attrib["term"] == IDENTIFIER
        desc = entry.find(f"{{{ATOM}}}content/{{{UPDATE}}}description")
        assert desc is not None
        for name, value in (("identifier", IDENTIFIER), ("version", item.version)):
            child = desc.find(f"{{{UPDATE}}}{name}")
            assert child is not None and child.attrib["value"] == value
        floor = desc.find(f"{{{UPDATE}}}dependencies/{{{LO}}}LibreOffice-minimal-version")
        assert floor is not None and floor.attrib["value"] == item.minimum
        for name, url in (("update-download", item.download), ("release-notes", item.notes)):
            link = desc.find(f"{{{UPDATE}}}{name}/{{{UPDATE}}}src")
            assert link is not None and link.attrib[f"{{{XLINK}}}href"] == url


def test_empty_feed_is_valid_and_does_not_advertise_an_unpublished_build() -> None:
    for stable in (True, False):
        root = ET.fromstring(feed([], stable=stable))
        assert root.tag == f"{{{ATOM}}}feed"
        assert not root.findall(f"{{{ATOM}}}entry")


def test_changelog_extracts_exact_section_with_subheadings_and_no_attribution() -> None:
    text = (
        "# Changelog\n\n## Unreleased\n\n- Future.\n\n## [0.1.0] - 2026-10-19\n\n"
        "### Added\n\n- One.\n\n## 0.0.90\n\n- Older.\n"
    )
    assert changelog_section(text, "0.1.0") == "### Added\n\n- One.\n"
    assert changelog_section(text, "0.0.90") == "- Older.\n"
    for bad in (text, "## 0.1.0\n", "## 0.1.0\n- A\n## 0.1.0\n- B\n", "## 0.1.01\n- A"):
        with pytest.raises(ValueError):
            changelog_section(bad, "0.1.1" if bad == text else "0.1.0")


def test_changelog_preserves_fenced_examples_containing_headings() -> None:
    for fence in ("```", "~~~~"):
        notes = f"### Example\n\n{fence}md\n## 0.1.0\n## Example heading\n{fence}\n\n- Rest.\n"
        text = f"## 0.1.0 - 2026-10-19\n\n{notes}\n## 0.0.90\n\n- Older.\n"
        assert changelog_section(text, "0.1.0") == notes


def test_metadata_floor_and_stable_feed_stay_in_the_package() -> None:
    description = (ROOT / "extension/description.xml").read_bytes()
    version, minimum = package_metadata(description)
    assert version_parts(version) and minimum == "26.2.1"
    root = ET.fromstring(description)
    link = root.find(
        "{http://openoffice.org/extensions/description/2006}update-information/"
        "{http://openoffice.org/extensions/description/2006}src"
    )
    assert link is not None and link.get(f"{{{XLINK}}}href") == f"{SITE}/updates/stable.xml"
    with pytest.raises(ValueError, match="identifier"):
        package_metadata(description.replace(IDENTIFIER.encode(), b"wrong.identifier"))
    with pytest.raises(ValueError, match="minimum"):
        package_metadata(description.replace(b"LibreOffice-minimal-version", b"ignored"))
