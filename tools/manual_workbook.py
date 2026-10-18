"""Write the synthetic workbook used by docs/manual-tests.md, as a flat OpenDocument file."""

import argparse
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parents[1]

NATO = [
    "Alfa",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
    "India",
    "Juliett",
    "Kilo",
    "Lima",
    "Mike",
    "November",
    "Oscar",
    "Papa",
    "Quebec",
    "Romeo",
    "Sierra",
    "Tango",
    "Uniform",
    "Victor",
    "Whiskey",
    "X-ray",
    "Yankee",
    "Zulu",
]
NAMES = NATO + [f"Sheet {number}" for number in range(27, 61)]
COLORS = {"Alfa": "#c9211e", "Bravo": "#3faf46", "Charlie": "#2a6099"}
HIDDEN = {"Hotel", "India"}
PROTECTED = {"Kilo"}

HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
 xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:tableooo="http://openoffice.org/2009/table"
 office:version="1.3" office:mimetype="application/vnd.oasis.opendocument.spreadsheet">
"""


def table_style(name: str) -> str:
    attributes = f' table:display="{"false" if name in HIDDEN else "true"}"'
    if name in COLORS:
        attributes += f' tableooo:tab-color="{COLORS[name]}"'
    return attributes


def workbook() -> str:
    styles = sorted({table_style(name) for name in NAMES})
    style_names = {attributes: f"ta{index}" for index, attributes in enumerate(styles, start=1)}
    lines = [HEADER, " <office:automatic-styles>\n"]
    for attributes, style in style_names.items():
        lines.append(
            f'  <style:style style:name="{style}" style:family="table">'
            f"<style:table-properties{attributes}/></style:style>\n"
        )
    lines.append(" </office:automatic-styles>\n <office:body>\n  <office:spreadsheet>\n")
    for name in NAMES:
        protected = ' table:protected="true"' if name in PROTECTED else ""
        text = f"Cell A1 of {name}; keep this text"
        lines.append(
            f"   <table:table table:name={quoteattr(name)}"
            f' table:style-name="{style_names[table_style(name)]}"{protected}>'
            "<table:table-column/><table:table-row>"
            f'<table:table-cell office:value-type="string"><text:p>{text}</text:p>'
            "</table:table-cell></table:table-row></table:table>\n"
        )
    lines.append("  </office:spreadsheet>\n </office:body>\n</office:document>\n")
    return "".join(lines)


def write(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "sheet-manager-manual-tests.fods"
    path.write_text(workbook(), encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    print(write(parser.parse_args().output))
