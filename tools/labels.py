"""Compare GitHub's labels with `.github/labels.json`, or bring them in line with it.

`check` changes nothing and exits with status 1 when the live labels differ. `sync` creates and
updates labels to match the catalog and deletes extra labels that no issue or pull request uses;
it refuses to delete an extra label that is still in use, so that items are relabelled
deliberately first. GitHub treats label names case-insensitively, so a live label that differs
only in case is updated, not recreated. Both use an authenticated `gh` command line.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import cast
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "viell-dev/slop-calc-sheet-manager"


def gh(*arguments: str) -> str:
    return subprocess.run(
        ["gh", *arguments], check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def catalog() -> dict[str, dict[str, str]]:
    labels = cast(
        list[dict[str, str]],
        json.loads((ROOT / ".github" / "labels.json").read_text(encoding="utf-8")),
    )
    return {label["name"]: label for label in labels}


def by_folded_name(labels: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return {name.casefold(): label for name, label in labels.items()}


def live(repository: str) -> dict[str, dict[str, str]]:
    pages = cast(
        list[list[dict[str, object]]],
        json.loads(gh("api", "--paginate", "--slurp", f"repos/{repository}/labels?per_page=100")),
    )
    return {
        cast(str, label["name"]): {
            "name": cast(str, label["name"]),
            "color": cast(str, label["color"]).lower(),
            "description": cast(str, label["description"] or ""),
        }
        for page in pages
        for label in page
    }


def in_use(repository: str, name: str) -> bool:
    """Whether any issue or pull request has the label, read directly rather than from search."""
    items = gh(
        "api",
        "-X",
        "GET",
        f"repos/{repository}/issues",
        "-f",
        "state=all",
        "-f",
        f"labels={name}",
        "-f",
        "per_page=1",
    )
    return bool(json.loads(items))


def differences(
    wanted: dict[str, dict[str, str]], present: dict[str, dict[str, str]]
) -> tuple[list[str], list[str], list[str]]:
    """Name the labels to create, to update (including a change of case), and the extra ones."""
    want, have = by_folded_name(wanted), by_folded_name(present)
    missing = sorted(want[key]["name"] for key in set(want) - set(have))
    changed = sorted(want[key]["name"] for key in set(want) & set(have) if want[key] != have[key])
    extra = sorted(have[key]["name"] for key in set(have) - set(want))
    return missing, changed, extra


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "sync"])
    parser.add_argument("--repository", default=REPOSITORY)
    arguments = parser.parse_args()
    wanted, present = catalog(), live(arguments.repository)
    missing, changed, extra = differences(wanted, present)
    for name in missing:
        print(f"missing: {name}")
    have = by_folded_name(present)
    for name in changed:
        print(f"differs: {have[name.casefold()]} -> {wanted[name]}")
    for name in extra:
        print(f"extra: {name}")
    if arguments.command == "check":
        sys.exit(1 if missing or changed or extra else 0)
    path = f"repos/{arguments.repository}/labels"
    for name in missing:
        label = wanted[name]
        fields = ["-f", f"color={label['color']}", "-f", f"description={label['description']}"]
        gh("api", path, "-f", f"name={name}", *fields)
    for name in changed:
        label, current = wanted[name], have[name.casefold()]["name"]
        fields = ["-f", f"color={label['color']}", "-f", f"description={label['description']}"]
        fields += ["-f", f"new_name={name}"]
        gh("api", "-X", "PATCH", f"{path}/{quote(current, safe='')}", *fields)
    used = [name for name in extra if in_use(arguments.repository, name)]
    for name in extra:
        if name not in used:
            gh("api", "-X", "DELETE", f"{path}/{quote(name, safe='')}")
    if used:
        sys.exit(f"Still in use, relabel these items first: {', '.join(used)}")


if __name__ == "__main__":
    main()
