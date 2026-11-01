"""Required routine/release evidence; missing or skipped work is never success (#143).

Workflows use dependency results for their aggregate; publication independently checks every
expected job on the exact revision. Keep these names, workflow matrices and the main ruleset
consistent. A manual release sweep is separate from routine CI and from PR planning previews.
It includes Intel macOS headless integration (#145); the earlier Linux/Windows-only sweep is
insufficient, and a separate focused macOS run cannot replace a sweep on the release revision.
"""

import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Policy:
    workflow: str
    aggregate: str
    dependencies: frozenset[str]
    checks: frozenset[str]


ROUTINE = Policy(
    "ci.yml",
    "Routine CI",
    frozenset({"checks", "docs", "linux"}),
    frozenset(
        {
            "Checks (Python 3.12)",
            "Checks (Python 3.14)",
            "Documentation",
            "Linux current",
            "Routine CI",
        }
    ),
)
SWEEP = Policy(
    "release-sweep.yml",
    "Full release sweep",
    frozenset({"linux", "linux-gtk3", "refusal", "windows", "desktop", "macos"}),
    frozenset(
        {
            *(
                f"Linux (LibreOffice {version})"
                for version in ("26.2.1", "26.2 latest", "26.8 latest")
            ),
            *(
                f"Linux gtk3 (LibreOffice {version})"
                for version in ("26.2.1", "26.2 latest", "26.8 latest")
            ),
            "Refuses LibreOffice 26.2.0",
            "Windows (LibreOffice 26.8 latest)",
            "Windows desktop real input",
            "macOS Intel packaged integration",
            "Full release sweep",
        }
    ),
)
POLICIES = {"routine": ROUTINE, "sweep": SWEEP}


def require_dependencies(results: dict[str, Any], policy: Policy) -> None:
    if frozenset(results) != policy.dependencies:
        raise ValueError(
            f"Required dependencies differ: expected {sorted(policy.dependencies)}, "
            f"got {sorted(results)}"
        )
    failed = {
        name: item.get("result")
        for name, item in results.items()
        if item.get("result") != "success"
    }
    if failed:
        raise ValueError(f"Required work did not succeed: {failed}")


def require_completed_jobs(jobs: list[dict[str, Any]], policy: Policy) -> None:
    counts = Counter(job["name"] for job in jobs)
    missing = sorted(name for name in policy.checks if counts[name] != 1)
    if missing:
        raise ValueError(f"Required jobs missing or duplicated: {missing}")
    failed = {
        job["name"]: (job.get("status"), job.get("conclusion"))
        for job in jobs
        if job["name"] in policy.checks
        and (job.get("status") != "completed" or job.get("conclusion") != "success")
    }
    if failed:
        raise ValueError(f"Required jobs did not succeed: {failed}")


if __name__ == "__main__":
    selected = POLICIES[sys.argv[1]]
    require_dependencies(json.loads(os.environ["CI_NEEDS"]), selected)
    print(f"{selected.aggregate}: every required dependency succeeded")
