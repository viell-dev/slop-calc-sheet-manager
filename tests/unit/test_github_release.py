"""Test release orchestration without a token, network, or GitHub writes."""

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from tools import github_release as cli
from tools.build import ROOT, build, version
from tools.release_data import STAGES, PublishedBuild, release_title, version_parts


def next_minor() -> str:
    major, minor, _ = version_parts(version())
    return f"{major}.{minor + 1}.0"


def next_major() -> str:
    return f"{version_parts(version())[0] + 1}.0.0"


# Each stage with the targets it accepts; test_release_data.py has the expected titles.
STAGE_REQUESTS = [
    ("stable", ""),
    ("alpha", ""),
    ("alpha", "minor"),
    ("beta", "minor"),
    ("rc", "minor"),
    ("beta", "major"),
    ("rc", "major"),
]


def target_for(kind: str) -> str:
    return {"": "", "minor": next_minor(), "major": next_major()}[kind]


def test_ci_gate_requires_exact_commit_and_main_push_for_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run: dict[str, object] = {
        "event": "push",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://example.invalid/ci/1",
    }
    calls: list[str] = []

    def api(path: str) -> dict[str, object]:
        calls.append(path)
        return {"workflow_runs": [run]}

    monkeypatch.setattr(cli, "api", api)
    assert cli.require_ci("a" * 40, publishing=True, timeout=0) == run["html_url"]
    assert f"head_sha={'a' * 40}" in calls[0]
    run["event"] = "pull_request"
    with pytest.raises(ValueError, match="No successful"):
        cli.require_ci("a" * 40, publishing=True, timeout=0)
    assert cli.require_ci("a" * 40, publishing=False, timeout=0) == run["html_url"]
    run["conclusion"] = "failure"
    with pytest.raises(ValueError, match="CI did not pass"):
        cli.require_ci("a" * 40, publishing=False, timeout=0)
    run.update(event="push", conclusion="success", head_branch="other-branch")
    with pytest.raises(ValueError, match="No successful"):
        cli.require_ci("a" * 40, publishing=True, timeout=0)


def test_ci_gate_waits_for_a_native_matrix_longer_than_twenty_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elapsed = 0.0

    def sleep(seconds: float) -> None:
        nonlocal elapsed
        elapsed += seconds

    def api(path: str) -> dict[str, object]:
        assert f"head_sha={'a' * 40}" in path
        completed = elapsed >= 25 * 60
        return {
            "workflow_runs": [
                {
                    "event": "pull_request",
                    "status": "completed" if completed else "in_progress",
                    "conclusion": "success" if completed else None,
                    "html_url": "https://example.invalid/ci/long-native-matrix",
                }
            ]
        }

    monkeypatch.setattr(cli.time, "monotonic", lambda: elapsed)
    monkeypatch.setattr(cli.time, "sleep", sleep)
    monkeypatch.setattr(cli, "api", api)
    assert cli.require_ci("a" * 40, publishing=False).endswith("/long-native-matrix")
    assert elapsed == 25 * 60


@pytest.mark.parametrize(("stage", "target_kind"), STAGE_REQUESTS)
def test_dry_run_builds_assets_and_prospective_feeds_without_api_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stage: str,
    target_kind: str,
) -> None:
    target = target_for(target_kind)
    monkeypatch.setattr(
        sys,
        "argv",
        ["release", "release", "--version", version(), "--stage", stage, "--output", str(tmp_path)],
    )
    if target:
        sys.argv += ["--target", target]
    monkeypatch.setenv("RELEASE_COMMIT", "a" * 40)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setattr(cli.subprocess, "check_output", Mock(return_value="a" * 40))
    monkeypatch.setattr(cli, "paginated", Mock(return_value=[]))
    monkeypatch.setattr(cli, "previous_builds", Mock(return_value=[]))
    monkeypatch.setattr(cli, "require_ci", Mock(return_value="https://example.invalid/ci/1"))

    def no_write(*args: object, **kwargs: object) -> None:
        pytest.fail("Dry run attempted a GitHub API write")

    monkeypatch.setattr(cli, "api", no_write)
    cli.main()
    assert (tmp_path / f"sheet-manager-{version()}.oxt").exists()
    assert (tmp_path / f"sheet-manager-{version()}.oxt.sha256").exists()
    plan = json.loads((tmp_path / "release-plan.json").read_text(encoding="utf-8"))
    assert plan["release"]["target_commitish"] == "a" * 40
    assert plan["release"]["draft"] is True
    assert plan["stage"] == stage and plan["target"] == target
    assert plan["release"]["name"] == release_title(version(), stage, target)
    assert plan["release"]["prerelease"] is (stage != "stable")
    assert plan["release"]["body"] == (tmp_path / "release-notes.md").read_text(encoding="utf-8")
    offered = f'value="{version()}"'.encode()
    assert offered in (tmp_path / "site/updates/prerelease.xml").read_bytes()
    assert (offered in (tmp_path / "site/updates/stable.xml").read_bytes()) is (stage == "stable")
    history = json.loads((tmp_path / "site/releases.json").read_text(encoding="utf-8"))
    assert [item["prerelease"] for item in history] == [stage != "stable"]


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--prerelease"],
        ["--stage", "beta"],
        ["--stage", "rc"],
        ["--stage", "stable", "--target", "NEXT"],
        ["--stage", "beta", "--target", "0.0.99"],
        ["--stage", "candidate", "--target", "NEXT"],
    ],
)
@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
def test_a_missing_or_invalid_stage_stops_before_reading_github(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, arguments: list[str], event: str
) -> None:
    arguments = [next_minor() if item == "NEXT" else item for item in arguments]
    monkeypatch.setattr(
        sys,
        "argv",
        ["release", "release", "--version", version(), "--output", str(tmp_path), *arguments],
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("RELEASE_COMMIT", "a" * 40)
    monkeypatch.setattr(cli.subprocess, "check_output", Mock(return_value="a" * 40))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("An invalid release request reached GitHub")

    for name in ("api", "paginated", "previous_builds", "require_ci", "download"):
        monkeypatch.setattr(cli, name, forbidden)
    with pytest.raises((SystemExit, ValueError)):
        cli.main()
    assert list(tmp_path.iterdir()) == []


def test_release_workflow_offers_each_stage_and_never_defaults_to_stable() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text("utf-8"))
    # PyYAML reads the bare key `on` as True.
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert "prerelease" not in inputs
    assert inputs["stage"]["type"] == "choice"
    assert tuple(inputs["stage"]["options"]) == STAGES
    assert inputs["stage"]["default"] == "alpha"
    runs = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "github_release.py" in step.get("run", "")
    ]
    assert len(runs) == 2
    for run in runs:
        calls = [line for line in run.splitlines() if "release --version" in line]
        assert calls and all("--stage" in line for line in calls), run
        assert "--prerelease" not in run


def test_existing_draft_and_mismatched_metadata_stop_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli, "paginated", Mock(return_value=[{"tag_name": version(), "draft": True}])
    )
    with pytest.raises(ValueError, match="draft already exists"):
        cli.prepare(version(), "stable", "", tmp_path)
    with pytest.raises(ValueError, match="description.xml contains"):
        cli.prepare("999.0.0", "stable", "", tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
@pytest.mark.parametrize("draft", [False, True])
def test_only_prs_skip_release_planning_for_an_already_published_metadata_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    event: str,
    draft: bool,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["release", "release", "--version", version(), "--stage", "stable"]
        + ["--output", str(tmp_path)],
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("RELEASE_COMMIT", "a" * 40)
    monkeypatch.setattr(cli.subprocess, "check_output", Mock(return_value="a" * 40))
    monkeypatch.setattr(
        cli, "paginated", Mock(return_value=[{"tag_name": version(), "draft": draft}])
    )
    builds = [PublishedBuild(version(), False, "26.2.1", "2026-10-19T00:00:00Z")]
    monkeypatch.setattr(cli, "published_builds", Mock(return_value=builds))
    monkeypatch.setattr(cli, "previous_builds", Mock(return_value=builds))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Skipped release planning attempted CI polling or a GitHub write")

    monkeypatch.setattr(cli, "require_ci", forbidden)
    monkeypatch.setattr(cli, "api", forbidden)
    if event == "pull_request" and not draft:
        cli.main()
        assert "::notice::" in capsys.readouterr().out
        assert not (tmp_path / "release-plan.json").exists()
        assert json.loads((tmp_path / "site/releases.json").read_text()) == [asdict(builds[0])]
    else:
        with pytest.raises(ValueError, match="draft already exists"):
            cli.main()


def test_noncanonical_published_release_tags_fail_loudly() -> None:
    with pytest.raises(ValueError, match="three plain dotted numbers"):
        cli.published_builds([{"tag_name": "manual-build", "draft": False, "prerelease": False}])


def test_publishing_is_refused_from_a_pr_or_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["release", "release", "--version", version(), "--stage", "alpha", "--publish"]
    )
    for event, ref in (
        ("pull_request", "refs/heads/main"),
        ("workflow_dispatch", "refs/heads/task"),
    ):
        monkeypatch.setenv("GITHUB_REF", ref)
        monkeypatch.setenv("GITHUB_EVENT_NAME", event)
        with pytest.raises(ValueError, match="only by workflow_dispatch on main"):
            cli.main()


@pytest.mark.parametrize(
    ("title", "prerelease"),
    [
        (f"0.1.0 test build ({version()})", True),
        (f"{version()} alpha", True),
        (f"0.1.0 beta ({version()})", True),
        (f"0.1.0 rc ({version()})", True),
        (version(), False),
        ("A title in no scheme", False),
    ],
)
def test_published_metadata_comes_from_checksummed_oxt_and_drafts_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    title: str,
    prerelease: bool,
) -> None:
    package = build(tmp_path)
    base = f"https://github.com/{cli.REPOSITORY}/releases/download/{version()}/"
    assets: dict[str, bytes] = {
        base + package.name: package.read_bytes(),
        base + package.name + ".sha256": package.with_suffix(".oxt.sha256").read_bytes(),
    }
    monkeypatch.setattr(cli, "download", Mock(side_effect=assets.__getitem__))
    release: dict[str, Any] = {
        "tag_name": version(),
        "name": title,
        "prerelease": prerelease,
        "draft": False,
        "published_at": "2026-10-19T00:00:00Z",
        "assets": [{"name": url.rsplit("/", 1)[1], "browser_download_url": url} for url in assets],
    }
    builds = cli.published_builds([release, {"draft": True}])
    assert builds == [
        PublishedBuild(version(), release["prerelease"], "26.2.1", release["published_at"])
    ]
    assets[base + package.name + ".sha256"] = b"bad checksum\n"
    with pytest.raises(ValueError, match="checksum"):
        cli.published_builds([release])
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    assets[base + package.name + ".sha256"] = f"{digest}  {package.name}\n".encode()
    release["assets"] = release["assets"][:1]
    with pytest.raises(ValueError, match="missing"):
        cli.published_builds([release])


def test_pages_refuses_to_remove_previously_deployed_builds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old = PublishedBuild("0.0.90", True, "26.2.1", "2026-10-18T00:00:00Z")
    new = PublishedBuild("0.1.0", False, "26.2.1", "2026-10-19T00:00:00Z")
    monkeypatch.setattr(cli, "previous_builds", lambda: [old])
    with pytest.raises(ValueError, match="removed or changed"):
        cli.write_site(tmp_path, [new])
    cli.write_site(tmp_path, [old, new])
    assert json.loads((tmp_path / "releases.json").read_text()) == [asdict(old), asdict(new)]


def feed_site(monkeypatch: pytest.MonkeyPatch, site: Path) -> None:
    def no_history() -> list[PublishedBuild]:
        return []

    monkeypatch.setattr(cli, "previous_builds", no_history)
    cli.write_site(site, [])


def built_guide(guide: Path, *extra: str) -> None:
    for name in ("index.html", "404.html", "guide/install.html", "assets/app.js", *extra):
        (guide / name).parent.mkdir(parents=True, exist_ok=True)
        (guide / name).write_text(f"guide {name}", encoding="utf-8")


def test_the_guide_joins_the_feeds_without_replacing_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    site, guide = tmp_path / "site", tmp_path / "guide"
    feed_site(monkeypatch, site)
    assert not (site / "index.html").exists(), "The site root belongs to the user guide"
    feeds = {name: (site / name).read_bytes() for name in cli.FEED_FILES}
    built_guide(guide)
    copied = cli.combine_site(guide, site)
    assert copied == ["404.html", "assets/app.js", "guide/install.html", "index.html"]
    assert (site / "index.html").read_text(encoding="utf-8") == "guide index.html"
    assert {name: (site / name).read_bytes() for name in cli.FEED_FILES} == feeds
    assert (site / ".nojekyll").exists()


@pytest.mark.parametrize(
    "overlap",
    ["releases.json", "releases.json/nested.html", "updates/stable.xml", "updates/other.html"],
)
def test_the_guide_may_not_overlap_the_feeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, overlap: str
) -> None:
    site, guide = tmp_path / "site", tmp_path / "guide"
    feed_site(monkeypatch, site)
    feeds = {name: (site / name).read_bytes() for name in cli.FEED_FILES}
    built_guide(guide, overlap)
    with pytest.raises(ValueError, match="would replace feed site files"):
        cli.combine_site(guide, site)
    assert {name: (site / name).read_bytes() for name in cli.FEED_FILES} == feeds
    assert not (site / "index.html").exists(), "Nothing is copied when any file overlaps"


def test_offline_pages_write_empty_feeds_without_reading_github(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def no_network(*_: object, **__: object) -> object:
        raise AssertionError("offline generation must not read GitHub")

    for name in ("previous_builds", "paginated", "download"):
        monkeypatch.setattr(cli, name, no_network)
    monkeypatch.setattr(
        sys, "argv", ["github_release.py", "pages", "--offline", "--output", str(tmp_path)]
    )
    cli.main()
    assert json.loads((tmp_path / "releases.json").read_text()) == []
    for name in cli.FEED_FILES:
        assert (tmp_path / name).is_file(), name


def test_combining_requires_both_halves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    site, guide = tmp_path / "site", tmp_path / "guide"
    built_guide(guide)
    with pytest.raises(ValueError, match="feed site lacks"):
        cli.combine_site(guide, site)
    feed_site(monkeypatch, site)
    (guide / "404.html").unlink()
    with pytest.raises(ValueError, match="user guide lacks 404.html"):
        cli.combine_site(guide, site)


def test_missing_history_only_bootstraps_before_any_version_was_reserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download = Mock(return_value=None)
    monkeypatch.setattr(cli, "download", download)
    monkeypatch.setattr(cli, "paginated", Mock(return_value=[]))
    assert cli.previous_builds() == []
    assert "/releases.json?verify=" in download.call_args.args[0]
    monkeypatch.setattr(cli, "paginated", Mock(return_value=[{"name": "0.0.90"}]))
    with pytest.raises(ValueError, match="history is missing"):
        cli.previous_builds()


@pytest.mark.parametrize("missing_asset", [False, True])
@pytest.mark.parametrize(("stage", "target_kind"), STAGE_REQUESTS)
def test_publication_attaches_both_assets_to_draft_before_publishing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing_asset: bool,
    stage: str,
    target_kind: str,
) -> None:
    target = target_for(target_kind)
    candidate = stage != "stable"
    monkeypatch.setattr(
        sys,
        "argv",
        ["release", "release", "--version", version(), "--stage", stage, "--publish"]
        + ["--output", str(tmp_path)]
        + (["--target", target] if target else []),
    )
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("RELEASE_COMMIT", "a" * 40)
    monkeypatch.setattr(cli.subprocess, "check_output", Mock(return_value="a" * 40))
    monkeypatch.setattr(cli, "paginated", Mock(return_value=[]))
    monkeypatch.setattr(cli, "previous_builds", Mock(return_value=[]))
    monkeypatch.setattr(cli, "require_ci", Mock(return_value="https://example.invalid/ci/1"))
    events: list[str] = []

    def api(path: str, *, method: str = "GET", data: dict[str, object] | None = None) -> Any:
        events.append(f"{method} {path.rsplit('/', 1)[1]}")
        if method == "POST" and path.endswith("/refs"):
            assert data == {"ref": f"refs/tags/{version()}", "sha": "a" * 40}
        if method == "POST" and path.endswith("/releases"):
            assert data is not None and data["draft"] is True
            assert data["target_commitish"] == "a" * 40
            assert data["prerelease"] == candidate
            assert data["name"] == release_title(version(), stage, target)
            return {"id": 37}
        if path.endswith("/assets"):
            names = [f"sheet-manager-{version()}.oxt", f"sheet-manager-{version()}.oxt.sha256"]
            return [{"name": name} for name in (names[:1] if missing_asset else names)]
        if method == "PATCH":
            assert data == {"draft": False, "make_latest": "false" if candidate else "true"}
        return {}

    def upload(command: list[str], *, check: bool) -> None:
        assert check and command[:4] == ["gh", "release", "upload", version()]
        assert [Path(item).name for item in command[4:6]] == [
            f"sheet-manager-{version()}.oxt",
            f"sheet-manager-{version()}.oxt.sha256",
        ]
        assert "--clobber" not in command
        events.append("upload")

    monkeypatch.setattr(cli, "api", api)
    monkeypatch.setattr(cli.subprocess, "run", upload)
    if missing_asset:
        with pytest.raises(ValueError, match="exactly the OXT and its checksum"):
            cli.main()
    else:
        cli.main()
    assert events == ["POST refs", "POST releases", "upload", "GET assets"] + (
        [] if missing_asset else ["PATCH 37"]
    )
