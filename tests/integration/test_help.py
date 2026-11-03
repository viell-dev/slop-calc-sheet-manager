"""Resolve the installed OXT's registered Help HID through the native help content provider.

LibreOffice compiles our raw XHP during installation. A generated sidebar HID needs a registered
topic, not an XDeck setter (#81). Read the actual rendered content, including English fallback
for other UI locales, and keep an unknown-HID control. This is offline lookup evidence; the
painted Linux header check separately exercises the host's '?' action and internal viewer.
"""

import os
from pathlib import Path

TITLE = "Sheet Manager quick help"
HID = "SIDEBAR_SHEETMANAGERDECK"


def read_help(context, hid, language):
    service = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.ucb.SimpleFileAccess", context
    )
    stream = service.openFileRead(
        f"vnd.sun.star.help://scalc/{hid}?Language={language}"
        f"&System={'WIN' if os.name == 'nt' else 'UNIX'}"
    )
    try:
        chunks = []
        while True:
            count, data = stream.readBytes((), 65536)
            if count == 0:
                break
            chunks.append(bytes(data.value))
        return b"".join(chunks).decode("utf-8")
    finally:
        stream.closeInput()


def exercise(context, desktop, directory, output):
    evidence = {}
    for language in ("en-US", "en-GB", "de-DE"):
        content = read_help(context, HID, language)
        (Path(output) / f"help-{language}.html").write_text(content, encoding="utf-8")
        assert TITLE in content, (language, content)
        assert "Picking rows alone does not group" in content, content
        assert "https://viell-dev.github.io/slop-calc-sheet-manager/" in content, content
        evidence[language] = {"bytes": len(content.encode("utf-8")), "topic": HID}
    missing = read_help(context, "SHEET_MANAGER_HELP_MISSING_CONTROL", "en-US")
    assert TITLE not in missing, missing
    evidence["missing_topic_rejected"] = True
    return evidence
