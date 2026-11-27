# Rules for all code

These rules apply to every change to the extension and its tests, alongside the rules in each
module's docstring.

Breaking one of these has hung or crashed LibreOffice, or let an action reach the wrong sheet:

- **Sheet identity.** A retained sheet handle is not an identity: when a sheet is deleted, its
  handle turns to another sheet and can later report the deleted sheet's name. Whatever holds
  handles across user time keeps refs made at the user's input, never from a name later, and
  checks the shared structure monitor's generation when it acts (`selection.py`, `structure.py`).
  Every action checks its sheets when it runs, never against the list's cached rows. Read handles
  by index: Calc's lookup by name can find another sheet (`uno_reorder.py`,
  [#113](https://github.com/viell-dev/slop-calc-sheet-manager/issues/113)).
- **Listeners** can be called on other threads, without LibreOffice's solar mutex (the toolkit's
  mouse listeners, [#269](https://github.com/viell-dev/slop-calc-sheet-manager/issues/269), and
  the drag gesture's, [#264](https://github.com/viell-dev/slop-calc-sheet-manager/issues/264)), or
  in the middle of a change. They only record state or post work to the main thread
  (`uno_calc.MainThread`, an `AsyncCallback`, whose work holds that mutex). The documented
  exceptions are the structure monitor's state reads (`uno_structure.py`), the drag gesture's
  checks before it starts a drag, and the mouse handlers' reads of the tree, the handles and the
  document and their writes of a refused release's picks, which use calls that lock for
  themselves so that a gesture is decided and shown at once (`uno_list.SheetList`). Code that
  runs without the mutex, the drag gesture's and the mouse handlers' checks included, reads the
  structure monitor's `generation` and never calls its `check()`, which updates shared state
  from separately locked reads and relies on the mutex to keep other threads' change reports out
  between them ([#284](https://github.com/viell-dev/slop-calc-sheet-manager/issues/284)). The
  gesture compares its snapshot with `uno_reorder.is_current_as_reported`.
- **Threads** start only through `uno_calc.start_thread`, never with `threading`: Calc hung when
  `Thread.start` waited for a thread that was waiting for LibreOffice's main lock
  ([#55](https://github.com/viell-dev/slop-calc-sheet-manager/issues/55)).
- **Test observation.** Tests observe only public UNO: the `XPanel.getDialog()` window, its child
  tree control (`tests/integration/sheet_list_view.py`), and its `XEventListener`. Keep test hooks
  and failure-injection seams out of the shipped extension; inject failures through test-only
  forwarding adapters.
- **Test documents** are visible before native UI assertions and input, even in headless runs.
  The theme fixture alone prepares its workbook with `Hidden=True`, finishes edits and cleanup,
  then shows the frame before opening the panel. This measured preparation exception prevents
  cleanup from invalidating an already-visible list's structure proof
  ([#160](https://github.com/viell-dev/slop-calc-sheet-manager/issues/160#issuecomment-6565110912)).
  Windows proof-state controls and eight normal-package Mac cases verify the correction; all
  theme, input and workbook-state checks still run visibly. Revisit the exception if Calc's
  panel initialization or this fixture's cleanup changes. Every Calc document is closed through
  `main_thread.close_document`: on Windows, closing one from the test's own thread crashed
  LibreOffice ([#47](https://github.com/viell-dev/slop-calc-sheet-manager/issues/47)).
- **PyUNO exceptions** reject a new `__traceback__`, so a UNO exception leaving a
  `@contextmanager` block, such as `office_session`, arrives as a RuntimeException about a
  traceback object ([#41](https://github.com/viell-dev/slop-calc-sheet-manager/issues/41)). Keep
  UNO calls whose exceptions a caller catches out of generator-based context managers; in a
  failed run, read the first traceback.
- **Shipped files.** Add a new shipped module to the allowlist in `tools/build.py` and to the
  package-content test.
