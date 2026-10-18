# Contributing

Issues and pull requests from people and from agents are welcome. The project is maintained by AI
agents, as the [README](README.md#status) says, and its owner follows it through issue and pull
request descriptions rather than code, so write them for a reader who has not seen the code.
Agents maintaining the repository also follow [AGENTS.md](AGENTS.md). Everyone follows the
[code of conduct](CODE_OF_CONDUCT.md).

## Report a defect

Search the open and closed [issues](https://github.com/viell-dev/slop-calc-sheet-manager/issues)
first, then open one with:

- the Sheet Manager version, from Tools ▸ Extension Manager;
- the LibreOffice version and user interface, from Help ▸ About (the "VCL" line, such as `win`,
  `gtk3`, or `kf6`), and the operating system;
- the exact steps, from opening the workbook to the problem;
- what happened and what you expected;
- a workbook that shows it, made for the report: never attach a real workbook or a screenshot of
  one with private content.

Report vulnerabilities privately, as [SECURITY.md](SECURITY.md) describes.

## Set up

Use Python 3.12–3.14, Git, and Node.js (24.21.0 in CI, for Pyright). Install Node before running
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

This uses digest-pinned Python 3.12.15 and Node 24.21.0 images and hash-pinned development tools.
It writes caches, test output and `dist/` into the checkout; the container is removed on exit.
Rebuild the image after changing `requirements-dev.txt`. This checks Linux semantics; CI also runs
the complete check command on Windows in the Windows integration job.

## Checks

One command runs Ruff lint and format checks, Pyright, unit tests, and two builds whose bytes must
match. Pyright uses Python 3.12 semantics and strict checking, with limited exceptions at the
dynamic UNO boundary. The test stubs never ship in the extension.

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
only LibreOffice's Python). This writes `dist/sheet-manager-0.0.1.oxt` and its `.oxt.sha256` file.
The version comes only from `extension/description.xml`. Packaging uses explicit file lists,
sorted ZIP members, fixed timestamps and permissions, LF text, and uncompressed members so that
different zlib versions cannot change the result. Add new shipped modules to the allowlist in
`tools/build.py` and to the package-content test.

## Tests

Unit tests need no LibreOffice and run as part of the checks. To run them alone:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

```sh
.venv/bin/python -m pytest
```

The integration runner installs the built OXT into a fresh temporary profile, connects over a
unique local UNO pipe, and checks the factory, tab-control peer, exact panel resizing and disposal,
read-only Calc documents, Writer exclusion, and SVG decoding. Every workbook is synthetic and
loaded visibly, even when the office process itself is headless. It retries only startup, up to
three times, to tolerate a Windows crash just after connecting. It never attaches to an existing
office or uses the normal LibreOffice profile.

On Windows, build and test the installed LibreOffice with its bundled Python:

```powershell
$lo = 'C:\Program Files\LibreOffice\program'
& "$lo\python.exe" tools/build.py
& "$lo\python.exe" tests/integration/run.py --program $lo --oxt dist/sheet-manager-0.0.1.oxt
```

On Linux, when using an official TDF installation at `/opt/libreoffice26.8`:

```sh
python3 tools/build.py
/opt/libreoffice26.8/program/python tests/integration/run.py \
  --program /opt/libreoffice26.8/program --oxt dist/sheet-manager-0.0.1.oxt
```

Run the complete Linux matrix in Docker with these commands (PowerShell 7 and POSIX shells both
accept them; substitute the path to a working Python if `python` is unavailable):

```text
python tools/linux_integration.py minimum --screenshot
python tools/linux_integration.py current-26.2 --screenshot
python tools/linux_integration.py current-26.8 --screenshot
python tools/linux_integration.py unsupported
```

The helper builds `ci/Dockerfile`, verifies the repository-pinned TDF archive checksum, builds the
extension, and runs the container unprivileged with networking disabled. Source and the OXT are
mounted read-only; only `test-results/<lane>/` is writable on the host. On Linux, run as a non-root
user: the helper maps that user's UID/GID into the container so artifacts remain writable. The
container has a temporary home directory. It uses Xvfb and Openbox inside the container and
never mounts a host display socket. `--skip-build` reuses the corresponding `sheet-manager-ci`
image. `--screenshot` also starts a separate painted gtk3 session and saves `deck.png`; the default
session always checks the headless mode used by automation. The `unsupported` lane asserts that
26.2.0 refuses installation for a dependency error and leaves the extension uninstalled.

Logs, actual office/Python versions, package inventory, and results are in `test-results/` and in
CI artifacts. The runner records the exit status of each office session and rejects nonzero exits,
forced shutdowns, and fatal-error messages, including during termination. The intermittent minimum
version gtk3 abort is tracked in [issue #8](https://github.com/viell-dev/slop-calc-sheet-manager/issues/8).
Windows CI verifies a pinned MSI before silently installing it; this installation script is for
disposable CI runners, not a contributor's existing installation.

`ci/libreoffice.json` pins the minimum 26.2.1 build, the newest tested 26.2 and 26.8 builds, the
unsupported 26.2.0 build, and Windows. When updating a lane, verify the current TDF catalogue and
published SHA-256, update the version, URL and digest together, and run that lane. Always use
`https://downloadarchive.documentfoundation.org/libreoffice/old/<full version>/` and the full
four-part version in filenames: `stable/` downloads disappear when the offered releases change.
These pins do not discover newer releases automatically. Dependabot checks development tools,
GitHub-owned actions and Docker base images weekly after a seven-day cooldown. Action references
remain full commit SHAs, with their versions in comments. Two base images are pinned on purpose:
the checks image keeps Python 3.12, the oldest supported version, so Dependabot proposes only its
patch releases; and its Node image matches the `node-version` in the workflow, so Dependabot
leaves it alone and both are changed together by hand.

## Pull requests

Every change to `main` goes through a pull request with passing checks and is merged with a merge
commit. Contributions are made under the [Mozilla Public License 2.0](LICENSE).

- Describe the problem, the resulting behaviour, and the decisions made and why, for a reader who
  will not read the diff. Link the issue.
- Add a "Verification" section: the commands run, the inputs tried beyond the tests, and the
  platforms and LibreOffice versions checked.
- Update every document, test, and setting that describes what you changed, in the same pull
  request, and add the change to the `Unreleased` section of [CHANGELOG.md](CHANGELOG.md).
- Keep changes scoped, and state remaining limits.
