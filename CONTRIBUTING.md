# Contributing

Issues and pull requests from people and from agents are welcome. The project is maintained by AI
agents, as the [README](README.md#status) says, and its owner follows it through issue and pull
request descriptions rather than code, so write them for a reader who has not seen the code.
Agents maintaining the repository also follow [AGENTS.md](AGENTS.md). Everyone follows the
[code of conduct](CODE_OF_CONDUCT.md).

If an AI agent wrote or submitted your issue, pull request, or comment, say so at the start: which
agent, for whom, and whether a person reviewed it. The maintainers' own posts open with such a
note.

## Report a defect

Search the open and closed [issues](https://github.com/viell-dev/slop-calc-sheet-manager/issues)
first, then open one with the
[bug report form](https://github.com/viell-dev/slop-calc-sheet-manager/issues/new?template=bug.yml).
It asks for:

- the Sheet Manager version, from Tools ▸ Extension Manager, or the commit you built;
- LibreOffice's version information: in Help ▸ About, select **Copy Version Information**. It
  includes the operating system and the user interface (the "VCL" line, such as `win`, `gtk3`, or
  `kf6`);
- how LibreOffice was installed, such as from libreoffice.org or as a distribution package;
- the exact steps, from opening the workbook to the problem;
- what happened and what you expected;
- a workbook that shows it, made for the report: never attach a real workbook or a screenshot of
  one with private content.

Suggest an improvement to existing behaviour or a new capability with the other forms, and ask how
something works with the question form.
[#33](https://github.com/viell-dev/slop-calc-sheet-manager/issues/33) lists known defects in
LibreOffice that affect Sheet Manager. Report vulnerabilities privately, as
[SECURITY.md](SECURITY.md) describes.

Maintainers label each issue with one `Type:` label, at most one `Status:` label, and `Needs: Owner`
or `Needs: Human` when a particular person has to act. The labels and their meanings are in
[`.github/labels.json`](.github/labels.json).

## Choose your checks

| Your change | Start here |
| --- | --- |
| Documentation only | [Build the guide and check synthetic release history](#documentation). |
| Pure Python | [Set up the development tools](#set-up), then run the [normal checks](#checks) or [a unit test](#tests) while iterating. |
| Linux integration or real input | Run [integration in the Linux Docker lab](docs/development/native-testing.md#linux-docker-lab) or [real-input checks](docs/development/native-testing.md#linux-real-input). |
| Hosted platform checks | Run the [visible Windows desktop](docs/development/hosted-checks.md#visible-windows-desktop) or [macOS packaged integration](docs/development/hosted-checks.md#macos-packaged-integration) workflow. For local headless checks on Windows, use [installed LibreOffice](docs/development/native-testing.md#installed-libreoffice). |

## Documentation

The user guide is in `docs/` and is built with VitePress, whose exact version `package.json` pins.
It is published on [GitHub Pages](https://viell-dev.github.io/slop-calc-sheet-manager/) together
with the update feeds. To work on it, select the Node.js version in `.nvmrc` (`nvm use` or
`fnm use`), then run:

```sh
npm ci
npm run docs:build
python tools/check_release_page.py
```

Use `npm run docs:dev` for live editing. The build checks links between pages. The Python helper
builds empty and synthetic release histories to verify the channels, version order, rendered
OXT/checksum links, and markers for unpublished behaviour.

If Windows blocks VitePress's native module, use the
[documentation container build](docs/development/index.md#building-the-guide).
For user-facing changes, follow the guide's
[version and availability rules](docs/development/index.md#which-version-it-describes).

## Set up

Use Python 3.12–3.14, Git, and Node.js for Pyright, at the version in `.nvmrc` that CI also
installs; `nvm use` or `fnm use` in the repository root selects it. Install Node before running
checks; the check command fails without it rather than allowing Pyright to download a runtime.
The extension has no third-party runtime dependencies. Development tools and UNO type stubs stay
in a project virtual environment; never install them into LibreOffice's Python. Docker Desktop
on Windows, or Docker Engine on Linux,
runs the official Linux LibreOffice builds in an isolated test environment.

Windows, in PowerShell 7 with a development Python installed:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
```

Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
```

LibreOffice's bundled Python is for integration tests. Some bundled builds cannot create a venv
(including Windows 26.8.1.1, which lacks `venvlauncher.exe`). On Windows with Docker Desktop and
no development Python or Node, run these commands from the repository root in PowerShell 7:

```powershell
docker build --file ci/checks.Dockerfile --tag sheet-manager-checks .
docker run --rm --network none --mount "type=bind,source=${PWD},target=/work" sheet-manager-checks
```

This uses digest-pinned Python 3.12.16 and Node images, the latter at the `.nvmrc` version, and
hash-pinned development tools. It writes caches, test output and `dist/` into the checkout; the
container is removed on exit. Rebuild the image after changing `requirements-dev.txt`. This checks
Linux semantics; the release sweep also runs the complete check command on Windows.

## Checks

One command runs Ruff lint and format checks, Pyright, unit tests, and two builds whose bytes must
match. Pyright checks Linux, Windows and macOS API availability; this does not execute
native behaviour on those platforms. It uses Python 3.12 semantics and strict checking, with
limited exceptions at the dynamic UNO boundary. The test stubs never ship in the extension.

Windows PowerShell 7:

```powershell
.\.venv\Scripts\python.exe tools/check.py
```

Linux:

```sh
.venv/bin/python tools/check.py
```

To build without installing development tools, run `python tools/build.py` (or
`& 'C:\Program Files\LibreOffice\program\python.exe' tools/build.py` on a Windows machine with
only LibreOffice's Python). This writes `dist/sheet-manager-0.0.10.oxt` and its `.oxt.sha256` file.
The version comes only from `extension/description.xml`. Packaging uses explicit file lists,
sorted ZIP members, fixed timestamps and permissions, LF text, and uncompressed members so that
different zlib versions cannot change the result. Add new shipped modules to the allowlist in
`tools/build.py` and to the package-content test.

The OXT also includes one English XHP quick-help page, registered through its manifest as an
extension help component. LibreOffice compiles it during installation; no HelpLinker SDK or
generated help databases are shipped. For reviewing shipped text and the online guide, follow the
[affected-surface review in AGENTS.md](AGENTS.md#public-surfaces-and-documentation).

## Tests

Unit tests need no LibreOffice and run as part of the checks. To run them alone:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

```sh
.venv/bin/python -m pytest
```

Append a path such as `tests/unit/test_consistency.py` to run a single test file.

The [verification map](docs/verification.md) owns coverage and evidence limits. Update it when a
promise or its checks change.

- <a name="integration-suites"></a>[Integration suites](docs/development/native-testing.md#integration-suites)
  covers private profiles, suite conventions, and fixture rules.
- <a name="failures-and-shutdown"></a>[Failures and shutdown](docs/development/native-testing.md#failures-and-shutdown)
  explains logs, timeouts and crash evidence.
- <a name="soak-painted-sessions"></a>[Soak painted sessions](docs/development/native-testing.md#soak-painted-sessions)
  covers local and hosted gtk3 soak runs.
- <a name="routine-ci-and-release-sweeps"></a>[Hosted checks](docs/development/hosted-checks.md)
  explains routine CI, the release sweep, and where to find artifacts.
- <a name="visible-windows-desktop"></a>[Visible Windows desktop](docs/development/hosted-checks.md#visible-windows-desktop)
  covers the focused workflow and desktop restrictions.
- <a name="macos-packaged-integration"></a>[macOS packaged integration](docs/development/hosted-checks.md#macos-packaged-integration)
  covers the focused Intel workflow and its diagnostics.

Follow [RELEASING.md](RELEASING.md#prepare-and-dry-run) for release readiness and the
[human usability gate](RELEASING.md#human-release-testing).

## Pull requests

Every change to `main` goes through a pull request with passing checks and is merged with a merge
commit. Contributions are made under the [Mozilla Public License 2.0](LICENSE).

- Describe the problem, the resulting behaviour, and the decisions made and why, for a reader who
  will not read the diff. Link the issue.
- Add a "Verification" section: the commands run, the inputs tried beyond the tests, the
  platforms and LibreOffice versions checked, and any behaviour you broke on purpose to show that
  a check catches it. Maintainers add how the change was reviewed, as
  [AGENTS.md](AGENTS.md#review) describes.
- Update every document, test, and setting that describes what you changed, in the same pull
  request, and add the change to the `Unreleased` section of [CHANGELOG.md](CHANGELOG.md).
- Keep changes scoped, and state remaining limits.
