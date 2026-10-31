# Agent maintenance

Sheet Manager is built, tested, documented, released, and maintained by AI agents. This file holds
the rules agents follow in this repository. [CONTRIBUTING.md](CONTRIBUTING.md) holds the setup,
checks, and pull request rules that apply to everyone; follow it and do not repeat it here.

## Who decides

- The owner decides what is worked on and any change of direction or scope, and performs the steps
  that need their identity, sign-in, or second factor, such as the extensions.libreoffice.org
  listing.
- Agents decide everything else: architecture, design, implementation, tooling, dependencies,
  supported versions, and repository settings such as rulesets, labels, environments, and Actions
  permissions. The agent assigned to a task makes the decisions the task needs, including questions
  an issue leaves open, and records each choice, its reasoning, and the rejected alternatives in the
  issue or pull request. Design questions are not put to the owner, and a setting is never changed
  just to get a failing change merged.
- Agents carry assigned work through to the end: reproduction, implementation, tests,
  documentation, review, merge, and any release the release rules call for. Unfinished work and its
  dependencies are recorded in issues; the issue, not an agent's session, is the record of
  progress.
- The owner is not the project's code reviewer or release engineer, and is not assumed to
  have read its code, issues, or documentation. Their reports from using the extension, directly or
  through other agents, are consumer reports: reproduce and investigate them without asking the
  reporter to diagnose the implementation.

## Requests to the owner

Agents own functional verification and prepare focused human usability tests under
[RELEASING.md](RELEASING.md#human-release-testing). Human testing is mandatory before the first
stable release and after substantial interface or workflow changes. Other owner requests cover
direction, scope, account access, or personal observations. Repeated mechanical checks are
maintenance gaps; required human judgement is a separate kind of evidence.

- Put the request in a self-contained issue, or reuse the issue that already owns the question.
  Assign it to the owner and label it `Needs: Owner`. Use `Needs: Human` instead when another
  suitable person could supply what is needed. Assign the person being asked under either label,
  including the owner when asking them to test. Label work that waits for the answer
  `Status: Blocked` and link it; optional feedback blocks nothing.
- State exactly what is needed, why an agent cannot provide it, the recommendation or the choices,
  the expected result, and which work waits. A request for an observation names the build, supplies
  a synthetic workbook, and gives numbered steps with the expected outcome of each. It asks for the
  operating system, the LibreOffice version, and the user interface shown in Help ▸ About, and for
  a screenshot where looks matter. It must be answerable on GitHub alone.
- Screenshots for public issues are taken with synthetic workbooks, so that no real sheet names
  appear in public. Performance on the owner's own workbooks is reported as timings only.
- On an answer, act on it and update the assignment, labels, and linked blockers. Check open
  requests whenever maintenance resumes.
- Before ending a thread with a human request, verify its live assignee and labels and link it
  prominently with the pending action and release impact. Candidate publication or a preparation
  merge does not complete the request. Keep it open until the answer and resulting work are handled.

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

## Verification

- [docs/verification.md](docs/verification.md) maps each promise to the checks that show it, where
  they run, their limits, and the checks shown to fail when deliberately broken. Change it in the
  same pull request as a promise or a check.
- Before implementing an issue, reproduce or measure its claim on `main` and record, with the
  evidence, whether it is accepted, narrowed, or declined. Reports from agents get the same
  scrutiny as any other.
- Every change gets relevant tests. A reproduced defect gets a regression check at the layer that
  exposes it: unit tests for pure logic, integration tests against a real LibreOffice for UNO
  behaviour, and painted sessions for anything that depends on drawing or real input. A mock is
  not evidence of LibreOffice's behaviour.
- Where practical, show that a deliberately broken critical behaviour fails its check, and say so
  in the pull request.
- A failed or intermittent check is classified from its artifacts and then fixed in the extension
  or the test harness. Never rerun a job until it is green, widen a limit without understanding the
  failure, or let a skipped test, a swallowed failure, or a crashed office pass as success.
- Release readiness requires this automated evidence and the human usability gate in
  [RELEASING.md](RELEASING.md#human-release-testing). The release PR links the human report,
  coverage, remaining limits, and open-defect dispositions. Missing required human coverage or
  unresolved release blockers prevent stable publication even when CI passes.

## Review

Every pull request gets its author's review of the complete diff after the checks pass, trying
inputs the tests do not cover. The author decides whether a separate reviewer is also needed,
weighing sensitivity, complexity, impact, and uncertainty, and records the choice in the
"Verification" section. A small diff can still be high risk. For a pull request opened by a bot,
such as Dependabot, the agent that merges it does the author review.

- **When to use independent review.** The maintainer decides whether another agent's perspective
  would materially improve confidence, considering complexity, sensitivity, impact, and uncertainty.
  Sheet identity, undo and recovery, native dispatch, and release authority deserve particular
  attention because a mistake can change documents or published artifacts. They do not create a
  blanket review gate for every change in those areas. Record the choice and its reason.
- **Every release pull request gets independent review** of all changes since the previous release,
  unresolved defects, verification evidence, compatibility, packaging, documentation, installation,
  and updates. For the first release, review the complete maintained implementation.
- **Who reviews.** An independent reviewer is a separate agent with fresh context, not the
  author's second pass. Use the same or another model with strong reasoning suited to the work.
  Prefer a different model provider for release pull requests and particularly sensitive or
  complex changes, when one is available.
- **Rounds.** Reviewers report findings and do not push to the branch. The review names the commit
  it covered. The author fixes or answers each finding and decides whether the remaining uncertainty
  warrants a focused follow-up. Do not restart broad review rounds for straightforward fixes or
  unrelated suggestions.
- **Review apps** supplement this process; their quotas do not decide whether a change has been
  verified enough.
- Every pull request has a "Verification" section listing the commands run, the inputs tried beyond
  the tests, what was checked on which platform and LibreOffice version, and the review choice.

## Issues and labels

Labels follow [`.github/labels.json`](.github/labels.json), which copies the owner's common catalog
for agent-maintained projects. A project-specific label, added only for a distinction the catalog
lacks, goes after the catalog's entries in the file and uses one of its prefixes.
`python tools/labels.py check` compares GitHub's labels with the file. After a change to the file
reaches `main`, relabel the items of any label it removes or renames, then run
`python tools/labels.py sync`. Rename a label on GitHub, rather than deleting and recreating it,
when its items should keep it.

- Every issue and pull request has one `Type:` label.
  - `Type: Enhancement` improves an existing capability, including its usability or performance.
  - `Type: Feature Request` adds a new, independently useful capability.
- Every issue and pull request has at most one `Status:` label, for its current disposition.
  `Needs: Owner` or `Needs: Human` names who must act, and can accompany `Status: Blocked`.
- Retitle an issue so that it names the confirmed problem or the accepted request. Close a declined
  or duplicate one as not planned, and close an accepted one through the pull request that fixes
  it.
- Record every defect or limit found during assigned work in an issue, reusing an existing one when
  appropriate, and link it from the pull request.

## Defects in LibreOffice

LibreOffice is the extension's only runtime upstream. The owner has decided that agents submit no
bug reports or patches to LibreOffice: reporting there is not a route this project uses, so every
defect is handled here, with a workaround or a documented limit. Do not ask the owner to
reconsider. The owner may report a defect themselves, in their own words.

- **The overview.** The pinned issue
  [#33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33) lists every LibreOffice or
  other dependency defect that affects Sheet Manager, in one of four states:
  - **Blocked upstream:** no local remedy; the affected behaviour waits for LibreOffice.
  - **Worked around:** a verified local workaround handles it; the overview records its limits and
    when it can be removed.
  - **Resolved upstream:** a fix is verified in a named LibreOffice release, and the overview
    tracks what remains here, such as adoption or removing a workaround.
  - **Upstream route unavailable:** used only for defects in a dependency other than LibreOffice
    whose project is unresponsive, declines the relevant collaboration, or prohibits the proposed
    contribution. Defects in LibreOffice itself use the first three states, since reports there are
    ruled out for every defect.

  The overview also records the user-visible limits and any release impact.
- **One issue per defect,** labelled `Status: Blocked`. It records the affected versions, the
  impact, a reproduction, the local handling, and what would reopen work. An issue for actionable
  local work around a defect, such as reducing a workaround's cost, stays open with its own
  status and is linked from the overview.
- **Parked issues.** When no local work remains, close the issue as not planned and keep
  `Status: Blocked`: it is parked, not fixed or declined.
- **Reopening.** Reopen the issue when a LibreOffice release fixes the defect, so that the
  workaround can be narrowed or dropped for fixed versions, or when the workaround falls short.
  Close it as completed only after verifying the local result.
- **Checking new releases.** During maintenance, and before each release, check new LibreOffice
  releases against the overview. Log each check, and each change of state, in the overview.
- **Other dependencies.** Before reporting a defect to any other dependency's project, read its
  contribution guide, code of conduct, templates, and AI policy, and record in the overview what
  they permit, with the evidence. Disclose that an agent wrote the report.
  - **A prohibition settles the route.** Handle the defect here, and do not ask the owner to
    overrule the prohibition or to set up an account for it.
  - **Access needs acceptance first.** Establish that the intended agent-written contribution is
    acceptable before asking the owner for any account, tracker access, or credentials.
  - **Unknown acceptance.** Where the project's acceptance of agent-written reports is unknown,
    send one initial report and invite its maintainers to say if they want no further agent
    reports. Send more only after a maintainer's response establishes acceptance. Silence,
    automated replies, and the absence of a ban do not establish it.
  - **Code.** Offer code only once code contributions are shown to be welcome, and stop when asked.

## Public surfaces and documentation

- **Sources of facts.** Each fact has one source, and every surface that repeats it must agree with
  that source:
  - `extension/description.xml`: the identifier, the version, the minimum LibreOffice version,
    and the update feed;
  - `ci/libreoffice.json`: the tested LibreOffice builds;
  - GitHub Releases, and the feeds and `releases.json` that Pages generates from them: what is
    published;
  - the README's Status section: what exists and what is planned.

  The surfaces that repeat these facts are:
  - the README;
  - the user guide in `docs/`;
  - SECURITY.md;
  - CHANGELOG.md;
  - the release notes;
  - the repository's About text, homepage, and topics on GitHub.
- **One delivery.** Update every affected surface in the same pull request.
  `tests/unit/test_consistency.py` compares what can be compared mechanically. Prose is reviewed
  for meaning. After a change that affects the About text or the homepage, read the live settings
  and correct them.
- **Which version the guide describes** follows
  [About this site](docs/development/index.md#which-version-it-describes): the latest stable
  release, the newest test build while only prereleases exist, or the development version before
  any release, with **Unreleased** markers for what that baseline lacks. Never infer publication
  from the source manifest, changelog, tag, or draft. Corrections to the guide are ordinary pull
  requests that deploy on merge without a software release. CI's **Documentation** job builds the
  guide, with its exactly pinned VitePress 2 prerelease, on every pull request; `pages.yml` alone
  deploys it, together with the feeds, and refuses guide files that would replace a feed or the
  release history.
- **Guide pages.** Keep every guide page in the sidebar. A new page that users need belongs in the
  Guide section. Developer reference goes in the Development section.

## Git and merging

- Pull requests merge with a merge commit after checking the exact head
  (`gh pr merge --merge --match-head-commit SHA --body "Assisted-by: <model> via <harness>"`).
  Squash and rebase merges are disabled so that each commit keeps its own attribution trailer and
  the history of reviewed rounds survives.
- Pull requests need not be up to date with `main` before merging, so that they do not wait for one
  another; CI runs again on `main` after every merge, and a failure there is fixed forward first.
  GitHub offers no merge queue for this repository's owner account.
- `.github/rulesets/main.json` and `release-tags.json` are the API request bodies of rulesets
  25349507 (`main`) and 25349508 (immutable version tags); recording them does not apply them.
  Keep the main ruleset's required contexts identical to CI's job names, and its strict
  up-to-date policy off.

## Code map

Each module's docstring, or the comment at the top of a command-line tool, holds the rules for
changing that module, with the measured LibreOffice behaviour and the issues behind them. Read it
before changing the module, and update it in the same pull request when a rule changes.
[docs/reordering.md](docs/reordering.md) is the contract between the list and the move operation.

- **Packaging.** `extension/description.xml` is the version source.
  `extension/sheet-manager.components` and `registration.py` provide passive Python registration;
  `Factories.xcu` maps tool-panel URLs to that factory, and `Sidebar.xcu` registers the Calc-only
  deck and panel. `tools/build.py` allowlists every packaged file and includes the root licence as
  `LICENSE.txt`. `src/sheet_manager/` ships as `pythonpath/sheet_manager/`.
- **Pure logic,** importable without `uno`: `keys.py` key routing, `sheet_list.py` rows and
  geometry, `selection.py` the list's picks and cursor, `structure.py` the structural generation,
  `reorder.py` the move planner, `rename.py` the batch rename planner, and `i18n.py` the
  translation boundary.
- **UNO adapters:** `uno_panel.py` the factory and panel window; `uno_list.py` the tree, its
  refresh, input, drag and drop, and observation of Calc's tabs; `uno_rows.py` row painting;
  `uno_keys.py` the key handler; `uno_menu.py` the context menu and Calc's commands;
  `uno_moves.py` the move buttons; `uno_status.py` the footer; `uno_show.py` Show;
  `uno_rename.py` batch renames, their undo and recovery; `uno_rename_dialog.py` the Rename
  Sheets dialog; `uno_reorder.py` moves, undo and recovery; `uno_structure.py` the per-document
  structure monitor; `uno_calc.py` shared Calc and threading helpers.
- **Tests:** `tests/unit/`; `tests/integration/run.py` and its `test_*.py` suites, with
  `main_thread.py` and `teardown.py` for closing documents and stalls; `tests/ui/run_ui.py` for
  real input under Xvfb; `tools/linux_integration.py` for the Docker lab. CONTRIBUTING.md says what
  each covers. Human usability tasks and additional platform observations are in
  [docs/manual-tests.md](docs/manual-tests.md); keep it current.
- **Releases:** `tools/release_data.py` owns version policy, changelog extraction, and feed XML;
  `tools/github_release.py` validates history and exact-commit CI, publishes, and generates Pages
  from published OXT metadata. `release.yml` publishes only by dispatch on `main` and checks
  workflow changes on pull requests without writing; `pages.yml` is the only workflow that deploys
  Pages. RELEASING.md describes them.

### Rules for all code

Breaking one of these has hung or crashed LibreOffice, or let an action reach the wrong sheet:

- **Sheet identity.** A retained sheet handle is not an identity: when a sheet is deleted, its
  handle turns to another sheet and can later report the deleted sheet's name. Whatever holds
  handles across user time keeps refs made at the user's input, never from a name later, and
  checks the shared structure monitor's generation when it acts (`selection.py`, `structure.py`).
  Every action checks its sheets when it runs, never against the list's cached rows. Read handles
  by index: Calc's lookup by name can find another sheet (`uno_reorder.py`,
  [#113](https://github.com/viell-dev/slop-calc-sheet-manager/issues/113)).
- **Listeners** can be called on other threads or in the middle of a change. They only record
  state or post work to the main thread (`uno_calc.MainThread`, an `AsyncCallback`). The structure
  monitor's state reads are the one documented exception (`uno_structure.py`).
- **Threads** start only through `uno_calc.start_thread`, never with `threading`: Calc hung when
  `Thread.start` waited for a thread that was waiting for LibreOffice's main lock
  ([#55](https://github.com/viell-dev/slop-calc-sheet-manager/issues/55)).
- **Test observation.** Tests observe only public UNO: the `XPanel.getDialog()` window, its child
  tree control (`tests/integration/sheet_list_view.py`), and its `XEventListener`. Keep test hooks
  and failure-injection seams out of the shipped extension; inject failures through test-only
  forwarding adapters.
- **Test documents** are opened visibly, even in headless runs, and every Calc document is closed
  through `main_thread.close_document`: on Windows, closing one from the test's own thread
  crashed LibreOffice ([#47](https://github.com/viell-dev/slop-calc-sheet-manager/issues/47)).
- **PyUNO exceptions** reject a new `__traceback__`, so a UNO exception leaving a
  `@contextmanager` block, such as `office_session`, arrives as a RuntimeException about a
  traceback object ([#41](https://github.com/viell-dev/slop-calc-sheet-manager/issues/41)). Keep
  UNO calls whose exceptions a caller catches out of generator-based context managers; in a
  failed run, read the first traceback.
- **Shipped files.** Add a new shipped module to the allowlist in `tools/build.py` and to the
  package-content test.

## Releases

- The current phase is beta towards 0.1.0, from the owner's direction of 2026-10-31: the feature
  set is frozen at what 0.0.6 delivers, and each beta fixes a chosen subset of the open defects.
  The stable release goal is proposed in
  [#120](https://github.com/viell-dev/slop-calc-sheet-manager/issues/120); a release candidate
  waits for its agreement and for the blockers it names, and
  [#93](https://github.com/viell-dev/slop-calc-sheet-manager/issues/93) tracks the work. This
  does not waive the human usability gate or required defect dispositions for the stable release.
- The owner has given standing approval for agents to publish releases, prereleases and stable
  versions alike, with their release notes, whenever the agents judge a build ready. Only the
  listing on extensions.libreoffice.org needs the owner's sign-in.
- Follow [RELEASING.md](RELEASING.md) for version numbers, channels, changelog sections, dry runs,
  publication, and recovery. Its guarantees hold without exception: published files, tags, and
  channels never change, update feeds never lose history or move backwards, and a bad release is
  fixed by a newer version. Keep GitHub release immutability disabled during early development;
  do not enable it without the owner's direction.

## Ongoing maintenance

- **Start of assigned maintenance.** Inspect the releases, failed checks, open security and
  Dependabot reports, and new LibreOffice releases that affect the overview. Triage what affects
  the assignment, and record other findings as issues without widening the work.
- **End of assigned maintenance.** Reconcile issues and pull requests, public claims, deployments,
  and finished branches and worktrees. Preserve work that has an active owner or a recorded
  purpose, such as research branches. Never clean up another agent's work as a side effect.
- **User-journey check,** at each release and monthly while maintenance is assigned. Follow the
  path from discovery, through installation and first use, to reporting a defect, and fix what no
  longer works or no longer agrees. Neither this check nor anything else in this file starts work
  by itself or schedules a recurring job.
- Work in parallel with one branch, and one worktree of this repository, per agent. Commit and push
  early, so that a stop for usage limits loses little.

## Repository boundary

Everything the project needs lives in this repository. Never stage, copy, quote, or publish
content from outside it. Tests, issues, and pull requests use synthetic workbooks only, and logs
and screenshots must not contain private documents or credentials.
