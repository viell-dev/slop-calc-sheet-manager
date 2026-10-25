# Install, update, and remove

## Requirements

- **LibreOffice 26.2.1 or later.** LibreOffice 26.2.0 and earlier refuse to install the extension:
  they cannot keep a selection of several sheets while it is dragged.
- **LibreOffice's Python support.** Builds from libreoffice.org include it. On Linux distributions
  it can be a separate package, such as `python3-uno` on Debian and Ubuntu or `libreoffice-pyuno`
  on Fedora and openSUSE.

See [Compatibility and known issues](./known-issues.md) for the environments that are tested.

## Install

There is no release yet. When there is, download the `.oxt` file from
[GitHub Releases](https://github.com/viell-dev/slop-calc-sheet-manager/releases) and install it as
described below.

Until then, you can build the development version yourself. Its sheet list is unreleased, so this is
mainly useful for testing.

1. Get the source with Git:
   `git clone https://github.com/viell-dev/slop-calc-sheet-manager.git`.
2. In the `slop-calc-sheet-manager` folder, run `python tools/build.py` with Python 3.12 or later.
   On Windows, LibreOffice's own Python works too:
   `& 'C:\Program Files\LibreOffice\program\python.exe' tools/build.py`.
3. The package is `dist/sheet-manager-<version>.oxt`, named after the version it was built as.

To install a package:

1. In LibreOffice, open **Tools ▸ Extension Manager** and select **Add**.
2. Choose the `.oxt` file and follow the prompts.
3. Restart LibreOffice when asked.
4. Open a workbook in Calc. Open the sidebar with **View ▸ Sidebar** (Ctrl+F5), then select
   **Sheet Manager** in the sidebar's tab bar.

## Check a download

Each release also has an `.oxt.sha256` file with the package's SHA-256 checksum. To check a
download, compare the checksum of the `.oxt` file with that file's content.

- On Linux, in the download folder:

  ```sh
  sha256sum -c sheet-manager-0.1.0.oxt.sha256
  ```

  It prints `OK` for a matching file.
- On Windows, in PowerShell:

  ```powershell
  (Get-FileHash .\sheet-manager-0.1.0.oxt -Algorithm SHA256).Hash
  Get-Content .\sheet-manager-0.1.0.oxt.sha256
  ```

  The two values must be the same. PowerShell prints the checksum in capitals.

## Update

Select **Tools ▸ Extension Manager ▸ Check for Updates**. LibreOffice asks the project's
[stable feed](https://viell-dev.github.io/slop-calc-sheet-manager/updates/stable.xml) for newer
releases, and offers only those your LibreOffice version can run.

- **When it asks.** Sheet Manager makes no network requests of its own, and opening a workbook does
  not check for updates.
- **Today.** No build is published, so no update is offered yet.
- **Test builds.** Download their `.oxt` packages from
  [Releases and test builds](./releases.md#test-builds). They are marked **Pre-release** on GitHub.
  Installing one keeps you on the stable feed, so the final release is offered when it appears;
  later test builds are downloaded manually. Their numeric versions sort below that final
  release in LibreOffice. See [Version numbers](./releases.md#version-numbers) for why SemVer
  suffixes such as `-rc.1` cannot be used directly.

## Remove

1. Open **Tools ▸ Extension Manager**, select **Sheet Manager**, and select **Remove**.
2. Restart LibreOffice. The Sheet Manager deck is gone from Calc's sidebar.

If LibreOffice does not start, or you prefer the command line, close LibreOffice and run its
`unopkg` program, which is in its `program` folder:

```sh
unopkg remove dev.viell.sheetmanager
```

On Windows:

```powershell
& 'C:\Program Files\LibreOffice\program\unopkg.exe' remove dev.viell.sheetmanager
```

Removal leaves no Sheet Manager deck, panel, or installed copy behind. LibreOffice may keep its
own temporary copy of the package it added until it cleans up that folder itself.
