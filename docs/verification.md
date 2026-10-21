# Verification map

What Sheet Manager promises, which checks show it, where they run, and what they do not show. Keep
this map current in the same pull request as any change to a promise or to its checks. Commands
are in
[CONTRIBUTING.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/CONTRIBUTING.md).

"CI" means the required jobs on every pull request and every push to `main`:

- two Checks jobs: Ruff, strict Pyright, unit tests, and two builds that must match byte for byte,
  on Python 3.12 and 3.14;
- three Linux headless jobs and three Linux gtk3 jobs, on LibreOffice 26.2.1, the newest 26.2, and
  the newest 26.8;
- the refusal job on 26.2.0;
- a Windows job on 26.8.

The jobs use official libreoffice.org builds pinned in `ci/libreoffice.json`.

## What `main` does today

| Promise                                                                                                 | Evidence                                                                                                                                                                                                                                                                                                                 | Runs                               | Limits                                                                                                                             |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| LibreOffice 26.2.0 and earlier refuse the extension with a dependency error and leave nothing installed | `check_refusal` in `tests/integration/run.py`                                                                                                                                                                                                                                                                            | CI refusal job                     | Only 26.2.0 is tried.                                                                                                              |
| The extension installs without prompts on supported versions                                            | `unopkg add` into a new private profile before every session                                                                                                                                                                                                                                                             | Every CI integration job           | The Extension Manager's installation dialog is not driven.                                                                         |
| Calc gets a Sheet Manager deck; Writer does not; read-only workbooks have it too                        | `exercise()` in `run.py`: the deck and panel, read-only documents, and Writer exclusion                                                                                                                                                                                                                                  | Every CI integration job           |                                                                                                                                    |
| The panel fills the sidebar, follows its size, and is released when its document closes                | `exercise()`: the tab-control peer, exact 150-pixel growth of frame and panel, and disposal listeners                                                                                                                                                                                                                    | Every CI integration job           | The gtk3 frame reports a different height than requested ([#9](https://github.com/viell-dev/slop-calc-sheet-manager/issues/9)); the checks compare growth. |
| Shift, Ctrl, and Alt do not crash LibreOffice while the deck is shown                                   | Real key presses with `xdotool` in painted sessions                                                                                                                                                                                                                                                                      | CI gtk3 jobs                       | Not pressed on Windows.                                                                                                            |
| Headless conversion still works with the extension installed                                            | `check_lifecycle` in `run.py`: `soffice --headless --convert-to ods` and the converted content                                                                                                                                                                                                                           | CI Linux headless and Windows jobs | One conversion direction.                                                                                                          |
| Removing the extension leaves no deck, no panel factory, and no installed copy                          | `check_lifecycle`: deck and factory present before `unopkg remove`, absent in a new office after it; the installed copy, found by its description naming the extension's identifier, present before and absent after                                                                                                                                                              | CI Linux headless and Windows jobs | Removal through the Extension Manager's dialog is not driven. LibreOffice keeps its own staging copy under `user/extensions/tmp`. |
| Installed copies are offered newer builds that their LibreOffice can run                                | `tests/unit/test_release_data.py` (version order, feeds, the candidate rules); `tests/integration/test_updates.py` (LibreOffice's own feed parser over loopback HTTP, and its dependency check of candidate packages)                                                                                                    | CI                                 | The update dialog, the download, and the restart are not exercised: [#57](https://github.com/viell-dev/slop-calc-sheet-manager/issues/57). |
| Releases are built from a commit whose CI passed and are never replaced; feeds never lose history      | `tests/unit/test_github_release.py`; the release dry run, which also runs on pull requests that change release files                                                                                                                                                                                                     | CI and the Release workflow        | Creating the tag and draft, uploading, and publishing have never run live; the first published build will be their first test.   |
| The package contains exactly the allowlisted files and builds reproducibly                              | `tests/unit/test_build.py`; two builds compared byte for byte by `tools/check.py`                                                                                                                                                                                                                                        | CI Checks                          |                                                                                                                                    |

## The reorder layer

The reorder layer is on `main` but no control reaches it yet: the sheet list that will call it is
in [#21](https://github.com/viell-dev/slop-calc-sheet-manager/pull/21). Its contract is in
[reordering.md](./reordering.md).

| Promise                                                                                         | Evidence                                                                                                                                                                                                                               | Runs                     | Limits                                                                                                                                       |
| ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Plans reach the target order with the fewest moves, and keep scenario blocks whole                | `tests/unit/test_reorder.py`: all permutations up to seven sheets, all scenario partitions up to seven, and an independent longest-common-subsequence oracle                                                                           | CI Checks                |                                                                                                                                              |
| A move is one undo step, and undo restores the order completely                                  | `tests/integration/test_reorder.py`: one undo and redo, active-sheet and selection preservation, and two configured undo steps that force nested groups                                                                                | Every CI integration job | LibreOffice's own undo defects: [#16](https://github.com/viell-dev/slop-calc-sheet-manager/issues/16) is worked around; [#37](https://github.com/viell-dev/slop-calc-sheet-manager/issues/37) is a documented limit. |
| A failure part-way is rolled back and verified, and the user's previous action is never undone   | Test-only forwarding adapters that fail after each real mutation; a silently ineffective undo; a full 100-step undo stack                                                                                                     | Every CI integration job | No injection seam ships, so recovery is shown on real LibreOffice calls made through the adapters.                                          |
| Protected, read-only, and change-tracked documents, and stale handles, are refused before any change | `assert_permissions` and the stale-handle checks in `test_reorder.py`                                                                                                                                                                 | Every CI integration job | Retained sheet handles are not stable identities: [#19](https://github.com/viell-dev/slop-calc-sheet-manager/issues/19) records a delete, insert, and rename sequence that passes every check. |
| Large workbooks stay usable                                                                      | Planning under five seconds at 10,000 sheets; complete moves and undo timed on synthetic 200- and 1,000-sheet workbooks with formulas, named ranges, and charts, with the references checked before and after undo                    | CI Checks; every CI integration job | The timings are recorded in `reorder-performance-*.json` as measurements, not limits.                                                   |

## Not implemented on `main`

The sheet list, its selection and grouped-tabs handling, the sheet tab menu, keyboard operation,
and synchronization are planned for 0.1.0. Their checks are on #21's branch and are not mapped here
until that work lands. When it does, add rows for:

- sheet identity across refreshes;
- grouped-selection safety;
- native menu dispatch;
- the list's lifecycle across document switches;
- keyboard handling.

## The checks themselves

A check that cannot see a failure is worse than none. The integration runner therefore fails a
session in each of these cases:

- **Nonzero exit or forced shutdown.** The office exits with a nonzero status, or has to be stopped
  after the 30-second grace period.
- **Fatal message.** The office logs LibreOffice's fatal-error message.
- **Crash dump.** The office leaves one of LibreOffice's own crash dumps. On Windows a crashed
  office exits with status 0
  ([#48](https://github.com/viell-dev/slop-calc-sheet-manager/issues/48)).
- **Stalled callback.** A callback on LibreOffice's main thread does not finish
  ([#50](https://github.com/viell-dev/slop-calc-sheet-manager/issues/50)).
- **Held terminate request.** The terminate request does not return, for example because a dialog
  holds it ([#40](https://github.com/viell-dev/slop-calc-sheet-manager/issues/40)).

Only startup is retried, and never a test assertion. `tests/unit/test_office_process.py`,
`test_teardown.py`, and `test_stalled_cleanup.py` cover these rules against fakes.

## Breaking a check on purpose

These checks were shown to fail when the behaviour they guard was deliberately broken.

| Check                                   | Deliberate break                                                                                                  | Result                                                                                      |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Removal                                 | `unopkg remove` replaced by `unopkg list`, LibreOffice 26.8.1.1 on Windows                                        | Fails on the package left installed; with that check disabled, fails on "Deck present: True" |
| Termination (#40)                       | A suite fails with a modified workbook open, in a painted 26.2.1.2 session                                        | Before the fix: the run hung until stopped at 360 s with no results. After: it fails in 50 s, with the shutdown recorded as forced |
| Initial geometry (#9)                   | The window is maximized 0.1 s after the first geometry request, in a painted 26.2.1.2 session                     | Before the fix: the baseline wait timed out. After: the request is repeated once and the resize checks pass |
| Clean-up after a stall (#50, #51)       | `close_leftovers` changed to swallow timeouts and failed closes                                                   | Six of nine teardown tests and two of four stall tests fail                                 |
| Settings restore after a stall (#51)    | The undo-limit restore runs even after a stall                                                                    | Two of four stall tests fail; the other two cover a normal restore and a failed restore                           |
| Issue forms                             | A form applies a label missing from `.github/labels.json`                                                        | `test_each_issue_form_applies_one_known_type_label` fails                                   |
