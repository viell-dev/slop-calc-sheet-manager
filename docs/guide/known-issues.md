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
  click a Calc tab to end grouping. Context menus can temporarily group tabs for native commands;
  restoration is refused if the original sheet identities or visibility can no longer be proved.
- **Header Help.** The header's native `?` opens LibreOffice's local error page for the generated
  `SIDEBAR_SHEETMANAGERDECK` help topic. No supported deck help-target setter is available. Use
  **Sheet Manager Help** in the context menu for this guide. Header hover sizing is also controlled
  by LibreOffice and its theme
  ([#81](https://github.com/viell-dev/slop-calc-sheet-manager/issues/81)).
- **Save focus.** Ctrl+S from the list saves through Calc and moves focus to the sheet
  ([#23](https://github.com/viell-dev/slop-calc-sheet-manager/issues/23)).
- **Conservative selection clearing.** Inserting or deleting sheets, undoing or redoing, and
  modifications whose continuity cannot be established can clear the list's selection. A notice
  explains conservative clearing of a user-made selection. Ordinary refreshes retain the list's
  range anchor while its sheet identity remains valid.
- **Large lists.** The list rebuilds after changes. During rapid sheet switches the active-sheet
  marker can lag; timing measurements and the remaining work are in
  [#22](https://github.com/viell-dev/slop-calc-sheet-manager/issues/22).
- **Refused held clicks.** If a held click is refused after the list changes, its picks are restored
  and, when any survive, the keyboard cursor returns to one of them. An unpicked position made
  during that hold is not preserved
  ([#71](https://github.com/viell-dev/slop-calc-sheet-manager/issues/71)).
- **Macros that suppress notifications.** The list cannot detect structural edits for which
  LibreOffice reports nothing, or a deliberately constructed edit indistinguishable from ordinary
  typed input. The reorder adapter uses the same structural monitor and has the same boundary.
  The [reordering interface](../reordering.md) describes what is detected.
- **A LibreOffice defect in two commands.** The sheet tab menu runs
  LibreOffice's own Duplicate Sheet and Move or Copy Sheet. In LibreOffice 26.8.0 and 26.8.1 these
  commands copy formulas with relative sheet references incorrectly
  ([tdf#173608](https://bugs.documentfoundation.org/show_bug.cgi?id=173608)), whether they are
  started from the tab bar or from the menu. LibreOffice's fix is due in 26.8.2.
- **Other LibreOffice defects.** Defects in LibreOffice that affect Sheet Manager, and how each is
  handled, are listed in
  [issue #33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33).
