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

The development setup, the checks, and the test layout arrive with the first code and will be
described here.

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
