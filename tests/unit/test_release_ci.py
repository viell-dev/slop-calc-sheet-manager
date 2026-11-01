"""Publication requires complete, exact-revision release evidence beyond routine CI."""

from typing import Any

import pytest

from tools import github_release as cli
from tools.ci_policy import ROUTINE, SWEEP


@pytest.fixture
def evidence(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any]:
    runs: dict[str, list[dict[str, Any]]] = {}
    jobs: dict[int, list[dict[str, Any]]] = {}
    for number, policy in enumerate((ROUTINE, SWEEP), 1):
        runs[policy.workflow] = [
            {
                "id": number,
                "head_sha": "a" * 40,
                "head_branch": "main",
                "event": "push" if policy == ROUTINE else "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
                "html_url": f"https://example.invalid/ci/{number}",
            }
        ]
        jobs[number] = [
            {"name": name, "status": "completed", "conclusion": "success"}
            for name in sorted(policy.checks)
        ]
    calls: list[str] = []

    def api(path: str) -> dict[str, Any]:
        calls.append(path)
        if "/jobs?" in path:
            number = int(path.split("/runs/")[1].split("/")[0])
            return {"jobs": jobs[number]}
        assert f"head_sha={'a' * 40}" in path
        name = path.split("/workflows/")[1].split("/")[0]
        return {"workflow_runs": runs[name]}

    monkeypatch.setattr(cli, "api", api)
    return runs, jobs, calls


def test_routine_alone_cannot_authorize_a_release_or_manual_dry_run(evidence: Any) -> None:
    runs, _, calls = evidence
    assert cli.require_ci("a" * 40, publishing=True, timeout=0).endswith("/2")
    runs[SWEEP.workflow] = []
    for publishing in (False, True):
        with pytest.raises(ValueError, match="No successful Full release sweep"):
            cli.require_ci("a" * 40, publishing=publishing, timeout=0)
    assert cli.require_ci("a" * 40, publishing=False, preview=True, timeout=0).endswith("/1")
    before = len(calls)
    with pytest.raises(ValueError, match="preview cannot authorize publication"):
        cli.require_ci("a" * 40, publishing=True, preview=True, timeout=0)
    assert len(calls) == before


@pytest.mark.parametrize("workflow", [ROUTINE.workflow, SWEEP.workflow])
@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "b" * 40),
        ("head_branch", "task"),
        ("event", "schedule"),
    ],
)
def test_publication_rejects_stale_wrong_branch_or_wrong_event_evidence(
    evidence: Any,
    workflow: str,
    field: str,
    value: str,
) -> None:
    runs, _, _ = evidence
    runs[workflow][0][field] = value
    with pytest.raises(ValueError, match="No successful"):
        cli.require_ci("a" * 40, publishing=True, timeout=0)


@pytest.mark.parametrize("run_number", [1, 2])
@pytest.mark.parametrize("failure", ["missing", "duplicate", "skipped", "failure", "neutral"])
def test_a_green_workflow_cannot_hide_missing_or_unsuccessful_jobs(
    evidence: Any,
    run_number: int,
    failure: str,
) -> None:
    _, jobs, _ = evidence
    if failure == "missing":
        jobs[run_number].pop()
    elif failure == "duplicate":
        jobs[run_number].append(jobs[run_number][0])
    else:
        jobs[run_number][0]["conclusion"] = failure
    with pytest.raises(ValueError, match="Required jobs"):
        cli.require_ci("a" * 40, publishing=True, timeout=0)


def test_latest_failed_sweep_cannot_fall_back_to_an_older_green_run(evidence: Any) -> None:
    runs, _, _ = evidence
    newer = {**runs[SWEEP.workflow][0], "id": 3, "conclusion": "failure"}
    runs[SWEEP.workflow].append(newer)
    with pytest.raises(ValueError, match="Full release sweep did not pass"):
        cli.require_ci("a" * 40, publishing=True, timeout=0)


@pytest.mark.parametrize("failure", ["missing", "skipped", "failure", "cancelled", "in_progress"])
def test_green_linux_windows_sweep_cannot_authorize_release_without_macos(
    evidence: Any, failure: str
) -> None:
    _, jobs, _ = evidence
    macos = next(job for job in jobs[2] if job["name"] == "macOS Intel packaged integration")
    if failure == "missing":
        jobs[2].remove(macos)
    elif failure == "in_progress":
        macos["status"] = "in_progress"
    else:
        macos["conclusion"] = failure
    for publishing in (False, True):
        with pytest.raises(ValueError, match="Required jobs"):
            cli.require_ci("a" * 40, publishing=publishing, timeout=0)


def test_a_branch_pr_cannot_supply_main_publication_evidence(evidence: Any) -> None:
    runs, _, _ = evidence
    runs[ROUTINE.workflow][0].update(event="pull_request", head_branch="task")
    runs[SWEEP.workflow][0]["head_branch"] = "task"
    assert cli.require_ci("a" * 40, publishing=False, timeout=0).endswith("/2")
    with pytest.raises(ValueError, match="No successful"):
        cli.require_ci("a" * 40, publishing=True, timeout=0)


def test_ci_gate_paginates_job_evidence(evidence: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _, jobs, _ = evidence
    original = cli.api

    def api(path: str) -> Any:
        if "/runs/2/jobs?" in path:
            if path.endswith("page=1"):
                return {"jobs": [{"name": f"extra-{i}"} for i in range(100)]}
            return {"jobs": jobs[2]}
        return original(path)

    monkeypatch.setattr(cli, "api", api)
    assert cli.require_ci("a" * 40, publishing=True, timeout=0).endswith("/2")
