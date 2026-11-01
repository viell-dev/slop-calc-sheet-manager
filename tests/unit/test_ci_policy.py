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
    for filename in ("release-sweep.yml", "windows-desktop.yml", "macos.yml"):
        workflow = yaml.load(
            (ROOT / ".github/workflows" / filename).read_text("utf-8"), Loader=yaml.BaseLoader
        )
        assert set(workflow["on"]) == {"workflow_dispatch"}


def test_routine_linux_retains_early_failure_before_starting_input() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text("utf-8"), Loader=yaml.BaseLoader
    )
    job = workflow["jobs"]["linux"]
    assert job["timeout-minutes"] == "45", "Diagnostic handling must not widen the job budget"
    steps = job["steps"]
    headless = next(
        i for i, step in enumerate(steps) if "--sessions headless" in step.get("run", "")
    )
    upload = steps[headless + 1]
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "test-results/"
    assert upload["with"]["if-no-files-found"] == "error"
    real_input = steps[headless + 2]
    assert "--ui --backtrace" in real_input["run"]
    assert real_input["if"] == "${{ success() }}"
    for step in (steps[headless], real_input):
        assert step["shell"] == "bash"
        assert "set -o pipefail" in step["run"], "tee must not hide a failed runner"
        assert "2>&1 | tee test-results/ci/" in step["run"]
        assert step.get("continue-on-error", "false") == "false"


@pytest.mark.parametrize("result", [None, "failure", "skipped", "cancelled"])
def test_macos_is_required_even_when_every_other_sweep_dependency_passes(
    result: str | None,
) -> None:
    results: dict[str, Any] = {name: {"result": "success"} for name in SWEEP.dependencies}
    assert "macos" in results
    if result is None:
        results.pop("macos")
    else:
        results["macos"]["result"] = result
    with pytest.raises(ValueError, match="dependencies differ|did not succeed"):
        require_dependencies(results, SWEEP)
