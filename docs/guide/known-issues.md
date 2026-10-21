# Compatibility and known issues

## Where it is tested

Every change runs against official LibreOffice builds from libreoffice.org, in these environments:

<!--@include: ../../README.md#environments-->

"Verified" means automated checks on every change. They install the extension, open and resize the
deck, check read-only workbooks and Writer, press modifier keys in a real window, convert a file
headlessly, and remove the extension. The checks and their limits are listed in the project's
[verification map](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/docs/verification.md).

If Sheet Manager does not work in an environment where it is expected to, please
[report it](./report.md).

## Known issues

- **The deck is empty.** The sheet list is still being built.
- **Planned for 0.1.0: a LibreOffice defect in two commands.** The sheet tab menu will run
  LibreOffice's own Duplicate Sheet and Move or Copy Sheet. In LibreOffice 26.8.0 and 26.8.1 these
  commands copy formulas with relative sheet references incorrectly
  ([tdf#173608](https://bugs.documentfoundation.org/show_bug.cgi?id=173608)), whether they are
  started from the tab bar or from the menu. LibreOffice's fix is due in 26.8.2.
- **Other LibreOffice defects.** Defects in LibreOffice that affect Sheet Manager, and how each is
  handled, are listed in
  [issue #33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33).
