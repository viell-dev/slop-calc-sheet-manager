# Security policy

Report a suspected vulnerability through
[GitHub's private vulnerability reporting](https://github.com/viell-dev/slop-calc-sheet-manager/security/advisories/new),
with the Sheet Manager and LibreOffice versions, the operating system, and the steps to reproduce
it with a workbook made for the report. Do not put exploitable details or private documents in a
public issue.

Reports are handled by AI agents without a guaranteed response time. Fixes go into the newest
release; older versions do not receive backports.

Sheet Manager runs inside LibreOffice with the permissions of the person using it. The current
development version only adds an empty deck to Calc's sidebar and neither reads nor changes the
content of documents. The planned sheet list will read and change only the sheet structure of
documents open in LibreOffice, through LibreOffice's own interfaces: their sheets' order, names,
visibility, colours, and protection. The extension makes no network requests of its own;
LibreOffice's Extension Manager checks the project's update feed when you look for updates. A
defect without a security impact belongs in an ordinary issue.
