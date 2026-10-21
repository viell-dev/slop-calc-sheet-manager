"""Keep the label catalog, the issue forms, and the files that apply labels in agreement."""

import json
import re
from pathlib import Path
from typing import Any, cast

import yaml

from tools.build import ROOT
from tools.labels import differences

GITHUB = ROOT / ".github"
FORMS = GITHUB / "ISSUE_TEMPLATE"
COLOR = re.compile(r"[0-9a-f]{6}")


def labels() -> list[dict[str, str]]:
    return cast(list[dict[str, str]], json.loads((GITHUB / "labels.json").read_text("utf-8")))


def label_names() -> set[str]:
    return {label["name"] for label in labels()}


def load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(path.read_text("utf-8")))


def forms() -> list[Path]:
    return sorted(path for path in FORMS.glob("*.yml") if path.name != "config.yml")


def test_label_catalog_is_well_formed() -> None:
    catalog = labels()
    names = [label["name"] for label in catalog]
    assert len(names) == len(set(names)), "duplicate label names"
    # GitHub compares label names case-insensitively, and so does tools/labels.py.
    assert len({name.casefold() for name in names}) == len(names), "names differing only in case"
    for label in catalog:
        assert set(label) == {"name", "color", "description"}, label
        assert COLOR.fullmatch(label["color"]), label
        assert 0 < len(label["description"]) <= 100, label  # GitHub's description limit
    prefixes = {name.split(": ")[0] for name in names if ": " in name}
    assert prefixes == {"Type", "Status", "Needs"}
    assert {"Type: Enhancement", "Type: Feature Request", "Needs: Owner", "Needs: Human"} <= set(
        names
    )


def test_each_issue_form_applies_one_known_type_label() -> None:
    known = label_names()
    assert forms(), "no issue forms"
    for path in forms():
        form = load(path)
        assert form["name"] and form["description"] and form["body"], path.name
        applied = cast(list[str], form.get("labels", []))
        assert set(applied) <= known, (path.name, applied)
        assert len([label for label in applied if label.startswith("Type: ")]) == 1, path.name
        assert not [label for label in applied if label.startswith("Status: ")], path.name


def test_bug_form_asks_for_what_a_report_needs() -> None:
    fields = {
        cast(str, item["id"]): item
        for item in cast(list[dict[str, Any]], load(FORMS / "bug.yml")["body"])
        if "id" in item
    }
    for required in (
        "extension-version",
        "libreoffice-version",
        "installation",
        "steps",
        "actual",
        "expected",
        "workbook",
    ):
        assert fields[required]["validations"]["required"] is True, required
    assert "Copy Version Information" in fields["libreoffice-version"]["attributes"]["description"]


def test_blank_issues_are_routed_through_the_forms() -> None:
    config = load(FORMS / "config.yml")
    assert config["blank_issues_enabled"] is False
    urls = [link["url"] for link in cast(list[dict[str, str]], config["contact_links"])]
    assert any(url.endswith("/security/advisories/new") for url in urls)


def test_label_differences_name_missing_changed_and_extra_labels() -> None:
    def label(name: str, color: str = "ffffff", description: str = "d") -> dict[str, str]:
        return {"name": name, "color": color, "description": description}

    wanted = {"A": label("A"), "B": label("B"), "C": label("C", description="new")}
    present = {"B": label("B"), "C": label("C", description="old"), "D": label("D")}
    assert differences(wanted, present) == (["A"], ["C"], ["D"])
    assert differences(wanted, dict(wanted)) == ([], [], [])
    # GitHub label names are case-insensitive: a change of case is an update, not a new label.
    assert differences(
        {"Needs: Owner": label("Needs: Owner")}, {"Needs: owner": label("Needs: owner")}
    ) == ([], ["Needs: Owner"], [])


def test_dependabot_labels_exist() -> None:
    dependabot = load(GITHUB / "dependabot.yml")
    known = label_names()
    for update in cast(list[dict[str, Any]], dependabot["updates"]):
        assert set(cast(list[str], update.get("labels", []))) <= known, update
