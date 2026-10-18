# Agent maintenance

Sheet Manager is built, tested, documented, released, and maintained by AI agents. This file holds
the rules they follow. [CONTRIBUTING.md](CONTRIBUTING.md) holds the setup, checks, and pull request
rules that apply to everyone; follow it and do not repeat it here.

## Authority

The owner uses the extension and sets its direction. They do not read the code or the diffs; they
follow the project through the README, issue and pull request descriptions, release notes, and the
extension itself.

- Agents have full authority over the repository, its settings, and its releases. Architecture,
  design, implementation, tooling, supported versions, and release timing are theirs to decide.
  The agent assigned to a task makes every decision the task needs and records the choice, its
  reasoning, and the alternatives rejected in the issue or pull request.
- Ask the owner only for steps that need their sign-in or second factor (such as the listing on
  extensions.libreoffice.org), for actions outside this repository that speak for them (reports to
  other projects, blocking accounts), and for their opinion on how the extension feels in use,
  which only they can observe. Their feedback from real use is a requirement; how to meet it is
  the agents' decision.
- Deciding how the project is built is not deciding what to work on. Do not extend an assignment
  to unrelated issues or design changes, and state the interpretation used when an assignment is
  ambiguous.

## Talking to the owner

- Write issues and pull requests for a reader who has not seen the code: the observed problem, the
  resulting behaviour, the scope decision, and the design decisions made, without the diff.
- A request to the owner says exactly what to do, why, and what result to expect. A test request
  names the build to install and gives numbered steps, each with its expected outcome, and lists
  what to report: the operating system, the LibreOffice version and user interface from
  Help ▸ About, and a screenshot where looks matter.
- Owner testing is batched into one checklist per release candidate. Each checklist ships with a
  synthetic test workbook, and screenshots for public issues are taken with it, so that no real
  sheet names appear in public. Performance on the owner's own workbooks is reported as timings
  only.

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
- The author's own pass is still required: every pull request has a "Verification" section
  listing the commands run, the inputs tried beyond the tests, and what was checked on which
  platform and LibreOffice version.

## Keeping the repository consistent

A change is complete only when everything that describes or depends on it agrees with it, in the
same pull request: documentation, the changelog, tests, configuration, and metadata. Before
committing, search for other statements of what the change touches, such as behaviour, commands,
file locations, version numbers, and requirements. Drift found along the way is a defect: fix it
in the same pull request when it lies in what the pull request changes, and otherwise file an
issue.

## Issues and labels

Labels follow [`.github/labels.json`](.github/labels.json); keep GitHub in sync with it. Every
item has one `Type:` label and at most one `Status:` label for its current disposition.

Take each assigned issue through these steps, and leave it accurate after each; the issue, not the
session, is the record:

1. **Validate.** Reproduce a defect, or measure a claim, on the current `main`, and post the
   commands, inputs, and results.
2. **Decide.** Accept, narrow, or decline; settle the open design questions; post the decision,
   its reasoning, and the alternatives rejected.
3. **Split** a different problem into its own issue, linked, even when one pull request fixes both.
4. **Label and retitle** so the title names the confirmed problem or the accepted request.
5. **Close or keep open.** Close a declined or duplicate issue as not planned. Keep an accepted
   issue open until its fix merges; the fixing pull request names it with a closing keyword.

`Status: Needs Owner Testing` marks work that waits for a check on a real desktop. File an issue
for every defect or limit found during assigned work instead of only mentioning it. Reports from
agents get the same scrutiny as reports from people.

## Git and merging

- Every change to `main` goes through a pull request with passing checks, including
  documentation, dependency updates, and these instructions. Branch names are short kebab-case
  descriptions.
- Merge with a merge commit after checking the exact head
  (`gh pr merge --merge --match-head-commit SHA --body "Assisted-by: <model> via <harness>"`);
  squash and rebase merges are disabled so that history and attribution survive. Never bypass
  the branch rules.
- Pull requests need not be up to date with `main` before merging, so that they do not wait for one
  another; CI runs again on `main` after every merge, and a failure there is fixed forward first.
- Use focused commits, push early so that an interrupted session loses little, and never rewrite
  shared history. Delete a branch once its pull request is merged or closed, unless active work
  depends on it.
- Agents working in parallel use one branch and one worktree each.

## Technical map

- `reorder.py` is the UNO-free target/minimum-call planner; `uno_reorder.py` captures snapshots,
  checks permissions and stale handles, applies one undo group, and verifies recovery. The panel
  contract is [docs/reordering.md](docs/reordering.md). Keep the panel busy and defer refresh during
  application: consecutive individual scenario moves have intermediate block splits. Never pass
  an interior scenario gap through as a raw move destination or use native multi-sheet Move.
- `tests/integration/test_reorder.py` uses test-only forwarding adapters to fail after actual UNO
  mutations; no injection seam ships. Its populated synthetic workbooks exercise formulas,
  named ranges, and charts at 200/1,000 sheets and emit median complete-move/undo timings.
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
- `tests/integration/run.py` runs with the tested office's bundled Python, installs into a new
  temporary profile, starts only its own process with a unique pipe, and disposes it afterwards.
  Open documents visibly even in headless runs: hidden documents do not reliably execute Calc
  commands or undo. Startup retries end before document creation and never retry failed tests.
- `ci/libreoffice.json`, `ci/Dockerfile`, and `tools/linux_integration.py` define the same Linux
  lab for CI and local tests. Headless checks use svp; screenshot checks use gtk3 under Xvfb.
  Never mount host display sockets or use an existing office profile. The Windows MSI installer
  helper is only for disposable CI runners; use the existing installation on developer machines.
- `.github/rulesets/main.json` records the main ruleset with the CI job names to require after
  this workflow is merged. `release-tags.json` records immutable version tags. These are API
  request bodies captured from rulesets 25349507 and 25349508; recording them does not apply them.
  Keep required contexts identical to the workflow's job names and strict up-to-date policy off.

## Releases

- Version numbers are plain dotted numbers without a `v` prefix, strictly increasing across every
  published build. There are no `-rc` suffixes, because LibreOffice's update check ranks
  `0.1.0-rc.1` above `0.1.0`. Whether a build is a prerelease or stable is a property of its GitHub
  release and of the update feed it appears in.
- Published files and tags are never replaced, and update feeds never move backwards: a bad release
  is fixed by a newer version.

## Reports to other projects

A defect in LibreOffice or another dependency gets a `Status: Blocked` tracking issue here with
everything needed to report and verify it without testing again: the versions, the reproduction,
the result, and what unblocks it. Posting a report to another project needs the owner's decision
for that report. A report follows that project's own guidelines, opens with a `> [!NOTE]` callout
saying that an AI agent wrote and submitted it, for whom, and that we stop if asked, and links the
tracking issue, which links back.

## Repository boundary

Everything the project needs lives in this repository. Never stage, copy, quote, or publish
content from outside it. Tests, issues, and pull requests use synthetic workbooks only, and logs
and screenshots must not contain private documents or credentials.

## Attribution

Identify the agent as `<model> via <harness>`, using the most specific model name and version the
session exposes, without an email address. Commit messages end with
`Assisted-by: <model> via <harness>` after a blank line; this is the only permitted agent
attribution trailer, so never add a `Co-Authored-By:` or `Signed-off-by:` trailer for an agent, in
any capitalization, and replace any that tooling supplies. Issues, pull requests, reviews,
comments, and release notes end with `🤖 Generated with <model> via <harness>`. Do not add
attribution footers to repository documents; the README's status section covers them.
