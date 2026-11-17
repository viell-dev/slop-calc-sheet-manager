# Troubleshooting

## LibreOffice refuses to install the extension

If the Extension Manager reports a missing dependency, your LibreOffice is older than 26.2.1.
Update LibreOffice, then install Sheet Manager again. See [Requirements](./install.md#requirements).

## The Sheet Manager deck does not appear

1. **Calc.** Make sure that you are in Calc: the deck does not appear in Writer or the other
   applications.
2. **Installed and enabled.** Open **Tools ▸ Extension Manager** and check that Sheet Manager is
   listed and enabled. If you installed it just now, restart LibreOffice.
3. **Sidebar shown.** Show the sidebar with **View ▸ Sidebar** (Ctrl+F5), and look for Sheet
   Manager in the sidebar's tab bar.
4. **Python support.** On Linux, check that LibreOffice's Python support is installed: the package
   is `python3-uno` on Debian and Ubuntu and `libreoffice-pyuno` on Fedora and openSUSE. Builds
   from libreoffice.org include it.

If it still does not appear, [report it](./report.md) with LibreOffice's version information.

## The deck shows a message instead of the sheet list

<Unreleased /> If the Sheet Manager deck says that Sheet Manager could not open its sheet list,
the list failed to start for this document; earlier versions left the deck empty instead.

1. **Reopen.** Close and reopen the document. If the message stays, restart LibreOffice.
2. **Report it** if it happens again, as described in [Report a problem](./report.md). Include
   the error name shown in brackets, LibreOffice's version information, and what you did before
   opening the document. The message never includes your sheet names. On Linux, starting
   LibreOffice from a terminal with `soffice` also prints the technical details after a line
   beginning with `Sheet Manager:`; check that they name no private sheets before including
   them.

## LibreOffice crashes or misbehaves after installing

1. **Start in Safe Mode.** Select **Help ▸ Restart in Safe Mode**. If LibreOffice does not start
   normally, start it from a terminal with `soffice --safe-mode`.
2. **Disable the extensions.** In the Safe Mode dialog, under **Configure**, select **Disable all
   user extensions**, then **Apply Changes and Restart**.
3. **Remove Sheet Manager.** Remove it as described in [Remove](./install.md#remove). With
   LibreOffice closed, you can also remove it from the command line:
   `unopkg remove dev.viell.sheetmanager`.
4. **Report the problem.** Include the steps that led to it; see [Report a problem](./report.md).

## No update is offered

An empty update result can be expected. If only test builds have been published, the stable feed
is empty:

- **Check for Updates** offers only stable releases newer than the installed one, and only those
  your LibreOffice version can run.
- Test builds are never offered automatically. Download them from
  [Releases and test builds](./releases.md#test-builds). Installing one does not subscribe you to
  later test builds; the stable feed will offer the final release when it is available.
