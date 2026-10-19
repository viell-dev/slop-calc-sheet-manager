# Releasing Sheet Manager

Agents may publish prereleases, stable releases, and their user-facing release notes under the
owner's standing approval. Readiness includes the checks below and the independent review in
[AGENTS.md](AGENTS.md#review). The extensions.libreoffice.org listing is the only step that needs
the owner's sign-in; prepare the listing text, screenshots, compatibility information, and files
before asking them to sign in. Do not put that account's credentials in CI.

There is no published build yet. The `0.0.1` changelog section is an unpublished development
baseline for exercising the release dry run, not a decision to ship it. The first feature release
remains 0.1.0.

## Versions and titles

`extension/description.xml` is the only source of the extension version. Use exactly three plain
dotted numbers, without a `v` prefix, leading zeroes, suffixes, or build metadata. Every published
build must exceed every earlier build, stable or prerelease, and every reserved numeric tag.
Never replace a published file, move a tag, delete a published release, or reclassify a prerelease
as stable. Fix a bad build with a larger version.

- Stable versions use patch numbers `0` through `89`: `0.1.0`, `0.1.1`, …, `0.1.89`.
- Candidates for `X.Y.0` use the previous minor series starting at `.90`. For 0.1.0, use
  `0.0.90`, `0.0.91`, …; for 0.2.0, use `0.1.90`, `0.1.91`, …. The candidate title is
  `0.1.0 release candidate 1 (0.0.90)`, then `0.1.0 release candidate 2 (0.0.91)`.
- Candidates for a major `X.0.0` use `.90` onward in the previous major's final minor series.
  Set the workflow's optional `target` input to `X.0.0`; for example, if 0.8 is that last series,
  `0.8.90` with target `1.0.0` is `1.0.0 release candidate 1 (0.8.90)`.
- Once a series enters its candidate range, do not publish smaller patch releases in it. For
  example, after `0.1.90`, `0.1.2` is too small; continue candidates or publish `0.2.0`. If more
  stable fixes are needed before that transition, delay the candidate.

LibreOffice does not use SemVer prerelease ordering. Its
[`compareVersions` implementation in 26.8.1.1](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/desktop/source/deployment/misc/dp_version.cxx)
splits on dots, removes leading zeroes, and compares each component by length and then text.
Thus `0.0.90 < 0.0.91 < 0.1.0`, but **`0.1.0-rc.1 > 0.1.0`**. The pure comparator used by release
checks and the feed tests follows those rules, including zero and missing components. Release
validation additionally refuses all noncanonical version strings and enforces the candidate
range and stable patch limit.

## Prepare and dry-run

1. On a task branch, set the version in `extension/description.xml`. Move the changes being
   released into a nonempty `## VERSION - YYYY-MM-DD` section in `CHANGELOG.md`, retaining an
   `Unreleased` section above it. The exact section body becomes the release notes; write for
   users, without an agent callout or footer. Update compatibility and installation documentation
   if needed. Do not change the extension identifier.
2. Run `python tools/check.py` and the relevant LibreOffice integration checks described in
   [CONTRIBUTING.md](CONTRIBUTING.md). Have the candidate tested on real desktops with the batched
   checklist in [AGENTS.md](AGENTS.md#testing-with-the-owner). Complete independent review, then
   merge the preparation PR and wait for **CI** on its exact `main` commit to succeed.
3. In Actions, select **Release → Run workflow**, choose `main`, enter the exact version, select
   `prerelease` for a candidate, and leave `dry_run` checked. For a next-major candidate supply
   its `target`; next-minor candidates derive it automatically. Inspect the resulting artifact:
   the OXT, `.oxt.sha256`, `release-plan.json`, `release-notes.md`, and prospective `site/` feeds.
   Check the title, notes, download URLs, minimum LibreOffice version, and CI URL.

The dry run builds from the exact checked-out commit with `tools/build.py`, runs the full static
and unit checks, requires successful CI on that commit, validates version/metadata/changelog,
checks release history and tags, and generates prospective feeds. It creates no tag, draft,
release, or deployment. `dry_run` defaults to true.

For release-workflow development, a PR that changes `.github/workflows/release.yml` also runs
this same dry run on its head commit, using the metadata version and inferring the candidate
flag from its patch number. Its artifact is the branch dry run; it uses the PR's successful CI
run instead of `main`'s. Manual dry runs may also choose a branch after the workflow has first
landed on the default branch. All publishing jobs stay disabled outside a manual dispatch on
`main`. Normal feature PRs do not run this release readiness gate: the metadata can still name
the last published version until the next release is prepared.

## Publish

Run **Release** again on the same `main` commit with the same inputs and `dry_run` unchecked.
If `main` has advanced, dry-run that new commit first. Publication repeats validation and
requires a successful **CI** push run on that exact commit; a successful PR run is insufficient.
Only the publishing job receives `contents: write`; no stored secret is needed.

The workflow creates the numeric tag at that commit, creates a **draft** GitHub release with the
changelog section and prerelease flag, uploads the OXT and checksum, verifies both are present,
and only then publishes. This ordering supports GitHub's immutable releases. An existing tag,
published version, or draft is refused. Publication is serialized so two workflow runs cannot
reserve the same version or overtake one another.

After publication, the workflow calls **Update feeds**. Check the release's assets and checksum,
the Pages deployment, and both live feeds. Stable builds appear in both feeds. Candidates appear
only in the prerelease feed. Installed copies always point to the stable feed; installing a
candidate does not opt a user into future candidates.

If a run fails after reserving its tag, do not delete or move it and do not rerun publication for
that version. Inspect the tag's exact commit, the draft and its assets, and the successful CI run.
A maintainer may finish that same draft by uploading only missing assets, verifying their bytes
against a rebuild of the tagged commit, and publishing it. Never use `--clobber` or replace an
asset. If its content is wrong or uncertain, abandon the draft/tag and prepare a higher version.
If publication succeeded but Pages failed, rerun **Update feeds** on `main`; do not republish.

## Feed storage and safeguards

GitHub Releases are the source of truth, rather than release-bot commits to protected `main`.
**Update feeds** downloads each published release's versioned OXT and checksum, verifies them,
and reads its identifier, version, and minimum LibreOffice version from the packaged metadata.
It ignores drafts and refuses missing assets or mismatched tags/checksums. This retains each
build's actual compatibility floor even after the source metadata changes.

Both feeds are Atom documents whose entries contain descriptions in
`http://openoffice.org/extensions/update/2006`. Entries have the extension identifier, version,
`lo:LibreOffice-minimal-version`, versioned release-asset URL, and release-notes URL. All eligible
builds are retained in descending version order. LibreOffice's extension-specific lookup takes
the first matching description, so newest-first order matters. An empty feed advertises nothing
before the first release. The stable feed excludes prereleases, including from its timestamp,
so publishing a candidate does not change it.

The site also contains `releases.json`, the history used by the last deployment. Generation
compares it with the current releases and refuses removal, reclassification, changed metadata,
or a later publication with a lower version. A missing site (HTTP 404) permits the initial
bootstrap; other fetch failures stop deployment. Do not delete the Pages site or its history.
Generation and deployment share one concurrency lock, so queued runs read fresh release data.

GitHub Pages must use **GitHub Actions** as its source, with a `github-pages` environment allowing
protected branches. Pages publication runs only from `main` or a release tag, using tooling from
`main`. A push to `main`, a manual dispatch, and an hourly schedule can rebuild feeds. The release
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
performs that step inside a modal VCL dialog. Automated tests therefore cover the real feed
parser and deployment dependency checker separately. They do not claim to exercise the update
dialog, its offered-update state, download/install clicks, restart behaviour, or automatic check
scheduling. Check the Extension Manager's visible update behaviour on real desktops before the
first release.
