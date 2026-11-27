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
  just to get a failing change merged. A setting change with irreversible effects needs the owner's
  express approval for that change; if its reversibility is uncertain, verify it first.
- Agents carry assigned work through to the end: reproduction, implementation, tests,
  documentation, review, merge, and any release the release rules call for. Unfinished work and its
  dependencies are recorded in issues; the issue, not an agent's session, is the record of
  progress.
- The owner is not the project's code reviewer or release engineer, and is not assumed to
  have read its code, issues, or documentation. Their reports from using the extension, directly or
  through other agents, are consumer reports: reproduce and investigate them without asking the
  reporter to diagnose the implementation.
- Weigh every feature or enhancement request, including agents' own proposals and review
  suggestions, on two questions: does it belong within the agreed scope, and does its benefit
  justify the complexity, dependencies, tests, documentation, and support it adds for as long as
  the project is maintained? Record the reasoning on the issue and accept, narrow, or decline the
  request, closing a declined one as not planned with `Status: Won't Do`.
  - Weigh the owner's suggestions the same way; an assignment to handle such an issue includes that
    judgement. Only an explicit instruction or scope decision from the owner commits the project to
    an addition. When the intent is unclear, treat it as a suggestion and say so on the issue.
  - Recommend a scope change in a `Needs: Owner` issue only when a request outside the scope clearly
    justifies its cost, and do not implement it before the owner's decision.

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
  they run, and their limits, with links to investigation evidence. Change it in the same pull
  request as a promise or a check; record run results and deliberate-break receipts in the issue
  or pull request.
- Before implementing an issue, reproduce or measure its claim on `main` and record, with the
  evidence, whether it is accepted, narrowed, or declined. Reports from agents get the same
  scrutiny as any other.
- Every change gets relevant tests. A reproduced defect gets a regression check at the layer that
  exposes it: unit tests for pure logic, integration tests against a real LibreOffice for UNO
  behaviour, and painted sessions for anything that depends on drawing or real input. A mock is
  not evidence of LibreOffice's behaviour.
- Where practical, show that a deliberately broken critical behaviour fails its check, and say so
  in the pull request.
- Define the acceptance evidence before implementing. Triage a newly found input or review
  suggestion before it widens the assignment, and never get a passing result by discarding
  evidence, weakening a check, or changing random inputs.
- A failed or intermittent check is classified from its artifacts: whether the change caused or
  worsened it, and whether it blocks delivery or meaningful verification. Compare the same inputs
  and environment on `main` where practical. Fix what the change caused and what blocks, in the
  extension or the test harness; a failure that predates the change does not waive a required
  check. Record an unrelated failure that blocks nothing in an issue, with its inputs, versions,
  and evidence, and defer its deeper diagnosis and repair. Never rerun a job until it is green,
  widen a limit without understanding the failure, or let a skipped test, a swallowed failure, or a
  crashed office pass as success.
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

Every review, the author's own or an independent one, judges how the code is written as well as
whether it works. Follow the [review procedure](docs/development/maintenance.md#review) for code
quality, deliberate departures, profiling, weak precedents, and when and how to use an independent
reviewer.

- **Every release pull request gets independent review** of all changes since the previous release,
  unresolved defects, verification evidence, compatibility, packaging, documentation, installation,
  and updates. For the first release, review the complete maintained implementation.
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

The pinned overview issue [#33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33)
lists every LibreOffice or other dependency defect that affects Sheet Manager. Follow the
[dependency defect procedure](docs/development/maintenance.md#dependency-defects) for its states,
the per-defect issues, parking and reopening them, checking new LibreOffice releases, and reporting
to other dependencies.

## Security fixes and release-age gates

[`.github/dependabot.yml`](.github/dependabot.yml) holds Dependabot's version updates back for a
7-day cooldown, so that others can catch a compromised or broken release first. The cooldown guards
against an unknown risk; a published advisory against a version in the dependency tree is a known
one. Resolving the advisory takes precedence over the cooldown and over routine update batching,
but only for the versions the fix needs, and only after checking that the fix is genuine. The
cooldown does not delay Dependabot's security updates; they get the same checks before merging.

Follow the [security fix procedure](docs/development/maintenance.md#security-fixes) to verify the
fix, choose the level to apply it at, decide on review of the bypassed cooldown, and record it in
the pull request.

## Public surfaces and documentation

- **Sources of facts.** Each fact has one source, and every surface that repeats it must agree with
  that source:
  - `extension/description.xml`: the identifier, the version, the minimum LibreOffice version,
    and the update feed;
  - `ci/libreoffice.json`: the tested LibreOffice builds;
  - GitHub Releases, and the feeds and `releases.json` that Pages generates from them: what is
    published;
  - the user guide: how the published baseline behaves; issues own scope decisions and plans.

  The surfaces that repeat these facts are:
  - the README;
  - the user guide in `docs/`;
  - the [bundled quick help](extension/help/en/dev.viell.sheetmanager/index.xhp) and the
    [Extension Manager description](extension/description-en.txt);
  - SECURITY.md;
  - CHANGELOG.md;
  - the release notes;
  - the repository's About text, homepage, and topics on GitHub.
- **Affected-surface review.** Use the inventory above for behaviour, compatibility and release
  changes. Update each affected surface in the same pull request. Compare short descriptions with
  the detailed instructions and their applicable build: the published baseline for the online
  guide and the package's own behaviour for shipped Help and the Extension Manager description.
  Review the meaning of descriptions of picks and Calc tabs, command effects, undo and recovery,
  and limits where they are mentioned. `tests/unit/test_consistency.py` checks repeated facts
  such as versions, identifiers and the feed URL. `tools/check_release_page.py` checks downloads
  and availability markers against synthetic release histories. Review behaviour prose against
  the implementation and its verification evidence. If the About text or homepage is affected,
  read the live GitHub settings and correct them.
- **Document ownership.** Keep the README focused on purpose, capabilities, compatibility and entry
  points. CONTRIBUTING.md owns setup, routine commands, and task entry points. The linked
  Development pages own native test procedures, the rules for all code, and the maintainer
  procedures this file links; docs/verification.md owns coverage and limits, and RELEASING.md owns
  release procedures. This file holds agent instructions and non-obvious safeguards. Primary
  documents describe the current state and how to work in the repository, not a journal of past
  sessions. Stated status names the current release, blockers, and pending decisions, links their
  issues or PRs, and replaces the previous status. Issues and PRs own decisions, progress and
  detailed verification receipts; do not duplicate their history here or create a replacement
  ledger.
- **Historical records.** Keep one only when a future reader needs rationale or experiment results
  that Git history, issues, and PRs cannot serve. Put it in a `docs/` subdirectory named for its
  content, and state at its top why it is kept. On finding session history in a primary document, or
  a record whose reason is missing or no longer holds, fix it as part of the current work: fold
  still-current facts into the present-state description, move justified material to a record, and
  delete the rest.
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
  Keep the main ruleset's required context at **Routine CI**, whose always-running aggregate
  requires every routine job to succeed. Keep workflow job names and `tools/ci_policy.py` in sync,
  and leave the strict up-to-date policy off. Publication also requires the manual full release
  sweep on the exact revision; a PR planning preview cannot supply that release evidence.

## Working with the code

Each module's docstring, or the comment at the top of a command-line tool, holds the rules for
changing that module, with the measured LibreOffice behaviour and the issues behind them. Read it
before changing the module, and update it in the same pull request when a rule changes.
[docs/reordering.md](docs/reordering.md) is the contract between the list and the move operation.

Pure logic and `uno_` adapters live in [`src/sheet_manager/`](src/sheet_manager/).
[Native LibreOffice testing](docs/development/native-testing.md) explains the runners and
suite conventions. [docs/verification.md](docs/verification.md) maps behaviours to their tests, and
[docs/manual-tests.md](docs/manual-tests.md) supplies human usability tasks. Keep these documents
current when their procedures or coverage change. [RELEASING.md](RELEASING.md) owns packaging,
publication and feed procedures.

For package, metadata and interface changes, use the
[LibreOffice extension and interface guidance](docs/development/index.md#libreoffice-extension-and-interface-guidance).

Before changing code, read the [rules for all code](docs/development/code-rules.md): sheet
identity, listeners, threads, test observation, test documents, PyUNO exceptions, and shipped files.
Breaking one of them has hung or crashed LibreOffice, or let an action reach the wrong sheet.

## Releases

Follow [RELEASING.md](RELEASING.md) for publication authority, versioning, channels, readiness,
human testing, dry runs and recovery. Its
[first-stable-release rules](RELEASING.md#first-stable-release)
link the scope agreement, tracker and outstanding human request. Published files, tags and
channels never change, feeds never lose history or move backwards, and a bad release is fixed by
a newer version. Keep GitHub release immutability disabled unless the owner expressly approves
enabling it; repository administration authority does not waive that approval.

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
- Use a separate worktree for each independent branch; cooperating helpers may share an assigned
  checkout with explicit scope and Git coordination, with the lead or assigned branch owner
  committing and pushing. Commit and push early, and keep progress in the issue so that a stop for
  usage limits loses little.

## Repository boundary

Everything the project needs lives in this repository. Never stage, copy, quote, or publish
content from outside it. Tests, issues, and pull requests use synthetic workbooks only, and logs
and screenshots must not contain private documents or credentials.
