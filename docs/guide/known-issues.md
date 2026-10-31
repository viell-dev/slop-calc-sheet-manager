# Compatibility and known issues

## Where it is tested

Every change runs against official LibreOffice builds from libreoffice.org, in these environments:

<!--@include: ../../README.md#environments-->

"Verified" means automated checks on every change. They install the extension, open and resize the
deck, check read-only workbooks and Writer, press modifier keys in a real window, convert a file
headlessly, and remove the extension. The checks and their limits are listed in the
[verification map](../verification.md).

If Sheet Manager does not work in an environment where it is expected to, please
[report it](./report.md).

## Known issues

- **Grouped tabs.** Cell edits affect every grouped Calc tab. The footer identifies the group
  separately from the list's picks. Double-click a row, press Enter on a single selected row, or
  click a Calc tab to end grouping. <Unreleased since="0.0.5" /> A Calc command chosen from the
  list's menu groups its targets and leaves them grouped, even when its dialog is cancelled
  ([#100](https://github.com/viell-dev/slop-calc-sheet-manager/issues/100)). Closing the menu
  without choosing a command changes nothing. A command refused because its sheets changed
  leaves the view as it was, unless the previous sheets can no longer be proved.
- **Header Help.** The header's native `?` opens LibreOffice's local error page for the generated
  `SIDEBAR_SHEETMANAGERDECK` help topic. No supported deck help-target setter is available. Use
  **Sheet Manager Help** in the context menu for this guide. Header hover sizing is also controlled
  by LibreOffice and its theme
  ([#81](https://github.com/viell-dev/slop-calc-sheet-manager/issues/81)).
- **Save focus.** Ctrl+S from the list saves through Calc and moves focus to the sheet
  ([#23](https://github.com/viell-dev/slop-calc-sheet-manager/issues/23)).
- **Unavailable menu actions.** Native popup rendering can hide disabled commands and move
  actions, and their help text. In the gen backend, use Down to highlight the first available
  entry; Home can leave no entry highlighted when the leading actions are unavailable. Alt move
  shortcuts still apply the same permission and edge checks
  ([#84](https://github.com/viell-dev/slop-calc-sheet-manager/issues/84)).
- **Conservative selection clearing.** Inserting or deleting sheets, undoing or redoing, and
  modifications whose continuity cannot be established can clear the list's selection. A notice
  explains conservative clearing of a user-made selection. Ordinary refreshes retain the list's
  range anchor while its sheet identity remains valid. Native Undo and Redo can also activate an
  affected sheet; the list then follows Calc's new tab selection. A grouped move can activate
  the sheet above the returned group, whereas a single move can activate the returned sheet.
  Keeping independent picks is tracked in
  [#91](https://github.com/viell-dev/slop-calc-sheet-manager/issues/91).
  **Selection feedback.** <Unreleased since="0.0.5" /> The clearing notice expires within the
  panel after ten seconds, preserving focus.
  An immediate selection after Reload or during concurrent document changes can remain empty or
  clear again, including during some recorded changes. Select the desired rows again once loading
  or concurrent edits finish; the cause of this intermittent observation is still under
  investigation ([#88](https://github.com/viell-dev/slop-calc-sheet-manager/issues/88)).
- **Large lists.** The list rebuilds after changes. During rapid sheet switches the active-sheet
  marker can lag; timing measurements and the remaining work are in
  [#22](https://github.com/viell-dev/slop-calc-sheet-manager/issues/22).
- **Final row divider.** At the end of a long list, the last row's lower divider can be absent.
  The painter leaves an ambiguous boundary pixel clear to keep decorations off scrollbars
  ([#86](https://github.com/viell-dev/slop-calc-sheet-manager/issues/86)).
- **Refused held clicks.** If a held click is refused after the list changes, its picks are restored
  and, when any survive, the keyboard cursor returns to one of them. An unpicked position made
  during that hold is not preserved
  ([#71](https://github.com/viell-dev/slop-calc-sheet-manager/issues/71)).
- **Rename Sheets.** <Unreleased since="0.0.6" /> Sheet names written as text are not changed: after
  a rename, a formula such as `INDIRECT("'WIP North'.A1")` refers to no sheet, or to whichever sheet
  then has that name. Calc's own formula references, named ranges, and charts follow the new names.
  After a Find & Replace in the same LibreOffice session, Calc can refuse some full-width or
  half-width names, such as `Ａ` beside `A`. Rename Sheets then undoes its own step, checks the old
  names, and says which name was refused; if it cannot confirm the old names, it says so, and you
  should check them. Restarting LibreOffice ends this
  ([#112](https://github.com/viell-dev/slop-calc-sheet-manager/issues/112)). The dialog refuses a
  few names that Calc accepts, such as `ss` beside `ß`, because LibreOffice can confuse them. Other
  windows on the same workbook clear their list's selection after a rename of several sheets.
- **Names that LibreOffice confuses.** Calc accepts two sheets whose names differ only in some
  characters, such as `ﬁ` (a single ligature character) and `fi`, or `ı` and `I`, but then finds
  whichever of them comes first for either name, also in formulas: while `ﬁ` comes first,
  `='fi'.A1` refers to a cell of `ﬁ`. This is a limit of LibreOffice; renaming one of the sheets
  avoids it ([#113](https://github.com/viell-dev/slop-calc-sheet-manager/issues/113)). Test
  builds up to 0.0.6 show the second sheet with the first one's hidden, protected, or colour
  state, and refuse to move, show, or rename sheets until one of them is renamed.
  <Unreleased /> The list shows each sheet's own state, and Show, the menu's commands, moves, and
  Rename Sheets act on the sheet you picked. Calc moves a sheet only by its name, so the list
  refuses a move that would need the name of the sheet that does not come first, and says which
  two names Calc confuses ([#125](https://github.com/viell-dev/slop-calc-sheet-manager/issues/125)).
  Rename Sheets still refuses to create such a pair.
- **Macros that suppress notifications.** The list cannot detect structural edits for which
  LibreOffice reports nothing, or a deliberately constructed edit indistinguishable from ordinary
  typed input. The reorder adapter uses the same structural monitor and has the same boundary.
  The [reordering interface](../reordering.md) describes what is detected.
- **A LibreOffice defect in two commands.** In LibreOffice 26.8.0 and 26.8.1, Calc's own
  Duplicate Sheet and Move or Copy Sheet copy formulas with relative sheet references incorrectly
  ([tdf#173608](https://bugs.documentfoundation.org/show_bug.cgi?id=173608)). LibreOffice's fix
  is due in 26.8.2. Test builds up to 0.0.4 offer both through **Sheet actions…**.
  <Unreleased since="0.0.5" /> The list's menu leaves them to Calc's sheet tabs. Calc's Move or
  Copy also reverses several sheets moved to the right
  ([#3](https://github.com/viell-dev/slop-calc-sheet-manager/issues/3)); the list's own moves
  keep their order.
- **Other LibreOffice defects.** Defects in LibreOffice that affect Sheet Manager, and how each is
  handled, are listed in
  [issue #33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33). Among them, Hide
  Sheet keeps Calc's own undo, whether chosen from Calc's tabs or the list's menu: LibreOffice
  skips undoing it when no Calc window is current, as can happen when a macro undoes it, yet uses
  up the undo step ([#108](https://github.com/viell-dev/slop-calc-sheet-manager/issues/108)).
