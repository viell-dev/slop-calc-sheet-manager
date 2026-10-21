"""The manual-test workbook is well-formed and has the sheet states the checklist relies on."""

import xml.etree.ElementTree as ET
from pathlib import Path

from tools.manual_workbook import COLORS, HIDDEN, NAMES, PROTECTED, write

TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
STYLE = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
TABLEOOO = "{http://openoffice.org/2009/table}"


def test_manual_workbook(tmp_path: Path) -> None:
    root = ET.parse(write(tmp_path)).getroot()
    properties = {
        style.attrib[f"{STYLE}name"]: style.find(f"{STYLE}table-properties")
        for style in root.iter(f"{STYLE}style")
    }
    tables = list(root.iter(f"{TABLE}table"))
    assert [table.attrib[f"{TABLE}name"] for table in tables] == NAMES
    for table in tables:
        name = table.attrib[f"{TABLE}name"]
        style = properties[table.attrib[f"{TABLE}style-name"]]
        assert style is not None
        assert style.attrib[f"{TABLE}display"] == ("false" if name in HIDDEN else "true")
        assert style.attrib.get(f"{TABLEOOO}tab-color") == COLORS.get(name)
        assert (table.attrib.get(f"{TABLE}protected") == "true") == (name in PROTECTED)
