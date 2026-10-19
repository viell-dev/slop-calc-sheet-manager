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
  `uno` (`keys.py`, `sheet_list.py`, `swatch.py`, `reorder.py`); the `uno_*.py` modules adapt
  it: `uno_panel.py` owns the UNO factory and panel, `uno_list.py` the tree control, its drag and
  drop and refresh, `uno_keys.py` the key handler, `uno_menu.py` the sheet tab menu, `uno_show.py`
  the list's own Show operation, and `uno_calc.py` shared Calc helpers. Tests observe only public
  UNO: the `XPanel.getDialog()` window, its child tree control
  (`tests/integration/sheet_list_view.py`), and its `XEventListener`; keep test hooks out of the
  production factory.
- The list keeps the `uno_reorder.snapshot` that produced its rows. Its picks, keyboard cursor,
  and Shift anchor live in `selection.py` as refs: the name a sheet had when the user's input made
  the ref, and that sheet's retained handle. A ref is never made again from a name later, and
  everything the list writes to the tree, restores, or acts on comes from refs. Retained handles
  are not identities: when a sheet is deleted, its handle turns to the previous sheet and can
  report the deleted sheet's name again after a rename (measured; `docs/reordering.md`). So each
  list has a `uno_structure.StructureMonitor`: it listens to the document's modify, undo, and
  document events, reads the sheet count and the document's undo and lock state at every modify
  and undo notification, and moves a generation (`structure.StructureEvents`) whenever a sheet
  may have been inserted or deleted. It moves when the count changes; when undo recording is
  off or locked, the controllers or actions are locked, or modify notifications are off at a
  notification, except for the controller lock of the list's own move (`own_move`); on every
  undo and redo; at a modify notification that no recorded undo action explains, except inside
  a save window (`OnSave`, `OnSaveAs`, or `OnCopyTo` up to its `Done` or `Failed` event, or the
  next undo notification); and at a check, when the undo history changed without a notification
  or undo recording or modify notifications are off (LibreOffice turns modify notifications off
  while it saves, so not inside a save window). Undo notifications come for every recorded
  action, also inside `lockControllers`, `addActionLock`, `disableSetModified`, and undo
  contexts, where modify notifications are batched or missing. Every action checks the
  generation again when it runs (`check()`). Picks, presses, drags, and an open menu carry the
  generation they were proved at; when it moves, the list drops every ref and any held press and
  tells the user in an infobar, which only the user closes, since removing one moves the focus
  to the sheet. As a second line, every refresh checks that its handles map one to one onto the
  sheets with at most one rename (`structure_kept`). Otherwise refs stay while their handles
  report their names, so a renamed pick goes and a moved one stays (#28). Over-clearing is the
  accepted cost: undo and redo, document property changes, and other changes LibreOffice does
  not record for undo clear the picks too. Threat model, decided by the maintainer: everything
  LibreOffice reports must be caught; only a structural edit that LibreOffice does not report at
  all (undo recording and modify notifications both off), or whose only report falls inside a
  save window, is out of scope. The one other known way past the rules is a sequence built to
  report like typed input, documented in `structure.py`; such a program could hide or delete any
  sheet itself. The monitor's listeners read the sheet count and the five state getters while
  LibreOffice notifies: a narrow exception to the rule that listeners only note and post, for
  getters that take the main lock and return a count or a flag without UI work (checked in the
  pinned sources); call nothing else from them. Drops plan against the snapshot of the drag's
  start through `apply_order`, which refuses stale state, and the list refuses a drop when the
  generation moved during the drag. The menu opens
  only for refs checked just before, with a fresh snapshot; while it is open, a dispatch
  interceptor on the frame checks at dispatch time that the generation did not move, that the
  picked sheets are unchanged, and that they are exactly Calc's selected tabs.
  `uno_show.show_sheets` applies the reorder layer's undo rules: refuse without undo or beyond
  the undo limit, one group, undo only its own group on failure, verify. A plain click or Enter
  makes the sheet Calc's only selected tab and reads that back: `setActiveSheet` keeps an
  existing group when the sheet belongs to it.
- Refreshing reads every sheet and rebuilds the tree on the main thread, so `uno_list.py` limits
  it: an activation refreshes at once only after the list has been idle for several times the last
  refresh's cost, and other changes wait for a pause, with a bounded wait. Bulk API changes, such
  as a 500-call move, send an event for each call; refreshing on each one slowed such a move on
  Windows from seconds to over a minute. So rows can be out of date when the user acts on them:
  every action checks its sheets when it runs, never against the cached rows. A left press keeps
  the pressed sheet's handle, and its release activates only that sheet, still in that row
  (#28). If a refresh during the press moved the sheet or showed another under its name, the
  release has no effect at all: the list writes its own refs back, whatever the tree selected on
  release, so a newer pick made meanwhile (following Calc, or by keyboard) stays. While a press
  is held, a refresh does not take the tree's selection as the user's; the press and release
  handlers do. Activation reads the handle's current name and visibility first, because
  Calc sends the activation of a hidden sheet to another sheet (#43); if Calc goes elsewhere
  anyway, the list restores the previous sheet and tabs and reads both back before saying the
  view is unchanged (#46). The list's mouse handlers and its notice of a sheet switch both run
  after input already queued, so a switch is matched to the list's input count when Calc reports
  it: newer clicks or keys in the list win over following Calc's selection, and a switch the list
  made itself is not followed (#44).
- `extension/description.xml` is the version source. `extension/sheet-manager.components` and
  `registration.py` provide passive Python registration. `Factories.xcu` maps tool-panel URLs to
  that factory; `Sidebar.xcu` registers the Calc-only deck and panel. `tools/build.py` explicitly
  allowlists every packaged file and includes the root licence as `LICENSE.txt`.
- `tools/release_data.py` owns version policy, changelog extraction, and feed XML.
  `tools/github_release.py` validates GitHub history and exact-commit CI, builds/publishes releases,
  and generates Pages from published OXT metadata. `release.yml` validates PR workflow changes
  without writes and publishes only by dispatch on `main`; `pages.yml` is also callable by it.
  `tests/integration/test_updates.py` checks loopback feeds with LibreOffice's real parser and
  candidate dependencies through its temporary deployment repository. The modal update dialog
  has no public UNO offered-update API; keep parser and dependency assertions distinct.
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
- The list is a borderless `TreeControl` (so that it is a direct child of the panel window) with
  a hidden root. With a hidden root, the tree peer mishandles every data-model change event and
  re-parents all rows under the root, so never change nodes in place: build a new data model and
  restore selection, scroll position, and keyboard cursor. The tree exposes no cursor, so the list
  tracks it from clicks and the keys it passes to the tree (`keys.cursor_after`); a rebuild cannot
  restore the tree's Shift anchor, so the next Shift move starts a range at the cursor. Listener
  callbacks can arrive on other threads or during a change; they only record state or post work
  through `AsyncCallback`. Start threads only through `uno_calc.start_thread`, never with
  `threading`: `Thread.start` waits for the new thread, whose first steps can wait for
  LibreOffice's main lock that listeners and the main thread hold, and Calc then hangs (#55).
- Keys: a toolkit `XKeyHandler` is registered only while the tree has focus and checks
  `hasFocus()` again for every key. Navigation keys go to the tree (the sidebar swallows what the
  tree ignores); Enter, typed characters, and the menu keys are handled by the list; other
  shortcuts are resolved through the document, Calc, and global shortcut configurations and
  dispatched to the panel's frame; Tab, F6, F10, and Esc pass; everything else is consumed so it
  cannot reach a cell (`keys.py` documents the routing).
- `tests/integration/run.py` runs with the tested office's bundled Python, installs into a new
  temporary profile, starts only its own process with a unique pipe, and disposes it afterwards.
  Open documents visibly even in headless runs: hidden documents do not reliably execute Calc
  commands or undo. Startup retries end before document creation and never retry failed tests.
  `--sessions headless|gtk3|both` selects sessions; default headless. The feature suite
  `test_sheet_list.py` checks the list's contents, refresh, identity, robot clicks and menu,
  clicks on rows not yet refreshed, and Show with LibreOffice's synthetic input; the robot only
  posts events, so they reach the list ahead of its delayed refresh. Robot input cannot reach
  gtk3's native menus, so it skips the menu steps in painted sessions, and it closes leftover
  workbooks after a failure: a painted office asks to save them when the runner terminates it,
  which blocks the run (#40).
  Real-input UI tests live in `tests/ui/run_ui.py`, use XTEST under Xvfb with separate gtk3 and
  gen sessions, and run in the `linux-gtk3` jobs through `tools/linux_integration.py <lane> --ui`.
  What neither can reach is on the manual checklist, `docs/manual-tests.md`; keep it current.
  Keep shared lifecycle changes additive.
- PyUNO exceptions reject a new `__traceback__`, so a UNO exception leaving a `@contextmanager`
  block, such as `office_session`, arrives as a RuntimeException about a traceback object
  ([#41](https://github.com/viell-dev/slop-calc-sheet-manager/issues/41)). Keep UNO calls whose
  exceptions a caller catches out of generator-based context managers; in a failed run, read the
  first traceback.
- On Windows, a Calc document closed from the test's own thread, which is a UNO bridge thread in
  the office, crashes LibreOffice when one of its toolbars has an update pending: the close
  releases LibreOffice's lock while it destroys native windows, and the main thread then updates
  a toolbar control being disposed
  ([#47](https://github.com/viell-dev/slop-calc-sheet-manager/issues/47)). The user interface
  closes on the main thread, where this cannot happen. Close every Calc document in the tests and
  the workbook generator through `main_thread.close_document`, which on Windows closes inside an
  `AsyncCallback` notification, on the main thread; close in place of a `finally` clause with
  `close_after`, close a suite's leftovers through `teardown.run_checks`, and set office settings
  for a block with `teardown.Configured`. A callback that does not finish in time is recorded in
  `teardown` (#50): no further close, check, suite, or settings restore is tried (#51), the UI
  runner stops too (#52), the session fails without an earlier failure being hidden, and the
  runner stops its own office process tree instead of asking it to terminate, which would wait
  for the stuck main thread too (#40). A crashed office exits with status 0 on Windows
  ([#48](https://github.com/viell-dev/slop-calc-sheet-manager/issues/48)), so the runner copies
  LibreOffice's own crash dumps from the profile into the results as `crash-*.dmp` and fails a
  session whose office left one; a retried startup attempt's dumps are kept but do not fail a
  clean retry. GitHub's Windows runners have CDB, not on `PATH`, at
  `C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe`; with it,
  `cdb -z <dump> -y "srv*<cache>*https://dev-downloads.libreoffice.org/symstore/symbols;srv*<cache>*https://msdl.microsoft.com/download/symbols" -c ".ecxr; !analyze -v; ~* kp; q"`
  gives every thread's stack with TDF's symbols.
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
- Version numbers are plain dotted numbers without a `v` prefix. New versions exceed every
  published build and reserved tag; an already-reserved draft can be recovered later without
  changing the feeds' version order. There are no `-rc` suffixes, because LibreOffice's update
  check ranks `0.1.0-rc.1` above `0.1.0`. Whether a build is a prerelease or stable is a property of
  its GitHub release and of the update feed it appears in.
- Published files and tags are never replaced, and update feeds never move backwards: a bad release
  is fixed by a newer version.
- Follow [RELEASING.md](RELEASING.md) for candidate numbering below the final version, patch numbers
  below `.90`, changelog sections, dry runs, publication and recovery. Publication requires a
  successful CI push run on the exact `main` commit. Upload assets to the draft before publishing
  because releases are immutable. The stable feed excludes candidates; the prerelease feed
  retains every build. Never reclassify a published candidate or delete deployed feed history.

## Repository boundary

Everything the project needs lives in this repository. Never stage, copy, quote, or publish
content from outside it. Tests, issues, and pull requests use synthetic workbooks only, and logs
and screenshots must not contain private documents or credentials.
