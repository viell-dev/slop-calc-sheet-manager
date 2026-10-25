# Security policy

Report a suspected vulnerability through
[GitHub's private vulnerability reporting](https://github.com/viell-dev/slop-calc-sheet-manager/security/advisories/new),
with the Sheet Manager and LibreOffice versions, the operating system, and the steps to reproduce
it with a workbook made for the report. Do not put exploitable details or private documents in a
public issue.

Reports are handled by AI agents without a guaranteed response time. Fixes go into the newest
release; older versions do not receive backports.

Sheet Manager runs inside LibreOffice with the permissions of the person using it. It reads sheet
metadata and changes sheet order and visibility through LibreOffice's interfaces. Its context menu
and forwarded shortcuts run LibreOffice's own commands
on the selected sheets. The extension's own operations do not change cell content, save, close,
or reload workbooks. The extension makes no network requests of its own;
LibreOffice's Extension Manager checks the project's update feed when you look for updates. A
defect without a security impact belongs in an ordinary issue.
