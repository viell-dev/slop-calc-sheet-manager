"""Validate, build, and optionally publish one GitHub release."""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.build import build  # noqa: E402
from tools.release_data import (  # noqa: E402
    REPOSITORY,
    SITE,
    VERSION,
    PublishedBuild,
    changelog_section,
    check_new_version,
    feed,
    package_metadata,
    release_title,
    validate_history,
)


def api(path: str, *, method: str = "GET", data: dict[str, object] | None = None) -> Any:
    command = ["gh", "api", path, "--method", method]
    if data is not None:
        command.extend(["--input", "-"])
    result = subprocess.run(
        command,
        input=json.dumps(data) if data is not None else None,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def paginated(path: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["gh", "api", path, "--paginate", "--slurp"],
        text=True,
        capture_output=True,
        check=True,
    )
    pages = cast(list[list[dict[str, Any]]], json.loads(result.stdout))
    return [item for page in pages for item in page]


def download(url: str, *, missing_ok: bool = False) -> bytes | None:
    # No credentials are sent to asset redirects or the public Pages site.
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise


def published_builds(releases: list[dict[str, Any]]) -> list[PublishedBuild]:
    builds: list[PublishedBuild] = []
    for release in releases:
        if release["draft"]:
            continue
        version = cast(str, release["tag_name"])
        prerelease = cast(bool, release["prerelease"])
        release_title(version, prerelease)
        name = f"sheet-manager-{version}.oxt"
        assets = {asset["name"]: asset for asset in release["assets"]}
        base = f"https://github.com/{REPOSITORY}/releases/download/{version}/"
        for filename in (name, name + ".sha256"):
            if (
                filename not in assets
                or assets[filename]["browser_download_url"] != base + filename
            ):
                raise ValueError(f"Release {version} is missing its versioned asset {filename}")
        package = download(base + name)
        checksum = download(base + name + ".sha256")
        assert package is not None and checksum is not None
        if checksum.decode("ascii") != f"{hashlib.sha256(package).hexdigest()}  {name}\n":
            raise ValueError(f"Release {version} checksum does not match")
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            packaged_version, minimum = package_metadata(archive.read("description.xml"))
        if packaged_version != version:
            raise ValueError(f"Release tag {version} disagrees with packaged version")
        builds.append(PublishedBuild(version, prerelease, minimum, release["published_at"]))
    return builds


def previous_builds() -> list[PublishedBuild]:
    # Bypass cached history when checking a deployment against its predecessor.
    content = download(f"{SITE}/releases.json?verify={time.time_ns()}", missing_ok=True)
    if content is None:
        tags = paginated(f"repos/{REPOSITORY}/tags?per_page=100")
        if any(re.fullmatch(VERSION, item["name"]) for item in tags):
            raise ValueError("Feed history is missing after a version tag was reserved; restore it")
        return []
    records = cast(list[dict[str, Any]], json.loads(content))
    return [PublishedBuild(**record) for record in records]


def write_site(output: Path, builds: list[PublishedBuild], *, check_history: bool = True) -> None:
    """Write the feeds and release history; refuse a history that drops or changes a build.

    Only `pages --offline` skips the check, to give pull request builds a feed site without
    depending on live release data; it writes empty feeds and is never deployed.
    """
    if check_history:
        validate_history(builds, previous_builds())
    updates = output / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    for stable in (True, False):
        (updates / ("stable.xml" if stable else "prerelease.xml")).write_bytes(
            feed(builds, stable=stable)
        )
    (output / "releases.json").write_text(
        json.dumps([asdict(item) for item in builds], indent=2) + "\n", encoding="utf-8"
    )
    # The site's root belongs to the user guide; see combine_site. Download links for people go
    # to the guide's releases page, whose tables use this same verified history as the guide's
    # version notice, not to the XML feeds.
    (updates / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<title>Sheet Manager updates</title><h1>Sheet Manager updates</h1>"
        '<p><a href="../guide/releases.html">Download stable and test builds</a></p>'
        '<p>Machine-readable XML: <a href="stable.xml">Stable feed</a> · '
        '<a href="prerelease.xml">All published builds</a></p>'
        f'<p><a href="https://github.com/{REPOSITORY}/releases">Downloads and release notes</a></p>'
        '<p><a href="../">User guide</a></p>'
        "</html>\n",
        encoding="utf-8",
    )
    (output / ".nojekyll").touch()


FEED_FILES = ("updates/stable.xml", "updates/prerelease.xml", "updates/index.html", "releases.json")
GUIDE_FILES = ("index.html", "404.html")


def combine_site(guide: Path, site: Path) -> list[str]:
    """Copy the built user guide into the generated feed site, refusing to replace any file.

    Both share one GitHub Pages deployment. A guide file at a feed path would replace an update
    feed or the release history, so any overlap stops the build. Return the copied paths.
    """
    for name in FEED_FILES:
        if not (site / name).is_file():
            raise ValueError(f"The feed site lacks {name}")
    for name in GUIDE_FILES:
        if not (guide / name).is_file():
            raise ValueError(f"The user guide lacks {name}")
    files = sorted(path for path in guide.rglob("*") if path.is_file())
    relative = [path.relative_to(guide).as_posix() for path in files]
    reserved = {name.split("/")[0] for name in FEED_FILES} | {".nojekyll"}
    overlaps = [
        name for name in relative if name.split("/")[0] in reserved or (site / name).exists()
    ]
    if overlaps:
        raise ValueError(f"The user guide would replace feed site files: {overlaps}")
    for source, name in zip(files, relative, strict=True):
        target = site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return relative


def require_ci(commit: str, *, publishing: bool, timeout: float = 3000) -> str:
    # Native CI jobs allow 45 minutes; include a small queue/startup margin.
    deadline = time.monotonic() + timeout
    while True:
        response = api(
            f"repos/{REPOSITORY}/actions/workflows/ci.yml/runs?head_sha={commit}&per_page=100"
        )
        runs = [
            run
            for run in response["workflow_runs"]
            if run["event"] == ("push" if publishing else "pull_request")
            and (not publishing or run["head_branch"] == "main")
        ]
        # A dispatch dry run on main uses the same push CI gate as publication.
        if not runs and not publishing:
            runs = [run for run in response["workflow_runs"] if run["event"] == "push"]
        if runs:
            latest = runs[0]
            if latest["status"] == "completed":
                if latest["conclusion"] != "success":
                    raise ValueError(f"CI did not pass for {commit}: {latest['html_url']}")
                return cast(str, latest["html_url"])
        if time.monotonic() >= deadline:
            raise ValueError(f"No successful completed CI run for exact commit {commit}")
        print(f"Waiting for CI on {commit}", flush=True)
        time.sleep(15)


def prepare(
    version: str, prerelease: bool, target: str, output: Path
) -> tuple[dict[str, object], list[PublishedBuild]]:
    title = release_title(version, prerelease, target)
    actual, minimum = package_metadata((ROOT / "extension/description.xml").read_bytes())
    if actual != version:
        raise ValueError(f"Requested {version}, but description.xml contains {actual}")
    notes = changelog_section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    releases = paginated(f"repos/{REPOSITORY}/releases?per_page=100")
    if any(item["tag_name"] == version for item in releases):
        raise ValueError(f"Release or draft already exists for {version}")
    tags = paginated(f"repos/{REPOSITORY}/tags?per_page=100")
    builds = published_builds(releases)
    validate_history(builds, previous_builds())
    check_new_version(version, builds, [item["name"] for item in tags])
    package = build(output)
    with zipfile.ZipFile(package) as archive:
        if package_metadata(archive.read("description.xml")) != (version, minimum):
            raise ValueError("Built metadata disagrees with release request")
    (output / "release-notes.md").write_text(notes, encoding="utf-8")
    plan: dict[str, object] = {
        "tag_name": version,
        "name": title,
        "body": notes,
        "draft": True,
        "prerelease": prerelease,
    }
    return plan, builds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["release", "pages", "combine"])
    parser.add_argument("--guide", type=Path, help="combine: the built user guide")
    parser.add_argument(
        "--offline", action="store_true", help="pages: write empty feeds without reading GitHub"
    )
    parser.add_argument("--version")
    parser.add_argument("--prerelease", action="store_true")
    parser.add_argument("--target", default="")
    parser.add_argument("--publish", action="store_true", help="Default is a read-only dry run")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release")
    args = parser.parse_args()
    if args.offline and args.command != "pages":
        parser.error("--offline applies only to pages")
    if args.command == "pages":
        if args.offline:
            write_site(args.output, [], check_history=False)
            return
        write_site(
            args.output, published_builds(paginated(f"repos/{REPOSITORY}/releases?per_page=100"))
        )
        return
    if args.command == "combine":
        if args.guide is None:
            parser.error("combine requires --guide")
        copied = combine_site(args.guide, args.output)
        print(f"Combined {len(copied)} user guide files with the update feeds in {args.output}")
        return
    if not args.version:
        parser.error("release requires --version")
    if args.publish and (
        os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
    ):
        raise ValueError("Publication is allowed only by workflow_dispatch on main")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if commit != os.environ.get("RELEASE_COMMIT"):
        raise ValueError("Checkout does not match the exact requested release commit")
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        releases = paginated(f"repos/{REPOSITORY}/releases?per_page=100")
        if any(item["tag_name"] == args.version and not item["draft"] for item in releases):
            # Workflow/tooling PRs commonly retain the last published metadata version.
            # Still exercise the live assets and deployed-history safeguards, without
            # pretending to prepare that version again or weakening dispatch validation.
            write_site(args.output / "site", published_builds(releases))
            print(
                f"::notice::Version {args.version} is already published; release planning "
                "skipped for this PR. Current published feeds validated without deployment."
            )
            return
    plan, builds = prepare(args.version, args.prerelease, args.target, args.output)
    ci_url = require_ci(commit, publishing=args.publish)
    plan["target_commitish"] = commit
    (args.output / "release-plan.json").write_text(
        json.dumps({"release": plan, "ci": ci_url}, indent=2) + "\n", encoding="utf-8"
    )
    # Exercise prospective feeds too, without changing the deployed site.
    _, minimum = package_metadata((ROOT / "extension/description.xml").read_bytes())
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_site(
        args.output / "site",
        [*builds, PublishedBuild(args.version, args.prerelease, minimum, timestamp)],
    )
    if not args.publish:
        print(f"Dry run passed for {commit}; no tag, draft, release, or deployment created")
        return
    # Recheck state immediately before the first write. The workflow serializes publishers.
    current_releases = paginated(f"repos/{REPOSITORY}/releases?per_page=100")
    current_tags = paginated(f"repos/{REPOSITORY}/tags?per_page=100")
    check_new_version(
        args.version,
        published_builds(current_releases),
        [item["name"] for item in current_tags] + [item["tag_name"] for item in current_releases],
    )
    api(
        f"repos/{REPOSITORY}/git/refs",
        method="POST",
        data={"ref": f"refs/tags/{args.version}", "sha": commit},
    )
    release = api(f"repos/{REPOSITORY}/releases", method="POST", data=plan)
    package = args.output / f"sheet-manager-{args.version}.oxt"
    subprocess.run(
        [
            "gh",
            "release",
            "upload",
            args.version,
            str(package),
            str(package.with_suffix(".oxt.sha256")),
            "--repo",
            REPOSITORY,
        ],
        check=True,
    )
    assets = api(f"repos/{REPOSITORY}/releases/{release['id']}/assets")
    if {item["name"] for item in assets} != {package.name, package.name + ".sha256"}:
        raise ValueError("Draft must contain exactly the OXT and its checksum before publication")
    api(
        f"repos/{REPOSITORY}/releases/{release['id']}",
        method="PATCH",
        data={"draft": False, "make_latest": "false" if args.prerelease else "true"},
    )
    print(f"Published {args.version} from {commit}; CI: {ci_url}")


if __name__ == "__main__":
    main()
