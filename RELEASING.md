# Releasing Sheet Manager

Agents may publish prereleases, stable releases, and their user-facing release notes under the
owner's standing approval. Readiness includes the checks below and the independent review in
[AGENTS.md](AGENTS.md#review). The extensions.libreoffice.org listing is the only step that needs
the owner's sign-in; prepare the listing text, screenshots, compatibility information, and files
before asking them to sign in. Do not put that account's credentials in CI.

The `0.0.4` test build targets the first feature release, `0.1.0`. Current published builds are
listed on [Releases and test builds](https://viell-dev.github.io/slop-calc-sheet-manager/guide/releases).
The changelog's development-history section records unpublished work before 0.0.2. Before the
first publication, let Pages deploy empty feeds before reserving a version tag.

## Versions and titles

This is a LibreOffice-compatible numeric versioning policy, **not full Semantic Versioning**.
The constraint comes from the installed extension's version comparison, not from GitHub or
extensions.libreoffice.org. GitHub can host SemVer tags, and a directory listing may contain only
stable builds, but neither changes how LibreOffice compares a manually installed test OXT with
the next stable OXT. Every published build, stable or test, gets a GitHub release with its OXT
and checksum; the extension directory is an optional discovery channel.

`extension/description.xml` is the only source of the extension version. Use exactly three plain
dotted numbers, without a `v` prefix, leading zeroes, suffixes, or build metadata. When reserving
a new version, it must exceed every published build, stable or prerelease, and every reserved
numeric tag. Completing an already-reserved draft follows the recovery procedure below.
Never replace a published file, move a tag, delete a published release, or reclassify a prerelease
as stable. Fix a bad build with a larger version.

- Stable patch numbers have no reserved range: `0.1.89`, `0.1.90`, `0.1.91` and `0.1.100` are
  all valid stable versions. The workflow's `prerelease` input and GitHub's stored flag determine
  the channel; no version digit implies test status.
- Test builds for the next minor use the next unused numeric version in the preceding series.
  For example, `0.0.2` and `0.0.3` can test `0.1.0`. Set `prerelease`; the title becomes
  `0.1.0 test build (0.0.2)`. No candidate sequence number is inferred from the patch number.
- Test builds for a major `X.0.0` use the current major's last minor series. Set the optional
  `target` input to `X.0.0`; `0.8.91` with target `1.0.0` is `1.0.0 test build (0.8.91)`.
- Every later publication, including a stable fix between test builds, takes a larger unused
  version. For example, after stable `0.1.90` and test build `0.1.91` for `0.2.0`, a stable fix
  can use `0.1.92`. The final `0.2.0` remains larger than all three. This preserves one increasing
  installed-package version across channels without putting a ceiling on stable patches.

LibreOffice does not use SemVer prerelease ordering. Its
[`compareVersions` implementation in 26.8.1.1](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/desktop/source/deployment/misc/dp_version.cxx)
splits on dots, removes leading zeroes, and compares each component by length and then text.
Thus `0.0.2 < 0.0.3 < 0.1.0`, but **`0.1.0-beta.1 > 0.1.0`** and
**`0.1.0-rc.1 > 0.1.0`**, contrary to SemVer. LibreOffice uses this comparator for
[update selection](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/desktop/source/deployment/misc/dp_update.cxx)
and [manual replacement warnings](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/desktop/source/deployment/gui/dp_gui_extensioncmdqueue.cxx).
A final release would not be offered to someone running the suffixed candidate; installing it
manually would be described as a downgrade. Removing the candidate first is possible, but is an
unnecessary obstacle in the normal test-to-stable path.

Keeping one version across the installed package, Git tag, release and asset names avoids a
separate mapping between SemVer labels and native package numbers. Stable versions use
major/minor/patch numbers, while test-build status is explicit metadata rather than a suffix or
reserved numeric range. This differs from SemVer prerelease notation and precedence. Before 1.0,
compatibility may change between feature releases.

The pure comparator used by release checks and feed tests follows LibreOffice's rules, including
zero and missing components. Release validation additionally refuses noncanonical strings and
checks test-build targets and increasing versions across both channels. Revisit this policy if
LibreOffice supports SemVer prerelease precedence.

## Prepare and dry-run

1. On a task branch, set the version in `extension/description.xml`. Move the changes being
   released into a nonempty `## VERSION - YYYY-MM-DD` section in `CHANGELOG.md`, retaining an
   `Unreleased` section above it. The exact section body becomes the release notes; write for
   users, without an agent callout or footer. Update compatibility and installation documentation
   if needed. Do not change the extension identifier. In the user guide, remove the **Unreleased**
   markers for what this release contains. For the first release, also rewrite the statements that
   no release exists, which
   `git grep -n -i -E "no (release|build|download)|published yet|until then" -- docs README.md`
   finds.
2. Run `python tools/check.py` and the relevant LibreOffice integration checks described in
   [CONTRIBUTING.md](CONTRIBUTING.md). Readiness rests on those checks and on CI; no release waits
   on a manual checklist. If an observation that no check can make matters for this release, ask
   for it as [AGENTS.md](AGENTS.md#requests-to-the-owner) describes, and say in the preparation PR
   whether it blocks the release. Complete the release review that
   [AGENTS.md](AGENTS.md#review) requires, then merge the preparation PR and wait for **CI** on its
   exact `main` commit to succeed.
3. In Actions, select **Release → Run workflow**, choose `main`, enter the exact version, select
   `prerelease` for a candidate, and leave `dry_run` checked. For a next-major candidate supply
   its `target`; next-minor candidates derive it automatically. Inspect the resulting artifact:
   the OXT, `.oxt.sha256`, `release-plan.json`, `release-notes.md`, and prospective `site/` feeds.
   Check the title, notes, download URLs, minimum LibreOffice version, and CI URL.

The dry run builds from the exact checked-out commit with `tools/build.py`, runs the full static
and unit checks, requires successful CI on that commit, validates version/metadata/changelog,
checks release history and tags, and generates prospective feeds. It creates no tag, draft,
release, or deployment. `dry_run` defaults to true.

For release-workflow development, a PR that changes `.github/workflows/release.yml`,
`.github/workflows/pages.yml`, `tools/github_release.py`, or `tools/release_data.py` also runs
the dry run on its head commit using the metadata version. The artifact contains the stable
preview and a separate `prerelease-preview/`, so both explicit channels are exercised without
inferring one from the number. It waits for the PR's successful CI run instead of `main`'s, so
this check normally finishes after CI. It waits up to 50 minutes,
covering the native matrix's 45-minute job limit plus startup time; the dry-run job allows
60 minutes for setup and asset validation as well. If that metadata version is
already published, the PR check emits a notice and skips release planning after static/unit
checks and validation of live published assets, history, and current feeds. In that case its
artifact contains only the current feed preview, with no prospective release plan. Existing
drafts and reserved tags still fail preparation; manual dispatches never skip readiness checks.
Manual dry runs may also choose a branch after the workflow has first landed on the default
branch. All publishing jobs stay disabled outside a manual dispatch on `main`. Normal feature
PRs do not run this release readiness gate: the metadata can still name the last published
version until the next release is prepared.

## Publish

Run **Release** again on the same `main` commit with the same inputs and `dry_run` unchecked.
If `main` has advanced, dry-run that new commit first. Publication repeats validation and
requires a successful **CI** push run on that exact commit; a successful PR run is insufficient.
Only the publishing job receives `contents: write`; no stored secret is needed.

The workflow creates the numeric tag at that commit, creates a **draft** GitHub release with the
changelog section and prerelease flag, uploads the OXT and checksum, verifies both are present,
and only then publishes. GitHub release immutability is disabled during early development.
Keep it disabled unless the owner directs otherwise. An existing tag,
published version, or draft is refused. Publication is serialized so two workflow runs cannot
reserve the same version or overtake one another.

After publication, the workflow calls **Pages**. Check the release's assets and checksum,
the Pages deployment, and both live feeds. Stable builds appear in both feeds. Candidates appear
only in the prerelease feed. Installed copies always point to the stable feed; installing a
candidate does not opt a user into future candidates.

If a run fails after reserving its tag, do not delete or move it and do not rerun publication for
that version. Inspect the tag's exact commit, the draft and its assets, and the successful CI run.
A maintainer may finish that same draft by uploading only missing assets, verifying their bytes
against a rebuild of the tagged commit, and publishing it. Never use `--clobber` or replace an
asset. If its content is wrong or uncertain, abandon the draft/tag and prepare a higher version.
An older stalled draft may be completed even after a higher version has been published: feeds
sort by version, so the recovered build enters history without replacing the newest offer.
If publication succeeded but Pages failed, rerun **Pages** on `main`; do not republish.

The tag/draft/upload/publish sequence has mock coverage; each actual publication still needs the
live verification above. Keep this recovery procedure open during publication. If the reserved
tag or draft content is uncertain, abandon it and use a higher version.

## Feed storage and safeguards

GitHub Releases are the source of truth, rather than release-bot commits to protected `main`.
**Pages** downloads each published release's versioned OXT and checksum, verifies them,
and reads its identifier, version, and minimum LibreOffice version from the packaged metadata.
It ignores drafts and refuses missing assets or mismatched tags/checksums. Published releases
with noncanonical version tags also stop generation; this repository reserves GitHub Releases
for extension builds, so unrelated manual releases must not silently disappear from its feeds.
This retains each build's actual compatibility floor even after the source metadata changes.

Both feeds are Atom documents whose entries contain descriptions in
`http://openoffice.org/extensions/update/2006`. Entries have the extension identifier, version,
`lo:LibreOffice-minimal-version`, versioned release-asset URL, and release-notes URL. All eligible
builds are retained in descending version order. LibreOffice's extension-specific lookup takes
the first matching description, so newest-first order matters. An empty feed advertises nothing
before the first release. The stable feed excludes prereleases, including from its timestamp,
so publishing a candidate does not change it.

The site also contains `releases.json`, the history used by the last deployment. Generation
compares it with the current releases and refuses removal, reclassification, changed metadata,
or duplicate versions. Publication timestamps need not follow version order, so finishing an
older draft cannot block future feeds. History requests bypass cached URLs. A missing site
(HTTP 404) permits bootstrap only before any numeric version tag exists; afterwards it stops
deployment so missing history cannot hide a regression. Other fetch failures also stop deployment.
Do not delete the Pages site or its history; restore the last deployed history if it goes missing.
Generation and deployment share the `update-feeds` concurrency lock, so queued runs read fresh
release data. Both the release workflow's caller job and the standalone Pages workflow hold it
across the complete build and deployment; locking deployment alone would allow stale builds.

The same deployment serves the user guide.

- **Building.** **Pages** builds the guide with VitePress from `main`. It passes the guide the
  release history it has just generated, so that the guide's notice names the latest release.
- **Combining.** Pages then copies the guide into the generated site, and refuses to replace any
  file there: the guide may not write `releases.json` or anything under `updates/`.
- **Pull requests.** CI's **Documentation** job builds and combines the guide on every pull
  request, against empty feeds generated offline (`pages --offline`), so the live release history
  cannot block an unrelated pull request. Pages checks the live history when it deploys.
- **Recording the deployment.** The notice at the top of each page, and the run's summary, name
  the commit the site was built from.
- **One workflow.** No other workflow deploys Pages, so a guide deployment and a feed update
  cannot overwrite each other.

GitHub Pages must use **GitHub Actions** as its source. Set the `github-pages` environment's custom
deployment policies to branch `main` and tags `[0-9]*`, so manual release events can deploy too.
Other branches and PR refs cannot deploy. Pages uses tooling from `main`. A push to `main`, a
manual dispatch, and a daily schedule at 03:23 UTC can rebuild the feeds and the guide. None of
these publishes a build: they only regenerate feeds from releases already published. The release
workflow calls it directly because events created with `GITHUB_TOKEN` do not trigger another
workflow's `release` event. The event trigger also handles a manually completed draft.

## Verification boundary

Unit tests check numeric ordering, the suffix trap, candidate titles, existing-version refusal,
changelog boundaries, feed XML, stable-feed immutability, empty feeds, and history regression
refusal. The normal Linux and Windows integration lanes run `test_updates.py` too: an older
installed build's identifier is used to query generated feeds served on a loopback HTTP server.
LibreOffice's `UpdateInformationProvider` returns the expected descriptions in newest-first
order; temporary candidate OXTs pass or fail LibreOffice's real `XPackage.checkDependencies`
according to their minimum-version dependency. No public network or normal profile is used.

There is no public UNO method for the Extension Manager's enabled/disabled update list. The
provider parses descriptions without evaluating dependencies; the UI's
[`prepareUpdateData`](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/desktop/source/deployment/gui/dp_gui_updatedialog.cxx)
performs that step inside a modal VCL dialog. `tests/ui/update_dialog.py` drives those real dialogs
with XTEST in the private painted Linux lab. It checks empty, same-version, older, compatible and
incompatible feeds, the disabled candidate's dependency reason, the actual OXT download and
successful installation, then restarts the same profile and verifies the new version, complete
installed payload and deck.
Screenshots, accessibility trees, HTTP requests and both office lifecycles are retained as CI
artifacts. This runs after the UI suite in every required Linux gtk3 job.

The dialog check uses **gen** because its public UNO accessibility tree exposes the deployment
dialogs; GTK's native weld manager is absent from Toolkit top windows in this lab. It invokes
the selected extension's **Check for Updates** context command, which uses the same update
queue without checking bundled extensions against external services. The fixture keeps the full
built package payload and changes only its version, minimum and loopback update URL. Production
packages retain the stable feed, checked separately by integration tests. GTK-specific dialog
presentation, Windows GUI updates, automatic scheduling, and public HTTPS/redirect behavior are
outside this loopback check. The release workflow verifies public asset checksums and packaged
metadata; the live LibreOffice provider and installation of downloaded public bytes need the
separate post-publication checks.
[Issue #57](https://github.com/viell-dev/slop-calc-sheet-manager/issues/57) records this boundary.
