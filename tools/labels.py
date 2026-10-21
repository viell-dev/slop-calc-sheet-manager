"""Compare GitHub's labels with `.github/labels.json`, or bring them in line with it.

`check` changes nothing and exits with status 1 when the live labels differ. `sync` creates and
updates labels to match the catalog and deletes extra labels that no issue or pull request uses;
it refuses to delete an extra label that is still in use, so that items are relabelled
deliberately first. Both use an authenticated `gh` command line.
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


def uses(repository: str, name: str) -> int:
    query = f'repo:{repository} label:"{name}"'
    return int(gh("api", "-X", "GET", "search/issues", "-f", f"q={query}", "--jq", ".total_count"))


def differences(
    wanted: dict[str, dict[str, str]], present: dict[str, dict[str, str]]
) -> tuple[list[str], list[str], list[str]]:
    missing = sorted(set(wanted) - set(present))
    changed = sorted(name for name in set(wanted) & set(present) if wanted[name] != present[name])
    extra = sorted(set(present) - set(wanted))
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
    for name in changed:
        print(f"differs: {name}: {present[name]} -> {wanted[name]}")
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
        label = wanted[name]
        fields = ["-f", f"color={label['color']}", "-f", f"description={label['description']}"]
        gh("api", "-X", "PATCH", f"{path}/{quote(name, safe='')}", *fields)
    in_use = [name for name in extra if uses(arguments.repository, name)]
    for name in extra:
        if name not in in_use:
            gh("api", "-X", "DELETE", f"{path}/{quote(name, safe='')}")
    if in_use:
        sys.exit(f"Still in use, relabel these items first: {', '.join(in_use)}")


if __name__ == "__main__":
    main()
