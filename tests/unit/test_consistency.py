"""Keep the facts that several public surfaces repeat in agreement with their sources.

`extension/description.xml` is the source of the identifier, the minimum LibreOffice version, and
the update feed; `ci/libreoffice.json` is the source of the tested versions. The README, the user
guide, and the integration runner must agree with them. Prose is reviewed by people; this test
compares only what can be compared mechanically.
"""

import json
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, cast

import yaml

from tools.build import ROOT

DOCS = ROOT / "docs"
NAMESPACES = {
    "d": "http://openoffice.org/extensions/description/2006",
    "lo": "http://libreoffice.org/extensions/description/2011",
    "xlink": "http://www.w3.org/1999/xlink",
}


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def description() -> ElementTree.Element:
    return ElementTree.parse(ROOT / "extension" / "description.xml").getroot()


def identifier() -> str:
    element = description().find("d:identifier", NAMESPACES)
    assert element is not None
    return element.attrib["value"]


def minimum() -> str:
    element = description().find("d:dependencies/lo:LibreOffice-minimal-version", NAMESPACES)
    assert element is not None
    return element.attrib["value"]


def feed_url() -> str:
    element = description().find("d:update-information/d:src", NAMESPACES)
    assert element is not None
    return element.attrib[f"{{{NAMESPACES['xlink']}}}href"]


def lanes() -> dict[str, dict[str, str]]:
    return json.loads(text(ROOT / "ci" / "libreoffice.json"))


def readme_region(name: str) -> str:
    match = re.search(
        rf"<!-- #region {name} -->\n(.*?)\n<!-- #endregion {name} -->",
        text(ROOT / "README.md"),
        re.S,
    )
    assert match, f"README.md lacks the {name} region"
    return match[1]


def bullets(markdown: str, heading: str) -> list[str]:
    """The top-level list items that follow `heading`, joined across wrapped lines."""
    section = markdown.split(heading, 1)[1]
    items: list[str] = []
    for line in section.splitlines():
        if line.startswith("- "):
            items.append(line[2:])
        elif line.startswith("  ") and items:
            items[-1] += " " + line.strip()
        elif items and not line.strip():
            break
    return items


def test_minimum_version_agrees_everywhere() -> None:
    version = minimum()
    assert f"LibreOffice **{version} or later**" in text(ROOT / "README.md")
    assert f"**LibreOffice {version} or later.**" in text(DOCS / "guide" / "install.md")
    pins = lanes()
    assert pins["minimum"]["version"].startswith(version + ".")
    oldest = [int(part) for part in version.split(".")]
    refused = [int(part) for part in pins["unsupported"]["version"].split(".")[:3]]
    assert refused < oldest, "The refusal lane must test a version below the minimum"


def test_environment_table_names_the_tested_builds() -> None:
    table = readme_region("environments")
    pins = lanes()
    linux = next(line for line in table.splitlines() if line.startswith("| Linux x86-64"))
    for lane in ("minimum", "current-26.2", "current-26.8"):
        assert pins[lane]["version"] in linux, lane
    windows = next(line for line in table.splitlines() if line.startswith("| Windows x86-64"))
    assert pins["windows"]["version"] in windows
    refused = ".".join(pins["unsupported"]["version"].split(".")[:3])
    assert f"| LibreOffice {refused} and earlier " in table
    assert "<!--@include: ../../README.md#environments-->" in text(
        DOCS / "guide" / "known-issues.md"
    )


def test_identifier_and_feed_agree_everywhere() -> None:
    name = identifier()
    assert f'IDENTIFIER = "{name}"' in text(ROOT / "tests" / "integration" / "run.py")
    for page in ("install.md", "troubleshooting.md"):
        assert f"unopkg remove {name}" in text(DOCS / "guide" / page), page
    url = feed_url()
    assert url in text(ROOT / "README.md")
    assert url in text(DOCS / "guide" / "install.md")


def test_planned_features_match_the_readme() -> None:
    readme = bullets(text(ROOT / "README.md"), "planned to offer:\n")
    guide = bullets(text(DOCS / "guide" / "status.md"), "The first release is planned to offer:\n")
    assert readme and readme == guide


def ci_job_names() -> set[str]:
    """The names CI reports for its jobs, with each matrix entry's values filled in."""
    workflow = yaml.load(text(ROOT / ".github" / "workflows" / "ci.yml"), Loader=yaml.BaseLoader)
    names: set[str] = set()
    for job in cast(dict[str, dict[str, Any]], workflow["jobs"]).values():
        template = cast(str, job["name"])
        matrix = cast(dict[str, Any], job.get("strategy", {}).get("matrix", {}))
        entries = cast(list[dict[str, str]], matrix.get("include", [])) or [
            {key: value} for key, values in matrix.items() for value in cast(list[str], values)
        ]
        for entry in entries or [{}]:
            name = template
            for key, value in entry.items():
                name = name.replace("${{ matrix." + key + " }}", value)
            names.add(name)
    return names


def test_recorded_ruleset_requires_exactly_the_ci_jobs() -> None:
    ruleset = json.loads(text(ROOT / ".github" / "rulesets" / "main.json"))
    rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    required = {check["context"] for check in rule["parameters"]["required_status_checks"]}
    assert required == ci_job_names()
    assert rule["parameters"]["strict_required_status_checks_policy"] is False


def test_every_guide_page_is_in_the_sidebar_and_every_link_has_a_page() -> None:
    config = text(DOCS / ".vitepress" / "config.mts")
    links = set(re.findall(r'link: "(/[^"]*)"', config))
    pages = {
        "/" + path.relative_to(DOCS).with_suffix("").as_posix()
        for path in DOCS.rglob("*.md")
        if ".vitepress" not in path.parts
    }
    pages = {page.removesuffix("index") if page.endswith("/index") else page for page in pages}
    assert links <= pages | {"/"}, links - pages
    assert pages - {"/"} <= links, f"Pages missing from the sidebar: {pages - {'/'} - links}"
