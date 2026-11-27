# Maintainer procedures

These procedures support the rules in
[AGENTS.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/AGENTS.md), which links
each section from the rule it applies.

## Review

Every review, the author's own or an independent one, judges how the code is written as well as
whether it works:

- **Code quality.** Confirm the behaviour, then judge the code: readable, idiomatic for Python and
  PyUNO, or for Vue and VitePress in the guide, consistent in structure and naming, appropriately
  tested, and in line with current best practices where reasonable. Working code that adds poor or
  smelly patterns still needs changes. Check the current LibreOffice and dependency documentation
  rather than remembered conventions.
- **Deliberate departures.** A departure from the better practice is acceptable when a host,
  dependency, or compatibility constraint makes that practice infeasible, or when the chosen form
  is measured to be significantly faster; a marginal gain does not justify the inconsistency.
  Explain the constraint or measured difference in a code comment at that site, with the condition
  for revisiting it where one exists. Treat an unexplained departure as a finding.
- **Profiling.** Support performance departures with profiles and benchmarks, and check from time
  to time whether idiomatic code on hot paths costs more than expected. A finding that becomes a
  regression gate gets an explicit limit and correctness assertions, as in
  [Performance measurements](../verification.md#performance-measurements).
- **Weak precedents.** Look for the source of a weak pattern, not only its instance. When a pull
  request copies merged code, examples, templates, or guidance that teach the pattern, the
  precedent is the defect, the submitter is not at fault, and the finding names the precedent.
  Correct the source in separate pull requests before settling the original: one refactoring the
  precedent code and one updating the guidance that taught it, as applicable. Then either replace
  the original with a new pull request on the corrected base or refactor it in place. Link these
  pull requests to each other so that the history shows why the original changed.
- **Proportionate findings.** Weigh style findings by scope and maturity: prefer established
  practices with a clear benefit over churn for novelty, and keep each recommendation proportionate
  to the code it touches.

Independent review and its record:

- **When to use independent review.** The maintainer decides whether another agent's perspective
  would materially improve confidence, considering complexity, sensitivity, impact, and uncertainty.
  Sheet identity, undo and recovery, native dispatch, and release authority deserve particular
  attention because a mistake can change documents or published artifacts. They do not create a
  blanket review gate for every change in those areas. Record the choice and its reason.
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

## Dependency defects

The pinned overview issue
[#33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33) lists every LibreOffice or
other dependency defect that affects Sheet Manager, in one of four states:

- **Blocked upstream:** no local remedy; the affected behaviour waits for LibreOffice.
- **Worked around:** a verified local workaround handles it; the overview records its limits and
  when it can be removed.
- **Resolved upstream:** a fix is verified in a named LibreOffice release, and the overview tracks
  what remains here, such as adoption or removing a workaround.
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

## Security fixes

Resolve a published advisory against a version in the dependency tree without waiting for
Dependabot's cooldown, as follows:

- Confirm that the advisory covers the resolved version, and that the fixed release comes from the
  package's usual publisher and source and is identified as the fix by the advisory, changelog, or
  release notes.
- Apply the fix without waiting for the cooldown, at the closest level that works:
  1. The vulnerable package has a fixed release within the project's or its dependant's declared
     range: update to it, moving the exact pin where there is one (`requirements-dev.txt`,
     `package.json` and its lockfile, workflow actions, `ci/` base images).
  2. The vulnerable package is transitive and its dependant has not yet adopted the fix: override
     or pin it with the ecosystem's mechanism (such as npm `overrides` or a hash-pinned entry in
     `requirements-dev.txt`) when the dependant's tests or the project's checks show it still
     works. Record the override, its advisory, and its removal condition in a code comment or the
     pull request. Once the dependant releases a version that adopts the fix, update to it, also
     without waiting for the cooldown, and remove the override.
  3. No working fixed version exists: track the advisory as blocked upstream or worked around in
     the overview, [#33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33), as
     [Dependency defects](#dependency-defects) describes.
- Take the smallest version that resolves the advisory, normally its patch release. Unrelated
  updates and later releases of the same package keep the normal cooldown.
- Bypassing the cooldown moves its check to the agent. Decide whether the fix needs an independent
  review of the change between the current and fixed versions, using the published package contents
  rather than only the repository. For a widely used, actively maintained package with an
  established release process, checking its release notes and diff may suffice; get an independent
  review for a less widely used package, a recent change of maintainer or publishing method, or a
  fix release carrying substantial unrelated changes.
- Record the advisory, affected and fixed versions, dependency path, bypassed cooldown, and review
  decision with its reason in the pull request. Ordinary required checks still apply.
