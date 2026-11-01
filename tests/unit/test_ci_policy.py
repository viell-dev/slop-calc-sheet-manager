"""Missing/skipped evidence cannot become a green aggregate or a publication gate."""

from typing import Any

import pytest
import yaml

from tools.build import ROOT
from tools.ci_policy import (
    POLICIES,
    ROUTINE,
    SWEEP,
    Policy,
    require_completed_jobs,
    require_dependencies,
)


@pytest.mark.parametrize("policy", [ROUTINE, SWEEP])
def test_every_dependency_must_be_present_and_succeed(policy: Policy) -> None:
    results: dict[str, Any] = {name: {"result": "success"} for name in policy.dependencies}
    require_dependencies(results, policy)
    name = sorted(results)[0]
    for status in ("failure", "cancelled", "skipped", "neutral", None):
        results[name] = {"result": status}
        with pytest.raises(ValueError, match="did not succeed"):
            require_dependencies(results, policy)
    results.pop(name)
    with pytest.raises(ValueError, match="dependencies differ"):
        require_dependencies(results, policy)


@pytest.mark.parametrize("policy", [ROUTINE, SWEEP])
def test_every_required_job_must_complete_successfully(policy: Policy) -> None:
    jobs: list[dict[str, Any]] = [
        {"name": name, "status": "completed", "conclusion": "success"}
        for name in sorted(policy.checks)
    ]
    require_completed_jobs(jobs, policy)
    for status in ("failure", "cancelled", "skipped", "neutral", None):
        jobs[0]["conclusion"] = status
        with pytest.raises(ValueError, match="did not succeed"):
            require_completed_jobs(jobs, policy)
    jobs[0]["conclusion"] = "success"
    jobs[0]["status"] = "in_progress"
    with pytest.raises(ValueError, match="did not succeed"):
        require_completed_jobs(jobs, policy)
    jobs[0]["status"] = "completed"
    with pytest.raises(ValueError, match="missing or duplicated"):
        require_completed_jobs(jobs[1:], policy)
    with pytest.raises(ValueError, match="missing or duplicated"):
        require_completed_jobs([*jobs, jobs[0]], policy)


@pytest.mark.parametrize("kind", list(POLICIES))
def test_aggregate_depends_on_every_job_and_runs_even_after_a_failure(kind: str) -> None:
    policy = POLICIES[kind]
    path = ROOT / ".github/workflows" / policy.workflow
    workflow = yaml.load(path.read_text("utf-8"), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    aggregate = jobs["gate"]
    assert aggregate["name"] == policy.aggregate and aggregate["if"] == "always()"
    assert set(aggregate["needs"]) == policy.dependencies == set(jobs) - {"gate"}
    assert aggregate["steps"][-1]["env"]["CI_NEEDS"] == "${{ toJSON(needs) }}"
    assert aggregate["steps"][-1]["run"] == f"python3 tools/ci_policy.py {kind}"
    for job in jobs.values():
        checkout = next(
            step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha || github.sha }}"


def test_platform_sweeps_and_windows_investigations_are_manual_only() -> None:
    for filename in ("release-sweep.yml", "windows-desktop.yml"):
        workflow = yaml.load(
            (ROOT / ".github/workflows" / filename).read_text("utf-8"), Loader=yaml.BaseLoader
        )
        assert set(workflow["on"]) == {"workflow_dispatch"}
