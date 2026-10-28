"""Build a deterministic OXT using only the standard library."""

import argparse
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

try:
    from .release_data import version_parts
except ImportError:  # Direct invocation: python tools/build.py.
    from release_data import version_parts

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sheet_manager.i18n import tr  # noqa: E402

# Explicit inputs prevent accidentally publishing local files, caches, or development tools.
EXTENSION_FILES = (
    "META-INF/manifest.xml",
    "description.xml",
    "description-en.txt",
    "Factories.xcu",
    "Sidebar.xcu",
    "icons/deck.svg",
    "registration.py",
    "sheet-manager.components",
)
PACKAGE_FILES = (
    "__init__.py",
    "i18n.py",
    "keys.py",
    "rename.py",
    "reorder.py",
    "selection.py",
    "sheet_list.py",
    "structure.py",
    "uno_calc.py",
    "uno_keys.py",
    "uno_list.py",
    "uno_menu.py",
    "uno_moves.py",
    "uno_status.py",
    "uno_panel.py",
    "uno_rename.py",
    "uno_rename_dialog.py",
    "uno_reorder.py",
    "uno_rows.py",
    "uno_show.py",
    "uno_structure.py",
)
DESCRIPTION_NS = "{http://openoffice.org/extensions/description/2006}"


def version(root: Path = ROOT) -> str:
    node = ET.parse(root / "extension/description.xml").find(f"{DESCRIPTION_NS}version")
    if node is None:
        raise ValueError("description.xml must contain a three-part version")
    version_parts(node.attrib["value"])
    return node.attrib["value"]


def render(content: str, *, xml: bool) -> str:
    def translate(match: re.Match[str]) -> str:
        translated = tr(match.group(1))
        return escape(translated, {'"': "&quot;"}) if xml else translated

    return re.sub(r"\{\{(.*?)\}\}", translate, content)


def build(output: Path, root: Path = ROOT) -> Path:
    members: dict[str, bytes] = {}
    for name in EXTENSION_FILES:
        source = root / "extension" / name
        content = source.read_text(encoding="utf-8")
        members[name] = render(content, xml=source.suffix in {".xml", ".xcu"}).encode("utf-8")
    for name in PACKAGE_FILES:
        members[f"pythonpath/sheet_manager/{name}"] = (
            (root / "src/sheet_manager" / name).read_text(encoding="utf-8").encode("utf-8")
        )
    members["LICENSE.txt"] = (root / "LICENSE").read_text(encoding="utf-8").encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    package = output / f"sheet-manager-{version(root)}.oxt"
    # Stored members avoid zlib-version differences between platforms and Python releases.
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    package.with_suffix(".oxt.sha256").write_text(
        f"{digest}  {package.name}\n", encoding="ascii", newline="\n"
    )
    return package


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    print(build(parser.parse_args().output))
