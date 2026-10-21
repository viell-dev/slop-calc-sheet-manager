"""Test release orchestration without a token, network, or GitHub writes."""

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from tools import github_release as cli
from tools.build import build, version
from tools.release_data import PublishedBuild, version_parts


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


def test_dry_run_builds_assets_and_prospective_feeds_without_api_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["release", "release", "--version", version(), "--output", str(tmp_path)]
    )
    monkeypatch.setenv("RELEASE_COMMIT", "a" * 40)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    if version_parts(version())[2] >= 90:
        sys.argv.append("--prerelease")
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
    plan = json.loads((tmp_path / "release-plan.json").read_text())
    assert plan["release"]["target_commitish"] == "a" * 40
    assert plan["release"]["draft"] is True
    assert plan["release"]["body"] == (tmp_path / "release-notes.md").read_text()
    assert (tmp_path / "site/updates/stable.xml").exists()
    assert (tmp_path / "site/updates/prerelease.xml").exists()


def test_existing_draft_and_mismatched_metadata_stop_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli, "paginated", Mock(return_value=[{"tag_name": version(), "draft": True}])
    )
    with pytest.raises(ValueError, match="draft already exists"):
        cli.prepare(version(), version_parts(version())[2] >= 90, "", tmp_path)
    with pytest.raises(ValueError, match="description.xml contains"):
        cli.prepare("999.0.0", False, "", tmp_path)
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
        sys, "argv", ["release", "release", "--version", version(), "--output", str(tmp_path)]
    )
    if version_parts(version())[2] >= 90:
        sys.argv.append("--prerelease")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("RELEASE_COMMIT", "a" * 40)
    monkeypatch.setattr(cli.subprocess, "check_output", Mock(return_value="a" * 40))
    monkeypatch.setattr(
        cli, "paginated", Mock(return_value=[{"tag_name": version(), "draft": draft}])
    )
    builds = [
        PublishedBuild(
            version(), version_parts(version())[2] >= 90, "26.2.1", "2026-10-19T00:00:00Z"
        )
    ]
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
    monkeypatch.setattr(sys, "argv", ["release", "release", "--version", version(), "--publish"])
    for event, ref in (
        ("pull_request", "refs/heads/main"),
        ("workflow_dispatch", "refs/heads/task"),
    ):
        monkeypatch.setenv("GITHUB_REF", ref)
        monkeypatch.setenv("GITHUB_EVENT_NAME", event)
        with pytest.raises(ValueError, match="only by workflow_dispatch on main"):
            cli.main()


def test_published_metadata_comes_from_checksummed_oxt_and_drafts_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
        "prerelease": version_parts(version())[2] >= 90,
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


@pytest.mark.parametrize("overlap", ["releases.json", "updates/stable.xml", "updates/other.html"])
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
def test_publication_attaches_both_assets_to_draft_before_publishing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing_asset: bool,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["release", "release", "--version", version(), "--publish", "--output", str(tmp_path)],
    )
    candidate = version_parts(version())[2] >= 90
    if candidate:
        sys.argv.append("--prerelease")
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
