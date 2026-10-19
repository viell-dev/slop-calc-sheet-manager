# Agent maintenance

Sheet Manager is built, tested, documented, released, and maintained by AI agents. They follow the
owner's general rules for agent-maintained projects, which cover who decides what, how issues and
pull requests are written, verification, parallel work, attribution, and reports to other
projects. This file adds only what is specific to Sheet Manager. [CONTRIBUTING.md](CONTRIBUTING.md)
holds the setup, checks, and pull request rules that apply to everyone; follow it and do not repeat
it here.

## Testing with the owner

The owner uses the extension; their observations on a real desktop are evidence that automated
tests cannot produce, so the extension's look and feel in use is theirs to judge.

- Owner testing is batched into one checklist per release candidate, built from the repository's
  manual tests. Each test request names the build to install, gives numbered steps with the
  expected outcome of each, and asks for the operating system, the LibreOffice version, the user
  interface shown in Help ▸ About, and a screenshot where looks matter.
- Each checklist ships with a synthetic test workbook, and screenshots for public issues are taken
  with it, so that no real sheet names appear in public. Performance on the owner's own workbooks
  is reported as timings only.

## Safety invariants

The extension changes the user's documents. Every change keeps these, and tests enforce them
where they can:

1. Each document change the extension makes itself is exactly one undo step, and undo restores the
   previous state completely. Before acting, the extension checks that the change can be undone;
   when an action fails partway, it undoes what was done, verifies the result, and tells the user
   if that did not work. Built-in commands started from the extension's menu keep LibreOffice's
   own undo behaviour.
2. The extension changes only the sheet structure the user asked to change. It never saves,
   closes, or reloads a document, and never changes cell content.
3. Destructive actions ask for confirmation as the built-in commands do, or run those commands.
4. Where an action is not allowed (protected structure, read-only document, recorded changes, the
   last visible sheet), its control is disabled, with the reason available, rather than failing
   halfway.
5. The extension never acts on stale state: before an operation, it checks that the sheets it
   targets are still the ones the user saw, and it never runs a command on a different set of
   sheets than the user picked.
6. The extension does not change the user's active sheet or sheet selection unexpectedly.

## Review

- Every pull request that can change what ships is reviewed by an agent from a different model
  provider than the one that wrote it, because a different provider makes different mistakes.
  Reviewers report findings and do not push to the branch.
- The author fixes or answers each finding. A material finding is closed only when the reviewer
  accepts the fix or the answer in a further round. The review names the commit it covered; a
  behaviour-changing commit pushed after it needs another round.
- Only wording and typo fixes in documentation, and comments, may skip independent review.
  Dependency updates, workflows, release steps, compatibility metadata such as the minimum
  LibreOffice version, and any change that loosens these rules are always reviewed.
- Every pull request has a "Verification" section listing the commands run, the inputs tried
  beyond the tests, and what was checked on which platform and LibreOffice version.

## Issues and labels

Labels follow [`.github/labels.json`](.github/labels.json); keep GitHub in sync with it. Every
item has one `Type:` label and at most one `Status:` label for its current disposition. Retitle an
issue so that it names the confirmed problem or the accepted request, close a declined or duplicate
one as not planned, and close an accepted one through the pull request that fixes it.

- `Status: Needs Owner Testing` marks work that waits for a check on a real desktop.
- `Status: Blocked` marks accepted work that waits on an identified external dependency.

## Defects in LibreOffice

LibreOffice is the extension's only upstream, and the owner has decided that no reports go to it.
A defect in LibreOffice that affects Sheet Manager gets an issue here holding the versions, the
reproduction, the result, and how Sheet Manager works around the defect or documents the limit.
Once the workaround or the documented limit is in place, the issue is closed as not planned with
`Status: Won't Do`; it remains the record for later agents. Reopen it when a LibreOffice release
fixes the defect, so that the workaround can be narrowed or dropped for fixed versions, or when
the workaround falls short. There is no pinned overview of these defects; search the closed issues
labelled `Status: Won't Do`.

## Git and merging

- Pull requests merge with a merge commit after checking the exact head
  (`gh pr merge --merge --match-head-commit SHA --body "Assisted-by: <model> via <harness>"`).
  Squash and rebase merges are disabled so that each commit keeps its own attribution trailer and
  the history of reviewed rounds survives.
- Pull requests need not be up to date with `main` before merging, so that they do not wait for one
  another; CI runs again on `main` after every merge, and a failure there is fixed forward first.
  GitHub offers no merge queue for this repository's owner account.

## Technical map

- `reorder.py` is the UNO-free target/minimum-call planner; `uno_reorder.py` captures snapshots,
  checks permissions and stale handles, applies one undo group, and verifies recovery. The panel
  contract is [docs/reordering.md](docs/reordering.md). Keep the panel busy and defer refresh during
  application: consecutive individual scenario moves have intermediate block splits. Never pass
  an interior scenario gap through as a raw move destination or use native multi-sheet Move.
  Retain balanced nested undo groups: Calc limits the current context to configured undo Steps,
  so a flat group silently loses early moves above that capacity
  ([#16](https://github.com/viell-dev/slop-calc-sheet-manager/issues/16)). Tests cover capacity two.
- `tests/integration/test_reorder.py` uses test-only forwarding adapters to fail after actual UNO
  mutations; no injection seam ships. Its populated synthetic workbooks exercise formulas,
  named ranges, and charts at 200/1,000 sheets and emit median complete-move/undo timings.
  `generate_workbooks.py` retains copies for inspection using the same synthetic generator.
- `src/sheet_manager/` ships under `pythonpath/sheet_manager/`. Keep pure logic importable without
  `uno`; `uno_panel.py` owns the UNO factory and panel. Integration tests use the public
  `XPanel.getDialog()` window and observe disposal with its `XEventListener`; keep test hooks out
  of the production factory.
- `extension/description.xml` is the version source. `extension/sheet-manager.components` and
  `registration.py` provide passive Python registration. `Factories.xcu` maps tool-panel URLs to
  that factory; `Sidebar.xcu` registers the Calc-only deck and panel. `tools/build.py` explicitly
  allowlists every packaged file and includes the root licence as `LICENSE.txt`.
- Python UI strings go through `sheet_manager.i18n.tr`. Metadata templates use `{{message}}`,
  rendered as English through that helper at build time. This renderer supports only English;
  adding the first translation catalogue must also replace it with locale-aware XML/XCU element
  generation and per-locale description files. Keep English as the fallback.
- The panel uses a `"tabcontrol"` peer. A plain `"window"` does not consume mouse-down events,
  which lets VCL interpret clicks as the start of sidebar undocking. Retain the tab-control
  interface assertion when adding controls, and keep the panel filling its container on resize.
  The tab control sits inside a plain `"window"` of the same size: on every Shift, Ctrl, or Alt
  change, VCL's access-key walk enters each tab control's current page and crashes on a tab
  control without pages (#18), but it does not descend into plain windows. Keep any page-less tab
  control out of that walk, and keep the painted modifier-key test.
- `tests/integration/run.py` runs with the tested office's bundled Python, installs into a new
  temporary profile, starts only its own process with a unique pipe, and disposes it afterwards.
  Open documents visibly even in headless runs: hidden documents do not reliably execute Calc
  commands or undo. Startup retries end before document creation and never retry failed tests.
  `--sessions headless|gtk3|both` selects sessions; default headless. Add real-input UI tests to
  the painted path in `exercise()` (`screenshot=True`), so they join the separate `linux-gtk3`
  jobs without requiring a display in headless jobs. Keep shared lifecycle changes additive.
- `ci/libreoffice.json`, `ci/Dockerfile`, and `tools/linux_integration.py` define the same Linux
  lab for CI and local tests. Headless checks use svp; screenshot checks use gtk3 under Xvfb.
  Never mount host display sockets or use an existing office profile. The Windows MSI installer
  helper is only for disposable CI runners; use the existing installation on developer machines.
  `Linux (LibreOffice …)` jobs run the headless checks and `Linux gtk3 (LibreOffice …)` jobs the
  painted ones; both are required. The painted jobs were not required from #10 until #32, while
  their intermittent abort (#8) was investigated: LibreOffice crashed when a test closed Writer
  within milliseconds of opening it (#30). Close test documents in painted sessions only after
  they have settled, as `close_writer()` does. A red painted job blocks merging like any other;
  never rerun it until it is green without classifying the failure from its artifacts. The
  generic fatal message alone is not proof of #8 and is never allowed in the runner.
  `gtk3-soak.yml` and `tests/integration/soak.py` repeat fresh painted sessions in installed and
  absent modes; dispatch the workflow on a branch to measure the reliability of painted sessions.
  `--backtrace` uses LibreOffice's gdb wrapper; validate its trace as well as the wrapper status.
  That wrapper bypasses the normal launcher's exit-81 bootstrap restart. The runner handles it
  once, only before connecting UNO, and preserves the initialization trace; never extend this
  startup handling into retrying test assertions or shutdown failures.
- `.github/rulesets/main.json` records the main ruleset with the CI job names to require after
  this workflow is merged. `release-tags.json` records immutable version tags. These are API
  request bodies captured from rulesets 25349507 and 25349508; recording them does not apply them.
  Keep required contexts identical to the workflow's job names and strict up-to-date policy off.

## Releases

- The owner has given standing approval for agents to publish releases, prereleases and stable
  versions alike, with their release notes, whenever the agents judge a build ready. Only the
  listing on extensions.libreoffice.org needs the owner's sign-in.
- Version numbers are plain dotted numbers without a `v` prefix, strictly increasing across every
  published build. There are no `-rc` suffixes, because LibreOffice's update check ranks
  `0.1.0-rc.1` above `0.1.0`. Whether a build is a prerelease or stable is a property of its GitHub
  release and of the update feed it appears in.
- Published files and tags are never replaced, and update feeds never move backwards: a bad release
  is fixed by a newer version.

## Repository boundary

Everything the project needs lives in this repository. Never stage, copy, quote, or publish
content from outside it. Tests, issues, and pull requests use synthetic workbooks only, and logs
and screenshots must not contain private documents or credentials.
